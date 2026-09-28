#!/usr/bin/env python3
"""Parse synthesis/run_timing_study.sh raw outputs into one CSV.

For every (engine, mapping) point the CSV holds mapped area, register count,
and the worst path of each path class:

  in2reg   data input port -> register
  reg2reg  register -> register
  reg2out  register -> output port
  in2out   data input port -> output port (purely combinational)

Because every input/output delay is zero and there is one ideal clock, the
minimum clock period of a class on a fixed netlist is ``period - slack``.
The engine's minimum period is the largest class minimum.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path

from parse_power_study import require_complete_reports

CLASSES = ("in2reg", "reg2reg", "reg2out", "in2out")
SEQ_PREFIXES = ("DFF", "SDFF", "DLH", "DLL", "TLAT")


def liberty_areas(path: Path) -> dict[str, float]:
    text = path.read_text(encoding="utf-8", errors="replace")
    areas: dict[str, float] = {}
    for m in re.finditer(r"\bcell\s*\(\s*\"?([A-Za-z0-9_]+)\"?\s*\)\s*\{", text):
        am = re.search(r"\barea\s*:\s*([0-9.]+)", text[m.end() : m.end() + 4000])
        if am:
            areas[m.group(1)] = float(am.group(1))
    return areas


def parse_path(path: Path) -> dict | None:
    text = path.read_text(encoding="utf-8")
    if text.strip() == "none" or "No paths found" in text:
        return None

    def grab(pattern: str) -> str:
        m = re.search(pattern, text, re.MULTILINE)
        if not m:
            raise ValueError(f"{path}: missing {pattern!r}")
        return m.group(1)

    stages = len(re.findall(r"^\s.*\s[\^v]\s+\S+/(?:Z|ZN|Q|QN|CO|S)\s+\(", text, re.MULTILINE))
    return {
        "start": grab(r"^Startpoint:\s+(\S+)"),
        "end": grab(r"^Endpoint:\s+(\S+)"),
        "arrival_ns": float(grab(r"^\s*(-?[0-9.]+)\s+data arrival time")),
        "required_ns": float(grab(r"^\s*(-?[0-9.]+)\s+data required time")),
        "slack_ns": float(grab(r"^\s*(-?[0-9.]+)\s+slack \((?:MET|VIOLATED)\)")),
        "stages": stages,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("raw", type=Path)
    ap.add_argument("--liberty", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()

    points = {p.name.removesuffix(".stat.json") for p in args.raw.glob("*.stat.json")}
    environment = args.raw / "environment.txt"
    if environment.exists():
        env = dict(line.split(maxsplit=1) for line in environment.read_text().splitlines() if line.strip())
        engines = {point.split("__")[0] for point in points}
        recipes = [key.removeprefix("recipe_") for key in env if key.startswith("recipe_") and key != "recipe_default"]
        points = {f"{engine}__default" for engine in engines} | {
            f"{engine}__{recipe}_d{delay}"
            for engine in engines for recipe in recipes for delay in env["delays_ps"].split()
        }
    require_complete_reports(args.raw, points, ".stat.json")
    areas = liberty_areas(args.liberty)
    rows = []
    for stat_path in sorted(args.raw.glob("*.stat.json")):
        point = stat_path.name[: -len(".stat.json")]
        engine, mapping = point.split("__")
        recipe, _, delay = mapping.rpartition("_d") if mapping != "default" else ("default", "", "")
        stats = json.loads(stat_path.read_text(encoding="utf-8"))
        modules = stats["modules"]
        if len(modules) != 1:
            raise ValueError(f"{stat_path}: expected one flattened module")
        mod = next(iter(modules.values()))
        if mod.get("num_memories", 0):
            raise ValueError(f"{stat_path}: unmapped memories remain")
        cells = mod["num_cells_by_type"]
        unknown = [c for c in cells if c not in areas]
        if unknown:
            raise ValueError(f"{stat_path}: cells missing from liberty: {unknown}")
        seq_cells = sum(n for c, n in cells.items() if c.startswith(SEQ_PREFIXES))
        seq_area = sum(areas[c] * n for c, n in cells.items() if c.startswith(SEQ_PREFIXES))

        summary = dict(
            line.split(maxsplit=1)
            for line in (args.raw / f"{point}.summary.txt").read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
        period = float(summary["period_ns"])
        row = {
            "engine": engine,
            "recipe": recipe,
            "abc_delay_target_ps": int(delay) if delay else "",
            "sta_period_ns": f"{period:.3f}",
            "cells": mod["num_cells"],
            "area": f"{mod['area']:.3f}",
            "seq_cells": seq_cells,
            "seq_area": f"{seq_area:.3f}",
            "comb_area": f"{mod['area'] - seq_area:.3f}",
        }
        worst_class, worst_min = "", -1.0
        for cls in CLASSES:
            p = parse_path(args.raw / f"{point}.{cls}.txt")
            if p is None:
                row.update({f"{cls}_min_period_ns": "", f"{cls}_slack_ns": "",
                            f"{cls}_stages": "", f"{cls}_start": "", f"{cls}_end": ""})
                continue
            min_period = period - p["slack_ns"]
            row.update({
                f"{cls}_min_period_ns": f"{min_period:.6f}",
                f"{cls}_slack_ns": f"{p['slack_ns']:.6f}",
                f"{cls}_stages": p["stages"],
                f"{cls}_start": p["start"],
                f"{cls}_end": p["end"],
            })
            if min_period > worst_min:
                worst_class, worst_min = cls, min_period
        worst_slack = float(summary["worst_slack_ns"])
        if abs((period - worst_slack) - worst_min) > 1e-5:
            raise ValueError(f"{point}: class paths do not cover the overall worst path")
        row.update({
            "min_period_ns": f"{worst_min:.6f}",
            "fmax_mhz": f"{1000.0 / worst_min:.2f}",
            "limiting_class": worst_class,
            "meets_period": "yes" if worst_slack >= 0 else "no",
        })
        rows.append(row)

    rows.sort(key=lambda r: (r["engine"], r["recipe"], r["abc_delay_target_ps"] or 0))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {len(rows)} rows to {args.output}")


if __name__ == "__main__":
    main()
