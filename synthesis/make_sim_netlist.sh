#!/usr/bin/env bash
# Turn a mapped Nangate45 netlist into a zero-delay simulation model.
#
# Cell behavior comes from the liberty "function" / "ff" descriptions, so the
# simulated netlist is exactly the one that OpenSTA times and powers. Cells stay
# as separate module instances: OpenSTA matches VCD signals to instance pins
# (<instance>/<pin>), so dump the DUT two levels deep.
set -euo pipefail

NETLIST="${1:?usage: make_sim_netlist.sh <mapped.v> <top> <out.v>}"
TOP="${2:?}"
OUT_V="${3:?}"
: "${LIBERTY:?set LIBERTY to the Nangate45 liberty file}"

yosys -q -p "
  read_liberty -ignore_miss_func ${LIBERTY}
  read_verilog ${NETLIST}
  hierarchy -check -top ${TOP}
  write_verilog -noattr ${OUT_V}
"
