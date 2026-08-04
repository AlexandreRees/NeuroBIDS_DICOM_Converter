#!/usr/bin/env bash
#SBATCH --job-name=build_scilus
#SBATCH --account=def-amirs
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --time=6:00:00
#SBATCH --output=/lustre07/scratch/alexrees/logs/dmriqc/%x_%j.out
#SBATCH --error=/lustre07/scratch/alexrees/logs/dmriqc/%x_%j.err

# Build scilus_1.4.2.sif from already-unpacked rootfs on node-local disk.
set -euo pipefail

ROOT=/lustre07/scratch/alexrees
SIF="$ROOT/containers/scilus_1.4.2.sif"
ROOTFS="$ROOT/work/dmriqc/tmp_pull/build-temp-100781115/rootfs"
LOG="$ROOT/logs/dmriqc/build_from_rootfs.log"

mkdir -p "$ROOT/containers" "$ROOT/logs/dmriqc"

module load StdEnv/2023
module load apptainer/1.3.5
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY all_proxy

if [[ -f "$SIF" ]] && [[ -s "$SIF" ]] && [[ $(stat -c%s "$SIF") -gt 1000000000 ]]; then
  echo "SIF already present:"
  ls -lh "$SIF"
  exit 0
fi

test -d "$ROOTFS" || { echo "ROOTFS missing: $ROOTFS"; exit 1; }

TMP="${SLURM_TMPDIR:?}/scilus_build"
mkdir -p "$TMP"
export APPTAINER_TMPDIR="$TMP"
export SINGULARITY_TMPDIR="$TMP"
export TMPDIR="$TMP"

{
  echo "SLURM_BUILD_START $(date -Is) host=$(hostname) job=${SLURM_JOB_ID:-?} tmp=$TMP"
  df -h "$TMP"
} | tee -a "$LOG"

LOCAL_ROOTFS="$TMP/rootfs"
echo "COPY_ROOTFS_START $(date -Is)" | tee -a "$LOG"
rsync -a "$ROOTFS/" "$LOCAL_ROOTFS/"
echo "COPY_ROOTFS_DONE $(date -Is)" | tee -a "$LOG"
du -sh "$LOCAL_ROOTFS" | tee -a "$LOG"
df -h "$TMP" | tee -a "$LOG"

PARTIAL="$TMP/scilus_1.4.2.sif"
# Apptainer 1.3.5 on CC has no --mksquashfs-args; 32G node mem is enough for default mksquashfs
apptainer build --force "$PARTIAL" "$LOCAL_ROOTFS" 2>&1 | tee -a "$LOG"

echo "BUILD_OK $(date -Is)" | tee -a "$LOG"
ls -lh "$PARTIAL" | tee -a "$LOG"

cp -f "$PARTIAL" "$SIF"
chmod 750 "$SIF"
echo "COPY_OK $(date -Is)" | tee -a "$LOG"
ls -lh "$SIF" | tee -a "$LOG"

apptainer exec "$SIF" bash -lc 'command -v dmriqc_generic.py' | tee -a "$LOG"
echo "ALL_DONE $(date -Is)" | tee -a "$LOG"
