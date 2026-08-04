#!/bin/bash
#SBATCH --job-name=deface_audit
#SBATCH --account=def-amirs
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --time=12:00:00
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --output=/home/alexrees/scratch/logs/defacing_audit/%x_%j.out
#SBATCH --error=/home/alexrees/scratch/logs/defacing_audit/%x_%j.err

set -euo pipefail

mkdir -p /home/alexrees/scratch/logs/defacing_audit \
         /home/alexrees/scratch/reports/defacing_audit

module purge
module load StdEnv/2023
module load python/3.11

export PYTHONUNBUFFERED=1

python3.11 /home/alexrees/scratch/code/audit_defacing.py \
  --bids-dir /home/alexrees/scratch/bids \
  --defacing-dir /home/alexrees/scratch/derivatives/defacing \
  --output-dir /home/alexrees/scratch/reports/defacing_audit
