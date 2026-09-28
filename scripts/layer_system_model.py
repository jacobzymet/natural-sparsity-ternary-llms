#!/usr/bin/env python3
"""Layer/system model: energy per token and throughput bounds for real
ternary checkpoints, built from the per-tensor statistics of each checkpoint
and the synthesized/simulated engine results.

Per ternary tensor t with R rows (output features), K inputs, zero fraction
z and N nonzeros, for one decoded token (batch 1, every weight read once):

  cycles_t          = R * (ceil(K/5) + 2)         matched power-trace schedule: start + prefill
  five-trit bits    = R * ceil(K/5) * 8           rows start on a byte
  bitmap A bits     = R*K + N                    continuous streams
  bitmap B bits     = 5*R*ceil(K/5) + N           whole presence words per row
  compute energy    = e(z_t) * 5 * cycles_t

Architecture B's source bitmap is padded with zero presence bits at each
row end before byte packing, so the existing byte-to-five-bit loader can
fill the bank without a row-boundary shifter. Padding adds no sign bits.
Final activations are zero-padded for every design. Tail positions use the
same tensor-average compute estimate as full groups; they are not separately
simulated. Bit counts are payload costs: stream-end byte rounding and
redundant prefetch reads at row boundaries are not modeled.

e(z) is the simulated energy per weight position of each fed design at the
smallest netlist meeting the clock, linearly interpolated in z between the
synthetic zero-fraction workloads of the power study (0.2 to 0.7; outside
that range the end segments are extended and the tensor is counted in
extrapolated_tensors). Weight-read energy = bits x memory energy per bit
(literature constants). Optional non-ternary weights (for example a BF16
output head) are read identically by every design; they are added to the
"with_other_weights" columns only, and their compute is not modeled.

Throughput columns are upper bounds from this model, not measurements:
compute-bound tokens/s per mm2 of engine area (engines only, no memories)
and memory-bound tokens/s at a given bandwidth (weights only).

Designs:
  five_trit          tace_stream5_fed (baseline)
  bitmap_A           bitcos_stream5_fed: two byte streams
  bitmap_B_resident  bitcos_stream5_bank_fed: 5-bit presence memory, loader
                     not running during inference (weights resident on chip)
  bitmap_B_streamed  bitcos_stream5_bank_fed+repack: loader dedicated to the
                     engine (its area and energy added)

--five-trit-block B (sensitivity): five-trit packing restarts at every
B-weight quantization block; five-trit bits and cycles then use ceil(B/5) bytes per block
(ceil(128/5) = 26, i.e. 1.625 bits per weight). The bitmap/sign streams are
unchanged.
"""

from __future__ import annotations

import argparse
import csv
import math
from pathlib import Path

DESIGNS = {
    "five_trit": "tace_stream5_fed",
    "bitmap_A": "bitcos_stream5_fed",
    "bitmap_B_resident": "bitcos_stream5_bank_fed",
    "bitmap_B_streamed": "bitcos_stream5_bank_fed+repack",
}
BANDWIDTHS_GBPS = {"34.1": 34.1, "256": 256.0}  # illustrative bandwidth scenarios
# Matched to the power traces: start + one prefill for every fed design.
# The bitmap feeders require the prefill; the five-trit feeder can omit it.
ROW_SETUP_CYCLES = 2


def tensor_layout(rows: int, k: int, nonzeros: int,
                  five_trit_block: int = 0) -> dict[str, dict[str, int]]:
    """Execution cycles and payload bits for the implemented row interfaces."""
    groups = math.ceil(k / 5)
    ft_groups = groups
    if five_trit_block:
        full, rem = divmod(k, five_trit_block)
        ft_groups = full * math.ceil(five_trit_block / 5) + math.ceil(rem / 5)
    presence_padding = rows * (5 * groups - k)
    out = {}
    for design in DESIGNS:
        g = ft_groups if design == "five_trit" else groups
        pad = presence_padding if design.startswith("bitmap_B") else 0
        bits = rows * ft_groups * 8 if design == "five_trit" else rows * k + pad + nonzeros
        out[design] = {
            "cycles": rows * (g + ROW_SETUP_CYCLES),
            "weight_bits": bits,
            "presence_padding_bits": pad,
        }
    return out


def interp(points: list[tuple[float, float]], z: float) -> tuple[float, bool]:
    pts = sorted(points)
    i = 0
    while i < len(pts) - 2 and z > pts[i + 1][0]:
        i += 1
    (z0, e0), (z1, e1) = pts[i], pts[i + 1]
    return e0 + (e1 - e0) * (z - z0) / (z1 - z0), not pts[0][0] <= z <= pts[-1][0]


def load_energy(compare: Path) -> dict[tuple[str, str], list[tuple[float, float]]]:
    """(design, clock) -> [(z, energy per position fJ)] from synthetic workloads."""
    out: dict[tuple[str, str], list[tuple[float, float]]] = {}
    base_seen = set()
    for r in csv.DictReader(compare.open(encoding="utf-8")):
        if r["netlists"] != "smallest meeting clock" or r["workload"] == "bitnet":
            continue
        z, clk = float(r["zero_density"]), r["clock_period_ns"]
        for design, engine in DESIGNS.items():
            if r["engine"] == engine:
                out.setdefault((design, clk), []).append((z, float(r["engine_energy_per_position_fj"])))
        if r["engine"] == DESIGNS["bitmap_A"] and (clk, z) not in base_seen:
            base_seen.add((clk, z))
            out.setdefault(("five_trit", clk), []).append((z, float(r["five_trit_energy_per_position_fj"])))
    return out


