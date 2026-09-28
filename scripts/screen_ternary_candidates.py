#!/usr/bin/env python3
"""Cheap zero-density screen of public ternary checkpoints by HTTP range reads.

Fetches only selected BitLinear tensors (never whole checkpoints) from pinned
Hugging Face revisions, decodes them with the same decoders as
analyze_ternary_checkpoint.py, and reports sampled zero densities. Used to
decide which checkpoints are worth a full download; sampled densities are
estimates over the listed layers, not exact whole-model statistics.

Extra decoders beyond analyze_ternary_checkpoint.py:
- group-prescaled: {0, +-scale} with one scale per contiguous K-group
  (validated: every group has a single nonzero magnitude).
- torch-zip-absmean: legacy pytorch_model.bin (zip) latent weights, read by
  range requests with a restricted unpickler that only records tensor
  metadata (no code execution), then absmean-quantized.
"""

from __future__ import annotations

import argparse
import collections
import io
import json
import pickle
import re
import struct
import sys
import time
import zlib
from pathlib import Path

import numpy as np
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from analyze_packed_bitnet import TARGET_SUFFIXES, unpack_hf_bitnet  # noqa: E402
from analyze_ternary_checkpoint import AbsmeanQuantizer, decode_prescaled  # noqa: E402
from validate_absmean_quantizer import to_float32  # noqa: E402

MMFREE = (
    "attn.i_proj.weight",
    "attn.f_proj.weight",
    "attn.g_proj.weight",
    "attn.o_proj.weight",
    "mlp.gate_proj.weight",
    "mlp.down_proj.weight",
)
OLMO = ("att_proj.weight", "attn_out.weight", "ff_proj.weight", "ff_out.weight")
QUP = ("self_attn.q_proj.weight", "mlp.up_proj.weight")

# (repo, revision or branch, format, suffixes, layers: "quartiles" | "mid")
CANDIDATES = [
    ("tiiuae/Falcon3-10B-Instruct-1.58bit", "4b61e8876b19bf7a4b271b757a1bd2974bf38913", "hf-packed", TARGET_SUFFIXES, "quartiles"),
    ("tiiuae/Falcon-E-1B-Base", "f4001b8b1c26d28a717d79a8ece14901816d92e8", "hf-packed", TARGET_SUFFIXES, "quartiles"),
    ("tiiuae/Falcon-E-3B-Base", "ad18b0713c10a8696144b1112accf4ccd28af6d3", "hf-packed", TARGET_SUFFIXES, "quartiles"),
    ("SpectraSuite/TriLM_99M_Unpacked", "61cd2c766000fc544595d6570ad1990017d0cb43", "prescaled-ternary", TARGET_SUFFIXES, "quartiles"),
    ("SpectraSuite/TriLM_390M_Unpacked", "79cd1fe5a9650ea5342baa2034ecb1b2aaf792e9", "prescaled-ternary", TARGET_SUFFIXES, "quartiles"),
    ("SpectraSuite/TriLM_830M_Unpacked", "e220c2792a635575f7ebb419f77e8e4e047f052c", "prescaled-ternary", TARGET_SUFFIXES, "quartiles"),
    ("SpectraSuite/TriLM_2.4B_Unpacked", "f7f0523855503e83f90d6f0e0f79daa61fabe8d1", "prescaled-ternary", TARGET_SUFFIXES, "mid"),
    ("SpectraSuite/TriLM_3.9B_Unpacked", "90dbbd12fe60ec9835890f61b5b6a2289ad827ac", "prescaled-ternary", QUP, "mid"),
    ("1bitLLM/bitnet_b1_58-xl", "f99799ff5b55cc2dce88832644b9ff1c44f6c434", "absmean-latent", QUP, "mid"),
    ("1bitLLM/bitnet_b1_58-3B", "af89e318d78a70802061246bf037199d2fb97020", "absmean-latent", QUP, "mid"),
    ("ridger/MMfreeLM-370M", "4c799d7e1fcc66093a27acf36ab2faffd8bb9626", "absmean-latent", MMFREE, "quartiles"),
    ("ridger/MMfreeLM-1.3B", "b6d861b71c2f53ce7b84033fa764594cae972956", "absmean-latent", MMFREE, "quartiles"),
    ("ridger/MMfreeLM-2.7B", "77deff0c1c9ac79aa51eb3ab7dd34fc375bf9324", "absmean-latent", MMFREE, "mid"),
    ("prism-ml/Ternary-Bonsai-1.7B-unpacked", "3aca840085293d026ce6f6b80fafdae937fd2eeb", "group-prescaled", TARGET_SUFFIXES, "mid"),
    ("prism-ml/Ternary-Bonsai-8B-unpacked", "ac20f03fc62e872399218b659c8e949dfca05769", "group-prescaled", QUP, "mid"),
    ("NousResearch/OLMo-Bitnet-1B", "cd17870d2c3a3557b5ca8efc693117c8ea0312f3", "torch-zip-absmean", OLMO, "mid"),
] + [
    ("SpectraSuite/TriLM_99M_Unpacked_ckpts", f"step{s}", "prescaled-ternary", TARGET_SUFFIXES, "quartiles")
    for s in (10000, 30000, 60000, 100000, 150000, 210000, 280000)
]


