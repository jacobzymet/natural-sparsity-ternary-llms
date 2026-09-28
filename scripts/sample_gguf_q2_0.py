#!/usr/bin/env python3
"""Sampled zero density of a Q2_0 GGUF checkpoint on the Hugging Face Hub,
read with HTTP range requests (header plus the projection tensors of a few
layers; never the whole file).

The header is parsed and the tensors decoded with the same code as
analyze_ternary_checkpoint.py (GGUFFile, decode_q2_0). Results are estimates
over the sampled layers, not whole-model statistics.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
import tempfile
from pathlib import Path

import numpy as np
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from analyze_ternary_checkpoint import (  # noqa: E402
    Q2_0_BLOCK_BYTES,
    Q2_0_GROUP,
    GGUFFile,
    decode_q2_0,
    gguf_hf_name,
    layer_index,
)


def fetch(url: str, start: int, end: int) -> bytes:
    for _ in range(5):
        r = requests.get(url, headers={"Range": f"bytes={start}-{end}"}, timeout=120)
        if r.status_code == 206 and len(r.content) == end - start + 1:
            return r.content
    raise RuntimeError(f"range {start}-{end} failed ({r.status_code})")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--repo-id", required=True)
    ap.add_argument("--revision", required=True)
    ap.add_argument("--file", required=True, help="path of the GGUF inside the repo")
    ap.add_argument("--layers", default="", help="comma-separated layer indices (default: 1/4, 1/2, 3/4)")
    ap.add_argument("--header-bytes", type=int, default=32 << 20)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()

    url = f"https://huggingface.co/{args.repo_id}/resolve/{args.revision}/{args.file}"
    with tempfile.TemporaryDirectory() as tmp:
        head = Path(tmp) / "header.gguf"
        head.write_bytes(fetch(url, 0, args.header_bytes - 1))
        g = GGUFFile(head)
    targets = {n: gguf_hf_name(n) for n in g.tensors if gguf_hf_name(n)}
    n_layers = 1 + max(layer_index(h) for h in targets.values())
    layers = [int(x) for x in args.layers.split(",") if x] or [n_layers // 4, n_layers // 2, 3 * n_layers // 4]

    rows, weights, zeros, fetched = [], 0, 0, 0
    for gname, hf in sorted(targets.items(), key=lambda kv: (layer_index(kv[1]), kv[1])):
        if layer_index(hf) not in layers:
            continue
        info = g.tensors[gname]
        k, r = info["dims"]
        nbytes = r * (k // Q2_0_GROUP) * Q2_0_BLOCK_BYTES
        start = g.data_start + info["offset"]
        raw = np.frombuffer(fetch(url, start, start + nbytes - 1), dtype=np.uint8)
        fetched += nbytes
        ternary, stats = decode_q2_0(raw.reshape(r, k // Q2_0_GROUP, Q2_0_BLOCK_BYTES))
        z = int(np.count_nonzero(ternary == 0))
        rows.append({"tensor": hf, "out_features": r, "in_features": k, "weights": int(ternary.size),
                     "zeros": z, "zero_density": z / ternary.size, **stats})
        weights += ternary.size
        zeros += z
        print(f"{hf}: {r}x{k} zero={z / ternary.size:.4f}")

    summary = {
        "repo_id": args.repo_id,
        "revision": args.revision,
        "file": args.file,
        "method": "sampled (HTTP range reads of the listed layers); estimate, not whole-model",
        "script": "scripts/sample_gguf_q2_0.py",
        "date": _dt.date.today().isoformat(),
        "architecture": g.metadata.get("general.architecture"),
        "layers_total": n_layers,
        "layers_sampled": layers,
        "bytes_fetched": fetched,
        "sampled_weights": int(weights),
        "sampled_zeros": int(zeros),
        "sampled_zero_density": zeros / weights,
        "tensors": rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"{args.file}: sampled zero density {zeros / weights:.4f} over layers {layers}/{n_layers} -> {args.output}")


if __name__ == "__main__":
    main()
