#!/usr/bin/env python3
"""Characterize exact ternary weights in the official packed BitNet checkpoint.

The official offline BitNet safetensors pack four ternary values into each
uint8 along the first (output) dimension. The packing convention matches
Hugging Face Transformers' BitNet integration:

    stored_code = ternary + 1
    ternary in {-1, 0, +1} -> code in {0, 1, 2}
    four 2-bit codes per uint8

This script reads only the packed BitLinear weight tensors, reconstructs the
exact ternary matrices, and reports:
- model/tensor zero density
- row zero-density quantiles
- block-local zero-count histograms
- exact representation byte counts for dense2, five-trit, and BITCOS layouts

It intentionally excludes embeddings, normalization tensors, and scales from
the ternary-weight statistics.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import defaultdict
from pathlib import Path

import numpy as np
from safetensors import safe_open


TARGET_SUFFIXES = (
    "self_attn.q_proj.weight",
    "self_attn.k_proj.weight",
    "self_attn.v_proj.weight",
    "self_attn.o_proj.weight",
    "mlp.gate_proj.weight",
    "mlp.up_proj.weight",
    "mlp.down_proj.weight",
)

DEFAULT_BLOCKS = (4, 5, 8, 16, 32, 64, 128)


def is_target(name: str) -> bool:
    return any(name.endswith(suffix) for suffix in TARGET_SUFFIXES)


def unpack_hf_bitnet(packed: np.ndarray) -> np.ndarray:
    """Unpack official HF BitNet uint8 weights to int8 {-1,0,+1}."""
    if packed.dtype != np.uint8:
        raise TypeError(f"expected uint8 packed weight, got {packed.dtype}")
    if packed.ndim != 2:
        raise ValueError(f"expected 2D packed BitLinear weight, got {packed.shape}")

    packed_rows, in_features = packed.shape
    out = np.empty((packed_rows * 4, in_features), dtype=np.int8)

    invalid = 0
    for i in range(4):
        codes = ((packed >> (2 * i)) & 0x3).astype(np.int8)
        invalid += int(np.count_nonzero(codes == 3))
        start = i * packed_rows
        out[start : start + packed_rows] = codes - 1

    if invalid:
        raise ValueError(f"checkpoint contains {invalid} reserved 2-bit code(s)")
    return out


def quantile(values: np.ndarray, q: float) -> float:
    return float(np.quantile(values, q))


def five_trit_row_bytes(k: int, quant_block: int = 128) -> int:
    """Five-trit byte packing that restarts at quantization-block boundaries."""
    full, rem = divmod(k, quant_block)
    total = full * math.ceil(quant_block / 5)
    if rem:
        total += math.ceil(rem / 5)
    return total


def block_histogram(zero_mask: np.ndarray, block: int) -> tuple[np.ndarray, int]:
    """Histogram of zero count for complete contiguous K-blocks per row."""
    rows, k = zero_mask.shape
    full_blocks = k // block
    if full_blocks == 0:
        return np.zeros(block + 1, dtype=np.int64), k

    trimmed = zero_mask[:, : full_blocks * block]
    counts = trimmed.reshape(rows, full_blocks, block).sum(axis=2)
    hist = np.bincount(counts.reshape(-1), minlength=block + 1)
    remainder = k - full_blocks * block
    return hist.astype(np.int64), remainder


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("checkpoint", help="Path to packed model.safetensors")
    ap.add_argument("--output-dir", default="data/real_bitnet")
    ap.add_argument(
        "--blocks",
        default=",".join(map(str, DEFAULT_BLOCKS)),
        help="Comma-separated K block sizes",
    )
    args = ap.parse_args()

    checkpoint = Path(args.checkpoint)
    outdir = Path(args.output_dir)
    outdir.mkdir(parents=True, exist_ok=True)
    blocks = tuple(int(x) for x in args.blocks.split(",") if x)

    tensor_rows: list[dict] = []
    aggregate_hist = {b: np.zeros(b + 1, dtype=np.int64) for b in blocks}
    aggregate_remainders = defaultdict(int)

    total_weights = 0
    total_zeros = 0
    total_nonzeros = 0
    total_dense2_bytes = 0
    total_five_trit_bytes = 0
    total_bitcos_tensor_bytes = 0
    total_bitcos_row_bytes = 0
    total_bitcos_rowptr32_bytes = 0

    with safe_open(str(checkpoint), framework="numpy") as f:
        names = [name for name in f.keys() if is_target(name)]
        if not names:
            raise RuntimeError("no expected packed BitLinear tensors found")

        for idx, name in enumerate(names, start=1):
            packed = f.get_tensor(name)
            if packed.dtype != np.uint8:
                raise TypeError(
                    f"{name}: expected uint8 packed offline BitNet weight, "
                    f"got {packed.dtype}"
                )

            ternary = unpack_hf_bitnet(packed)
            rows, k = ternary.shape
            zero_mask = ternary == 0
            row_zeros = zero_mask.sum(axis=1).astype(np.int64)
            row_density = row_zeros / k

            zeros = int(row_zeros.sum())
            weights = int(ternary.size)
            nonzeros = weights - zeros
            density = zeros / weights

            dense2_bytes = rows * math.ceil(2 * k / 8)
            five_bytes = rows * five_trit_row_bytes(k, 128)

            # Continuous bitmap and sign streams across the complete tensor.
            bitcos_tensor_bytes = math.ceil(weights / 8) + math.ceil(nonzeros / 8)

            # A row-addressable variant: bitmap rows are fixed-width; compact
            # signs are byte-rounded at each row.
            bitcos_row_bytes = rows * math.ceil(k / 8) + int(
                np.ceil((k - row_zeros) / 8).sum()
            )

            # Conservative alternative: keep signs continuous and store one
            # 32-bit sign bit-offset per row plus one terminal pointer.
            bitcos_rowptr32_bytes = bitcos_tensor_bytes + 4 * (rows + 1)

            tensor_rows.append(
                {
                    "tensor": name,
                    "packed_shape": "x".join(map(str, packed.shape)),
                    "out_features": rows,
                    "in_features": k,
                    "weights": weights,
                    "zeros": zeros,
                    "zero_density": density,
                    "row_zero_density_p05": quantile(row_density, 0.05),
                    "row_zero_density_p25": quantile(row_density, 0.25),
                    "row_zero_density_p50": quantile(row_density, 0.50),
                    "row_zero_density_p75": quantile(row_density, 0.75),
                    "row_zero_density_p95": quantile(row_density, 0.95),
                    "row_zero_density_min": float(row_density.min()),
                    "row_zero_density_max": float(row_density.max()),
                    "dense2_bytes": dense2_bytes,
                    "five_trit_128block_bytes": five_bytes,
                    "bitcos_tensor_continuous_bytes": bitcos_tensor_bytes,
                    "bitcos_row_aligned_bytes": bitcos_row_bytes,
                    "bitcos_continuous_plus_rowptr32_bytes": bitcos_rowptr32_bytes,
                }
            )

            for block in blocks:
                hist, remainder = block_histogram(zero_mask, block)
                aggregate_hist[block] += hist
                if remainder:
                    aggregate_remainders[(block, remainder)] += rows

            total_weights += weights
            total_zeros += zeros
            total_nonzeros += nonzeros
            total_dense2_bytes += dense2_bytes
            total_five_trit_bytes += five_bytes
            total_bitcos_tensor_bytes += bitcos_tensor_bytes
            total_bitcos_row_bytes += bitcos_row_bytes
            total_bitcos_rowptr32_bytes += bitcos_rowptr32_bytes

            print(
                f"[{idx:3d}/{len(names)}] {name}: "
                f"{rows}x{k}, zero={density:.5f}"
            )

    tensor_csv = outdir / "tensor_stats.csv"
    with tensor_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(tensor_rows[0].keys()))
        writer.writeheader()
        writer.writerows(tensor_rows)

    hist_csv = outdir / "block_zero_histogram.csv"
    with hist_csv.open("w", newline="", encoding="utf-8") as f:
        fieldnames = ["block_size", "zero_count", "zero_density", "blocks"]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for block in blocks:
            hist = aggregate_hist[block]
            for zeros, count in enumerate(hist):
                if count:
                    writer.writerow(
                        {
                            "block_size": block,
                            "zero_count": zeros,
                            "zero_density": zeros / block,
                            "blocks": int(count),
                        }
                    )

    block_summary = {}
    for block in blocks:
        hist = aggregate_hist[block]
        nblocks = int(hist.sum())
        zero_sum = int(sum(i * int(n) for i, n in enumerate(hist)))
        block_summary[str(block)] = {
            "complete_blocks": nblocks,
            "mean_zero_density": zero_sum / (block * nblocks) if nblocks else None,
            "histogram": [int(x) for x in hist],
        }

    summary = {
        "checkpoint": checkpoint.name,
        "target_tensor_count": len(tensor_rows),
        "weights": total_weights,
        "zeros": total_zeros,
        "nonzeros": total_nonzeros,
        "zero_density": total_zeros / total_weights,
        "representation_bytes": {
            "dense2_row_aligned": total_dense2_bytes,
            "five_trit_128block": total_five_trit_bytes,
            "bitcos_tensor_continuous": total_bitcos_tensor_bytes,
            "bitcos_row_aligned": total_bitcos_row_bytes,
            "bitcos_tensor_continuous_plus_rowptr32": total_bitcos_rowptr32_bytes,
        },
        "ratios_vs_five_trit": {
            "dense2": total_dense2_bytes / total_five_trit_bytes,
            "bitcos_tensor_continuous": total_bitcos_tensor_bytes / total_five_trit_bytes,
            "bitcos_row_aligned": total_bitcos_row_bytes / total_five_trit_bytes,
            "bitcos_continuous_plus_rowptr32": total_bitcos_rowptr32_bytes
            / total_five_trit_bytes,
        },
        "block_stats": block_summary,
        "ignored_partial_blocks": {
            f"{block}:{remainder}": rows
            for (block, remainder), rows in aggregate_remainders.items()
        },
    }

    summary_json = outdir / "summary.json"
    summary_json.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    print("\nSUMMARY")
    print(json.dumps(summary, indent=2))
    print(f"wrote {tensor_csv}")
    print(f"wrote {hist_csv}")
    print(f"wrote {summary_json}")


if __name__ == "__main__":
    main()
