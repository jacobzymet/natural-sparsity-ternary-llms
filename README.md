# Natural-Sparsity Acceleration for Ternary LLMs

[Paper](paper.pdf) · [Source](paper.tex) · [Reproduction guide](REPRODUCING.md)

Does natural ternary sparsity justify a presence bitmap and compact sign stream instead of five-trit packing for batch-1 GEMV hardware?

The matched Nangate45 study finds shorter clock periods, but streamed bitmap/sign engines cost more area and compute energy. Storage improves above 40% zeros. Across 13 checkpoints, the nine tested quantization-aware or fine-tuned models save at most 1.3% in the modeled projection path. Higher-zero CAT-Q Qwen3 models retain about 2% savings after scale and output-head weight reads.

Results are pre-layout estimates. Memory energy and throughput are modeled; the paper states the assumptions and limitations.

## Contents

- `paper.tex`, `paper.pdf`, `references.bib`, `figures/`: manuscript and figures.
- `rtl/`: evaluated five-position engines, feeders, presence loader, and testbenches.
- `synthesis/`: Docker environment and matched timing/power pipelines.
- `scripts/`: checkpoint analysis, result parsing, energy models, and plotting.
- `data/`: supporting measurements, raw reports, checkpoint statistics, and provenance.
- `tests/`: encoding, checkpoint-decoder, row-accounting, and pipeline-integrity tests.

## Verify

```sh
python -m pip install pytest numpy safetensors
python -m pytest -q
bash rtl/tb/run_tests.sh  # requires Icarus Verilog
```

GitHub Actions runs these checks and builds the paper. See [REPRODUCING.md](REPRODUCING.md) for the full reproduction commands.
