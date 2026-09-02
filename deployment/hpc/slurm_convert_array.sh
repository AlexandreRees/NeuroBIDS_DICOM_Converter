#!/bin/bash
#SBATCH --job-name=neuroconvert
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=04:00:00
#SBATCH --output=neuroconvert_%A_%a.out
#SBATCH --error=neuroconvert_%A_%a.err
#
# Generic Slurm array template for batch DICOM→NIfTI conversion.
# Do NOT hardcode account, partition, or personal paths here.
#
# Required environment variables:
#   INPUT_DIR   Root folder containing subject subfolders
#   OUTPUT_DIR  Root folder for converted outputs
#
# Optional:
#   SUBJECT_LIST  Text file with one subject folder name per line
#   EXTRA_ARGS    Extra CLI flags forwarded to the converter helper
#
# Example:
#   export INPUT_DIR=/path/to/dicoms
#   export OUTPUT_DIR=/path/to/niftis
#   sbatch --array=0-99 deployment/hpc/slurm_convert_array.sh

set -euo pipefail

if [[ -z "${INPUT_DIR:-}" || -z "${OUTPUT_DIR:-}" ]]; then
  echo "ERROR: INPUT_DIR and OUTPUT_DIR must be set." >&2
  exit 1
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

if [[ -f "$ROOT/.venv/bin/activate" ]]; then
  # shellcheck disable=SC1091
  source "$ROOT/.venv/bin/activate"
fi

mapfile -t SUBJECTS < <(
  if [[ -n "${SUBJECT_LIST:-}" && -f "${SUBJECT_LIST}" ]]; then
    grep -v '^\s*$' "$SUBJECT_LIST"
  else
    find "$INPUT_DIR" -mindepth 1 -maxdepth 1 -type d -printf '%f\n' | sort
  fi
)

IDX="${SLURM_ARRAY_TASK_ID:-0}"
if (( IDX < 0 || IDX >= ${#SUBJECTS[@]} )); then
  echo "Array index $IDX out of range (n=${#SUBJECTS[@]})" >&2
  exit 0
fi

SUBJECT="${SUBJECTS[$IDX]}"
IN_PATH="$INPUT_DIR/$SUBJECT"
OUT_PATH="$OUTPUT_DIR/$SUBJECT"

mkdir -p "$OUT_PATH"
echo "Converting subject=$SUBJECT"
echo "  input=$IN_PATH"
echo "  output=$OUT_PATH"

python - <<PY
from pathlib import Path
from neuro_pipeline.batch import BatchManager
from neuro_pipeline.models import ConversionOptions

inp = Path(r"""$IN_PATH""")
out = Path(r"""$OUT_PATH""")
mgr = BatchManager()
jobs = mgr.discover_datasets(inp.parent, output_root=out.parent)
# Keep only this subject
jobs = [j for j in jobs if Path(j.input_path).name == inp.name]
mgr.queue.replace_all(jobs)
mgr.run_all(options=ConversionOptions(), resume=True)
print("DONE", inp.name)
PY
