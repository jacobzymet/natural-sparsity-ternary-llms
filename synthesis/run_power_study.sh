#!/usr/bin/env bash
# Matched switching-activity power study for the bare five-position engines.
#
# For each netlist point (engine, recipe, delay target, clock period):
#   1. synthesize the netlist (same recipes as the timing study)
#   2. check with OpenSTA that it meets the clock period
#   3. simulate the gate-level netlist (zero delay) on every workload; the
#      testbench checks every row result against numpy's W @ x
#   4. annotate the simulated activity of every cell pin in OpenSTA and
#      report internal, switching and leakage power at that clock period
#
# What the numbers are: synthesized netlist + simulated activity + Nangate45
# liberty power tables. Not included: glitches (zero-delay simulation), wire
# capacitance, clock tree, memories, and the direct engine's byte registers
# (which are modeled behaviorally in the testbench).
#
# Usage (inside the ternary-eda container, from the repo root):
#   bash synthesis/run_power_study.sh [outdir]
set -euo pipefail
source synthesis/abc_recipes.sh
source synthesis/study_jobs.sh

OUT="${1:-synthesis/build/power_raw}"
: "${LIBERTY:?set LIBERTY to the Nangate45 liberty file}"
JOBS="${JOBS:-$(nproc)}"
ROWS="${ROWS:-24}"
K=2560
NGROUPS=$((K / 5))
ZSWEEP="${ZSWEEP:-0.20 0.30 0.4221 0.50 0.60 0.70}"
BITNET_ROWS="${BITNET_ROWS:-data/power/bitnet_rows_k2560_n24_seed1.npz}"
VCD_TMP="${VCD_TMP:-/tmp/power_vcd}"

# set|engine|recipe|delay_ps|period_ns  (delay empty for the default recipe)
# "frontier" points are the smallest netlist of each engine that meets the
# period, from data/timing/area_clock_frontier_2026-09-25.csv. "default"
# points are the unchanged area-flow netlists.
POINTS=(
  "default|tace_stream5|default||2.5"
  "default|bitcos_stream5_direct|default||2.5"
  "frontier|tace_stream5|map_sized|2300|2.5"
  "frontier|bitcos_stream5_direct|default||2.5"
  "frontier|tace_stream5|map_sized|1950|2.0"
  "frontier|bitcos_stream5_direct|map_sized|1850|2.0"
  "frontier|tace_stream5|map_sized|1550|1.6"
  "frontier|bitcos_stream5_direct|map_sized|1450|1.6"
  "default|bitcos_stream5_directiso|default||2.5"
  "frontier|bitcos_stream5_directiso|default||2.5"
  "frontier|bitcos_stream5_directiso|map_sized|1800|2.0"
  "frontier|bitcos_stream5_directiso|map_sized|1450|1.6"
  "default|tace_stream5_fed|default||2.5"
  "default|bitcos_stream5_fed|default||2.5"
  "frontier|tace_stream5_fed|map_sized|2250|2.5"
  "frontier|bitcos_stream5_fed|default||2.5"
  "frontier|tace_stream5_fed|map_sized|1950|2.0"
  "frontier|bitcos_stream5_fed|nf_sized|1850|2.0"
  "frontier|tace_stream5_fed|map_sized|1550|1.6"
  "frontier|bitcos_stream5_fed|map_sized|1500|1.6"
  "default|bitcos_stream5_bank_fed|default||2.5"
  "frontier|bitcos_stream5_bank_fed|default||2.5"
  "frontier|bitcos_stream5_bank_fed|nf_sized|1750|2.0"
  "frontier|bitcos_stream5_bank_fed|map_sized|1450|1.6"
)
# POINTS_ENGINES="a b": keep only the points of these engines (exploration).
if [[ -n "${POINTS_ENGINES:-}" ]]; then
  kept=()
  for spec in "${POINTS[@]}"; do
    IFS='|' read -r _ e _ _ _ <<< "${spec}"
    [[ " ${POINTS_ENGINES} " == *" ${e} "* ]] && kept+=("${spec}")
  done
  POINTS=("${kept[@]}")
fi

declare -A TB=( [tace_stream5]=tb_power_tace [bitcos_stream5_direct]=tb_power_direct [bitcos_stream5_directiso]=tb_power_direct
  [tace_stream5_fed]=tb_power_tace_fed [bitcos_stream5_fed]=tb_power_direct_fed [bitcos_stream5_bank_fed]=tb_power_bank_fed )
declare -A TB_DEFS=( [tace_stream5]="" [bitcos_stream5_direct]="" [bitcos_stream5_directiso]="-DDIRECT_TOP=ternary_bitcos_stream5_directiso_accum"
  [tace_stream5_fed]="" [bitcos_stream5_fed]="" [bitcos_stream5_bank_fed]="" )

