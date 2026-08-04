#!/bin/bash
set -euo pipefail
LOG=/home/alexrees/scratch/reports/protocol_fill/monitor.log
STATE=/home/alexrees/scratch/reports/protocol_fill/known_failures.txt
touch "$STATE"
echo "$(date -Is) monitor start" >> "$LOG"
for round in $(seq 1 80); do
  # New FAILED array tasks
  sacct -j 66496517,66498247,66498248 --format=JobID,State,ExitCode -P 2>/dev/null \
    | awk -F'|' 'NR>1 && $1!~/\./ && $2=="FAILED" {print $1}' | sort -u > /tmp/pf_failed_now.txt
  NEW=$(comm -13 <(sort -u "$STATE") /tmp/pf_failed_now.txt || true)
  if [[ -n "${NEW:-}" ]]; then
    echo "$(date -Is) NEW_FAILURES:" >> "$LOG"
    echo "$NEW" >> "$LOG"
    for jid in $NEW; do
      echo "$jid" >> "$STATE"
      # extract task id
      task=${jid##*_}
      if [[ "$jid" == 66496517_* ]]; then
        sub=$(sed -n "${task}p" /home/alexrees/scratch/metadata/slurm_subjects.txt)
      else
        # retry jobs - parse from log
        sub=$(rg -o 'subject=SUB[A-Z0-9]+|SUBJECT override: SUB[A-Z0-9]+|→ subject SUB[A-Z0-9]+' /home/alexrees/scratch/logs/protocol_fill_*${jid}*.out /home/alexrees/scratch/logs/protocol_fill_retry_*${jid}*.out 2>/dev/null | head -1 | rg -o 'SUB[A-Z0-9]+' || true)
      fi
      echo "  task=$task subject=$sub" >> "$LOG"
      # capture error snippet
      out=$(ls /home/alexrees/scratch/logs/protocol_fill_${jid}.out /home/alexrees/scratch/logs/protocol_fill_retry_*_${jid}.out 2>/dev/null | head -1 || true)
      if [[ -n "$out" ]]; then
        rg -n 'Subject worker failed|EmptyDataError|FATAL|Traceback|Error' "$out" 2>/dev/null | tail -20 >> "$LOG" || true
      fi
      echo "NEEDS_RETRY $sub $jid" >> /home/alexrees/scratch/reports/protocol_fill/needs_retry.tsv
    done
  fi
  # progress counts
  n_loc=$(ls /home/alexrees/scratch/bids/sub-*/ses-*/anat/*localizer*.nii.gz 2>/dev/null | wc -l)
  n_r03=$(ls /home/alexrees/scratch/bids/sub-*/ses-*/dwi/*run-03_dwi.nii.gz 2>/dev/null | wc -l)
  n_r11=$(ls /home/alexrees/scratch/bids/sub-*/ses-*/dwi/*run-11_dwi.nii.gz 2>/dev/null | wc -l)
  n_run=$(squeue -j 66496517,66498247,66498248 -h 2>/dev/null | wc -l)
  echo "$(date -Is) progress loc=$n_loc run03=$n_r03 run11=$n_r11 queue=$n_run" >> "$LOG"
  if [[ "$n_run" -eq 0 ]]; then
    echo "$(date -Is) queue empty — monitor exit" >> "$LOG"
    break
  fi
  sleep 90
done
