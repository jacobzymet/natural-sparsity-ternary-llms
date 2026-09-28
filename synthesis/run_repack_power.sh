#!/usr/bin/env bash
# Switching-activity power of the Architecture B presence loader
# (rtl/bitcos_presence_repack.sv), the hardware that repacks the byte-packed
# presence bitmap into 5-bit presence words. Same flow and limits as
# synthesis/run_power_study.sh (zero-delay gate-level activity, OpenSTA
# report_power, no glitches, wires or clock tree).
#
# The default-flow netlist is simulated on every power workload's bitmap at
# two input rates: a byte on 5 of every 8 cycles (the rate one engine
# consumes) and a byte every cycle (one loader shared by 1.6 engines).
#
# Usage (inside the ternary-eda container, from the repo root):
#   bash synthesis/run_repack_power.sh <power raw dir with wl_* workloads> <outdir>
set -euo pipefail
source synthesis/abc_recipes.sh
source synthesis/study_jobs.sh

WL_DIR="${1:?usage: run_repack_power.sh <power raw dir> <outdir>}"
OUT="${2:?usage: run_repack_power.sh <power raw dir> <outdir>}"
: "${LIBERTY:?set LIBERTY to the Nangate45 liberty file}"
JOBS="${JOBS:-$(nproc)}"
PERIODS="${PERIODS:-1.6 2.0 2.5}"
VCD_TMP="${VCD_TMP:-/tmp/repack_vcd}"
TOP=bitcos_presence_repack
TB=tb_presence_repack
POINT=presence_repack__default

mkdir -p "${OUT}" "${VCD_TMP}"
rm -rf "${OUT:?}"/*

synth_point presence_repack default "" "${OUT}" "${POINT}" > "${OUT}/${POINT}.yosys.log" 2>&1
for period in ${PERIODS}; do
  NETLIST="${OUT}/${POINT}.mapped.v" TOP="${TOP}" PERIOD="${period}" OUTPREFIX="${OUT}/${POINT}__p${period}" \
    sta -no_splash -exit synthesis/opensta_path_classes.tcl > "${OUT}/${POINT}__p${period}.sta.log" 2>&1
done
bash synthesis/make_sim_netlist.sh "${OUT}/${POINT}.mapped.v" "${TOP}" "${OUT}/${POINT}.sim.v" 2>/dev/null
iverilog -g2012 -s "${TB}" -o "${OUT}/${POINT}.vvp" "${OUT}/${POINT}.sim.v" "rtl/tb/${TB}.sv"

run() {
  local period="$1" duty="$2" wl="$3"
  local run="${POINT}__p${period}__duty${duty}__${wl##*/wl_}" meta rows groups
  meta="${wl}/meta.json"
  rows="$(python3 -c "import json;print(json.load(open('${meta}'))['rows'])")"
  groups="$(python3 -c "import json;print(json.load(open('${meta}'))['groups_per_row'])")"
  vvp -n "${OUT}/${POINT}.vvp" +DIR="${wl}" +ROWS="${rows}" +GROUPS="${groups}" +DUTY="${duty}" \
    +PERIOD="${period}" +VCD="${VCD_TMP}/${run}.vcd" 2>&1 | grep -v "^WARNING\|VCD info" > "${OUT}/${run}.sim.log" || true
  NETLIST="${OUT}/${POINT}.mapped.v" TOP="${TOP}" PERIOD="${period}" VCD="${VCD_TMP}/${run}.vcd" \
    VCD_SCOPE="${TB}/dut" OUTPREFIX="${OUT}/${run}" \
    sta -no_splash -exit synthesis/opensta_power.tcl > "${OUT}/${run}.sta.log" 2>&1
  rm -f "${VCD_TMP}/${run}.vcd"
}

{
  for period in ${PERIODS}; do
    for duty in 5 8; do
      for wl in "${WL_DIR}"/wl_*; do
        echo "${POINT}__p${period}__duty${duty}__${wl##*/wl_}"
      done
    done
  done
} > "${OUT}/expected_runs.txt"

for period in ${PERIODS}; do
  for duty in 5 8; do
    for wl in "${WL_DIR}"/wl_*; do
      study_launch run "${period}" "${duty}" "${wl}"
    done
  done
done
study_wait
rm -f "${OUT}/${POINT}.mapped.v" "${OUT}/${POINT}.sim.v" "${OUT}/${POINT}.vvp" "${OUT}/${POINT}.yosys.log"
echo "repack power complete: ${OUT}"
