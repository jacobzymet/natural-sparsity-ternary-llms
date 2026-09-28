#!/usr/bin/env bash
# Matched clocked timing study for the five-position streaming engines.
#
# Every engine is synthesized with the same mapping recipes and timed with the
# same OpenSTA constraints (synthesis/opensta_path_classes.tcl).
#
# Recipes (synthesis/abc_recipes.sh):
#   default    the unchanged area flow used for the earlier area tables
#              (ABC's default liberty script; no buffering or gate sizing).
#   map_sized  ABC delay-constrained mapping (map -D) followed by buffering
#              and gate up/down-sizing, swept over delay targets D.
#   nf_sized   ABC &nf mapping followed by buffering and gate sizing, at the
#              same delay targets.
#
# The delay target is only a synthesis knob. The reported minimum period of
# every netlist comes from OpenSTA, not from ABC.
#
# Usage (inside the ternary-eda container, from the repo root):
#   bash synthesis/run_timing_study.sh [outdir]
set -euo pipefail
source synthesis/abc_recipes.sh
source synthesis/study_jobs.sh

OUT="${1:-data/timing/raw}"
: "${LIBERTY:?set LIBERTY to the Nangate45 liberty file}"
DELAYS_PS="${DELAYS_PS:-$(seq -s ' ' 900 50 3000)}"
DEFAULT_PERIOD_NS="${DEFAULT_PERIOD_NS:-5.0}"
JOBS="${JOBS:-$(nproc)}"
if [[ -n "${ENGINES_OVERRIDE:-}" ]]; then
  read -r -a ENGINES <<< "${ENGINES_OVERRIDE}"
else
  ENGINES=(tace_stream5 bitcos_stream5_direct bitcos_stream5_directiso bitcos_stream5_bytecursor bitcos_stream5_fullfront tace_stream5_fed bitcos_stream5_fed bitcos_stream5_bank_fed)
fi

mkdir -p "${OUT}"
rm -f "${OUT}"/*

{
  echo "date_utc $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "git_commit $(git rev-parse HEAD 2>/dev/null || echo unknown)"
  echo "git_dirty $( [[ -z "$(git -c core.autocrlf=true status --porcelain -- rtl synthesis scripts 2>/dev/null)" ]] && echo no || echo yes)"
  echo "yosys $(yosys -V)"
  echo "opensta $(sta -version)"
  echo "liberty $(basename "${LIBERTY}") sha256 $(sha256sum "${LIBERTY}" | cut -d' ' -f1)"
  echo "os $(. /etc/os-release && echo "${PRETTY_NAME}")"
  echo "recipe_default abc -liberty <lib>"
  echo "recipe_map_sized abc -liberty <lib> -D <D> -constr ${ABC_CONSTR_FILE} -script ${RECIPE_map_sized}"
  echo "recipe_nf_sized abc -liberty <lib> -D <D> -constr ${ABC_CONSTR_FILE} -script ${RECIPE_nf_sized}"
  echo "abc_constr $(tr '\n' ';' < "${ABC_CONSTR_FILE}")"
  echo "delays_ps ${DELAYS_PS}"
  echo "default_period_ns ${DEFAULT_PERIOD_NS}"
  echo "sta_constraints zero input/output delay; 50 ps input transition; 10 fF output load; rst_n false path; ideal clock; no wire load"
  echo "act_w 8 (module default)"
  echo "acc_w 24 (module default)"
} > "${OUT}/environment.txt"

run_point() {
  local engine="$1" recipe="$2" delay="$3"
  local point period top
  top="${ENGINE_SPEC[${engine}]%%|*}"
  if [[ "${recipe}" == "default" ]]; then
    point="${engine}__default"
    period="${DEFAULT_PERIOD_NS}"
  else
    point="${engine}__${recipe}_d${delay}"
    period="$(awk "BEGIN{printf \"%.3f\", ${delay}/1000}")"
  fi
  synth_point "${engine}" "${recipe}" "${delay}" "${OUT}" "${point}" > "${OUT}/${point}.yosys.log" 2>&1
  NETLIST="${OUT}/${point}.mapped.v" TOP="${top}" PERIOD="${period}" OUTPREFIX="${OUT}/${point}" \
    sta -no_splash -exit synthesis/opensta_path_classes.tcl > "${OUT}/${point}.sta.log" 2>&1
  # Netlists and full Yosys logs are reproducible from the recipe; keep the
  # ABC command trace and ABC's own delay/area estimate, plus all STA reports.
  grep -E "^ABC: \+ |Delay =" "${OUT}/${point}.yosys.log" | grep -v "read_blif\|write_blif" \
    > "${OUT}/${point}.abc.txt" || true
  rm -f "${OUT}/${point}.mapped.v" "${OUT}/${point}.yosys.log"
}

{
  for engine in "${ENGINES[@]}"; do
    echo "${engine}__default"
    for recipe in map_sized nf_sized; do
      for d in ${DELAYS_PS}; do echo "${engine}__${recipe}_d${d}"; done
    done
  done
} > "${OUT}/expected_runs.txt"

for engine in "${ENGINES[@]}"; do
  study_launch run_point "${engine}" default ""
  for recipe in map_sized nf_sized; do
    for d in ${DELAYS_PS}; do
      study_launch run_point "${engine}" "${recipe}" "${d}"
    done
  done
done
study_wait
echo "timing study complete: ${OUT}"
