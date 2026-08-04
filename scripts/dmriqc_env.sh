#!/usr/bin/env bash
# Common environment for dmriqc_flow on Narval.
# Source from other scripts:  source "$ROOT/scripts/dmriqc_env.sh"

ROOT="${ROOT:-/lustre07/scratch/alexrees}"

module load StdEnv/2023
module load java/17.0.6
module load apptainer/1.3.5

# dmriqc_flow is DSL1 → requires Nextflow ≤22.10.x (module nextflow/24+ refuses DSL1)
export NEXTFLOW="${NEXTFLOW:-$ROOT/software/nextflow-22.10.8/nextflow}"
if [[ ! -x "$NEXTFLOW" ]]; then
  echo "ERROR: Nextflow 22.10.8 binary missing at $NEXTFLOW"
  echo "Download with:"
  echo "  mkdir -p $ROOT/software/nextflow-22.10.8"
  echo "  curl -fsSL -o $ROOT/software/nextflow-22.10.8/nextflow \\"
  echo "    https://github.com/nextflow-io/nextflow/releases/download/v22.10.8/nextflow-22.10.8-all"
  echo "  chmod +x $ROOT/software/nextflow-22.10.8/nextflow"
  return 1 2>/dev/null || exit 1
fi

export NXF_HOME="${NXF_HOME:-$ROOT/.nextflow}"
export NXF_TEMP="${NXF_TEMP:-$ROOT/work/dmriqc/tmp}"
export NXF_SINGULARITY_CACHEDIR="${NXF_SINGULARITY_CACHEDIR:-$ROOT/containers/apptainer_cache}"
export SINGULARITY_CACHEDIR="$NXF_SINGULARITY_CACHEDIR"
export APPTAINER_CACHEDIR="$NXF_SINGULARITY_CACHEDIR"
export APPTAINER_TMPDIR="${APPTAINER_TMPDIR:-$ROOT/work/dmriqc/tmp}"
export SINGULARITY_TMPDIR="$APPTAINER_TMPDIR"
export CAPSULE_LOG=none
export NXF_OPTS="${NXF_OPTS:--Xms1g -Xmx4g}"

mkdir -p "$NXF_HOME" "$NXF_TEMP" "$NXF_SINGULARITY_CACHEDIR" \
  "$ROOT/logs/dmriqc" "$ROOT/derivatives/dmriqc"
