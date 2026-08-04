#!/bin/bash
#SBATCH --job-name=dwi_qc_arr
#SBATCH --account=def-amirs
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --time=01:00:00
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --array=0-215%40
#SBATCH --output=/home/alexrees/scratch/logs/dwi_qc/%x_%A_%a.out
#SBATCH --error=/home/alexrees/scratch/logs/dwi_qc/%x_%A_%a.err

# Parallel fill of missing DWI masks (failed after sub-027 due to inode quota).
# %40 = at most 40 concurrent tasks.

set -euo pipefail

OUT=/home/alexrees/scratch/reports/dwi_qc
PARTS=${OUT}/fill_parts
MISS=${MISS_OVERRIDE:-${OUT}/missing_mask_indices.txt}

mkdir -p /home/alexrees/scratch/logs/dwi_qc "${OUT}/tmp" "${OUT}/figures" "${PARTS}"

module purge || true
module load StdEnv/2023
module load python/3.11
module load mrtrix/3.0.8

export PYTHONUNBUFFERED=1

# Task 0 refreshes the missing-index list (idempotent).
if [[ "${SLURM_ARRAY_TASK_ID}" -eq 0 ]]; then
  python3.11 /home/alexrees/scratch/code/fill_dwi_qc_mask_one.py \
    --output-dir "${OUT}" \
    --missing-index-file "${MISS}" \
    --write-missing-list
fi

# Wait briefly so task 0's list exists for other tasks that start in parallel.
for _ in $(seq 1 60); do
  [[ -s "${MISS}" ]] && break
  sleep 2
done
[[ -s "${MISS}" ]] || { echo "Missing index list not found: ${MISS}" >&2; exit 1; }

python3.11 /home/alexrees/scratch/code/fill_dwi_qc_mask_one.py \
  --output-dir "${OUT}" \
  --parts-dir "${PARTS}" \
  --missing-index-file "${MISS}" \
  --task-id "${SLURM_ARRAY_TASK_ID}"
