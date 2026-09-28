#!/usr/bin/env python3
"""Parse synthesis/run_repack_power.sh outputs into a CSV.

Energy per weight = average total power over the activity window x window
length / number of weights in the bitmap. Every run must pass the
testbench's row check and have every cell pin annotated from simulation.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path

from parse_power_study import power_rows, require_complete_reports


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("raw", type=Path, help="run_repack_power.sh output directory")
    ap.add_argument("--workloads", type=Path, required=True, help="power raw dir with wl_*/meta.json")
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()

    workloads = {m.parent.name[3:]: json.loads(m.read_text()) for m in args.workloads.glob("wl_*/meta.json")}
    require_complete_reports(args.raw, {
        f"{p.name.removesuffix('.summary.txt')}__duty{duty}__{wl}"
        for p in args.raw.glob("*__p*.summary.txt") for duty in (5, 8) for wl in workloads
    })
    stat = json.loads(next(args.raw.glob("*.stat.json")).read_text())
    mod = next(iter(stat["modules"].values()))

    rows = []
    for ptxt in sorted(args.raw.glob("*__duty*.power.txt")):
        run = ptxt.name[: -len(".power.txt")]
        name, recipe, ptag, dtag, wl = run.split("__")
        point = f"{name}__{recipe}"
        period = float(ptag[1:])
        duty = int(dtag[len("duty"):])
        meta = workloads[wl]
        sim = (args.raw / f"{run}.sim.log").read_text()
        m = re.search(r"PASS: .*duty (\d)/8, (\d+) rows x (\d+) groups", sim)
        if not m or (int(m.group(1)), int(m.group(2)), int(m.group(3))) != (duty, meta["rows"], meta["groups_per_row"]):
            raise SystemExit(f"{run}: simulation did not pass on the full bitmap:\n{sim}")
        window_ns = float(re.search(r"window_ns ([\d.]+)", sim).group(1))
        ann = (args.raw / f"{run}.annotation.txt").read_text()
        um = re.search(r"unannotated\s+(\d+)", ann)
        if not um or int(um.group(1)) != 0:
            raise SystemExit(f"{run}: not every pin annotated from simulation:\n{ann}")
        summary = dict(l.split(maxsplit=1) for l in (args.raw / f"{point}__{ptag}.summary.txt").read_text().splitlines() if l.strip())
        slack = float(summary["worst_slack_ns"])
        internal, switching, leakage, total = power_rows(ptxt.read_text())["Total"]
        weights = meta["rows"] * meta["k"]
        rows.append({
            "clock_period_ns": f"{period:.2f}",
            "input_bytes_per_8_cycles": duty,
            "workload": wl,
            "zero_density": f"{meta['zero_density']:.4f}",
            "area": f"{mod['area']:.3f}",
            "meets_period": "yes" if slack >= 0 else "no",
            "slack_ns": f"{slack:.4f}",
            "p_total_mw": f"{total * 1e3:.5f}",
            "window_ns": f"{window_ns:.4f}",
            "weights": weights,
            "energy_per_weight_fj": f"{total * window_ns * 1e6 / weights:.4f}",
            "dynamic_energy_per_weight_fj": f"{(internal + switching) * window_ns * 1e6 / weights:.4f}",
        })
    rows.sort(key=lambda r: (r["clock_period_ns"], r["input_bytes_per_8_cycles"], r["workload"]))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()), lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {len(rows)} runs to {args.output}")


if __name__ == "__main__":
    main()
