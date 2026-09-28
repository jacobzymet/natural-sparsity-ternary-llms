#!/usr/bin/env python3
"""Zero-weight statistics for public ternary (1.58-bit) LLM checkpoints.

Generalizes analyze_packed_bitnet.py (same target tensors, same unpacking,
same representation byte formulas and block histograms) to checkpoints that
store their ternary BitLinear weights in one of four ways:

hf-packed
    Hugging Face Transformers BitNet offline format (quant_method "bitnet"):
    uint8 tensors holding four 2-bit codes (ternary + 1) along the output
    dimension, plus a separate bf16 weight_scale. Decoded exactly with
    analyze_packed_bitnet.unpack_hf_bitnet. Used by
    microsoft/bitnet-b1.58-2B-4T, tiiuae Falcon3-*-1.58bit, Falcon-E and
    HF1BitLLM.

absmean-latent
    Full-precision latent (master) weights; the ternary weights are what the
    model's own BitNet b1.58 inference quantizer produces, per tensor:
        s = 1 / clamp(mean(|W|), min=1e-5)
        W_q = clamp(round(W * s), -1, 1)
    (1bitLLM utils_quant.weight_quant). Evaluated in float32 with torch when
    available so rounding matches the reference code; the count of weights
    within 2^-20 of the +-0.5 rounding threshold is reported as a sensitivity
    bound, together with the zero count obtained after casting the latent
    weights to float16 first (the dtype the reference eval loads).

prescaled-ternary
    Weights already ternarized and stored as {0, +-scale} in a float dtype
    (SpectraSuite TriLM "Unpacked": one scale per model-parallel shard). The
    ternary value is sign(W); the script verifies that every tensor has at most
    --max-magnitudes distinct nonzero |W| values and no NaN/Inf.

gguf-q2_0
    GGUF files whose projection tensors use the group-128 ternary block type
    Q2_0 of the PrismML llama.cpp fork (type id 42; one fp16 scale d plus
    128 two-bit codes q, weight = (q - 1) * d, q = 3 rejected), as written by
    CAT-Q (IntelLabsChina/CAT-Q). GGUF names blk.N.attn_q/.../ffn_down are
    mapped to the Hugging Face projection names. Groups with d = 0 or d < 0
    are counted and reported, since they change what a code means.

Embeddings, lm_head, normalization tensors and scales are excluded, exactly as
in analyze_packed_bitnet.py.
"""

from __future__ import annotations

import argparse
import csv
import datetime as _dt
import hashlib
import json
import math
import platform
import re
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import safetensors
from safetensors import safe_open

sys.path.insert(0, str(Path(__file__).resolve().parent))
from analyze_packed_bitnet import (  # noqa: E402
    DEFAULT_BLOCKS,
    TARGET_SUFFIXES,
    block_histogram,
    five_trit_row_bytes,
    is_target,
    quantile,
    unpack_hf_bitnet,
)

FORMATS = ("hf-packed", "absmean-latent", "prescaled-ternary", "gguf-q2_0")
LAYER_TYPES = tuple(s.split(".")[1] for s in TARGET_SUFFIXES)
TIE_TOLERANCE = 2.0**-20

METHOD_TEXT = {
    "hf-packed": (
        "Exact decode of HF Transformers BitNet offline packing: uint8, four "
        "2-bit codes per byte along the output dimension, code = ternary + 1, "
        "row block i stored in bits 2i..2i+1 "
        "(scripts/analyze_packed_bitnet.py:unpack_hf_bitnet). Code 3 rejected."
    ),
    "absmean-latent": (
        "Latent full-precision weights quantized with the model's BitNet b1.58 "
        "inference quantizer, per tensor: s = 1/clamp(mean(|W|), 1e-5); "
        "W_q = clamp(round(W*s), -1, 1), round half to even, float32."
    ),
    "prescaled-ternary": (
        "Weights stored already ternarized as {0, +-scale} (one scale per "
        "model-parallel shard); ternary = sign(W), validated to have at most "
        "--max-magnitudes distinct nonzero magnitudes per tensor."
    ),
    "gguf-q2_0": (
        "Exact decode of GGUF Q2_0 blocks (PrismML llama.cpp fork, type 42): "
        "fp16 scale d then 32 bytes of 2-bit codes, code j at bits "
        "2*(j%4) of byte j//4, weight = (code - 1) * d; code 3 rejected. "
        "Rows run along ne[0] = in_features."
    ),
}

