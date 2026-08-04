#!/usr/bin/env bash
# Wait for scilus SIF, smoke-test, optionally submit full DWI QC.
set -euo pipefail

ROOT=/lustre07/scratch/alexrees
SIF="$ROOT/containers/scilus_1.4.2.sif"
DO_SMOKE=1
DO_SUBMIT=0

for arg in "$@"; do
  case "$arg" in
    --submit) DO_SUBMIT=1 ;;
    --submit-only) DO_SMOKE=0; DO_SUBMIT=1 ;;
    --smoke-only) DO_SMOKE=1; DO_SUBMIT=0 ;;
    *) echo "Unknown arg: $arg"; exit 1 ;;
  esac
done

echo "Waiting for $SIF ..."
for i in $(seq 1 480); do
  if [[ -f "$SIF" ]] && [[ -s "$SIF" ]]; then
    s1=$(stat -c%s "$SIF" 2>/dev/null || echo 0)
    sleep 8
    s2=$(stat -c%s "$SIF" 2>/dev/null || echo 0)
    if [[ "$s1" == "$s2" ]] && [[ "$s1" -gt 1000000000 ]]; then
      ls -lh "$SIF"
      break
    fi
  fi
  if ! pgrep -f 'apptainer.bin pull .*scilus_1.4.2' >/dev/null 2>&1; then
    if [[ ! -f "$SIF" ]]; then
      echo "ERROR: pull ended but SIF missing"
      tail -40 "$ROOT/logs/dmriqc/pull_scilus_login.err" 2>/dev/null || true
      exit 1
    fi
  fi
  if (( i % 10 == 0 )); then
    echo "  still waiting... $(date +%H:%M:%S)"
    tail -2 "$ROOT/logs/dmriqc/pull_scilus_login.err" 2>/dev/null || true
  fi
  sleep 30
done

[[ -f "$SIF" ]] || { echo "ERROR: timed out"; exit 1; }

if [[ "$DO_SMOKE" == 1 ]]; then
  echo "=== smoke ==="
  bash "$ROOT/scripts/run_dmriqc_smoke.sh"
fi

if [[ "$DO_SUBMIT" == 1 ]]; then
  echo "=== sbatch full DWI QC ==="
  sbatch "$ROOT/scripts/run_dmriqc_dwi.slurm"
fi

echo "DONE"