class Remote:
    def __init__(self, repo: str, revision: str, filename: str) -> None:
        self.url = f"https://huggingface.co/{repo}/resolve/{revision}/{filename}"
        self.bytes_fetched = 0

    def get(self, start: int, end: int) -> bytes:
        for attempt in range(8):
            try:
                r = requests.get(self.url, headers={"Range": f"bytes={start}-{end}"}, timeout=(20, 120))
                r.raise_for_status()
                if len(r.content) != end - start + 1:
                    raise IOError("short read")
                self.bytes_fetched += len(r.content)
                return r.content
            except Exception as ex:  # noqa: BLE001
                print(f"  retry {attempt}: {type(ex).__name__}", flush=True)
                time.sleep(3)
        raise RuntimeError(f"range {start}-{end} failed for {self.url}")


class SafetensorsRemote(Remote):
    def __init__(self, *a) -> None:
        super().__init__(*a)
        (hlen,) = struct.unpack("<Q", self.get(0, 7))
        self.header = json.loads(self.get(8, 8 + hlen - 1))
        self.base = 8 + hlen

    def names(self) -> list[str]:
        return [k for k in self.header if k != "__metadata__"]

    def tensor(self, name: str) -> tuple[bytes, str, list[int]]:
        m = self.header[name]
        s, e = m["data_offsets"]
        return self.get(self.base + s, self.base + e - 1), m["dtype"], m["shape"]


