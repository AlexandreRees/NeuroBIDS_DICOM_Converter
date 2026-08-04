#!/usr/bin/env bash
# Login-node pull of scilus/scilus:1.4.2 (use when Slurm is unreachable).
# Prefer: sbatch scripts/pull_scilus_container.slurm
set -euo pipefail

ROOT=/lustre07/scratch/alexrees
SIF="$ROOT/containers/scilus_1.4.2.sif"
LOG="$ROOT/logs/dmriqc/pull_scilus_login"

mkdir -p "$ROOT/containers" "$ROOT/containers/apptainer_cache" \
  "$ROOT/work/dmriqc/tmp_pull" "$ROOT/logs/dmriqc"

module load StdEnv/2023
module load apptainer/1.3.5

export APPTAINER_CACHEDIR="$ROOT/containers/apptainer_cache"
export SINGULARITY_CACHEDIR="$APPTAINER_CACHEDIR"
export APPTAINER_TMPDIR="$ROOT/work/dmriqc/tmp_pull"
export SINGULARITY_TMPDIR="$APPTAINER_TMPDIR"
export TMPDIR="$APPTAINER_TMPDIR"

if [[ -f "$SIF" ]] && [[ -s "$SIF" ]]; then
  ls -lh "$SIF"
  echo "Already present."
  exit 0
fi

# Avoid duplicate pulls
if pgrep -f 'apptainer.bin pull .*scilus_1.4.2' >/dev/null 2>&1; then
  echo "A scilus pull is already running:"
  pgrep -af 'apptainer.bin pull .*scilus_1.4.2'
  exit 0
fi

echo "Pulling docker://scilus/scilus:1.4.2 -> $SIF"
echo "Log: ${LOG}.err"
nohup apptainer pull "$SIF" docker://scilus/scilus:1.4.2 \
  > "${LOG}.out" 2> "${LOG}.err" &
echo $! > "${LOG}.pid"
echo "Started PID=$(cat "${LOG}.pid")"
