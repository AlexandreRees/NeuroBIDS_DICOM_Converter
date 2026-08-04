# MRIQC retry2 monitor

**Started:** 2026-07-27T17:17Z  
**Loop:** every 10 min (PID monitor shell)  
**Policy:** auto-relaunch on FAIL / 0 IQMs; accept missing `sub-024_ses-01_run-03_T1w` (pathological)

## Active job

| Job | Tasks | Status |
|---|---|---|
| `66502493` | 1=sub-024/ses-01, 2=sub-074/ses-02 | PENDING (Priority) |

## Checks

| Time (UTC) | Note |
|---|---|
| 2026-07-27T17:17Z | Armed monitor; job still queued |
| 2026-07-27T17:20Z | Both array tasks **RUNNING** (nc10929=sub-024, nc30452=sub-074) |
| 2026-07-27T17:29Z | Still RUNNING (~10 min); sub-024 still at prior IQMs 1/3+9/12; sub-074 still 0/0 (in progress) |
| 2026-07-27T17:39Z | Still RUNNING (~20 min); logs active (sanitize/HMC). No FAIL yet. |
| 2026-07-27T17:49Z | Still RUNNING (~30 min); IQMs: sub-024 T1 1/3 BOLD 9/12; sub-074 T1 0/3 BOLD 0/11. Logs active (HMC/Spikes). No FAIL/segfault/MRIQC exit=. No resubmit. |
| 2026-07-27T18:10Z | Still RUNNING (~45–51 min); IQMs: sub-024 T1 2/≥2 BOLD 9/≥12; sub-074 T1 1/≥3 BOLD 0/≥11. Tasks _1/_2 RUNNING on nc10929/nc30452. No FAIL/segfault/MRIQC exit=. No resubmit. |
2026-07-27T14:14:22-04:00 | job=66502493 mriqc_fix2 BOTH_RUNNING elapsed~00:55 | IQM sub-024 T1=2 BOLD=9 (need T1>=2 BOLD>=12) | sub-074 T1=1 BOLD=0 (need T1>=3 BOLD>=11) | no fatal log patterns | action=WAIT
2026-07-27T14:21:16-04:00 | job=66502493 RUNNING (tasks 1+2 ~01:01:51) | sub-024 T1=2 BOLD=9 (need T1>=2 BOLD>=12) | sub-074 T1=3 BOLD=0 (need T1>=3 BOLD>=11) | logs: no exit/segfault/BrokenProcessPool yet | action=wait
2026-07-27T18:40:39Z DONE job=66502493 array=_1:RUNNING(01:21)_2:COMPLETED(0:0) IQMs sub-024 T1=3/BOLD=12 sub-074 T1=3/BOLD=11 PASS; monitor killed
