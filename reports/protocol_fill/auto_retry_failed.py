#!/usr/bin/env python3
"""Detect newly failed proto_fill jobs, clear failed manifest rows, relaunch."""
from __future__ import annotations
import re, subprocess, time
from pathlib import Path
import pandas as pd

SCRATCH = Path('/home/alexrees/scratch')
SUBJ_LIST = SCRATCH/'metadata'/'slurm_subjects.txt'
STATE = SCRATCH/'reports'/'protocol_fill'/'auto_retry_state.txt'
LOG = SCRATCH/'reports'/'protocol_fill'/'auto_retry.log'
subjects = [ln.strip() for ln in SUBJ_LIST.read_text().splitlines() if ln.strip()]
STATE.touch()
known = set(STATE.read_text().split())

def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {msg}"
    print(line, flush=True)
    with LOG.open('a') as f:
        f.write(line+'\n')

def sacct_failed(job_ids: str) -> list[str]:
    out = subprocess.check_output(
        ['sacct','-j',job_ids,'--format=JobID,State,ExitCode','-P'],
        text=True)
    failed=[]
    for line in out.splitlines()[1:]:
        parts=line.split('|')
        if len(parts)<2: continue
        jid, state = parts[0], parts[1]
        if '.' in jid: continue
        if state=='FAILED':
            failed.append(jid)
    return failed

def subject_for_array_task(task: int) -> str | None:
    if 1 <= task <= len(subjects):
        return subjects[task-1]
    return None

def clear_failed_manifest(subject: str) -> int:
    p = SCRATCH/'reports'/'shards'/subject/'processing_manifest.tsv'
    if not p.exists():
        return 0
    df=pd.read_csv(p, sep='\t', dtype=str).fillna('')
    drop = df['conversion_status']=='failed'
    n=int(drop.sum())
    if n:
        df.loc[~drop].to_csv(p, sep='\t', index=False)
    return n

def relaunch(subject: str) -> str:
    cmd = (
        f'SUBJECT={subject} RESUME=1 sbatch --parsable '
        f'--job-name=proto_fill_fix --time=06:00:00 --array=1-1 '
        f'--output={SCRATCH}/logs/protocol_fill_fix_{subject}_%j.out '
        f'--error={SCRATCH}/logs/protocol_fill_fix_{subject}_%j.err '
        f'{SCRATCH}/neuro_pipeline/slurm/run_pipeline_array.slurm'
    )
    return subprocess.check_output(cmd, shell=True, text=True).strip()

# Main job + known retry parents
parent_jobs = '66496517,66498247,66498248,66498850,66498851'
# Also discover other proto_fill_fix jobs
try:
    q = subprocess.check_output(['squeue','-u','alexrees','-h','-o','%i %j'], text=True)
    for line in q.splitlines():
        parts=line.split()
        if len(parts)>=2 and parts[1].startswith('proto_fill'):
            parent_jobs += ',' + parts[0].split('_')[0]
except Exception:
    pass

failed = sacct_failed(parent_jobs)
new = [j for j in failed if j not in known]
if not new:
    log(f'no new failures (known={len(known)} total_failed={len(failed)})')
else:
    for jid in new:
        known.add(jid)
        STATE.write_text('\n'.join(sorted(known))+'\n')
        m = re.match(r'(\d+)_(\d+)$', jid)
        sub=None
        if m and m.group(1)=='66496517':
            sub = subject_for_array_task(int(m.group(2)))
        if not sub:
            # try log
            logs=list((SCRATCH/'logs').glob(f'*{jid}*.out'))
            for lp in logs:
                txt=lp.read_text(errors='ignore')
                mm=re.search(r'subject=(SUB[A-Z0-9]+)|SUBJECT override: (SUB[A-Z0-9]+)|→ subject (SUB[A-Z0-9]+)', txt)
                if mm:
                    sub=next(g for g in mm.groups() if g)
                    break
        if not sub:
            log(f'cannot map {jid} to subject')
            continue
        # Skip if a fix/retry already running for this subject
        q = subprocess.check_output(['squeue','-u','alexrees','-h','-o','%i %j'], text=True)
        busy=False
        for line in q.splitlines():
            if 'proto_fill_fix' in line or 'proto_fill_retry' in line:
                # check log association
                base=line.split()[0].split('_')[0]
                for lp in (SCRATCH/'logs').glob(f'protocol_fill_*_{sub}_*.out'):
                    if base in lp.name:
                        busy=True
                        break
                for lp in (SCRATCH/'logs').glob(f'protocol_fill_*{base}*.out'):
                    t=lp.read_text(errors='ignore')[:2000]
                    if sub in t and ('SUBJECT override' in t or f'subject={sub}' in t):
                        busy=True
                        break
            if busy:
                break
        if busy:
            log(f'skip relaunch {sub} from {jid}: already running')
            continue
        n=clear_failed_manifest(sub)
        try:
            newj=relaunch(sub)
            log(f'relaunch {sub} from {jid} cleared_failed={n} -> {newj}')
        except Exception as e:
            log(f'relaunch FAILED {sub}: {e}')
