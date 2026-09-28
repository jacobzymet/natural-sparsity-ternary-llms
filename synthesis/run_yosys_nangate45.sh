#!/usr/bin/env bash
set -euo pipefail

TOP="${1:?usage: run_yosys_nangate45.sh <top-module> [outdir]}"
OUTDIR="${2:-synthesis/reports/generated}"
: "${LIBERTY:?set LIBERTY to the Nangate45 liberty file}"

LANES="${LANES:-16}"
ACT_W="${ACT_W:-8}"
ACC_W="${ACC_W:-24}"
TAG="${TAG:-${TOP}_l${LANES}_a${ACT_W}_acc${ACC_W}}"

CHPARAM_CMD=""
if [[ "${NO_COMMON_PARAMS:-0}" != "1" ]]; then
  GROUP_ARG=""
  if [[ -n "${GROUP:-}" ]]; then
    GROUP_ARG="-set GROUP ${GROUP}"
    TAG="${TAG}_g${GROUP}"
  fi
  CHPARAM_CMD="chparam -set LANES ${LANES} -set ACT_W ${ACT_W} -set ACC_W ${ACC_W} ${GROUP_ARG} ${TOP}"
fi

mkdir -p "${OUTDIR}"

# By default read all top-level RTL files. Studies running older toolchains or
# intentionally isolating one datapath can provide a whitespace-separated
# RTL_FILES_OVERRIDE list instead.
if [[ -n "${RTL_FILES_OVERRIDE:-}" ]]; then
  RTL_FILES="${RTL_FILES_OVERRIDE}"
else
  RTL_FILES="$(find rtl -maxdepth 1 -name '*.sv' -print | sort | tr '\n' ' ')"
fi

# Optional ABC delay target (ps), custom ABC script, and ABC driver/load
# constraints. All unset keeps the default mapping used by the area tables.
ABC_ARGS="-liberty ${LIBERTY}"
if [[ -n "${ABC_DELAY_PS:-}" ]]; then
  ABC_ARGS="${ABC_ARGS} -D ${ABC_DELAY_PS}"
fi
if [[ -n "${ABC_SCRIPT:-}" ]]; then
  ABC_ARGS="${ABC_ARGS} -script ${ABC_SCRIPT}"
fi
if [[ -n "${ABC_CONSTR:-}" ]]; then
  ABC_ARGS="${ABC_ARGS} -constr ${ABC_CONSTR}"
fi

yosys -Q -p "
  read_verilog -sv ${RTL_FILES}
  ${CHPARAM_CMD}
  hierarchy -check -top ${TOP}
  proc
  opt
  flatten
  opt
  memory_map
  opt
  techmap
  opt
  dfflibmap -liberty ${LIBERTY}
  abc ${ABC_ARGS}
  clean
  tee -o ${OUTDIR}/${TAG}.stat.json stat -json -liberty ${LIBERTY}
  write_verilog -noattr ${OUTDIR}/${TAG}.mapped.v
"
