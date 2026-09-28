# Reproducing the paper

Run commands from the repository root. Shell examples use Bash. The paper contains the methods, equations, and scope limitations.

## Paper and figure

```sh
python -m pip install matplotlib
python scripts/plot_breakeven.py \
  --checkpoints data/real_checkpoints/*_summary_2026-09-25.json \
  --output figures/breakeven.pdf
pdflatex -interaction=nonstopmode -halt-on-error paper.tex
bibtex paper
pdflatex -interaction=nonstopmode -halt-on-error paper.tex
pdflatex -interaction=nonstopmode -halt-on-error paper.tex
```

The architecture diagram is `figures/architecture_overview.tex`. GitHub Actions also builds the PDF.

## Hardware evaluation

The Dockerfile packages the evaluation environment: Ubuntu 24.04, Yosys 0.33, OpenSTA 3.1.0, Icarus Verilog 12, and Nangate45. OpenSTA and the liberty source are pinned in `synthesis/docker/Dockerfile`. Recorded versions, constraints, and hashes are in `data/{timing,power}/environment_2026-09-25.txt`.

```sh
docker build -t ternary-eda synthesis/docker
docker run --rm -v "$PWD:/work" -w /work ternary-eda \
  bash rtl/tb/run_tests.sh
docker run --rm -v "$PWD:/work" -w /work ternary-eda \
  bash -c "git config --global --add safe.directory /work && bash synthesis/run_timing_pipeline.sh 2026-09-25"
docker run --rm -v "$PWD:/work" -w /work ternary-eda \
  bash -c "git config --global --add safe.directory /work && bash synthesis/run_power_pipeline.sh 2026-09-25"
```

The pipelines regenerate the dated tables and raw archives under `data/timing/` and `data/power/`, plus the compute-and-memory estimates under `data/memory/`. The default full studies produce 696 timing rows, 168 engine-power rows, 42 loader rows, 140 power comparisons, and 91 diagnostic block rows. Each launcher records its expected runs; parsers reject incomplete or unexpected reports.

Timing sweeps use identical mapping recipes and delay targets for eight engines. The smallest netlist meeting each clock defines the area/clock frontier. Power comparisons use matched weights, activations, and row schedules, with every gate-level row result checked against the reference dot product. Raw reports are retained in the two `*_raw_2026-09-25.tar.gz` archives.

Areas exclude memory arrays and physical implementation overhead. Power uses zero-delay gate-level activity and Nangate45 cell tables, excluding glitches, wire capacitance, and clock-tree power. Memory energies are published estimates or model-derived values. The optional CACTI sensitivity value is recorded in the source CSV; its original configuration was not archived.

## Checkpoints

Large checkpoints are downloaded separately. Each exact result's `*_summary_2026-09-25.json` records its format, immutable Hub revision, file hashes, analysis command, and environment. Its matching `*_tensor_stats_2026-09-25.csv` contains per-tensor counts. Projection tensors are analyzed; embeddings, output heads, normalization tensors, and scale tensors are excluded from ternary zero statistics.

The primary workload uses Microsoft's packed `microsoft/bitnet-b1.58-2B-4T` checkpoint. To download and verify it:

```sh
python -m pip install 'huggingface_hub[hf_xet]' numpy safetensors requests
hf download microsoft/bitnet-b1.58-2B-4T model.safetensors \
  --revision 04c3b9ad9361b824064a1f25ea60a8be9599b127 \
  --local-dir checkpoints/bitnet
printf '%s  %s\n' \
  8143ae115ed6babe5e5ada8fb8c5b769d8f417802b2db042ad98b4f7ed73975b \
  checkpoints/bitnet/model.safetensors | sha256sum --check --strict
python scripts/analyze_packed_bitnet.py checkpoints/bitnet/model.safetensors \
  --output-dir data/real_bitnet
python scripts/sample_bitnet_rows.py checkpoints/bitnet/model.safetensors \
  --rows 24 --k 2560 --seed 1 --out data/power/bitnet_rows_k2560_n24_seed1
```

`analyze_ternary_checkpoint.py` supports `hf-packed`, `absmean-latent`, `prescaled-ternary`, and `gguf-q2_0`; use the recorded command in each summary to reproduce that checkpoint. Latent BitNet weights require quantization rather than exact unpacking. Install PyTorch to use the original float32 quantizer backend; `validate_absmean_quantizer.py` checks it against the packed deployment weights.

The block histograms in `data/real_bitnet/` support the storage analysis. `candidate_screen_2026-09-25.json` and the CAT-Q `*_sampled_2026-09-25.json` files contain the supplementary sampled results cited in the paper, with their revisions and selected layers. Their densities are estimates, not whole-model counts. Reproduce them with `screen_ternary_candidates.py` and `sample_gguf_q2_0.py`, respectively; both use HTTP range reads.

## Derived energy and system tables

The power pipeline generates the break-even and compute-plus-memory tables using `power_breakeven.py` and `memory_energy_model.py`. Memory constants and their sources are in `data/memory/energy_per_bit_sources.csv`.

```sh
for block in 0 128; do
  output=data/system/system_model_2026-09-25.csv
  if [ "$block" = 128 ]; then
    output=data/system/system_model_five_trit_block128_2026-09-25.csv
  fi
  python scripts/layer_system_model.py \
    data/real_checkpoints/*_tensor_stats_2026-09-25.csv \
    --compare data/power/power_vs_five_trit_2026-09-25.csv \
    --frontier data/timing/area_clock_frontier_2026-09-25.csv \
    --repack data/power/presence_repack_2026-09-25.csv \
    --memory data/memory/energy_per_bit_sources.csv \
    --other data/system/non_ternary_weights.csv \
    --five-trit-block "$block" --output "$output"
done
```

Each output has 1,872 rows: 13 checkpoints × three clocks × four designs × 12 memory points. Output-head precision assumptions and sources are in `non_ternary_weights.csv`. The model preserves the measured start/prefill schedule and charges Architecture B's presence padding and streamed loader. Scale application, attention, KV cache, and other inference costs are outside the modeled projection path; throughput is an upper bound.
