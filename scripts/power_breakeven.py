#!/usr/bin/env python3
"""Memory-energy break-even for each engine-vs-five-trit power comparison.

Per weight position, the bitmap/sign engine changes compute energy by dE
(from the gate-level power study) and changes the weight bits that must be
read from memory by dB (exact stream sizes of the same workload). If reading
one weight bit from memory costs E_bit, the bitmap/sign design saves energy
overall when dE + dB * E_bit < 0.

    dB < 0, dE > 0: saves energy only if E_bit > dE / -dB  (break-even E_bit)
    dB < 0, dE <= 0: saves energy for any E_bit
    dB > 0, dE < 0: saves energy only if E_bit < -dE / dB
    dB >= 0, dE >= 0: never saves energy

The break-even value uses only the power study itself; no memory energy is
assumed. Core-only comparisons exclude feeding hardware; *_fed comparisons
include it, and the +repack variant also includes the presence loader.
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("compare", type=Path)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()

    out = []
    for r in csv.DictReader(args.compare.open(encoding="utf-8")):
        de = float(r["engine_energy_per_position_fj"]) - float(r["five_trit_energy_per_position_fj"])
        db = float(r["engine_bits_per_weight"]) - float(r["five_trit_bits_per_weight"])
        if db < 0 and de > 0:
            rule, be = "saves if memory energy per bit is above", de / -db / 1e3
        elif db < 0 or (db == 0 and de < 0):
            rule, be = "saves at any memory energy per bit", None
        elif de < 0:
            rule, be = "saves only if memory energy per bit is below", -de / db / 1e3
        else:
            rule, be = "never saves", None
        out.append({
            "clock_period_ns": r["clock_period_ns"],
            "netlists": r["netlists"],
            "engine": r["engine"],
            "workload": r["workload"],
            "zero_density": r["zero_density"],
            "compute_energy_delta_fj_per_weight": f"{de:+.3f}",
            "memory_bits_delta_per_weight": f"{db:+.5f}",
            "outcome": rule,
            "break_even_memory_pj_per_bit": "" if be is None else f"{be:.3f}",
        })
    with args.output.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0].keys()), lineterminator="\n")
        w.writeheader()
        w.writerows(out)
    print(f"wrote {len(out)} break-even rows to {args.output}")


if __name__ == "__main__":
    main()
