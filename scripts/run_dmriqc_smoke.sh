#!/usr/bin/env bash
# Interactive smoke test: dmriqc_flow DWI QC on sub-001/ses-01.
set -euo pipefail

ROOT=/lustre07/scratch/alexrees
BIDS_DIR="${1:-$ROOT/work/dmriqc/smoke_bids}"
OUT_DIR="${2:-$ROOT/derivatives/dmriqc/smoke}"
WORK_DIR="${3:-$ROOT/work/dmriqc/nf_smoke}"
PIPELINE="$ROOT/pipelines/dmriqc_flow"
SIF="$ROOT/containers/scilus_1.4.2.sif"

# shellcheck source=/dev/null
source "$ROOT/scripts/dmriqc_env.sh"
export NXF_OPTS='-Xms512m -Xmx2g'

mkdir -p "$OUT_DIR" "$WORK_DIR"

if [[ ! -f "$SIF" ]] || [[ ! -s "$SIF" ]]; then
  echo "ERROR: missing $SIF"
  echo "Wait for pull or run: bash scripts/pull_scilus_login.sh"
  exit 1
fi

if [[ ! -d "$BIDS_DIR/sub-001" ]]; then
  echo "Building smoke BIDS subset (sub-001/ses-01)..."
  mkdir -p "$BIDS_DIR/sub-001"
  for f in dataset_description.json participants.tsv participants.json; do
    [[ -e "$BIDS_DIR/$f" ]] || ln -sfn "$ROOT/bids/$f" "$BIDS_DIR/$f"
  done
  [[ -e "$BIDS_DIR/sub-001/ses-01" ]] || ln -sfn "$ROOT/bids/sub-001/ses-01" "$BIDS_DIR/sub-001/ses-01"
fi

echo "=== dmriqc_flow SMOKE (DWI, local) ==="
echo "Nextflow: $($NEXTFLOW -version 2>&1 | awk '/version/{print $2; exit}')"
echo "BIDS:   $BIDS_DIR"
echo "Output: $OUT_DIR"
echo "SIF:    $SIF"
find -L "$BIDS_DIR" -name '*_dwi.nii.gz' | wc -l | awk '{print "DWI nifti:", $1}'

cd "$PIPELINE"

"$NEXTFLOW" run main.nf \
  -c conf/narval.config \
  -profile input_qc_dwi,local_smoke \
  --input "$BIDS_DIR" \
  --output_dir "$OUT_DIR" \
  -with-singularity "$SIF" \
  -w "$WORK_DIR" \
  -resume

echo
echo "SMOKE COMPLETE"
find "$OUT_DIR" -name '*.html' | sort
