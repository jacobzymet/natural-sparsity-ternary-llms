#!/usr/bin/env bash
# Run a compiled Icarus testbench and fail unless it prints its success line
# ("PASS: ..." or "... test passed") and no FAIL. vvp exits 0 even after
# $finish(1), so its exit code alone proves nothing.
#
# Usage: bash rtl/tb/check_sim.sh <compiled.vvp> [plusargs...]
set -euo pipefail
log="$(mktemp)"
vvp -n "$@" | tee "${log}"
if grep -q "FAIL" "${log}" || ! grep -qE "^PASS|test passed$" "${log}"; then
  echo "testbench did not pass: $1" >&2
  exit 1
fi
