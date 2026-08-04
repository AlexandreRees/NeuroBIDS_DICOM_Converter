#!/bin/bash
#SBATCH --job-name=dwi_qc_merge
#SBATCH --account=def-amirs
#SBATCH --cpus-per-task=1
#SBATCH --mem=4G
#SBATCH --time=00:30:00
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --output=/home/alexrees/scratch/logs/dwi_qc/%x_%j.out
#SBATCH --error=/home/alexrees/scratch/logs/dwi_qc/%x_%j.err

set -euo pipefail

module purge || true
module load StdEnv/2023
module load python/3.11

export PYTHONUNBUFFERED=1

python3.11 /home/alexrees/scratch/code/fill_dwi_qc_mask_one.py \
  --output-dir /home/alexrees/scratch/reports/dwi_qc \
  --merge
