#!/usr/bin/env bash
#SBATCH --job-name=dwi_motion_qc
#SBATCH --account=def-amirs
#SBATCH --cpus-per-task=8
#SBATCH --mem=48G
#SBATCH --time=12:00:00
#SBATCH --output=/lustre07/scratch/alexrees/logs/dmriqc/%x_%j.out
#SBATCH --error=/lustre07/scratch/alexrees/logs/dmriqc/%x_%j.err

set -euo pipefail
ROOT=/lustre07/scratch/alexrees
mkdir -p "$ROOT/logs/dmriqc" "$ROOT/derivatives/dmriqc/qc_metrics"

module load StdEnv/2023 || true
# nibabel is available on the login/compute python used previously
PY=python3
echo "=== dwi motion/SNR QC ==="
echo "Host=$(hostname) Date=$(date -Is)"
$PY -c 'import nibabel,numpy; print("nibabel", nibabel.__version__, "numpy", numpy.__version__)'

$PY "$ROOT/code/compute_dwi_motion_snr_qc.py" --workers 8 \
  --out "$ROOT/derivatives/dmriqc/qc_metrics/dwi_motion_snr_qc.tsv"

$PY "$ROOT/code/plot_scientific_data_dwi_figures_3456.py"
echo "DONE $(date -Is)"
ls -lh "$ROOT/derivatives/dmriqc/publication"/Figure{3,4,5,6}*
