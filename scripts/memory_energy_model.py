#!/usr/bin/env python3
"""Energy per weight including weight reads, for each power-study comparison.

Energy per weight position = compute energy (simulated, from the power
study) + weight bits read per weight (exact stream size of the workload) x
memory energy per bit (published estimate or modeled constant, data/memory/).
Only ternary-symbol weight traffic is modeled; activation, output, and scale
traffic are excluded. Some source constants already amortize background or
refresh energy into energy per bit; those components are scaled with payload
bits, not modeled separately. Percentages are relative to compute + modeled
ternary-symbol weight-read energy only.

Kinds: compute energies are simulated estimates; memory energies are
literature or modeled constants; every output number is a model result.
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("compare", type=Path, help="power_vs_five_trit CSV")
    ap.add_argument("memory", type=Path, help="energy_per_bit_sources CSV")
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()

    mems = list(csv.DictReader(args.memory.open(encoding="utf-8")))
    out = []
    for r in csv.DictReader(args.compare.open(encoding="utf-8")):
        e_ft = float(r["five_trit_energy_per_position_fj"])
        e_bm = float(r["engine_energy_per_position_fj"])
        b_ft = float(r["five_trit_bits_per_weight"])
        b_bm = float(r["engine_bits_per_weight"])
        for m in mems:
            e_bit_fj = 1e3 * float(m["pj_per_bit"])
            tot_ft = e_ft + b_ft * e_bit_fj
            tot_bm = e_bm + b_bm * e_bit_fj
            out.append({
                "clock_period_ns": r["clock_period_ns"],
                "netlists": r["netlists"],
                "engine": r["engine"],
                "workload": r["workload"],
                "zero_density": r["zero_density"],
                "memory_id": m["memory_id"],
                "memory_pj_per_bit": m["pj_per_bit"],
                "five_trit_compute_fj": f"{e_ft:.3f}",
                "five_trit_memory_fj": f"{b_ft * e_bit_fj:.3f}",
                "engine_compute_fj": f"{e_bm:.3f}",
                "engine_memory_fj": f"{b_bm * e_bit_fj:.3f}",
                "five_trit_total_fj_per_weight": f"{tot_ft:.3f}",
                "engine_total_fj_per_weight": f"{tot_bm:.3f}",
                "total_vs_five_trit_pct": f"{100 * (tot_bm / tot_ft - 1):+.2f}",
            })
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0].keys()), lineterminator="\n")
        w.writeheader()
        w.writerows(out)
    print(f"wrote {len(out)} rows to {args.output}")


if __name__ == "__main__":
    main()
