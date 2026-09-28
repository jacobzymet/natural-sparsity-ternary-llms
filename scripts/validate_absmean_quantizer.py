#!/usr/bin/env python3
"""Check the absmean-latent decoding path against an exactly packed checkpoint.

microsoft/bitnet-b1.58-2B-4T-bf16 publishes the bf16 master weights of the
same model whose ternary weights microsoft/bitnet-b1.58-2B-4T ships packed.
This script range-fetches selected latent BitLinear tensors from a pinned Hub
revision (no full download), quantizes them with the per-tensor absmean
quantizer used by analyze_ternary_checkpoint.py, and compares element-wise
against unpack_hf_bitnet() of the local packed checkpoint. It also compares
mean(|W|) with the packed checkpoint's weight_scale.
"""

from __future__ import annotations

import argparse
import json
import struct
import sys
from pathlib import Path

import numpy as np
import requests
from safetensors import safe_open

sys.path.insert(0, str(Path(__file__).resolve().parent))
from analyze_packed_bitnet import TARGET_SUFFIXES, unpack_hf_bitnet  # noqa: E402
from analyze_ternary_checkpoint import AbsmeanQuantizer  # noqa: E402

DTYPES = {"BF16": 2, "F16": 2, "F32": 4}


def fetch(url: str, start: int, end: int) -> bytes:
    r = requests.get(url, headers={"Range": f"bytes={start}-{end}"}, timeout=(20, 120))
    r.raise_for_status()
    if len(r.content) != end - start + 1:
        raise IOError(f"short range read {len(r.content)} != {end - start + 1}")
    return r.content


def to_float32(buf: bytes, dtype: str, shape: list[int]) -> np.ndarray:
    if dtype == "BF16":
        u = np.frombuffer(buf, dtype="<u2").astype(np.uint32) << 16
        return u.view(np.float32).reshape(shape)
    if dtype == "F16":
        return np.frombuffer(buf, dtype="<f2").astype(np.float32).reshape(shape)
    return np.frombuffer(buf, dtype="<f4").reshape(shape).copy()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("packed", type=Path, help="local packed model.safetensors")
    ap.add_argument("--latent-repo", default="microsoft/bitnet-b1.58-2B-4T-bf16")
    ap.add_argument("--latent-revision", default="276681394656abdadb8e80e5b2c3db5e5d7fcaff")
    ap.add_argument("--latent-file", default="model.safetensors")
    ap.add_argument("--layers", default="0,29")
    ap.add_argument(
        "--band",
        type=float,
        default=2.0**-8,
        help="half-width of the |W|/mean|W| band around 0.5 treated as below the "
        "latent storage precision (2^-8 ~ one bf16 ULP at 0.5)",
    )
    ap.add_argument("--output", type=Path)
    args = ap.parse_args()

    url = (
        f"https://huggingface.co/{args.latent_repo}/resolve/"
        f"{args.latent_revision}/{args.latent_file}"
    )
    (hlen,) = struct.unpack("<Q", fetch(url, 0, 7))
    header = json.loads(fetch(url, 8, 8 + hlen - 1))
    base = 8 + hlen

    quantizer = AbsmeanQuantizer()
    layers = [int(x) for x in args.layers.split(",") if x]
    results = []
    with safe_open(str(args.packed), framework="numpy") as packed, safe_open(
        str(args.packed), framework="pt"
    ) as packed_pt:
        for li in layers:
            for suffix in TARGET_SUFFIXES:
                name = f"model.layers.{li}.{suffix}"
                meta = header[name]
                s, e = meta["data_offsets"]
                latent = to_float32(fetch(url, base + s, base + e - 1), meta["dtype"], meta["shape"])
                q, ties = quantizer(latent)
                ref = unpack_hf_bitnet(packed.get_tensor(name))
                scale_name = name[: -len("weight")] + "weight_scale"
                packed_scale = float(packed_pt.get_tensor(scale_name).float().reshape(-1)[0])
                if q.shape != ref.shape:
                    raise ValueError(f"{name}: shape {q.shape} != packed {ref.shape}")
                mism = q != ref
                y = np.abs(latent.astype(np.float64)) / np.abs(latent.astype(np.float64)).mean()
                band = np.abs(y - 0.5) <= args.band
                row = {
                    "tensor": name,
                    "shape": list(q.shape),
                    "mismatches": int(mism.sum()),
                    "sign_disagreements": int(np.count_nonzero((q * ref) < 0)),
                    "weights_in_threshold_band": int(band.sum()),
                    "mismatches_outside_threshold_band": int(np.count_nonzero(mism & ~band)),
                    "tie_sensitive_weights": ties,
                    "latent_zero_density": float(np.mean(q == 0)),
                    "packed_zero_density": float(np.mean(ref == 0)),
                    "latent_mean_abs": float(np.abs(latent.astype(np.float64)).mean()),
                    "packed_weight_scale": packed_scale,
                }
                results.append(row)
                print(json.dumps(row))

    total = sum(int(np.prod(r["shape"])) for r in results)

    def tot(key: str) -> int:
        return sum(r[key] for r in results)

    summary = {
        "latent_repo": args.latent_repo,
        "latent_revision": args.latent_revision,
        "latent_file": args.latent_file,
        "packed_checkpoint": args.packed.name,
        "quantizer_backend": quantizer.backend,
        "layers": layers,
        "threshold_band_half_width": args.band,
        "tensors": len(results),
        "weights_compared": total,
        "mismatches": tot("mismatches"),
        "mismatch_fraction": tot("mismatches") / total,
        "sign_disagreements": tot("sign_disagreements"),
        "weights_in_threshold_band": tot("weights_in_threshold_band"),
        "mismatches_outside_threshold_band": tot("mismatches_outside_threshold_band"),
        "per_tensor": results,
    }
    print(
        f"\ncompared {total} weights in {len(results)} tensors: "
        f"{summary['mismatches']} mismatches, {summary['sign_disagreements']} sign "
        f"disagreements, {summary['mismatches_outside_threshold_band']} mismatches "
        f"outside the +-{args.band:g} threshold band"
    )
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("w", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(summary, indent=2) + "\n")
        print(f"wrote {args.output}")


if __name__ == "__main__":
    main()
