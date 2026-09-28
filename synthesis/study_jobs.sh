#!/usr/bin/env bash
# Bounded batches with an explicit wait for every child, including the final
# partial batch. A bare `wait` discards individual child exit statuses.
JOBS="${JOBS:-$(nproc)}"
if [[ ! "$JOBS" =~ ^[1-9][0-9]*$ ]]; then
  echo "JOBS must be a positive integer" >&2
  return 1
fi
STUDY_PIDS=()

study_wait() {
  local pid failed=0
  for pid in "${STUDY_PIDS[@]}"; do
    wait "$pid" || failed=1
  done
  STUDY_PIDS=()
  return "$failed"
}

study_launch() {
  "$@" &
  STUDY_PIDS+=("$!")
  if (( ${#STUDY_PIDS[@]} >= JOBS )); then
    study_wait
  fi
}
