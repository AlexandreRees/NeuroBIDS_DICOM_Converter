#!/bin/bash
# Offline rebuild of scilus_1.4.2.sif from existing unpacked rootfs.
# Copies rootfs to /tmp first so mksquashfs is local/fast.
set -euo pipefail

ROOT=/lustre07/scratch/alexrees
ROOTFS="$ROOT/work/dmriqc/tmp_pull/build-temp-100781115/rootfs"
OUT_SIF="$ROOT/containers/scilus_1.4.2.sif"
TMP=/tmp/alexrees_scilus_build
LOG="$ROOT/logs/dmriqc/build_from_rootfs.log"
LOCAL_ROOTFS="$TMP/rootfs"
PARTIAL="$TMP/scilus_1.4.2.sif"

mkdir -p "$TMP" "$ROOT/containers" "$ROOT/logs/dmriqc"

module load StdEnv/2023 apptainer/1.3.5
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY all_proxy
export APPTAINER_TMPDIR="$TMP"
export SINGULARITY_TMPDIR="$TMP"
export TMPDIR="$TMP"

{
  echo "BUILD_RESTART $(date -Is)"
  df -h /tmp
  test -d "$ROOTFS"
  echo "COPY_ROOTFS_START $(date -Is)"
} > "$LOG"

rm -rf "$LOCAL_ROOTFS"
mkdir -p "$LOCAL_ROOTFS"
rsync -a "$ROOTFS/" "$LOCAL_ROOTFS/"

{
  echo "COPY_ROOTFS_DONE $(date -Is)"
  du -sh "$LOCAL_ROOTFS" || true
  df -h /tmp
} >> "$LOG"

apptainer build --force "$PARTIAL" "$LOCAL_ROOTFS" >> "$LOG" 2>&1

{
  echo "BUILD_OK $(date -Is)"
  ls -lh "$PARTIAL"
} >> "$LOG"

cp -f "$PARTIAL" "$OUT_SIF"
chmod 750 "$OUT_SIF"

{
  echo "COPY_OK $(date -Is)"
  ls -lh "$OUT_SIF"
} >> "$LOG"

apptainer exec "$OUT_SIF" bash -lc 'command -v dmriqc_generic.py' >> "$LOG" 2>&1
echo "ALL_DONE $(date -Is)" >> "$LOG"
