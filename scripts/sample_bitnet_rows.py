#!/usr/bin/env python3
"""Sample exact ternary rows from the packed BitNet checkpoint.

Rows are drawn uniformly (seeded) from every row of every target BitLinear
tensor whose input width equals --k (2560 for q/k/v/o/gate/up in
microsoft/bitnet-b1.58-2B-4T). The rows and their provenance are saved so the
power workload can be regenerated without the 1.18 GB checkpoint.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from safetensors import safe_open

sys.path.insert(0, str(Path(__file__).resolve().parent))
from analyze_packed_bitnet import is_target, unpack_hf_bitnet  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("checkpoint", type=Path)
    ap.add_argument("--rows", type=int, default=24)
    ap.add_argument("--k", type=int, default=2560)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    with safe_open(str(args.checkpoint), framework="np") as f:
        names = sorted(n for n in f.keys() if is_target(n))
        shapes = {}
        for n in names:
            packed_rows, in_features = f.get_slice(n).get_shape()
            if in_features == args.k:
                shapes[n] = packed_rows * 4
        tensors = sorted(shapes)
        offsets = np.cumsum([0] + [shapes[n] for n in tensors])
        rng = np.random.default_rng(args.seed)
        picks = np.sort(rng.choice(offsets[-1], size=args.rows, replace=False))

        rows, prov = [], []
        cache: dict[str, np.ndarray] = {}
        for p in picks:
            t = int(np.searchsorted(offsets, p, side="right") - 1)
            name = tensors[t]
            r = int(p - offsets[t])
            if name not in cache:
                cache.clear()
                cache[name] = unpack_hf_bitnet(f.get_tensor(name))
            row = cache[name][r].astype(np.int8)
            rows.append(row)
            prov.append({"tensor": name, "row": r, "zero_density": float(np.mean(row == 0))})

    w = np.stack(rows)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(args.out, rows=w)
    meta = {
        "checkpoint": "microsoft/bitnet-b1.58-2B-4T model.safetensors",
        "seed": args.seed,
        "k": args.k,
        "eligible_tensors": len(tensors),
        "eligible_rows": int(offsets[-1]),
        "zero_density": float(np.mean(w == 0)),
        "rows": prov,
    }
    args.out.with_suffix(".json").write_text(json.dumps(meta, indent=2) + "\n")
    print(json.dumps({k: v for k, v in meta.items() if k != "rows"}))


if __name__ == "__main__":
    main()
