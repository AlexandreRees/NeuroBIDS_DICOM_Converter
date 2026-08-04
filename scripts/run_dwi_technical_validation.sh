#!/bin/bash
# Read-only DWI Technical Validation runner (Scientific Data).
set -euo pipefail

module load StdEnv/2023 python/3.11 scipy-stack

ROOT="${ROOT:-/home/alexrees/scratch}"
cd "$ROOT"

echo "python: $(which python3)"
python3 -c "import matplotlib,nibabel,numpy,pandas,docx,reportlab; print('imports_ok')"

python3 -u code/run_dwi_technical_validation.py \
  --bids-dir "$ROOT/bids" \
  --qc-dir "$ROOT/reports/dwi_qc" \
  --derivatives-dir "$ROOT/derivatives" \
  --reuse-existing \
  --workers "${WORKERS:-4}" \
  --max-visuals "${MAX_VISUALS:-12}" \
  "$@"