def load_area(frontier: Path, repack_csv: Path) -> dict[tuple[str, str], float]:
    repack_area = float(next(csv.DictReader(repack_csv.open(encoding="utf-8")))["area"])
    out = {}
    for r in csv.DictReader(frontier.open(encoding="utf-8")):
        if float(r["input_delay_ns"]) != 0 or float(r["output_delay_ns"]) != 0:
            continue
        clk = f"{float(r['clock_period_ns']):.2f}"
        for design, engine in DESIGNS.items():
            base = engine.replace("+repack", "")
            a = r.get(f"{base}_min_area", "")
            if a:
                out[(design, clk)] = float(a) + (repack_area if engine.endswith("+repack") else 0.0)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("tensor_stats", type=Path, nargs="+", help="*_tensor_stats_*.csv per checkpoint")
    ap.add_argument("--compare", type=Path, required=True, help="power_vs_five_trit CSV")
    ap.add_argument("--frontier", type=Path, required=True, help="area_clock_frontier CSV")
    ap.add_argument("--repack", type=Path, required=True, help="presence_repack CSV")
    ap.add_argument("--memory", type=Path, required=True, help="energy_per_bit_sources CSV")
    ap.add_argument("--other", type=Path, help="CSV: checkpoint,non_ternary_weight_bytes,...")
    ap.add_argument("--clocks", default="1.60,2.00,2.50")
    ap.add_argument("--five-trit-block", type=int, default=0,
                    help="restart five-trit packing every B weights (0: once per row)")
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()

    energy = load_energy(args.compare)
    area = load_area(args.frontier, args.repack)
    mems = list(csv.DictReader(args.memory.open(encoding="utf-8")))
    other = {}
    if args.other:
        other = {r["checkpoint"]: float(r["non_ternary_weight_bytes"])
                 for r in csv.DictReader(args.other.open(encoding="utf-8"))}

    out = []
    for path in sorted(args.tensor_stats):
        ckpt = path.name.split("_tensor_stats_")[0]
        tensors = list(csv.DictReader(path.open(encoding="utf-8")))
        weights = sum(int(t["weights"]) for t in tensors)
        zeros = sum(int(t["zeros"]) for t in tensors)
        layouts = [tensor_layout(int(t["out_features"]), int(t["in_features"]),
                                 int(t["weights"]) - int(t["zeros"]), args.five_trit_block)
                   for t in tensors]
        cycles = {d: sum(layout[d]["cycles"] for layout in layouts) for d in DESIGNS}
        bits = {d: sum(layout[d]["weight_bits"] for layout in layouts) for d in DESIGNS}
        padding = {d: sum(layout[d]["presence_padding_bits"] for layout in layouts) for d in DESIGNS}
        other_bytes = other.get(ckpt, 0.0)
        for clk in args.clocks.split(","):
            e_compute, extrap = {}, 0
            for d in DESIGNS:
                total = 0.0
                for t, layout in zip(tensors, layouts):
                    e, x = interp(energy[(d, clk)], float(t["zero_density"]))
                    extrap += x and d == "five_trit"
                    total += e * 5 * layout[d]["cycles"]
                e_compute[d] = total  # fJ per token
            period = float(clk)
            for m in mems:
                e_bit_fj = 1e3 * float(m["pj_per_bit"])
                tot = {d: e_compute[d] + bits[d] * e_bit_fj for d in DESIGNS}
                tot_o = {d: tot[d] + other_bytes * 8 * e_bit_fj for d in DESIGNS}
                for d in DESIGNS:
                    row = {
                        "checkpoint": ckpt,
                        "ternary_weights": weights,
                        "zero_density": f"{zeros / weights:.4f}",
                        "clock_period_ns": clk,
                        "design": d,
                        "memory_id": m["memory_id"],
                        "memory_pj_per_bit": m["pj_per_bit"],
                        "weight_bits_per_token": bits[d],
                        "execution_cycles_per_token": cycles[d],
                        "presence_padding_bits_per_token": padding[d],
                        "bits_per_ternary_weight": f"{bits[d] / weights:.5f}",
                        "compute_uj_per_token": f"{e_compute[d] * 1e-9:.4f}",
                        "weight_read_uj_per_token": f"{bits[d] * e_bit_fj * 1e-9:.4f}",
                        "total_uj_per_token": f"{tot[d] * 1e-9:.4f}",
                        "total_vs_five_trit_pct": f"{100 * (tot[d] / tot['five_trit'] - 1):+.2f}",
                        "non_ternary_weight_bytes": f"{other_bytes:.0f}",
                        "total_with_other_weights_uj": f"{tot_o[d] * 1e-9:.4f}",
                        "with_other_weights_vs_five_trit_pct": f"{100 * (tot_o[d] / tot_o['five_trit'] - 1):+.2f}",
                        "engine_area": f"{area[(d, clk)]:.3f}",
                        "compute_bound_tokens_per_s_per_mm2": f"{(1e6 / area[(d, clk)]) * (1e9 / period) / cycles[d]:.2f}",
                        "extrapolated_tensors": extrap,
                    }
                    for name, bw in BANDWIDTHS_GBPS.items():
                        row[f"memory_bound_tokens_per_s_at_{name}GBps"] = f"{bw * 1e9 / ((bits[d] / 8) + other_bytes):.2f}"
                    out.append(row)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0].keys()), lineterminator="\n")
        w.writeheader()
        w.writerows(out)
    print(f"wrote {len(out)} rows to {args.output}")


if __name__ == "__main__":
    main()
