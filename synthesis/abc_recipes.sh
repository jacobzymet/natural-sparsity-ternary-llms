# Shared ABC mapping recipes (sourced by the timing and power studies).
#
# Inline ABC scripts: Yosys substitutes {D} with "-D <ps>" only in inline
# scripts, and inline commands use ',' for spaces.
ABC_CONSTR_FILE="synthesis/abc_constr.sdc"
RECIPE_map_sized="+strash;&get,-n;&fraig,-x;&put;dc2;strash;dch,-f;map,{D};buffer,-p;topo;upsize,{D};dnsize,{D};stime,-p"
RECIPE_nf_sized="+strash;&get,-n;&fraig,-x;&put;dc2;strash;&get,-n;&dch,-f;&nf,{D};&put;buffer,-p;topo;upsize,{D};dnsize,{D};stime,-p"

# Evaluated engine tag -> "top|RTL files".
declare -A ENGINE_SPEC=(
  [tace_stream5]="ternary_five_trit_stream5_accum|rtl/signed_adder_tree.sv rtl/ternary_dense2_parallel_gemv.sv rtl/five_trit_tace_byte_decoder.sv rtl/ternary_five_trit_stream5_accum.sv"
  [bitcos_stream5_direct]="ternary_bitcos_stream5_direct_accum|rtl/signed_adder_tree.sv rtl/bitcos_presence5_bytecursor.sv rtl/ternary_bitcos_stream5_direct_accum.sv"
  [bitcos_stream5_directiso]="ternary_bitcos_stream5_directiso_accum|rtl/signed_adder_tree.sv rtl/bitcos_presence5_bytecursor.sv rtl/ternary_bitcos_stream5_directiso_accum.sv"
  [bitcos_stream5_bytecursor]="ternary_bitcos_stream5_accum|rtl/signed_adder_tree.sv rtl/ternary_dense2_parallel_gemv.sv rtl/bitcos_group5_decode.sv rtl/bitcos_stream5_bytecursor_decoder.sv rtl/ternary_bitcos_stream5_accum.sv"
  [bitcos_stream5_fullfront]="ternary_bitcos_stream5_fullfront_accum|rtl/signed_adder_tree.sv rtl/ternary_dense2_parallel_gemv.sv rtl/bitcos_group5_decode.sv rtl/bitcos_stream5_bytecursor_decoder.sv rtl/bitcos_presence5_bytecursor.sv rtl/ternary_bitcos_stream5_accum.sv rtl/ternary_bitcos_stream5_fullfront_accum.sv"
  [tace_stream5_fed]="ternary_five_trit_stream5_fed|rtl/signed_adder_tree.sv rtl/ternary_dense2_parallel_gemv.sv rtl/five_trit_tace_byte_decoder.sv rtl/ternary_five_trit_stream5_accum.sv rtl/ternary_five_trit_stream5_fed.sv"
  [bitcos_stream5_fed]="ternary_bitcos_stream5_fed|rtl/signed_adder_tree.sv rtl/bitcos_presence5_bytecursor.sv rtl/ternary_bitcos_stream5_direct_accum.sv rtl/ternary_bitcos_stream5_fed.sv"
    [presence_repack]="bitcos_presence_repack|rtl/bitcos_presence_repack.sv"
    [bitcos_stream5_bank_fed]="ternary_bitcos_stream5_bank_fed|rtl/signed_adder_tree.sv rtl/ternary_bitcos_stream5_directbank_accum.sv rtl/ternary_bitcos_stream5_bank_fed.sv"
)

# synth_point <engine> <recipe> <delay_ps|""> <outdir> <tag>
# Writes <outdir>/<tag>.mapped.v and <outdir>/<tag>.stat.json.
synth_point() {
  local engine="$1" recipe="$2" delay="$3" out="$4" tag="$5"
  local top files
  IFS='|' read -r top files <<< "${ENGINE_SPEC[${engine}]}"
  if [[ "${recipe}" == "default" ]]; then
    NO_COMMON_PARAMS=1 RTL_FILES_OVERRIDE="${files}" TAG="${tag}" \
      bash synthesis/run_yosys_nangate45.sh "${top}" "${out}"
  else
    local script_var="RECIPE_${recipe}"
    ABC_DELAY_PS="${delay}" ABC_SCRIPT="${!script_var}" ABC_CONSTR="${ABC_CONSTR_FILE}" \
      NO_COMMON_PARAMS=1 RTL_FILES_OVERRIDE="${files}" TAG="${tag}" \
      bash synthesis/run_yosys_nangate45.sh "${top}" "${out}"
  fi
}
