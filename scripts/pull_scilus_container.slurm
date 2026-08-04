#!/usr/bin/env bash
#SBATCH --job-name=pull_scilus
#SBATCH --account=def-amirs
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --time=8:00:00
#SBATCH --output=/lustre07/scratch/alexrees/logs/dmriqc/%x_%j.out
#SBATCH --error=/lustre07/scratch/alexrees/logs/dmriqc/%x_%j.err

# Pull scilus/scilus:1.4.2 using node-local $SLURM_TMPDIR then copy to scratch.
set -euo pipefail

ROOT=/lustre07/scratch/alexrees
SIF="$ROOT/containers/scilus_1.4.2.sif"
mkdir -p "$ROOT/containers" "$ROOT/containers/apptainer_cache" "$ROOT/logs/dmriqc"

module load StdEnv/2023
module load apptainer/1.3.5

TMP_BASE="${SLURM_TMPDIR:-$ROOT/work/dmriqc/tmp}"
mkdir -p "$TMP_BASE"
export APPTAINER_CACHEDIR="$ROOT/containers/apptainer_cache"
export SINGULARITY_CACHEDIR="$APPTAINER_CACHEDIR"
export APPTAINER_TMPDIR="$TMP_BASE"
export SINGULARITY_TMPDIR="$TMP_BASE"
export TMPDIR="$TMP_BASE"

echo "=== pull_scilus ==="
echo "Host: $(hostname)  Date: $(date -Is)  TMP: $TMPDIR"

if [[ -f "$SIF" ]] && [[ -s "$SIF" ]]; then
  ls -lh "$SIF"
  echo "Already present — nothing to do."
  exit 0
fi

PARTIAL="$TMP_BASE/scilus_1.4.2.sif"
rm -f "$PARTIAL" 2>/dev/null || true
echo "Pulling docker://scilus/scilus:1.4.2 -> $PARTIAL"
apptainer pull "$PARTIAL" docker://scilus/scilus:1.4.2
cp -f "$PARTIAL" "$SIF"
chmod 750 "$SIF"
ls -lh "$SIF"

apptainer exec "$SIF" bash -lc 'command -v dmriqc_generic.py; ls /usr/local/bin/dmriqc* 2>/dev/null | head'
echo "PULL COMPLETE"
