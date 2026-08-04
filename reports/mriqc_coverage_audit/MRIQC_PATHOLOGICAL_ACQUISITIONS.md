# MRIQC pathological acquisitions (accepted gaps)

**Updated:** 2026-07-27  
**Policy:** Do **not** re-retry these runs without a manual decision (exclude / replace / investigate DICOM). MRIQC fails correctly with `RuntimeError: Input inhomogeneity-corrected data seem empty` (or equivalent empty/invalid input).

## Accepted pathological cases

| Session | Run | BIDS finding | MRIQC outcome | Status |
|---|---|---|---|---|
| sub-002 / ses-01 | `task-fmri_run-07_bold` | **Truncated:** 4 volumes (expected ~226) | no IQM | **Accepted** |
| sub-011 / ses-01 | `task-fmri_run-03_bold` | **Truncated:** 3 volumes (expected ~226) | no IQM | **Accepted** |
| sub-039 / ses-02 | `run-03_T1w` | **Out-of-protocol T1:** FOV 192×224×224 @ 1.0 mm (OK sibling: 208×300×320 @ 0.8 mm); low intensity | no IQM | **Accepted** |
| sub-058 / ses-01 | `run-03_T1w` | **Out-of-protocol T1:** same FOV/intensity pattern as sub-039 | no IQM | **Accepted** |
| sub-066 / ses-02 | `run-03_T1w` | **Out-of-protocol T1:** same empty/abnormal N4 pattern after ses-02 retry11 MRIQC (BOLD 12/12 OK; T1 2/3) | no IQM | **Accepted (added 2026-07-27)** |
| sub-024 / ses-01 | `run-03_T1w` | **Out-of-protocol T1:** FOV 192×224×224, midslice max≈282 (OK runs: 208×300×320, max≈4095) | no IQM expected | **Accepted (documented 2026-07-27)** |

## Not pathological — MRIQC recovery

| Session | Missing / failed | Diagnosis | Action |
|---|---|---|---|
| sub-024 / ses-01 | prior partial IQMs | Healthy inputs | **Recovered** (`mriqc_retry2` → COMPLETE) |
| sub-074 / ses-02 | 0 IQMs after segfault | AFNI / BrokenProcessPool | **Recovered** (`mriqc_retry2` → COMPLETE) |
| sub-047 / ses-01 | `task-fmri_run-03_bold` | Healthy 226 vols; prior MRIQC left 11/12 BOLD | **Retry** (`mriqc_r047`) |

## Retry jobs

- sub-024 / sub-074: `metadata/mriqc_retry_partial_and_074.tsv` → `scripts/run_mriqc_retry_partial_and_074.slurm` (`logs/mriqc_retry2/`)
- sub-047: `metadata/mriqc_retry_sub047.tsv` → `scripts/run_mriqc_retry_sub047.slurm` (`logs/mriqc_retry_sub047/`)

## Notes for Technical Validation / PI

- Deposit narrative: MRIQC covers supported modalities (T1w + magnitude BOLD). Remaining gaps are **data pathology** (truncated BOLD or out-of-protocol T1), plus any transient compute failures that are re-queued.
- sub-066/ses-02 is otherwise complete (12/12 BOLD IQMs; 2/3 T1w). Only `run-03_T1w` is excluded from the “expected recoverable” set.
