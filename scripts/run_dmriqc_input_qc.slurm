#!/usr/bin/env bash
#SBATCH --job-name=dmriqc_input
#SBATCH --account=def-amirs
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --time=48:00:00
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --output=/lustre07/scratch/alexrees/logs/dmriqc/%x_%j.out
#SBATCH --error=/lustre07/scratch/alexrees/logs/dmriqc/%x_%j.err

# Head-job launcher for dmriqc_flow (input_qc): DWI + T1w + FLAIR visual QC.
# Nextflow submits child Slurm tasks via conf/narval.config.
#
# Example:
#   sbatch scripts/run_dmriqc_input_qc.slurm
#   sbatch scripts/run_dmriqc_input_qc.slurm /lustre07/scratch/alexrees/work/dmriqc/smoke_bids

set -euo pipefail

ROOT=/lustre07/scratch/alexrees
BIDS_DIR="${1:-$ROOT/bids}"
OUT_DIR="${2:-$ROOT/derivatives/dmriqc}"
WORK_DIR="${3:-$ROOT/work/dmriqc/nf_work}"
PIPELINE="$ROOT/pipelines/dmriqc_flow"
SIF="$ROOT/containers/scilus_1.4.2.sif"

mkdir -p "$ROOT/logs/dmriqc" "$OUT_DIR" "$WORK_DIR" \
  "$ROOT/containers/apptainer_cache" \
  "$ROOT/.nextflow" \
  "$ROOT/work/dmriqc/tmp"

module purge
# shellcheck source=/dev/null
source /lustre07/scratch/alexrees/scripts/dmriqc_env.sh

if [[ ! -f "$SIF" ]]; then
  echo "ERROR: missing container $SIF"
  echo "Pull with: sbatch scripts/pull_scilus_container.slurm"
  exit 1
fi

if [[ ! -d "$BIDS_DIR" ]]; then
  echo "ERROR: BIDS dir not found: $BIDS_DIR"
  exit 1
fi

echo "=== dmriqc_flow input_qc ==="
echo "BIDS:     $BIDS_DIR"
echo "Output:   $OUT_DIR"
echo "Work:     $WORK_DIR"
echo "SIF:      $SIF"
echo "Host:     $(hostname)"
echo "Date:     $(date -Is)"
echo

cd "$PIPELINE"

"$NEXTFLOW" run main.nf \
  -c conf/narval.config \
  -profile input_qc,narval \
  --input "$BIDS_DIR" \
  --output_dir "$OUT_DIR" \
  -with-singularity "$SIF" \
  -w "$WORK_DIR" \
  -resume

echo
echo "DMRIQC INPUT QC COMPLETE"
echo "Reports under: $OUT_DIR"
