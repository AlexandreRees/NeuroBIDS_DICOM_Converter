#!/bin/bash
#SBATCH --job-name=dwi_fill
#SBATCH --account=def-amirs
#SBATCH --cpus-per-task=2
#SBATCH --mem=12G
#SBATCH --time=01:00:00
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --output=/home/alexrees/scratch/logs/dwi_qc/%x_%A_%a.out
#SBATCH --error=/home/alexrees/scratch/logs/dwi_qc/%x_%A_%a.err

set -euo pipefail
OUT=/home/alexrees/scratch/reports/dwi_qc
MISS=${OUT}/missing_mask_indices.txt
PARTS=${OUT}/fill_parts
mkdir -p /home/alexrees/scratch/logs/dwi_qc "${OUT}/tmp" "${OUT}/figures" "${PARTS}"

module purge || true
module load StdEnv/2023
module load python/3.11
module load mrtrix/3.0.8
export PYTHONUNBUFFERED=1

# Map array task id -> pending task id (index into missing list)
PENDING=${OUT}/pending_task_ids.txt
TASK_ID=$(sed -n "$((SLURM_ARRAY_TASK_ID+1))p" "$PENDING")
[[ -n "${TASK_ID}" ]] || { echo "No pending task for array ${SLURM_ARRAY_TASK_ID}"; exit 0; }

python3.11 /home/alexrees/scratch/code/fill_dwi_qc_mask_one.py \
  --output-dir "${OUT}" \
  --parts-dir "${PARTS}" \
  --missing-index-file "${MISS}" \
  --task-id "${TASK_ID}"
