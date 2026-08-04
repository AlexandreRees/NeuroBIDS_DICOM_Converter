#!/usr/bin/env bash
# Safer DWI mask fill: max 1 concurrent worker, streaming signal metrics.
# Prefer Slurm (run_dwi_qc_fill_array.slurm); this is a login fallback only.

set -euo pipefail

OUT=/home/alexrees/scratch/reports/dwi_qc
MISS=${OUT}/missing_mask_indices.txt
LOG=/home/alexrees/scratch/logs/dwi_qc/fill_login_safe.log
PIDF=/home/alexrees/scratch/logs/dwi_qc/fill_login_safe.pid
MAX_JOBS=1

mkdir -p /home/alexrees/scratch/logs/dwi_qc "${OUT}/fill_parts" "${OUT}/tmp" "${OUT}/figures"

if [[ -f "$PIDF" ]] && kill -0 "$(cat "$PIDF")" 2>/dev/null; then
  echo "Already running PID $(cat "$PIDF")"
  exit 0
fi

module purge || true
module load StdEnv/2023 python/3.11 mrtrix/3.0.8
export PYTHONUNBUFFERED=1

# Refresh missing list from current NaN masks if present; else keep existing.
python3.11 /home/alexrees/scratch/code/fill_dwi_qc_mask_one.py --write-missing-list

# Build pending task ids (no OK part yet)
python3.11 - <<'PY'
from pathlib import Path
import json
miss=[int(x) for x in Path('/home/alexrees/scratch/reports/dwi_qc/missing_mask_indices.txt').read_text().splitlines() if x.strip()]
ok=set()
for p in Path('/home/alexrees/scratch/reports/dwi_qc/fill_parts').glob('idx_*.json'):
    try:
        d=json.loads(p.read_text())
    except Exception:
        continue
    if d.get('status')=='OK':
        ok.add(int(d['index']))
pending=[str(i) for i,idx in enumerate(miss) if idx not in ok]
Path('/home/alexrees/scratch/reports/dwi_qc/pending_task_ids.txt').write_text('\n'.join(pending)+('\n' if pending else ''), encoding='utf-8')
print(f'pending tasks: {len(pending)}')
PY

nohup bash -c '
  set -euo pipefail
  module purge || true
  module load StdEnv/2023 python/3.11 mrtrix/3.0.8
  export PYTHONUNBUFFERED=1
  PENDING=/home/alexrees/scratch/reports/dwi_qc/pending_task_ids.txt
  echo "START $(date -Is) pending=$(wc -l < "$PENDING") MAX_JOBS='"$MAX_JOBS"'"
  while read -r tid; do
    [[ -z "$tid" ]] && continue
    while [[ $(jobs -rp | wc -l) -ge '"$MAX_JOBS"' ]]; do sleep 3; done
    (
      python3.11 /home/alexrees/scratch/code/fill_dwi_qc_mask_one.py --task-id "$tid" \
        && echo "OK task $tid" \
        || echo "FAIL task $tid"
    ) &
    echo "launched $tid at $(date -Is)"
  done < "$PENDING"
  wait
  echo "ALL WORKERS DONE $(date -Is)"
  python3.11 /home/alexrees/scratch/code/fill_dwi_qc_mask_one.py --merge
  echo "MERGE DONE $(date -Is)"
' > "$LOG" 2>&1 &
echo $! > "$PIDF"
echo "Started safe fill PID $(cat "$PIDF") log $LOG"
