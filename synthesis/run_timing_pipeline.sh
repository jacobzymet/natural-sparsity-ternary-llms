#!/usr/bin/env bash
# Full matched timing study -> data/timing/.
#
#   docker build -t ternary-eda synthesis/docker
#   docker run --rm -v "$PWD:/work" -w /work ternary-eda \
#     bash -c "git config --global --add safe.directory /work && bash synthesis/run_timing_pipeline.sh 2026-09-25"
set -euo pipefail

STAMP="${1:?usage: run_timing_pipeline.sh <date-stamp>}"
: "${LIBERTY:?set LIBERTY to the Nangate45 liberty file}"
RAW=synthesis/build/timing_raw_${STAMP}
DATA=data/timing

bash synthesis/run_timing_study.sh "${RAW}"
mkdir -p "${DATA}"
python3 scripts/parse_timing_study.py "${RAW}" --liberty "${LIBERTY}" \
  --output "${DATA}/matched_timing_${STAMP}.csv"
python3 scripts/timing_frontier.py "${DATA}/matched_timing_${STAMP}.csv" \
  --frontier-out "${DATA}/area_clock_frontier_${STAMP}.csv" \
  --summary-out "${DATA}/timing_summary_${STAMP}.json"
cp "${RAW}/environment.txt" "${DATA}/environment_${STAMP}.txt"
tar -C synthesis/build -czf "${DATA}/timing_raw_${STAMP}.tar.gz" "timing_raw_${STAMP}"
echo "wrote ${DATA}"
