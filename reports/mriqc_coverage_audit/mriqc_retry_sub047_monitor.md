# MRIQC retry sub-047 monitor

**Goal:** recover `sub-047_ses-01_task-fmri_run-03_bold.json` (push coverage to 100% excl. pathological).

| Job | Script | Status |
|---|---|---|
| `66509759` | `scripts/run_mriqc_retry_sub047.slurm` | submitted |

Pass when: target IQM exists AND session has T1≥3, BOLD≥12.

## Checks

| Time | Note |
|---|---|
| 2026-07-27T19:00Z | Submitted job `66509759` (`mriqc_r047`) |
| 2026-07-27T19:03Z | **RUNNING** on nc10127; monitor armed (10 min) |
