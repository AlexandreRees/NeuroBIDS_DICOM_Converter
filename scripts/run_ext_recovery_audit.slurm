#!/bin/bash
#SBATCH --job-name=ext_audit
#SBATCH --account=def-amirs
#SBATCH --time=04:00:00
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --output=/lustre07/scratch/alexrees/logs/ext_recovery_audit_%j.out
#SBATCH --error=/lustre07/scratch/alexrees/logs/ext_recovery_audit_%j.err

set -euo pipefail
cd /lustre07/scratch/alexrees
export PYTHONUNBUFFERED=1
mkdir -p logs reports/ext_recovery_audit

echo "START $(date -Is)"
python3 -u code/audit_ext_recovery.py \
  --raw /lustre06/project/6001995/raw_original \
  --bids /lustre07/scratch/alexrees/bids \
  --output reports/ext_recovery_audit \
  --dry-run \
  --max-dicom-series 8000 \
  -v
echo "END $(date -Is)"
