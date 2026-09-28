#!/usr/bin/env python3
"""Group per-cell power from synthesis/run_power_breakdown.sh by RTL block.

Flip-flops are reported as one group ("registers") wherever they sit; all
other cells are grouped by the RTL block that contains them. Every run must
pass its self-check and have every pin annotated, and the per-cell powers
must add up to the reported total.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import defaultdict
from pathlib import Path

from parse_power_study import require_complete_reports

PERIOD_NS = 2.5
BLOCK_NAMES = {
    "decode": "five-trit decoder lookup",
    "partial_dot": "sign/zero selection of activations",
    "partial_dot/reduce": "five-input adder tree",
    "reduce": "five-input adder tree",
    "presence_cursor": "presence bit cursor",
}
TOP_LEVEL = {
    "tace_stream5": "accumulator adder and row control",
    "bitcos_stream5_direct": "sign alignment, zero masking, accumulator adder and row control",
    "bitcos_stream5_directiso": "sign alignment, zero masking, accumulator adder and row control",
}


def netlist_cells(path: Path) -> tuple[dict[str, dict[str, str]], dict[str, dict[str, str]]]:
    """Per module: cell name -> cell type, and submodule instance -> module."""
    # Verilog escaped names start with a backslash and end at whitespace.
    name_re = r"(\\\S+|[^\s(]+)"
    cells, subs, mod = {}, {}, None
    modules = set(re.findall(rf"^module\s+{name_re}", path.read_text(), re.M))
    for line in path.read_text().splitlines():
        m = re.match(rf"\s*module\s+{name_re}", line)
        if m:
            mod = m.group(1)
            cells[mod], subs[mod] = {}, {}
            continue
        m = re.match(r"\s*(\S+)\s+(\S+)\s*\($", line)
        if mod and m:
            ctype, name = m.groups()
            name = name.lstrip("\\")
            (subs if ctype in modules else cells)[mod][name] = ctype
    return cells, subs


def cell_type(hier: str, top: str, cells, subs) -> str | None:
    """Liberty cell type of a leaf cell; None for a submodule instance."""
    parts = hier.split("/")
    mod = top
    for inst in parts[:-1]:
        mod = subs[mod][inst]
    if parts[-1] in subs[mod]:
        return None
    return cells[mod][parts[-1]]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("raw", type=Path)
    ap.add_argument("--workloads", type=Path, required=True, help="power study raw dir with wl_*/meta.json")
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()

    workloads = {m.parent.name[3:]: json.loads(m.read_text())
                 for m in args.workloads.glob("wl_*/meta.json")}
    require_complete_reports(args.raw, {f"{engine}__{wl}" for engine in TOP_LEVEL for wl in workloads},
                             ".instances.txt")
    rows = []
    for inst in sorted(args.raw.glob("*.instances.txt")):
        run = inst.name[: -len(".instances.txt")]
        engine, wl = run.split("__")
        meta = workloads[wl]
        match = re.search(r"PASS: .*, (\d+) rows x (\d+) groups", (args.raw / f"{run}.sim.log").read_text())
        if not match or tuple(map(int, match.groups())) != (meta["rows"], meta["groups_per_row"]):
            raise SystemExit(f"{run}: simulation did not pass")
        ann = (args.raw / f"{run}.annotation.txt").read_text()
        if int(re.search(r"unannotated\s+(\d+)", ann).group(1)) != 0:
            raise SystemExit(f"{run}: unannotated pins")
        netlist = args.raw / f"{engine}.mapped.v"
        cells, subs = netlist_cells(netlist)
        top = next(m for m in cells if all(m not in s.values() for s in subs.values()))

        groups = defaultdict(float)
        for line in inst.read_text().splitlines():
            f = line.split()
            if len(f) != 5 or not re.match(r"^[0-9.eE+-]+$", f[0]):
                continue
            name, total = f[4], float(f[3])
            parts = name.split("/")
            ctype = cell_type(name, top, cells, subs)
            if ctype is None:
                continue
            key = "registers" if ctype.startswith(("DFF", "SDFF")) else "/".join(parts[:-1])
            groups[key] += total

        report_total = next(float(l.split()[4]) for l in (args.raw / f"{run}.power.txt").read_text().splitlines()
                            if l.startswith("Total"))
        if abs(sum(groups.values()) - report_total) > 1e-3 * report_total:
            raise SystemExit(f"{run}: cell powers add to {sum(groups.values())}, report says {report_total}")
        for key, p in sorted(groups.items()):
            rows.append({
                "engine": engine,
                "workload": wl,
                "zero_density": f"{meta['zero_density']:.4f}",
                "block": key if key == "registers" else (key or "top"),
                "description": ("all flip-flops" if key == "registers"
                                else TOP_LEVEL[engine] if key == "" else BLOCK_NAMES.get(key, key)),
                "power_mw": f"{p * 1e3:.5f}",
                "energy_per_position_fj": f"{p * PERIOD_NS * 1e6 / 5:.3f}",
                "share_pct": f"{100 * p / report_total:.2f}",
            })
    with args.output.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()), lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {len(rows)} block rows to {args.output}")


if __name__ == "__main__":
    main()