mkdir -p "${OUT}" "${VCD_TMP}"
rm -rf "${OUT:?}"/*

{
  echo "date_utc $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "git_commit $(git rev-parse HEAD 2>/dev/null || echo unknown)"
  echo "git_dirty $( [[ -z "$(git -c core.autocrlf=true status --porcelain -- rtl synthesis scripts 2>/dev/null)" ]] && echo no || echo yes)"
  echo "yosys $(yosys -V)"
  echo "opensta $(sta -version)"
  echo "iverilog $(iverilog -V 2>&1 | head -1)"
  echo "liberty $(basename "${LIBERTY}") sha256 $(sha256sum "${LIBERTY}" | cut -d' ' -f1)"
  echo "rows_per_workload ${ROWS}"
  echo "k ${K}"
  echo "zero_density_sweep ${ZSWEEP}"
  echo "bitnet_rows ${BITNET_ROWS} sha256 $(sha256sum "${BITNET_ROWS}" | cut -d' ' -f1)"
  echo "activity zero-delay gate-level simulation (Icarus Verilog), every cell pin annotated from VCD"
  echo "power OpenSTA report_power, Nangate45 typical, ideal clock, no wire parasitics"
} > "${OUT}/environment.txt"

# Workloads (identical activations for every workload: same seed).
WORKLOADS=(bitnet)
python3 scripts/power_workload.py "${OUT}/wl_bitnet" --bitnet-rows "${BITNET_ROWS}" \
  --rows "${ROWS}" --k "${K}" > /dev/null
for z in ${ZSWEEP}; do
  python3 scripts/power_workload.py "${OUT}/wl_z${z}" --zero-density "${z}" \
    --rows "${ROWS}" --k "${K}" > /dev/null
  WORKLOADS+=("z${z}")
done

point_name() { echo "$1__$2__$3${4:+_d$4}__p$5"; }

build_netlist() {
  local set="$1" engine="$2" recipe="$3" delay="$4" period="$5"
  local top point
  top="${ENGINE_SPEC[${engine}]%%|*}"
  point="$(point_name "$@")"
  synth_point "${engine}" "${recipe}" "${delay}" "${OUT}" "${point}" > "${OUT}/${point}.yosys.log" 2>&1
  NETLIST="${OUT}/${point}.mapped.v" TOP="${top}" PERIOD="${period}" OUTPREFIX="${OUT}/${point}" \
    sta -no_splash -exit synthesis/opensta_path_classes.tcl > "${OUT}/${point}.sta.log" 2>&1
  bash synthesis/make_sim_netlist.sh "${OUT}/${point}.mapped.v" "${top}" "${OUT}/${point}.sim.v" 2>/dev/null
  iverilog -g2012 ${TB_DEFS[${engine}]} -s "${TB[${engine}]}" -o "${OUT}/${point}.vvp" \
    "${OUT}/${point}.sim.v" "rtl/tb/${TB[${engine}]}.sv"
}

run_workload() {
  local set="$1" engine="$2" recipe="$3" delay="$4" period="$5" wl="$6"
  local top point run vcd
  top="${ENGINE_SPEC[${engine}]%%|*}"
  point="$(point_name "$1" "$2" "$3" "$4" "$5")"
  run="${point}__${wl}"
  vcd="${VCD_TMP}/${run}.vcd"
  vvp -n "${OUT}/${point}.vvp" +DIR="${OUT}/wl_${wl}" +ROWS="${ROWS}" +GROUPS="${NGROUPS}" \
    +PERIOD="${period}" +VCD="${vcd}" 2>&1 | grep -v "^WARNING\|VCD info" > "${OUT}/${run}.sim.log" || true
  NETLIST="${OUT}/${point}.mapped.v" TOP="${top}" PERIOD="${period}" VCD="${vcd}" \
    VCD_SCOPE="${TB[${engine}]}/dut" OUTPREFIX="${OUT}/${run}" \
    sta -no_splash -exit synthesis/opensta_power.tcl > "${OUT}/${run}.sta.log" 2>&1
  rm -f "${vcd}"
}

{
  for spec in "${POINTS[@]}"; do
    IFS='|' read -r set engine recipe delay period <<< "${spec}"
    for wl in "${WORKLOADS[@]}"; do
      echo "$(point_name "${set}" "${engine}" "${recipe}" "${delay}" "${period}")__${wl}"
    done
  done
} > "${OUT}/expected_runs.txt"

for spec in "${POINTS[@]}"; do
  IFS='|' read -r set engine recipe delay period <<< "${spec}"
  study_launch build_netlist "${set}" "${engine}" "${recipe}" "${delay}" "${period}"
done
study_wait
for spec in "${POINTS[@]}"; do
  IFS='|' read -r set engine recipe delay period <<< "${spec}"
  for wl in "${WORKLOADS[@]}"; do
    study_launch run_workload "${set}" "${engine}" "${recipe}" "${delay}" "${period}" "${wl}"
  done
done
study_wait
for spec in "${POINTS[@]}"; do
  IFS='|' read -r set engine recipe delay period <<< "${spec}"
  point="$(point_name "${set}" "${engine}" "${recipe}" "${delay}" "${period}")"
  rm -f "${OUT}/${point}.mapped.v" "${OUT}/${point}.sim.v" "${OUT}/${point}.vvp" "${OUT}/${point}.yosys.log"
done
echo "power study complete: ${OUT}"
