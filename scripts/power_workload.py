#!/usr/bin/env python3
"""Matched GEMV stimulus for the gate-level switching-activity study.

Both engines compute the same rows against the same activation vector:

    y[r] = sum_k W[r, k] * x[k],   K positions per row, 5 positions per cycle

Outputs (all $readmemh text) in the chosen directory:

    acts.memh        one 40-bit word per cycle group g (5 x int8, lane 0 LSB);
                     identical for every row, as in a real GEMV
    tace.memh        five-trit byte for row r, group g at index r*G+g
    presence.memh    continuous presence bitmap bytes (all rows back to back)
    signs.memh       continuous compact-sign bytes (all rows back to back)
    rows.memh        per row: {expected_dot[31:0], sign_start_bit[31:0]}
    meta.json        shapes, zero density, source, activation statistics

Weight sources:
    --bitnet-rows FILE   rows sampled from the real checkpoint (see
                         scripts/sample_bitnet_rows.py)
    --zero-density Z     i.i.d. synthetic rows: P(0)=Z, P(+1)=P(-1)=(1-Z)/2

Activations (synthetic, documented): per-token absmax int8 quantization as in
BitNet b1.58, applied to a Gaussian vector in which a small fraction of
channels are outliers. This is a modeling assumption, not a trace.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ternary_reference import encode_bitmap_sign, encode_five_trit  # noqa: E402

GROUP = 5


def synthetic_activations(k: int, rng: np.random.Generator, outlier_frac: float,
                          outlier_scale: float) -> np.ndarray:
    x = rng.standard_normal(k)
    n_out = max(1, int(round(outlier_frac * k)))
    idx = rng.choice(k, size=n_out, replace=False)
    x[idx] *= outlier_scale
    q = np.clip(np.round(x * 127.0 / np.max(np.abs(x))), -128, 127).astype(np.int64)
    return q


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("outdir", type=Path)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--bitnet-rows", type=Path)
    src.add_argument("--zero-density", type=float)
    ap.add_argument("--rows", type=int, default=24)
    ap.add_argument("--k", type=int, default=2560)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--act-outlier-frac", type=float, default=0.01)
    ap.add_argument("--act-outlier-scale", type=float, default=6.0)
    args = ap.parse_args()

    rng = np.random.default_rng(args.seed)
    if args.bitnet_rows:
        data = np.load(args.bitnet_rows)
        w = data["rows"].astype(np.int64)
        source = f"bitnet rows from {args.bitnet_rows.as_posix()}"
        if w.shape[1] != args.k:
            raise SystemExit(f"row length {w.shape[1]} != --k {args.k}")
        w = w[: args.rows]
    else:
        z = args.zero_density
        w = rng.choice([0, 1, -1], size=(args.rows, args.k), p=[z, (1 - z) / 2, (1 - z) / 2])
        source = f"synthetic iid ternary, target zero density {z}"
    rows, k = w.shape
    if k % GROUP or k % 8:
        raise SystemExit("K must be a multiple of 5 and 8")
    groups = k // GROUP

    x = synthetic_activations(k, np.random.default_rng(args.seed + 1000),
                              args.act_outlier_frac, args.act_outlier_scale)

    out = args.outdir
    out.mkdir(parents=True, exist_ok=True)

    with (out / "acts.memh").open("w") as f:
        for g in range(groups):
            word = 0
            for lane in range(GROUP):
                word |= (int(x[g * GROUP + lane]) & 0xFF) << (8 * lane)
            f.write(f"{word:010x}\n")

    with (out / "tace.memh").open("w") as f:
        for r in range(rows):
            enc = encode_five_trit(w[r].tolist())
            assert len(enc) == groups
            f.writelines(f"{b:02x}\n" for b in enc)

    flat = w.reshape(-1).tolist()
    bm = encode_bitmap_sign(flat)
    pad = b"\x00" * 4
    (out / "presence.memh").write_text("".join(f"{b:02x}\n" for b in bm.presence + pad))
    (out / "signs.memh").write_text("".join(f"{b:02x}\n" for b in bm.signs + pad))

    expected = w @ x
    nz_per_row = np.count_nonzero(w, axis=1)
    sign_start = np.concatenate([[0], np.cumsum(nz_per_row)[:-1]])
    with (out / "rows.memh").open("w") as f:
        for r in range(rows):
            f.write(f"{int(expected[r]) & 0xFFFFFFFF:08x}{int(sign_start[r]):08x}\n")

    meta = {
        "source": source,
        "seed": args.seed,
        "rows": rows,
        "k": k,
        "groups_per_row": groups,
        "zero_density": float(np.mean(w == 0)),
        "presence_bytes": len(bm.presence),
        "sign_bytes": len(bm.signs),
        "five_trit_bytes": rows * groups,
        "activation_model": {
            "kind": "synthetic gaussian with outlier channels, per-token absmax int8",
            "outlier_frac": args.act_outlier_frac,
            "outlier_scale": args.act_outlier_scale,
            "mean_abs": float(np.mean(np.abs(x))),
            "zero_fraction": float(np.mean(x == 0)),
        },
    }
    (out / "meta.json").write_text(json.dumps(meta, indent=2) + "\n")
    print(json.dumps(meta))


if __name__ == "__main__":
    main()
