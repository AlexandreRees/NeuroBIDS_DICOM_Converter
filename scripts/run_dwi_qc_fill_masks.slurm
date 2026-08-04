#!/bin/bash
#SBATCH --job-name=dwi_qc_fill
#SBATCH --account=def-amirs
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=12:00:00
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --output=/home/alexrees/scratch/logs/dwi_qc/%x_%j.out
#SBATCH --error=/home/alexrees/scratch/logs/dwi_qc/%x_%j.err

# Resume DWI QC mask/signal/figures after inode-quota failures from sub-027 onward.
# Keeps inventory + dwigradcheck results; only re-runs dwi2mask for NaN rows.

set -euo pipefail

mkdir -p /home/alexrees/scratch/logs/dwi_qc /home/alexrees/scratch/reports/dwi_qc/tmp

module purge || true
module load StdEnv/2023
module load python/3.11
module load mrtrix/3.0.8

export PYTHONUNBUFFERED=1

echo "Inode quota before fill:"
lfs quota -u "$USER" /lustre07/scratch 2>/dev/null | head -5 || true
command -v dwi2mask
command -v dwigradcheck

python3.11 /home/alexrees/scratch/code/run_dwi_qc.py \
  --bids-dir /home/alexrees/scratch/bids \
  --output-dir /home/alexrees/scratch/reports/dwi_qc \
  --fill-missing-masks