class TorchZipRemote(Remote):
    """Metadata-only reader for zip-format pytorch_model.bin over HTTP ranges."""

    def __init__(self, *a) -> None:
        super().__init__(*a)
        head = requests.head(self.url, allow_redirects=False, timeout=30)
        size = int(head.headers["X-Linked-Size"])
        tail = self.get(size - 65536, size - 1)
        eocd = tail[tail.rfind(b"PK\x05\x06") :]
        cd_size, cd_off = struct.unpack("<II", eocd[12:20])
        z64 = tail.rfind(b"PK\x06\x06")
        if z64 >= 0:
            cd_size, cd_off = struct.unpack("<QQ", tail[z64 + 40 : z64 + 56])
        cd = self.get(cd_off, cd_off + cd_size - 1)
        self.entries = {}
        p = 0
        while cd[p : p + 4] == b"PK\x01\x02":
            comp = struct.unpack("<H", cd[p + 10 : p + 12])[0]
            csz, usz = struct.unpack("<II", cd[p + 20 : p + 28])
            nlen, xlen, clen = struct.unpack("<HHH", cd[p + 28 : p + 34])
            off = struct.unpack("<I", cd[p + 42 : p + 46])[0]
            name = cd[p + 46 : p + 46 + nlen].decode()
            extra = cd[p + 46 + nlen : p + 46 + nlen + xlen]
            q = 0
            while q < len(extra):
                hid, hl = struct.unpack("<HH", extra[q : q + 4])
                if hid == 1:
                    vals = list(struct.unpack("<" + "Q" * (hl // 8), extra[q + 4 : q + 4 + hl]))
                    if usz == 0xFFFFFFFF:
                        usz = vals.pop(0)
                    if csz == 0xFFFFFFFF:
                        csz = vals.pop(0)
                    if off == 0xFFFFFFFF:
                        off = vals.pop(0)
                q += 4 + hl
            self.entries[name] = (comp, csz, off)
            p += 46 + nlen + xlen + clen
        pkl = next(n for n in self.entries if n.endswith("data.pkl"))
        self.prefix = pkl[: -len("data.pkl")]
        self.state = _MetaUnpickler(io.BytesIO(self._entry(pkl))).load()

    def _entry(self, name: str) -> bytes:
        comp, csz, off = self.entries[name]
        lh = self.get(off, off + 29)
        nlen, xlen = struct.unpack("<HH", lh[26:30])
        data = self.get(off + 30 + nlen + xlen, off + 30 + nlen + xlen + csz - 1)
        return data if comp == 0 else zlib.decompress(data, -15)

    def names(self) -> list[str]:
        return list(self.state)

    def tensor(self, name: str) -> tuple[bytes, str, list[int]]:
        (stype, key), offset, shape = self.state[name]
        dtype = {"FloatStorage": ("<f4", "F32"), "HalfStorage": ("<f2", "F16")}[stype]
        raw = self._entry(f"{self.prefix}data/{key}")
        n = int(np.prod(shape))
        item = np.dtype(dtype[0]).itemsize
        return raw[offset * item : (offset + n) * item], dtype[1], list(shape)


class _MetaUnpickler(pickle.Unpickler):
    def find_class(self, module: str, name: str):
        if name == "_rebuild_tensor_v2":
            return lambda storage, offset, shape, stride, *rest: (storage, offset, tuple(shape))
        if name == "_rebuild_from_type_v2":
            return lambda func, typ, args, state: func(*args)
        if (module, name) == ("collections", "OrderedDict"):
            return collections.OrderedDict
        if name.endswith("Storage") or (module, name) in (
            ("torch.nn.parameter", "Parameter"),
            ("torch", "Tensor"),
        ):
            return name
        raise pickle.UnpicklingError(f"blocked {module}.{name}")

    def persistent_load(self, pid):
        return (pid[1], pid[2])


def decode_group_prescaled(w: np.ndarray, rel_tol: float = 0.01) -> tuple[np.ndarray, int, int]:
    """Return (ternary, largest valid group size, groups needing the tolerance).

    A group is valid when its nonzero magnitudes agree within rel_tol (a few
    groups differ by one float16 rounding step).
    """
    a = np.abs(w)
    largest, inexact = None, 0
    for g in (32, 64, 128, 256, 512):
        if a.shape[1] % g:
            continue
        grp = a.reshape(a.shape[0], -1, g)
        mx = grp.max(axis=2)
        mn = np.where(grp > 0, grp, np.inf).min(axis=2)
        nz = mx > 0
        if np.all(mx[nz] <= mn[nz] * (1 + rel_tol)):
            largest, inexact = g, int(np.count_nonzero(nz & (mx != mn)))
    if largest is None:
        raise ValueError("no K-group size with a single nonzero magnitude per group")
    return np.sign(w).astype(np.int8), largest, inexact


def screen(entry, quantizer: AbsmeanQuantizer) -> dict:
    repo, rev, fmt, suffixes, layers = entry
    from huggingface_hub import HfApi

    api = HfApi()
    info = api.model_info(repo, revision=rev, files_metadata=True)
    commit = info.sha
    weight_files = [s.rfilename for s in info.siblings if s.rfilename.endswith((".safetensors", ".bin"))]
    remotes = {}
    if fmt == "torch-zip-absmean":
        remotes["pytorch_model.bin"] = TorchZipRemote(repo, commit, "pytorch_model.bin")
    else:
        for fn in weight_files:
            if fn.endswith(".safetensors"):
                remotes[fn] = SafetensorsRemote(repo, commit, fn)
    where = {n: r for r in remotes.values() for n in r.names()}
    idx = sorted({int(m.group(1)) for n in where for m in [re.search(r"(?:layers|blocks)\.(\d+)\.", n)] if m})
    nl = idx[-1] + 1
    picks = [nl // 4, nl // 2, (3 * nl) // 4] if layers == "quartiles" else [nl // 2]

    per_type: dict[str, list[int]] = {}
    W = Z = 0
    inexact_groups = 0
    notes = set()
    for li in picks:
        for suffix in suffixes:
            name = next(n for n in where if re.search(rf"(?:layers|blocks)\.{li}\.{re.escape(suffix)}$", n))
            raw, dtype, shape = where[name].tensor(name)
            if dtype == "U8":
                t = unpack_hf_bitnet(np.frombuffer(raw, np.uint8).reshape(shape))
            else:
                w = to_float32(raw, dtype, shape)
                if fmt in ("absmean-latent", "torch-zip-absmean"):
                    t, _ = quantizer(w)
                elif fmt == "prescaled-ternary":
                    t, _ = decode_prescaled(w, 8)
                else:
                    t, g, inexact = decode_group_prescaled(w)
                    notes.add(f"one magnitude (within 1%) per contiguous K-group of {g}")
                    inexact_groups += inexact
            z = int(np.count_nonzero(t == 0))
            key = suffix.split(".")[-2]
            acc = per_type.setdefault(key, [0, 0])
            acc[0] += t.size
            acc[1] += z
            W += t.size
            Z += z
    result = {
        "repo_id": repo,
        "requested_revision": rev,
        "revision": commit,
        "format": fmt,
        "layers_sampled": picks,
        "num_layers": nl,
        "tensor_suffixes": list(suffixes),
        "sampled_weights": W,
        "sampled_zeros": Z,
        "sampled_zero_density": Z / W,
        "per_type_zero_density": {k: v[1] / v[0] for k, v in per_type.items()},
        "bytes_fetched": sum(r.bytes_fetched for r in remotes.values()),
    }
    if notes:
        result["notes"] = sorted(notes)
        result["groups_with_magnitudes_differing_within_tolerance"] = inexact_groups
    return result


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--only", help="substring filter on repo id / revision")
    args = ap.parse_args()

    quantizer = AbsmeanQuantizer()
    results = []
    for entry in CANDIDATES:
        if args.only and args.only not in f"{entry[0]}@{entry[1]}":
            continue
        r = screen(entry, quantizer)
        results.append(r)
        print(
            f"{r['repo_id']}@{r['requested_revision'][:12]} layers {r['layers_sampled']}/{r['num_layers']}: "
            f"sampled zero density {r['sampled_zero_density']:.4f} "
            f"({r['sampled_weights']} weights, {r['bytes_fetched'] / 1e6:.0f} MB fetched)",
            flush=True,
        )
    out = {
        "method": (
            "HTTP range reads of selected BitLinear tensors from pinned Hub revisions; "
            "sampled densities are estimates over the listed layers only."
        ),
        "quantizer_backend": quantizer.backend,
        "total_bytes_fetched": sum(r["bytes_fetched"] for r in results),
        "candidates": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(out, indent=2) + "\n")
    print(f"wrote {args.output}")


if __name__ == "__main__":
    main()
