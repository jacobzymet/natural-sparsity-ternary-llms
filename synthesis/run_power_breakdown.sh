#!/usr/bin/env bash
# Per-block power breakdown (diagnostic for the power study).
#
# The study netlists are flattened, so their power cannot be split by block.
# Here each engine is synthesized with the default area flow but WITHOUT
# flattening, so every cell stays inside its RTL block (decoder, adder tree,
# presence cursor, ...). These netlists differ slightly from the study
# netlists; use them only to see where the power goes, not for the headline
# comparison. Same workloads, testbenches, clock (2.5 ns) and power flow as
# synthesis/run_power_study.sh.
#
# Usage (inside the ternary-eda container, from the repo root):
#   bash synthesis/run_power_breakdown.sh <power_raw_dir_with_workloads> [outdir]
set -euo pipefail
source synthesis/study_jobs.sh

WL_DIR="${1:?usage: run_power_breakdown.sh <power_raw_dir> [outdir]}"
OUT="${2:-synthesis/build/power_breakdown_raw}"
: "${LIBERTY:?set LIBERTY to the Nangate45 liberty file}"
ROWS="${ROWS:-24}"
NGROUPS=512
PERIOD=2.5
VCD_TMP="${VCD_TMP:-/tmp/power_breakdown_vcd}"

declare -A TOPS=(
  [tace_stream5]=ternary_five_trit_stream5_accum
  [bitcos_stream5_direct]=ternary_bitcos_stream5_direct_accum
  [bitcos_stream5_directiso]=ternary_bitcos_stream5_directiso_accum
)
declare -A FILES=(
  [tace_stream5]="rtl/signed_adder_tree.sv rtl/ternary_dense2_parallel_gemv.sv rtl/five_trit_tace_byte_decoder.sv rtl/ternary_five_trit_stream5_accum.sv"
  [bitcos_stream5_direct]="rtl/signed_adder_tree.sv rtl/bitcos_presence5_bytecursor.sv rtl/ternary_bitcos_stream5_direct_accum.sv"
  [bitcos_stream5_directiso]="rtl/signed_adder_tree.sv rtl/bitcos_presence5_bytecursor.sv rtl/ternary_bitcos_stream5_directiso_accum.sv"
)
declare -A TB=( [tace_stream5]=tb_power_tace [bitcos_stream5_direct]=tb_power_direct [bitcos_stream5_directiso]=tb_power_direct )
declare -A TB_DEFS=( [tace_stream5]="" [bitcos_stream5_direct]="" [bitcos_stream5_directiso]="-DDIRECT_TOP=ternary_bitcos_stream5_directiso_accum" )

mkdir -p "${OUT}" "${VCD_TMP}"
rm -rf "${OUT:?}"/*
cp "${WL_DIR}/environment.txt" "${OUT}/workload_environment.txt"

for engine in "${!TOPS[@]}"; do
  top="${TOPS[${engine}]}"
  yosys -q -p "
    read_verilog -sv ${FILES[${engine}]}
    hierarchy -check -top ${top}
    proc; opt; memory_map; opt; techmap; opt
    dfflibmap -liberty ${LIBERTY}
    abc -liberty ${LIBERTY}
    clean
    tee -o ${OUT}/${engine}.stat.txt stat -liberty ${LIBERTY}
    write_verilog -noattr ${OUT}/${engine}.mapped.v
  "
  bash synthesis/make_sim_netlist.sh "${OUT}/${engine}.mapped.v" "${top}" "${OUT}/${engine}.sim.v" 2>/dev/null
  # Dump every hierarchy level: cells sit below the engine's sub-blocks.
  sed 's/\$dumpvars(2, dut)/$dumpvars(0, dut)/' "rtl/tb/${TB[${engine}]}.sv" > "${OUT}/${engine}.tb.sv"
  iverilog -g2012 ${TB_DEFS[${engine}]} -s "${TB[${engine}]}" -o "${OUT}/${engine}.vvp" \
    "${OUT}/${engine}.sim.v" "${OUT}/${engine}.tb.sv"
done

{
  for wl_path in "${WL_DIR}"/wl_*; do
    for engine in "${!TOPS[@]}"; do echo "${engine}__${wl_path##*/wl_}"; done
  done
} > "${OUT}/expected_runs.txt"

run_workload() {
  local wl_path="$1" wl engine run vcd
  wl="${wl_path##*/wl_}"
  for engine in "${!TOPS[@]}"; do
    run="${engine}__${wl}"
    vcd="${VCD_TMP}/${run}.vcd"
    vvp -n "${OUT}/${engine}.vvp" +DIR="${wl_path}" +ROWS="${ROWS}" +GROUPS="${NGROUPS}" \
      +PERIOD="${PERIOD}" +VCD="${vcd}" 2>&1 | grep -v "^WARNING\|VCD info" > "${OUT}/${run}.sim.log" || true
    NETLIST="${OUT}/${engine}.mapped.v" TOP="${TOPS[${engine}]}" PERIOD="${PERIOD}" VCD="${vcd}" \
      VCD_SCOPE="${TB[${engine}]}/dut" OUTPREFIX="${OUT}/${run}" REPORT_INSTANCES=1 \
      sta -no_splash -exit synthesis/opensta_power.tcl > "${OUT}/${run}.sta.log" 2>&1
    rm -f "${vcd}"
  done
}
for wl_path in "${WL_DIR}"/wl_*; do
  study_launch run_workload "${wl_path}"
done
study_wait
rm -f "${OUT}"/*.sim.v "${OUT}"/*.vvp
echo "power breakdown complete: ${OUT}"
