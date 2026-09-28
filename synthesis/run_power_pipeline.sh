#!/usr/bin/env bash
# Full matched switching-activity power study -> data/power/.
#
#   docker build -t ternary-eda synthesis/docker
#   docker run --rm -v "$PWD:/work" -w /work ternary-eda \
#     bash -c "git config --global --add safe.directory /work && bash synthesis/run_power_pipeline.sh 2026-09-25"
set -euo pipefail

STAMP="${1:?usage: run_power_pipeline.sh <date-stamp>}"
: "${LIBERTY:?set LIBERTY to the Nangate45 liberty file}"
RAW=synthesis/build/power_raw_${STAMP}
DATA=data/power

bash synthesis/run_power_study.sh "${RAW}"
mkdir -p "${DATA}"
bash synthesis/run_repack_power.sh "${RAW}" "${RAW}/repack"
python3 scripts/parse_repack_power.py "${RAW}/repack" --workloads "${RAW}" \
  --output "${DATA}/presence_repack_${STAMP}.csv"
python3 scripts/parse_power_study.py "${RAW}" \
  --output "${DATA}/matched_power_${STAMP}.csv" \
  --compare-output "${DATA}/power_vs_five_trit_${STAMP}.csv" \
  --repack-csv "${DATA}/presence_repack_${STAMP}.csv"
bash synthesis/run_power_breakdown.sh "${RAW}" "${RAW}/breakdown"
python3 scripts/parse_power_breakdown.py "${RAW}/breakdown" --workloads "${RAW}" \
  --output "${DATA}/power_breakdown_${STAMP}.csv"
python3 scripts/power_breakeven.py "${DATA}/power_vs_five_trit_${STAMP}.csv" \
  --output "${DATA}/memory_breakeven_${STAMP}.csv"
python3 scripts/memory_energy_model.py "${DATA}/power_vs_five_trit_${STAMP}.csv" \
  data/memory/energy_per_bit_sources.csv \
  --output "data/memory/energy_with_weight_reads_${STAMP}.csv"
cp "${RAW}/environment.txt" "${DATA}/environment_${STAMP}.txt"
tar -C synthesis/build -czf "${DATA}/power_raw_${STAMP}.tar.gz" \
  --exclude='*.memh' "power_raw_${STAMP}"
echo "wrote ${DATA}"
