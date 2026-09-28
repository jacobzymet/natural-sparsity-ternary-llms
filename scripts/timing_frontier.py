#!/usr/bin/env python3
"""Area-versus-clock frontier from the parsed timing study CSV.

For each engine and each clock period T, report the smallest mapped area of
any synthesized netlist (any recipe, any delay target) whose OpenSTA minimum
period is <= T. Every engine is drawn from the same recipes and targets.

Input/output-delay sensitivity: on a fixed netlist, giving every data input
an arrival time d after the clock edge adds exactly d to the input->register
and input->output path classes; requiring every output o before the next
edge adds o to the register->output and input->output classes. So
min_period(d, o) = max(in2reg + d, reg2reg, reg2out + o, in2out + d + o).
For the stream-fed engines, d stands for the weight memory's clock-to-output
time and o for its address/enable setup time.

Engines tagged *_fed are compared with the fed five-trit engine; all others
with the bare five-trit engine.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

BASELINE = "tace_stream5"
FED_BASELINE = "tace_stream5_fed"


def baseline_for(engine: str, engines: list[str]) -> str:
    return FED_BASELINE if engine.endswith("_fed") and FED_BASELINE in engines else BASELINE


def load(path: Path) -> list[dict]:
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    for r in rows:
        r["area_f"] = float(r["area"])
        for cls in ("in2reg", "reg2reg", "reg2out", "in2out"):
            v = r[f"{cls}_min_period_ns"]
            r[f"{cls}_f"] = float(v) if v else None
    return rows


def min_period(r: dict, input_delay: float, output_delay: float = 0.0) -> float:
    extra = {"in2reg": input_delay, "reg2reg": 0.0, "reg2out": output_delay,
             "in2out": input_delay + output_delay}
    return max(r[f"{c}_f"] + x for c, x in extra.items() if r[f"{c}_f"] is not None)


def best_area(rows: list[dict], period: float, input_delay: float, output_delay: float = 0.0) -> dict | None:
    ok = [r for r in rows if min_period(r, input_delay, output_delay) <= period + 1e-9]
    return min(ok, key=lambda r: r["area_f"]) if ok else None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("timing_csv", type=Path)
    ap.add_argument("--frontier-out", type=Path, required=True)
    ap.add_argument("--summary-out", type=Path, required=True)
    ap.add_argument("--input-delays", default="0,0.1,0.2,0.3")
    ap.add_argument("--output-delays", default="0,0.1")
    args = ap.parse_args()

    rows = load(args.timing_csv)
    engines = sorted({r["engine"] for r in rows},
                     key=lambda e: (e not in (BASELINE, FED_BASELINE), e != BASELINE, e))
    by_engine = {e: [r for r in rows if r["engine"] == e] for e in engines}
    delays = [float(x) for x in args.input_delays.split(",")]
    out_delays = [float(x) for x in args.output_delays.split(",")]

    periods = [round(1.30 + 0.05 * i, 2) for i in range(27)]  # 1.30 .. 2.60 ns
    frontier = []
    for o in out_delays:
        for d in delays:
            for t in periods:
                out = {"input_delay_ns": f"{d:.2f}", "output_delay_ns": f"{o:.2f}",
                       "clock_period_ns": f"{t:.2f}"}
                best = {e: best_area(by_engine[e], t, d, o) for e in engines}
                for e in engines:
                    b = best[e]
                    out[f"{e}_min_area"] = f"{b['area_f']:.3f}" if b else ""
                    out[f"{e}_point"] = (f"{b['recipe']}:{b['abc_delay_target_ps']}" if b else "")
                    base = best[baseline_for(e, engines)]
                    if e not in (BASELINE, FED_BASELINE):
                        out[f"{e}_area_vs_five_trit_pct"] = (
                            f"{100.0 * (b['area_f'] / base['area_f'] - 1.0):+.2f}" if (b and base) else ""
                        )
                frontier.append(out)

    args.frontier_out.parent.mkdir(parents=True, exist_ok=True)
    with args.frontier_out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(frontier[0].keys()), lineterminator="\n")
        w.writeheader()
        w.writerows(frontier)

    summary: dict = {"source": str(args.timing_csv).replace("\\", "/"), "engines": {}}
    for e in engines:
        rs = by_engine[e]
        default = next(r for r in rs if r["recipe"] == "default")
        per_delay = {}
        for o in out_delays:
            for d in delays:
                fastest = min(rs, key=lambda r: (min_period(r, d, o), r["area_f"]))
                key = f"{d:.2f}" if o == 0 else f"{d:.2f}_out{o:.2f}"
                per_delay[key] = {
                    "min_period_ns": round(min_period(fastest, d, o), 6),
                    "fmax_mhz": round(1000.0 / min_period(fastest, d, o), 2),
                    "area_at_min_period": fastest["area_f"],
                    "point": f"{fastest['recipe']}:{fastest['abc_delay_target_ps']}",
                }
        summary["engines"][e] = {
            "baseline": baseline_for(e, engines),
            "default_flow": {
                "area": default["area_f"],
                "cells": int(default["cells"]),
                "min_period_ns": float(default["min_period_ns"]),
                "limiting_class": default["limiting_class"],
            },
            "smallest_area_any_recipe": min(r["area_f"] for r in rs),
            "fastest_by_input_delay": per_delay,
        }
    args.summary_out.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {args.frontier_out} and {args.summary_out}")


if __name__ == "__main__":
    main()
