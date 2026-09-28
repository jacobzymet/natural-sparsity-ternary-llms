#!/usr/bin/env bash
set -euo pipefail

build="$(mktemp -d)"
trap 'rm -f "$build"/*.vvp; rmdir "$build"' EXIT

for tb in \
  tb_five_trit_tace_exhaustive \
  tb_bitcos_stream5 \
  tb_bitcos_stream5_fullfront \
  tb_bitcos_stream5_direct \
  tb_five_trit_stream5_fed_random \
  tb_bitcos_stream5_fed_random \
  tb_bitcos_stream5_bank_fed_random \
  tb_presence_repack; do
  iverilog -g2012 -s "$tb" -o "$build/$tb.vvp" rtl/*.sv "rtl/tb/$tb.sv"
  bash rtl/tb/check_sim.sh "$build/$tb.vvp"
done

iverilog -g2012 -DDIRECT_TOP=ternary_bitcos_stream5_directiso_accum \
  -s tb_bitcos_stream5_direct -o "$build/sign_isolated.vvp" \
  rtl/*.sv rtl/tb/tb_bitcos_stream5_direct.sv
bash rtl/tb/check_sim.sh "$build/sign_isolated.vvp"
