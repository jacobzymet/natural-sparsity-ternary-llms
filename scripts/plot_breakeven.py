#!/usr/bin/env python3
"""Paper figure: modeled compute + weight-read energy of the stream-fed
bitmap/sign designs relative to stream-fed five-trit, versus zero fraction,
with the zero fractions of the analyzed real checkpoints marked.

Inputs are the committed CSV/JSON files; nothing is recomputed here.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

MEMORIES = [
    ("sram_32kb_45nm", "32 KB SRAM (0.31 pJ/bit)", "-", "o"),
    ("sram_1mb_45nm", "1 MB SRAM (1.56 pJ/bit)", "--", "s"),
    ("hbm2_streamed", "HBM2 streaming (3.59 pJ/bit)", "-.", "^"),
    ("lpddr4_package", "LPDDR4 (about 12 pJ/bit)", ":", "D"),
]
PANELS = [
    ("bitcos_stream5_fed", "(a) Two byte streams (Architecture A)"),
    ("bitcos_stream5_bank_fed+repack", "(b) Five-bit presence memory + loader (B, streamed)"),
]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--energy", type=Path, default=Path("data/memory/energy_with_weight_reads_2026-09-25.csv"))
    ap.add_argument("--checkpoints", type=Path, nargs="+", required=True, help="*_summary_*.json")
    ap.add_argument("--clock", default="2.00")
    ap.add_argument("--output", type=Path, default=Path("figures/breakeven.pdf"))
    args = ap.parse_args()

    rows = [
        r for r in csv.DictReader(args.energy.open())
        if r["clock_period_ns"] == args.clock and r["netlists"] == "smallest meeting clock"
        and r["workload"].startswith("z")
    ]
    zs = sorted({float(json.loads(p.read_text())["zero_density"]) for p in args.checkpoints})

    fig, axes = plt.subplots(1, 2, figsize=(7.0, 2.9), sharey=True)
    for ax, (engine, title) in zip(axes, PANELS):
        for mem, label, ls, mk in MEMORIES:
            pts = sorted(
                (float(r["zero_density"]), float(r["total_vs_five_trit_pct"]))
                for r in rows if r["engine"] == engine and r["memory_id"] == mem
            )
            if not pts:
                raise SystemExit(f"no rows for {engine} {mem} at {args.clock} ns")
            ax.plot(*zip(*pts), ls=ls, marker=mk, ms=3, lw=1.1, color="black", label=label)
        zline = [0.2, 0.7]
        ax.plot(zline, [((2 - z) / 1.6 - 1) * 100 for z in zline], color="0.6", lw=0.8,
                label="bits read only (memory-dominated limit)")
        ax.axhline(0, color="0.3", lw=0.6)
        for z in zs:
            ax.axvline(z, ymin=0, ymax=0.06, color="tab:red", lw=0.8)
        ax.set_title(title, fontsize=8)
        ax.set_xlabel("zero fraction $z$", fontsize=8)
        ax.set_xlim(0.18, 0.72)
        ax.tick_params(labelsize=7)
        ax.grid(alpha=0.25, lw=0.4)
    axes[0].set_ylabel("energy vs five-trit (%)", fontsize=8)
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncol=3, fontsize=6.5, frameon=False)
    fig.tight_layout(rect=(0, 0.13, 1, 1))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.output)
    print(f"wrote {args.output} ({len(zs)} checkpoint zero fractions marked)")


if __name__ == "__main__":
    main()
