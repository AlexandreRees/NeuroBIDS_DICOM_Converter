#!/usr/bin/env bash
# Watchdog: follow scilus SIF creation; auto-correct and relaunch on failure.
set -u
ROOT=/lustre07/scratch/alexrees
SIF=$ROOT/containers/scilus_1.4.2.sif
LOG=$ROOT/logs/dmriqc
SNAP=$LOG/watchdog.out
PIDFILE=$LOG/watchdog.pid
echo $$ > "$PIDFILE"

exec >> "$SNAP" 2>&1
echo "===== WATCHDOG START $(date -Is) pid=$$ ====="

ensure_slurm_build() {
  # Keep a compute-node build job in queue if SIF missing
  if [[ -f "$SIF" ]] && [[ -s "$SIF" ]]; then return 0; fi
  local running
  running=$(squeue -u alexrees -h -n build_scilus -o '%i %T' 2>/dev/null | head -1 || true)
  if [[ -z "$running" ]]; then
    echo "$(date +%H:%M:%S) submitting build_scilus.slurm"
    sbatch "$ROOT/scripts/build_scilus_from_rootfs.slurm" || echo "sbatch build failed"
  else
    echo "$(date +%H:%M:%S) slurm build present: $running"
  fi
}

ensure_login_lowmem() {
  if [[ -f "$SIF" ]] && [[ -s "$SIF" ]]; then return 0; fi
  if pgrep -f 'rebuild_lowmem_wrapper.sh|rebuild_scilus_from_rootfs.sh' >/dev/null 2>&1; then
    return 0
  fi
  # Only restart login path if /tmp has space and rootfs source exists
  if [[ ! -d "$ROOT/work/dmriqc/tmp_pull/build-temp-100781115/rootfs" ]]; then
    echo "$(date +%H:%M:%S) no lustre rootfs — skip login rebuild"
    return 0
  fi
  echo "$(date +%H:%M:%S) login build dead — relaunching lowmem wrapper"
  nohup bash "$LOG/rebuild_lowmem_wrapper.sh" >> "$LOG/build_restart.nohup" 2>&1 &
  echo "$(date +%H:%M:%S) relaunched login PID=$!"
}

launch_smoke_if_ready() {
  local s1 s2
  [[ -f "$SIF" ]] && [[ -s "$SIF" ]] || return 1
  s1=$(stat -c%s "$SIF")
  sleep 5
  s2=$(stat -c%s "$SIF")
  [[ "$s1" == "$s2" ]] && [[ "$s1" -gt 1000000000 ]] || return 1
  echo "$(date +%H:%M:%S) SIF_READY $(ls -lh "$SIF")"
  module load StdEnv/2023 apptainer/1.3.5 >/dev/null 2>&1 || true
  unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY all_proxy
  if apptainer exec "$SIF" bash -lc 'command -v dmriqc_generic.py' 2>/dev/null; then
    echo "$(date +%H:%M:%S) TOOLS_OK"
  else
    echo "$(date +%H:%M:%S) TOOLS_CHECK_FAILED — not launching smoke"
    return 1
  fi
  # Avoid double smoke
  if [[ -f "$LOG/smoke_launched.flag" ]]; then
    echo "$(date +%H:%M:%S) smoke already launched"
    return 0
  fi
  touch "$LOG/smoke_launched.flag"
  echo "$(date +%H:%M:%S) launching smoke..."
  bash "$ROOT/scripts/run_dmriqc_smoke.sh" && echo "$(date +%H:%M:%S) SMOKE_DONE" || echo "$(date +%H:%M:%S) SMOKE_FAILED"
  if sbatch "$ROOT/scripts/run_dmriqc_dwi.slurm"; then
    echo "$(date +%H:%M:%S) FULL_QC_SUBMITTED"
  else
    echo "$(date +%H:%M:%S) FULL_QC_SUBMIT_FAILED"
  fi
  return 0
}

# Initial ensure
ensure_slurm_build

for i in $(seq 1 480); do
  TS=$(date +%H:%M:%S)
  TMP_SZ=$(du -sh /tmp/alexrees_scilus_build 2>/dev/null | awk '{print $1}' || echo 0)
  DF=$(df -h /tmp | awk 'NR==2{print $3"/"$2" used "$5}')
  LAST=$(tail -1 "$LOG/build_from_rootfs.log" 2>/dev/null || echo)
  LOGIN=$(pgrep -c -f 'rebuild_lowmem_wrapper|rebuild_scilus_from_rootfs|rsync .*alexrees_scilus|apptainer.bin build .*scilus' 2>/dev/null || echo 0)
  SQ=$(squeue -u alexrees -h -n pull_scilus,build_scilus -o '%i:%j:%T' 2>/dev/null | tr '\n' ' ' || echo none)
  FATAL=$(tail -5 "$LOG/build_from_rootfs.log" 2>/dev/null | grep -c 'FATAL\|signal: killed' || true)

  echo "$TS tmp=$TMP_SZ df=$DF login_procs=$LOGIN slurm=[$SQ]"
  echo "     log=$LAST"

  if launch_smoke_if_ready; then
    echo "===== WATCHDOG DONE $(date -Is) ====="
    exit 0
  fi

  # If recent FATAL and login build not running, relaunch
  if [[ "${FATAL:-0}" -gt 0 ]]; then
    if ! pgrep -f 'rebuild_lowmem_wrapper.sh|apptainer.bin build .*scilus' >/dev/null 2>&1; then
      # Only relaunch if FATAL is the newest significant line (build died)
      if ! pgrep -f 'rsync .*alexrees_scilus' >/dev/null 2>&1; then
        ensure_login_lowmem
      fi
    fi
  fi

  # Keep Slurm build job alive if SIF missing
  if (( i % 3 == 0 )); then
    ensure_slurm_build
  fi

  # Detect login wrapper death without SIF
  if [[ -f "$LOG/rebuild_lowmem.pid" ]]; then
    BP=$(cat "$LOG/rebuild_lowmem.pid" 2>/dev/null || true)
    if [[ -n "${BP:-}" ]] && ! ps -p "$BP" >/dev/null 2>&1; then
      if [[ ! -f "$SIF" ]]; then
        echo "$TS login PID $BP dead without SIF — relaunch"
        ensure_login_lowmem
      fi
    fi
  elif ! pgrep -f 'rebuild_lowmem_wrapper.sh|rebuild_scilus_from_rootfs.sh|rsync .*alexrees_scilus' >/dev/null 2>&1; then
    if [[ ! -f "$SIF" ]]; then
      # Don't spam relaunch every loop — every 10 iterations (~5 min if 30s sleep)
      if (( i % 10 == 0 )); then
        ensure_login_lowmem
      fi
    fi
  fi

  sleep 30
done

echo "TIMEOUT $(date -Is)"
exit 1
