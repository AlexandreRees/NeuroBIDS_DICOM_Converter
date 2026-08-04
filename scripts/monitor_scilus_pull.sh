#!/usr/bin/env bash
# Monitor scilus pull; print status; exit 0 when SIF ready.
set -u
ROOT=/lustre07/scratch/alexrees
SIF=$ROOT/containers/scilus_1.4.2.sif
LOG=$ROOT/logs/dmriqc
PIDFILE=$LOG/pull_scilus_tmp.pid

for i in $(seq 1 240); do  # up to ~2h
  TS=$(date +%H:%M:%S)
  if [[ -f "$SIF" ]] && [[ -s "$SIF" ]]; then
    sz=$(stat -c%s "$SIF")
    sleep 5
    sz2=$(stat -c%s "$SIF")
    if [[ "$sz" == "$sz2" ]] && [[ "$sz" -gt 1000000000 ]]; then
      echo "$TS SIF_READY $(ls -lh "$SIF")"
      if grep -q ALL_DONE "$LOG/pull_scilus_tmp.log" 2>/dev/null; then
        echo "$TS ALL_DONE confirmed"
      fi
      exit 0
    fi
  fi

  PPID_PULL=""
  [[ -f "$PIDFILE" ]] && PPID_PULL=$(cat "$PIDFILE")
  AP=$(pgrep -f 'apptainer.bin pull .*scilus' | head -1 || true)
  MK=$(pgrep -f 'mksquashfs .*alexrees_scilus' | head -1 || true)
  SQ=$(ls -lh /tmp/alexrees_scilus_build/*/squashfs-* 2>/dev/null | tail -1 || true)
  PART=$(ls -lh /tmp/alexrees_scilus_build/scilus_1.4.2.sif 2>/dev/null || true)
  ERR=$(tail -1 "$LOG/pull_scilus_tmp.err" 2>/dev/null || true)
  DF=$(df -h /tmp | awk 'NR==2{print $4" free"}')

  echo "$TS pull=${AP:-none} mksq=${MK:-none} partial=${PART:-n/a} squash=${SQ:-n/a} tmp=$DF last=$ERR"

  # Detect failure
  if [[ -n "${PPID_PULL}" ]] && ! ps -p "$PPID_PULL" >/dev/null 2>&1; then
    if [[ ! -f "$SIF" ]]; then
      echo "$TS PULL_FAILED — wrapper exited without SIF"
      tail -40 "$LOG/pull_scilus_tmp.err"
      exit 1
    fi
  fi
  sleep 30
done
echo "TIMEOUT waiting for SIF"
exit 1
