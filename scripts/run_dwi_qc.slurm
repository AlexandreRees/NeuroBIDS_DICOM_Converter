#!/bin/bash
#SBATCH --job-name=dwi_qc
#SBATCH --account=def-amirs
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --time=48:00:00
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --output=/home/alexrees/scratch/logs/dwi_qc/%x_%j.out
#SBATCH --error=/home/alexrees/scratch/logs/dwi_qc/%x_%j.err

set -euo pipefail

mkdir -p /home/alexrees/scratch/logs/dwi_qc /home/alexrees/scratch/reports/dwi_qc

module purge
module load StdEnv/2023
module load python/3.11
module load mrtrix/3.0.8

export PYTHONUNBUFFERED=1

python3.11 /home/alexrees/scratch/code/run_dwi_qc.py \
  --bids-dir /home/alexrees/scratch/bids \
  --output-dir /home/alexrees/scratch/reports/dwi_qc
