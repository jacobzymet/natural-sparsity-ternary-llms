#!/usr/bin/env python3
"""Parse synthesis/run_power_study.sh outputs into CSV tables.

Every run must (a) pass the gate-level self-check against W @ x and (b) have
all cell pins annotated from simulation; otherwise parsing fails.

Energy per cycle = trace-average total power x clock period. The reported
`energy_per_position_fj` is this value divided by five, i.e. a five-lane
cycle-normalized metric. Power traces also include row-start cycles (and one
prefill cycle for fed engines), so this field is not total trace energy
divided by the number of logical weights. Relative comparisons use matched
row schedules; the protocol-normalization difference is ~0.2% for the bare
K=2560 traces and ~0.4% for the fed traces.

With --repack-csv (scripts/parse_repack_power.py output), every Architecture B
comparison (bitcos_stream5_bank_fed) gets a second row, engine
bitcos_stream5_bank_fed+repack, that adds the presence loader's area and its
energy per weight when dedicated to one engine (a byte on 5 of 8 cycles) at
the same clock period and workload.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path

BASELINE = "tace_stream5"
FED_BASELINE = "tace_stream5_fed"
BASELINES = (BASELINE, FED_BASELINE)


def require_complete_reports(raw: Path, legacy_expected: set[str],
                             suffix: str = ".power.txt") -> None:
    """Reject missing/extra runs before writing results, including legacy archives."""
    manifest = raw / "expected_runs.txt"
    planned = manifest.read_text().splitlines() if manifest.exists() else sorted(legacy_expected)
    if not planned or any(not run.strip() for run in planned) or len(set(planned)) != len(planned):
        raise ValueError(f"{raw}: empty or invalid expected-run list")
    expected = set(planned)
    actual = {p.name[:-len(suffix)] for p in raw.glob(f"*{suffix}")}
    if actual != expected:
        missing, extra = sorted(expected - actual), sorted(actual - expected)
        raise ValueError(f"{raw}: incomplete study; missing {missing}; unexpected {extra}")


def baseline_for(engine: str) -> str:
    """Stream-fed engines are compared with the stream-fed five-trit engine."""
    return FED_BASELINE if engine.endswith("_fed") else BASELINE


def power_rows(text: str) -> dict[str, list[float]]:
    out = {}
    for line in text.splitlines():
        f = line.split()
        if f and f[0] in ("Sequential", "Combinational", "Total") and len(f) >= 5:
            try:
                out[f[0]] = [float(x) for x in f[1:5]]
            except ValueError:
                continue
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("raw", type=Path)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--compare-output", type=Path, required=True)
    ap.add_argument("--repack-csv", type=Path)
    args = ap.parse_args()
    repack = {}
    if args.repack_csv:
        for r in csv.DictReader(args.repack_csv.open(encoding="utf-8")):
            if r["input_bytes_per_8_cycles"] == "5":
                repack[(r["clock_period_ns"], r["workload"])] = r

    raw = args.raw
    workloads = {}
    for meta in raw.glob("wl_*/meta.json"):
        workloads[meta.parent.name[3:]] = json.loads(meta.read_text())
    require_complete_reports(raw, {
        f"{p.name.removesuffix('.stat.json')}__{wl}"
        for p in raw.glob("*.stat.json") for wl in workloads
    })

    rows = []
    for ptxt in sorted(raw.glob("*.power.txt")):
        run = ptxt.name[: -len(".power.txt")]
        point, wl = run.rsplit("__", 1)
        netset, engine, mapping, ptag = point.split("__")
        recipe, _, delay = mapping.rpartition("_d") if "_d" in mapping else (mapping, "", "")
        period = float(ptag[1:])

        sim = (raw / f"{run}.sim.log").read_text()
        meta = workloads[wl]
        m = re.search(r"PASS: .*, (\d+) rows x (\d+) groups", sim)
        if not m or (int(m.group(1)), int(m.group(2))) != (meta["rows"], meta["groups_per_row"]):
            raise SystemExit(f"{run}: gate-level simulation did not pass on the full workload:\n{sim}")
        ann = (raw / f"{run}.annotation.txt").read_text()
        m = re.search(r"unannotated\s+(\d+)", ann)
        if not m or int(m.group(1)) != 0:
            raise SystemExit(f"{run}: not every pin annotated from simulation:\n{ann}")
        vcd_pins = int(re.search(r"vcd\s+(\d+)", ann).group(1))

        stat = json.loads((raw / f"{point}.stat.json").read_text())
        mod = next(iter(stat["modules"].values()))
        summary = dict(l.split(maxsplit=1) for l in (raw / f"{point}.summary.txt").read_text().splitlines() if l.strip())
        slack = float(summary["worst_slack_ns"])

        p = power_rows(ptxt.read_text())
        internal, switching, leakage, total = p["Total"]
        seq_total = p["Sequential"][3]
        dyn = internal + switching
        z = meta["zero_density"]
        e_cycle_pj = total * period * 1e3
        rows.append({
            "netlist_set": netset,
            "engine": engine,
            "recipe": recipe,
            "abc_delay_target_ps": delay,
            "clock_period_ns": f"{period:.2f}",
            "area": f"{mod['area']:.3f}",
            "meets_period": "yes" if slack >= 0 else "no",
            "slack_ns": f"{slack:.4f}",
            "workload": wl,
            "weight_source": "bitnet" if wl == "bitnet" else "synthetic",
            "zero_density": f"{z:.4f}",
            "annotated_pins": vcd_pins,
            "p_internal_mw": f"{internal * 1e3:.5f}",
            "p_switching_mw": f"{switching * 1e3:.5f}",
            "p_leakage_mw": f"{leakage * 1e3:.5f}",
            "p_total_mw": f"{total * 1e3:.5f}",
            "p_sequential_mw": f"{seq_total * 1e3:.5f}",
            "energy_per_cycle_pj": f"{e_cycle_pj:.5f}",
            "energy_per_position_fj": f"{e_cycle_pj * 1e3 / 5:.3f}",
            "dynamic_energy_per_position_fj": f"{dyn * period * 1e6 / 5:.3f}",
            "energy_per_nonzero_weight_fj": f"{e_cycle_pj * 1e3 / (5 * (1 - z)):.3f}",
        })

    rows.sort(key=lambda r: (r["netlist_set"], r["clock_period_ns"], r["workload"],
                             r["engine"] not in BASELINES, r["engine"]))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()), lineterminator="\n")
        w.writeheader()
        w.writerows(rows)

    # Pair each non-baseline run with the baseline run of the same netlist
    # set, clock period and workload.
    def key(r, engine):
        return (engine, r["netlist_set"], r["clock_period_ns"], r["workload"])

    base = {key(r, r["engine"]): r for r in rows if r["engine"] in BASELINES}
    comp = []
    for r in rows:
        if r["engine"] in BASELINES:
            continue
        b = base.get(key(r, baseline_for(r["engine"])))
        if not b:
            raise ValueError(f"missing matching baseline for {key(r, r['engine'])}")
        m = workloads[r["workload"]]
        comp.append({
            "clock_period_ns": r["clock_period_ns"],
            "netlists": "default flow" if r["netlist_set"] == "default" else "smallest meeting clock",
            "workload": r["workload"],
            "zero_density": r["zero_density"],
            "engine": r["engine"],
            "five_trit_area": b["area"],
            "engine_area": r["area"],
            "five_trit_energy_per_position_fj": b["energy_per_position_fj"],
            "engine_energy_per_position_fj": r["energy_per_position_fj"],
            "energy_vs_five_trit_pct": f"{100 * (float(r['energy_per_position_fj']) / float(b['energy_per_position_fj']) - 1):+.2f}",
            "dynamic_energy_vs_five_trit_pct": f"{100 * (float(r['dynamic_energy_per_position_fj']) / float(b['dynamic_energy_per_position_fj']) - 1):+.2f}",
            "weight_bytes_vs_five_trit_pct": f"{100 * ((m['presence_bytes'] + m['sign_bytes']) / m['five_trit_bytes'] - 1):+.2f}",
            "five_trit_bits_per_weight": f"{8 * m['five_trit_bytes'] / (m['rows'] * m['k']):.5f}",
            "engine_bits_per_weight": f"{8 * (m['presence_bytes'] + m['sign_bytes']) / (m['rows'] * m['k']):.5f}",
        })
        lr = repack.get((r["clock_period_ns"], r["workload"]))
        if args.repack_csv and r["engine"] == "bitcos_stream5_bank_fed" and not lr:
            raise ValueError(f"missing loader result for {r['clock_period_ns']} ns, {r['workload']}")
        if r["engine"] == "bitcos_stream5_bank_fed" and lr:
            c = dict(comp[-1])
            e = float(r["energy_per_position_fj"]) + float(lr["energy_per_weight_fj"])
            d = float(r["dynamic_energy_per_position_fj"]) + float(lr["dynamic_energy_per_weight_fj"])
            c["engine"] = "bitcos_stream5_bank_fed+repack"
            c["engine_area"] = f"{float(r['area']) + float(lr['area']):.3f}"
            c["engine_energy_per_position_fj"] = f"{e:.3f}"
            c["energy_vs_five_trit_pct"] = f"{100 * (e / float(b['energy_per_position_fj']) - 1):+.2f}"
            c["dynamic_energy_vs_five_trit_pct"] = f"{100 * (d / float(b['dynamic_energy_per_position_fj']) - 1):+.2f}"
            comp.append(c)
    with args.compare_output.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(comp[0].keys()), lineterminator="\n")
        w.writeheader()
        w.writerows(comp)
    print(f"wrote {len(rows)} runs to {args.output} and {len(comp)} comparisons to {args.compare_output}")


if __name__ == "__main__":
    main()