GGUF_TYPE_Q2_0 = 42
Q2_0_GROUP = 128
Q2_0_BLOCK_BYTES = 2 + Q2_0_GROUP // 4
GGUF_TO_HF = {
    "attn_q": "self_attn.q_proj",
    "attn_k": "self_attn.k_proj",
    "attn_v": "self_attn.v_proj",
    "attn_output": "self_attn.o_proj",
    "ffn_gate": "mlp.gate_proj",
    "ffn_up": "mlp.up_proj",
    "ffn_down": "mlp.down_proj",
}


class GGUFFile:
    """Minimal GGUF v2/v3 reader: metadata, tensor infos, raw tensor bytes."""

    _SCALAR = {0: "<B", 1: "<b", 2: "<H", 3: "<h", 4: "<I", 5: "<i", 6: "<f", 7: "<?", 10: "<Q", 11: "<q", 12: "<d"}

    def __init__(self, path: Path) -> None:
        import struct

        self.struct = struct
        self.path = path
        with path.open("rb") as f:
            self.f = f
            if f.read(4) != b"GGUF":
                raise ValueError(f"{path}: not a GGUF file")
            self.version = self._u("<I")
            n_tensors = self._u("<Q")
            n_kv = self._u("<Q")
            self.metadata = {}
            for _ in range(n_kv):
                key = self._str()
                self.metadata[key] = self._value(self._u("<I"))
            self.tensors = {}
            for _ in range(n_tensors):
                name = self._str()
                dims = [self._u("<Q") for _ in range(self._u("<I"))]
                self.tensors[name] = {"dims": dims, "type": self._u("<I"), "offset": self._u("<Q")}
            align = int(self.metadata.get("general.alignment", 32))
            self.data_start = (f.tell() + align - 1) // align * align
        del self.f

    def _u(self, fmt: str):
        size = self.struct.calcsize(fmt)
        return self.struct.unpack(fmt, self.f.read(size))[0]

    def _str(self) -> str:
        return self.f.read(self._u("<Q")).decode("utf-8")

    def _value(self, vtype: int):
        if vtype == 8:
            return self._str()
        if vtype == 9:
            etype = self._u("<I")
            return [self._value(etype) for _ in range(self._u("<Q"))]
        return self._u(self._SCALAR[vtype])

    def read_q2_0(self, name: str) -> np.ndarray:
        info = self.tensors[name]
        if info["type"] != GGUF_TYPE_Q2_0:
            raise ValueError(f"{name}: GGUF type {info['type']} is not Q2_0")
        if len(info["dims"]) != 2:
            raise ValueError(f"{name}: expected 2D tensor, got dims {info['dims']}")
        k, rows = info["dims"]
        if k % Q2_0_GROUP:
            raise ValueError(f"{name}: in_features {k} not a multiple of {Q2_0_GROUP}")
        nbytes = rows * (k // Q2_0_GROUP) * Q2_0_BLOCK_BYTES
        raw = np.fromfile(self.path, dtype=np.uint8, count=nbytes, offset=self.data_start + info["offset"])
        return raw.reshape(rows, k // Q2_0_GROUP, Q2_0_BLOCK_BYTES)


def gguf_hf_name(name: str) -> str | None:
    m = re.fullmatch(r"blk\.(\d+)\.(\w+)\.weight", name)
    if not m or m.group(2) not in GGUF_TO_HF:
        return None
    return f"model.layers.{m.group(1)}.{GGUF_TO_HF[m.group(2)]}.weight"


def decode_q2_0(blocks: np.ndarray) -> tuple[np.ndarray, dict]:
    """(rows, groups, 34) uint8 -> int8 ternary (rows, groups*128), scale stats."""
    rows, groups, _ = blocks.shape
    d = np.ascontiguousarray(blocks[..., :2]).view(np.float16).reshape(rows, groups).astype(np.float32)
    qs = blocks[..., 2:]
    codes = np.stack([(qs >> s) & 0x03 for s in (0, 2, 4, 6)], axis=-1).reshape(rows, groups * Q2_0_GROUP)
    if np.any(codes == 3):
        raise ValueError("Q2_0 code 3 (+2) present; tensor is not ternary")
    stats = {
        "q2_0_groups": int(d.size),
        "q2_0_zero_scale_groups": int(np.count_nonzero(d == 0)),
        "q2_0_negative_scale_groups": int(np.count_nonzero(d < 0)),
        "q2_0_nonfinite_scale_groups": int(np.count_nonzero(~np.isfinite(d))),
    }
    return codes.astype(np.int8) - np.int8(1), stats


def load_config(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".json":
        return json.loads(text)
    out = {}
    for line in text.splitlines():
        m = re.match(r"^([A-Za-z_][\w]*):\s*(.*?)\s*(#.*)?$", line)
        if m:
            out[m.group(1)] = m.group(2)
    return out


def sha256_file(path: Path, chunk: int = 1 << 24) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def hub_lfs_sha256(repo_id: str, revision: str) -> dict[str, str]:
    from huggingface_hub import HfApi

    info = HfApi().model_info(repo_id, revision=revision, files_metadata=True)
    return {s.rfilename: s.lfs.sha256 for s in info.siblings if s.lfs is not None}


def layer_type(name: str) -> str:
    for suffix in TARGET_SUFFIXES:
        if name.endswith(suffix):
            return suffix.split(".")[1]
    raise ValueError(name)


def layer_index(name: str) -> int | None:
    m = re.search(r"layers\.(\d+)\.", name)
    return int(m.group(1)) if m else None


class AbsmeanQuantizer:
    """BitNet b1.58 per-tensor absmean quantizer (1bitLLM weight_quant)."""

    def __init__(self) -> None:
        try:
            import torch

            self.torch = torch
            self.backend = f"torch {torch.__version__} (float32)"
        except ImportError:
            self.torch = None
            self.backend = f"numpy {np.__version__} (float32)"

    def __call__(self, w: np.ndarray) -> tuple[np.ndarray, int]:
        """Return (int8 ternary, number of weights within tolerance of a tie)."""
        if self.torch is not None:
            t = self.torch.from_numpy(np.ascontiguousarray(w)).float()
            s = 1.0 / t.abs().mean().clamp(min=1e-5)
            y = t * s
            q = y.round().clamp(-1, 1).to(self.torch.int8).numpy()
            ties = int(((y.abs() - 0.5).abs() <= TIE_TOLERANCE).sum().item())
            return q, ties
        x = w.astype(np.float32)
        s = np.float32(1.0) / max(np.float32(np.abs(x).mean(dtype=np.float32)), np.float32(1e-5))
        y = x * s
        q = np.clip(np.round(y), -1, 1).astype(np.int8)
        ties = int(np.count_nonzero(np.abs(np.abs(y) - 0.5) <= TIE_TOLERANCE))
        return q, ties


def decode_prescaled(w: np.ndarray, max_magnitudes: int) -> tuple[np.ndarray, list[float]]:
    x = w.astype(np.float32)
    if not np.all(np.isfinite(x)):
        raise ValueError("non-finite values in prescaled ternary tensor")
    mags = np.unique(np.abs(x[x != 0]))
    if len(mags) > max_magnitudes:
        raise ValueError(
            f"{len(mags)} distinct nonzero magnitudes (> {max_magnitudes}); "
            "tensor is not stored as prescaled ternary"
        )
    return np.sign(x).astype(np.int8), [float(m) for m in mags]


def dist(values: np.ndarray) -> dict:
    return {
        "min": float(values.min()),
        "p01": quantile(values, 0.01),
        "p05": quantile(values, 0.05),
        "p25": quantile(values, 0.25),
        "p50": quantile(values, 0.50),
        "p75": quantile(values, 0.75),
        "p95": quantile(values, 0.95),
        "p99": quantile(values, 0.99),
        "max": float(values.max()),
        "mean": float(values.mean()),
        "std": float(values.std()),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("checkpoint", nargs="+", type=Path, help="safetensors or GGUF file(s)")
    ap.add_argument("--format", required=True, choices=FORMATS)
    ap.add_argument("--repo-id", required=True, help="Hugging Face repo id")
    ap.add_argument("--revision", required=True, help="Hub commit hash downloaded")
    ap.add_argument("--config", type=Path, help="config.json (or flat config.yaml) of the checkpoint")
    ap.add_argument("--slug", help="output file prefix (default: repo id with / -> __)")
    ap.add_argument("--output-dir", type=Path, default=Path("data/real_checkpoints"))
    ap.add_argument("--date", default=_dt.date.today().isoformat())
    ap.add_argument("--blocks", default=",".join(map(str, DEFAULT_BLOCKS)))
    ap.add_argument("--max-magnitudes", type=int, default=8)
    ap.add_argument("--no-hub-check", action="store_true", help="skip Hub sha256 lookup")
    args = ap.parse_args()

    blocks = tuple(int(x) for x in args.blocks.split(",") if x)
    for b in (4, 5):
        if b not in blocks:
            raise SystemExit("--blocks must include 4 and 5")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    slug = args.slug or args.repo_id.replace("/", "__")

    files = []
    hub = {} if args.no_hub_check else hub_lfs_sha256(args.repo_id, args.revision)
    for path in args.checkpoint:
        digest = sha256_file(path)
        entry = {"file": path.name, "bytes": path.stat().st_size, "sha256": digest}
        if not args.no_hub_check:
            hub_name = next((n for n in hub if n == path.name or n.endswith("/" + path.name)), None)
            entry["hub_path"] = hub_name
            entry["hub_lfs_sha256"] = hub.get(hub_name)
            entry["sha256_matches_hub"] = hub.get(hub_name) == digest
            if not entry["sha256_matches_hub"]:
                raise SystemExit(f"{path.name}: sha256 does not match Hub LFS metadata")
        files.append(entry)
        print(f"sha256 {path.name} {digest}")

    config = None
    if args.config:
        config = load_config(args.config)

    quantizer = AbsmeanQuantizer() if args.format == "absmean-latent" else None

    tensor_rows: list[dict] = []
    all_row_density: list[np.ndarray] = []
    aggregate_hist = {b: np.zeros(b + 1, dtype=np.int64) for b in blocks}
    aggregate_remainders: dict[tuple[int, int], int] = defaultdict(int)
    non_target_dtypes: dict[str, int] = defaultdict(int)
    totals = defaultdict(int)
    by_type = {t: defaultdict(int) for t in LAYER_TYPES}
    by_layer: dict[int, defaultdict] = defaultdict(lambda: defaultdict(int))
    ties_total = 0
    fp16_zeros_total = 0
    magnitude_counts: list[int] = []

    names = []
    gguf_metadata = {}
    q2_0_totals: dict[str, int] = defaultdict(int)
    for p in args.checkpoint:
        if args.format == "gguf-q2_0":
            g = GGUFFile(p)
            gguf_metadata = {
                k: v
                for k, v in g.metadata.items()
                if not isinstance(v, list) and not k.startswith("tokenizer.")
            }
            for gname, info in g.tensors.items():
                hf = gguf_hf_name(gname)
                if hf is None:
                    non_target_dtypes[f"ggml_type_{info['type']}"] += 1
                else:
                    names.append((hf, lambda g=g, gname=gname: g.read_q2_0(gname)))
            continue
        f = safe_open(str(p), framework="numpy")
        for name in f.keys():
            if is_target(name):
                names.append((name, lambda f=f, name=name: f.get_tensor(name)))
            else:
                non_target_dtypes[str(f.get_slice(name).get_dtype())] += 1
    names.sort(key=lambda nf: (layer_index(nf[0]) or 0, LAYER_TYPES.index(layer_type(nf[0]))))
    if not names:
        raise RuntimeError("no target BitLinear tensors found")

    for idx, (name, load) in enumerate(names, start=1):
        raw = load()
        extra = {}
        if args.format == "gguf-q2_0":
            ternary, qstats = decode_q2_0(raw)
            extra.update(qstats)
            for key, val in qstats.items():
                q2_0_totals[key] += val
        elif args.format == "hf-packed":
            ternary = unpack_hf_bitnet(raw)
            extra["stored_shape"] = "x".join(map(str, raw.shape))
        elif args.format == "absmean-latent":
            ternary, ties = quantizer(raw)
            q16, _ = quantizer(raw.astype(np.float16))
            z16 = int(np.count_nonzero(q16 == 0))
            del q16
            ties_total += ties
            fp16_zeros_total += z16
            extra["tie_sensitive_weights"] = ties
            extra["zeros_if_fp16_cast"] = z16
        else:
            ternary, mags = decode_prescaled(raw, args.max_magnitudes)
            magnitude_counts.append(len(mags))
            extra["distinct_nonzero_magnitudes"] = len(mags)
            extra["magnitudes"] = ";".join(f"{m:.8g}" for m in mags)
        del raw
        if ternary.ndim != 2:
            raise ValueError(f"{name}: expected 2D weight, got {ternary.shape}")

        rows, k = ternary.shape
        zero_mask = ternary == 0
        row_zeros = zero_mask.sum(axis=1).astype(np.int64)
        row_density = row_zeros / k
        all_row_density.append(row_density.astype(np.float64))

        weights = int(ternary.size)
        zeros = int(row_zeros.sum())
        nonzeros = weights - zeros
        plus = int(np.count_nonzero(ternary == 1))
        minus = nonzeros - plus
        density = zeros / weights

        dense2_bytes = rows * math.ceil(2 * k / 8)
        five_bytes = rows * five_trit_row_bytes(k, 128)
        bitcos_tensor_bytes = math.ceil(weights / 8) + math.ceil(nonzeros / 8)
        bitcos_row_bytes = rows * math.ceil(k / 8) + int(np.ceil((k - row_zeros) / 8).sum())
        bitcos_rowptr32_bytes = bitcos_tensor_bytes + 4 * (rows + 1)

        lt = layer_type(name)
        li = layer_index(name)
        tensor_rows.append(
            {
                "tensor": name,
                "layer_type": lt,
                "layer_index": li,
                "out_features": rows,
                "in_features": k,
                "weights": weights,
                "zeros": zeros,
                "plus_ones": plus,
                "minus_ones": minus,
                "zero_density": density,
                "row_zero_density_p05": quantile(row_density, 0.05),
                "row_zero_density_p50": quantile(row_density, 0.50),
                "row_zero_density_p95": quantile(row_density, 0.95),
                "row_zero_density_min": float(row_density.min()),
                "row_zero_density_max": float(row_density.max()),
                "dense2_bytes": dense2_bytes,
                "five_trit_128block_bytes": five_bytes,
                "bitcos_tensor_continuous_bytes": bitcos_tensor_bytes,
                "bitcos_row_aligned_bytes": bitcos_row_bytes,
                "bitcos_continuous_plus_rowptr32_bytes": bitcos_rowptr32_bytes,
                **extra,
            }
        )

        for block in blocks:
            hist, remainder = block_histogram(zero_mask, block)
            aggregate_hist[block] += hist
            if remainder:
                aggregate_remainders[(block, remainder)] += rows

        for acc in (totals, by_type[lt], by_layer[li]):
            acc["tensors"] += 1
            acc["weights"] += weights
            acc["zeros"] += zeros
        totals["plus_ones"] += plus
        totals["minus_ones"] += minus
        totals["dense2"] += dense2_bytes
        totals["five"] += five_bytes
        totals["bitcos_tensor"] += bitcos_tensor_bytes
        totals["bitcos_row"] += bitcos_row_bytes
        totals["bitcos_rowptr32"] += bitcos_rowptr32_bytes
        totals["adaptive"] += min(bitcos_tensor_bytes, five_bytes)
        if bitcos_tensor_bytes < five_bytes:
            totals["bitcos_wins_tensors"] += 1
            totals["bitcos_wins_weights"] += weights

        print(f"[{idx:3d}/{len(names)}] {name}: {rows}x{k}, zero={density:.5f}")

    W = totals["weights"]
    Z = totals["zeros"]
    NZ = W - Z
    z = Z / W
    p_plus = totals["plus_ones"] / W
    p_minus = totals["minus_ones"] / W
    entropy = -sum(p * math.log2(p) for p in (z, p_plus, p_minus) if p > 0)

    tensor_density = np.array([r["zero_density"] for r in tensor_rows])
    row_density_all = np.concatenate(all_row_density)

    block_summary = {}
    for block in blocks:
        hist = aggregate_hist[block]
        nblocks = int(hist.sum())
        zero_sum = int(sum(i * int(n) for i, n in enumerate(hist)))
        block_summary[str(block)] = {
            "complete_blocks": nblocks,
            "mean_zero_density": zero_sum / (block * nblocks) if nblocks else None,
            "histogram": [int(x) for x in hist],
            "fractions": [int(x) / nblocks for x in hist] if nblocks else None,
        }

    def hist_dict(block: int) -> dict:
        hist = aggregate_hist[block]
        out = {"complete_blocks": int(hist.sum())}
        out.update({f"zero_count_{i}": int(n) for i, n in enumerate(hist)})
        return out

    per_type = {}
    for t in LAYER_TYPES:
        acc = by_type[t]
        if not acc["weights"]:
            continue
        dens = tensor_density[[r["layer_type"] == t for r in tensor_rows]]
        per_type[t] = {
            "tensors": acc["tensors"],
            "weights": acc["weights"],
            "zeros": acc["zeros"],
            "zero_density": acc["zeros"] / acc["weights"],
            "tensor_zero_density_min": float(dens.min()),
            "tensor_zero_density_max": float(dens.max()),
        }

    per_layer = [
        {
            "layer_index": li,
            "weights": acc["weights"],
            "zeros": acc["zeros"],
            "zero_density": acc["zeros"] / acc["weights"],
        }
        for li, acc in sorted(by_layer.items(), key=lambda kv: -1 if kv[0] is None else kv[0])
    ]

    decoding = {"format": args.format, "method": METHOD_TEXT[args.format]}
    if args.format == "absmean-latent":
        decoding["quantizer_backend"] = quantizer.backend
        decoding["tie_tolerance"] = TIE_TOLERANCE
        decoding["tie_sensitive_weights"] = ties_total
        decoding["tie_sensitive_fraction"] = ties_total / W
        decoding["zeros_if_latent_cast_to_fp16_first"] = fp16_zeros_total
        decoding["zero_density_if_latent_cast_to_fp16_first"] = fp16_zeros_total / W
    elif args.format == "gguf-q2_0":
        decoding.update(q2_0_totals)
        decoding["gguf_metadata"] = gguf_metadata
    elif args.format == "prescaled-ternary":
        decoding["max_distinct_nonzero_magnitudes_per_tensor"] = max(magnitude_counts)
        decoding["distinct_magnitude_count_histogram"] = {
            str(c): magnitude_counts.count(c) for c in sorted(set(magnitude_counts))
        }

    summary = {
        "source": f"{args.repo_id} " + ", ".join(fe["file"] for fe in files),
        "provenance": {
            "repo_id": args.repo_id,
            "revision": args.revision,
            "files": files,
            "config_quantization_config": (config or {}).get("quantization_config"),
            "config_architectures": (config or {}).get("architectures"),
            "analysis_date": args.date,
            "script": "scripts/analyze_ternary_checkpoint.py",
            "script_sha256": sha256_file(Path(__file__).resolve()),
            "helpers_from": "scripts/analyze_packed_bitnet.py",
            "command": "python " + " ".join(
                [Path(sys.argv[0]).as_posix()]
                + [a if not Path(a).is_absolute() else f"<{Path(a).name}>" for a in sys.argv[1:]]
            ),
            "environment": {
                "python": platform.python_version(),
                "numpy": np.__version__,
                "safetensors": safetensors.__version__,
                "platform": platform.platform(),
            },
        },
        "decoding": decoding,
        "target_suffixes": list(TARGET_SUFFIXES),
        "non_target_tensor_dtypes": dict(non_target_dtypes),
        "target_tensor_count": len(tensor_rows),
        "weights": W,
        "zeros": Z,
        "nonzeros": NZ,
        "plus_ones": totals["plus_ones"],
        "minus_ones": totals["minus_ones"],
        "zero_density": z,
        "per_layer_type": per_type,
        "per_layer_index": per_layer,
        "tensor_zero_density_distribution": dist(tensor_density),
        "row_zero_density_distribution": {"rows": int(row_density_all.size), **dist(row_density_all)},
        "bits_per_weight": {
            "bitmap_plus_sign_ideal": (W + NZ) / W,
            "five_trit_ideal": 8 / 5,
            "dense2": 2.0,
            "ternary_symbol_entropy": entropy,
            "five_trit_128block": 8 * totals["five"] / W,
            "bitcos_tensor_continuous": 8 * totals["bitcos_tensor"] / W,
            "bitmap_plus_sign_over_five_trit_ideal": ((W + NZ) / W) / 1.6,
            "breakeven_zero_density_vs_five_trit_ideal": 0.4,
        },
        "stream5_bits_per_cycle": {
            "presence": 5.0,
            "mean_signs": 5 * NZ / W,
            "bitcos_total": 5 + 5 * NZ / W,
            "five_trit": 8.0,
        },
        "representation_bytes": {
            "dense2_row_aligned": totals["dense2"],
            "five_trit_128block": totals["five"],
            "bitcos_tensor_continuous": totals["bitcos_tensor"],
            "bitcos_row_aligned": totals["bitcos_row"],
            "bitcos_tensor_continuous_plus_rowptr32": totals["bitcos_rowptr32"],
            "per_tensor_adaptive_min_bitcos_continuous_or_five_trit": totals["adaptive"],
        },
        "ratios_vs_five_trit": {
            "dense2": totals["dense2"] / totals["five"],
            "bitcos_tensor_continuous": totals["bitcos_tensor"] / totals["five"],
            "bitcos_row_aligned": totals["bitcos_row"] / totals["five"],
            "bitcos_continuous_plus_rowptr32": totals["bitcos_rowptr32"] / totals["five"],
            "per_tensor_adaptive": totals["adaptive"] / totals["five"],
        },
        "bitcos_smaller_than_five_trit": {
            "tensors": totals["bitcos_wins_tensors"],
            "of_tensors": len(tensor_rows),
            "weight_fraction": totals["bitcos_wins_weights"] / W,
        },
        "block4_zero_histogram": hist_dict(4),
        "block5_zero_histogram": hist_dict(5),
        "block_stats": block_summary,
        "ignored_partial_blocks": {
            f"{block}:{remainder}": rows for (block, remainder), rows in aggregate_remainders.items()
        },
    }

    summary_json = args.output_dir / f"{slug}_summary_{args.date}.json"
    tensor_csv = args.output_dir / f"{slug}_tensor_stats_{args.date}.csv"
    with summary_json.open("w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(summary, indent=2) + "\n")
    with tensor_csv.open("w", encoding="utf-8", newline="") as f:
        fieldnames = list(dict.fromkeys(k for r in tensor_rows for k in r))
        writer = csv.DictWriter(f, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(tensor_rows)

    print(
        f"\n{args.repo_id}: {len(tensor_rows)} tensors, {W} weights, "
        f"zero density {z:.6f}, bitmap+sign {(W + NZ) / W:.4f} bits/weight vs 1.6"
    )
    print(f"wrote {summary_json}")
    print(f"wrote {tensor_csv}")


if __name__ == "__main__":
    main()
