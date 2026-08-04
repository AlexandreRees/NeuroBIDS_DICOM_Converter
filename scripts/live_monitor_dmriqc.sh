#!/usr/bin/env bash
# Live monitor for scilus container build/pull until SIF is ready, then smoke-test.
set -u
ROOT=/lustre07/scratch/alexrees
SIF=$ROOT/containers/scilus_1.4.2.sif
LOG=$ROOT/logs/dmriqc
OUT=$LOG/live_monitor.out

exec > >(tee -a "$OUT") 2>&1

echo "===== LIVE MONITOR START $(date -Is) ====="

for i in $(seq 1 360); do
  TS=$(date +%H:%M:%S)

  if [[ -f "$SIF" ]] && [[ -s "$SIF" ]]; then
    s1=$(stat -c%s "$SIF")
    sleep 8
    s2=$(stat -c%s "$SIF")
    if [[ "$s1" == "$s2" ]] && [[ "$s1" -gt 1000000000 ]]; then
      echo "$TS SIF_READY $(ls -lh "$SIF")"
      # Verify tools
      module load StdEnv/2023 apptainer/1.3.5 >/dev/null 2>&1 || true
      unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY all_proxy
      if apptainer exec "$SIF" bash -lc 'command -v dmriqc_generic.py' 2>/dev/null; then
        echo "$TS TOOLS_OK"
      else
        echo "$TS TOOLS_CHECK_FAILED"
      fi
      echo "$TS launching smoke test..."
      bash "$ROOT/scripts/run_dmriqc_smoke.sh"
      echo "$TS SMOKE_DONE"
      # Try submit full DWI if slurm up
      if sbatch "$ROOT/scripts/run_dmriqc_dwi.slurm"; then
        echo "$TS FULL_QC_SUBMITTED"
      else
        echo "$TS FULL_QC_SUBMIT_FAILED (run later: sbatch scripts/run_dmriqc_dwi.slurm)"
      fi
      echo "===== LIVE MONITOR DONE $(date -Is) ====="
      exit 0
    fi
  fi

  BW=$(cat "$LOG/build_from_rootfs.pid" 2>/dev/null || echo)
  AP=$(pgrep -f 'apptainer.bin build .*scilus' | head -1 || true)
  MK=$(pgrep -f 'mksquashfs .*alexrees_scilus|/tmp/alexrees_scilus' | head -1 || true)
  SQ=$(ls -lh /tmp/alexrees_scilus_build/*/squashfs-* 2>/dev/null | grep -v comp-test | tail -1 || echo none)
  PART=$(ls -lh /tmp/alexrees_scilus_build/scilus_1.4.2.sif 2>/dev/null || echo none)
  LAST=$(tail -1 "$LOG/build_from_rootfs.log" 2>/dev/null || echo)
  DF=$(df -h /tmp | awk 'NR==2{print $3" used / "$4" free"}')

  echo "$TS build=${BW:-?} apptainer=${AP:-none} mksq=${MK:-none}"
  echo "     partial=$PART"
  echo "     squash=$SQ"
  echo "     tmp=$DF | log=$LAST"

  # Detect dead wrapper without SIF
  if [[ -n "$BW" ]] && ! ps -p "$BW" >/dev/null 2>&1; then
    if [[ ! -f "$SIF" ]]; then
      echo "$TS BUILD_FAILED"
      tail -50 "$LOG/build_from_rootfs.log"
      tail -30 "$LOG/build_from_rootfs.err"
      exit 1
    fi
  fi
  sleep 30
done
echo "TIMEOUT"
exit 1
