#!/usr/bin/env bash
#SBATCH --job-name=dmriqc_dwi
#SBATCH --account=def-amirs
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --time=48:00:00
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --output=/lustre07/scratch/alexrees/logs/dmriqc/%x_%j.out
#SBATCH --error=/lustre07/scratch/alexrees/logs/dmriqc/%x_%j.err

# Full-dataset DWI QC via dmriqc_flow (profile input_qc_dwi).
#
# Prerequisites:
#   1) containers/scilus_1.4.2.sif
#   2) software/nextflow-22.10.8/nextflow  (DSL1)
#   3) Slurm controller reachable
#
# Usage:
#   sbatch scripts/run_dmriqc_dwi.slurm
#   sbatch scripts/run_dmriqc_dwi.slurm /path/bids /path/out /path/work

set -euo pipefail

ROOT=/lustre07/scratch/alexrees
BIDS_DIR="${1:-$ROOT/bids}"
OUT_DIR="${2:-$ROOT/derivatives/dmriqc}"
WORK_DIR="${3:-$ROOT/work/dmriqc/nf_work}"
PIPELINE="$ROOT/pipelines/dmriqc_flow"
SIF="$ROOT/containers/scilus_1.4.2.sif"

# shellcheck source=/dev/null
source "$ROOT/scripts/dmriqc_env.sh"

mkdir -p "$OUT_DIR" "$WORK_DIR"

if [[ ! -f "$SIF" ]] || [[ ! -s "$SIF" ]]; then
  echo "ERROR: missing container $SIF"
  echo "Run:  sbatch scripts/pull_scilus_container.slurm"
  echo "  or: bash scripts/pull_scilus_login.sh"
  exit 1
fi

if [[ ! -d "$BIDS_DIR" ]]; then
  echo "ERROR: BIDS dir not found: $BIDS_DIR"
  exit 1
fi

N_DWI=$(find -L "$BIDS_DIR" -name '*_dwi.nii.gz' 2>/dev/null | wc -l | tr -d ' ')
echo "=== dmriqc_flow input_qc_dwi ==="
echo "Nextflow: $($NEXTFLOW -version 2>&1 | awk '/version/{print $2; exit}')"
echo "BIDS:     $BIDS_DIR"
echo "Output:   $OUT_DIR"
echo "Work:     $WORK_DIR"
echo "SIF:      $SIF ($(du -h "$SIF" | cut -f1))"
echo "DWI nii:  $N_DWI"
echo "Host:     $(hostname)"
echo "Date:     $(date -Is)"
echo

cd "$PIPELINE"

"$NEXTFLOW" run main.nf \
  -c conf/narval.config \
  -profile input_qc_dwi,narval \
  --input "$BIDS_DIR" \
  --output_dir "$OUT_DIR" \
  -with-singularity "$SIF" \
  -w "$WORK_DIR" \
  -resume

echo
echo "DMRIQC DWI QC COMPLETE"
echo "Reports under: $OUT_DIR"
ls -la "$OUT_DIR" || true
