# MRIQC retry notes — 2026-07-22

## Actions taken
1. Cancelled zombie tasks `66078951_[22-40]`.
2. Cleaned MRIQC workdirs under `tmp_processing/mriqc/` (finished + stale).
   - File quota: ~870k → ~733k / 1M inodes.
3. Submitted retry array for tasks **21–43**: job `66210990` (`mriqc_retry`).
4. Original array `66078951` continues for tasks 63–124 (and 62 if still alive).

## Retry mapping
Tasks 21–43 = sub-011 ses-02 through sub-024 ses-02 (see `metadata/mriqc_array_tasks.tsv`).

## Scripts
- `scripts/run_mriqc_array_retry_21_43.slurm`
