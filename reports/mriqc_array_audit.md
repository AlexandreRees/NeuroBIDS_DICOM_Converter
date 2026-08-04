# MRIQC array audit

**Generated:** 2026-07-22T10:25:00-04:00  
**Array JobID:** `66078951` (`mriqc_array`, `#SBATCH --array=1-124%20`, walltime 24h)  
**Task list:** `metadata/mriqc_array_tasks.tsv` — **124** participant×session tasks  
**Derivatives:** `derivatives/mriqc/`  
**Full table:** `reports/mriqc_array_audit.tsv`

## Verdict

The array is **not healthy**. About **19 tasks have been zombie-RUNNING for ~17h** (logs frozen ~16h), which **blocks the `%20` concurrency limit** and starves the remaining ~63 pending tasks. Only **one** currently running task (`61`, sub-034 ses-02) is still writing logs and making progress.

A second critical issue: **Lustre file (inode) quota is nearly full** (`870684 / 1000000` files). Task 21 already failed with `Disk quota exceeded` despite having terabytes of space left (`2.7T / 18.6T`).

## Summary counts (participant × session)

| Status | Count | Notes |
| --- | ---: | --- |
| COMPLETE | 37 | Usable T1w (+ usually some BOLD) outputs |
| RUNNING (healthy) | 1 | Task 61 — log age ~0 |
| RUNNING (stuck / zombie) | 19 | Tasks 22–40 — log age ~16h |
| SLURM FAILED | 4 | Tasks 21, 41, 42, 43 |
| PENDING / not started | 63 | Tasks 62–124 (+ any not yet scheduled) |

Slurm histogram for job `66078951`: COMPLETED=37, FAILED=4, RUNNING=20.

## Why it feels “stuck for a long time”

1. **Concurrency choke:** `%20` max parallel tasks. Nineteen zombies occupy slots since ~2026-07-21 17:16.
2. **Stuck on functional MRIQC:** log tails show nipype `FileNotFoundError` under `funcMRIQC` (e.g. `EPI2MNI`, `estimate_hm`, `apply_hmc`) then **no further log output**.
3. **Workload is heavy by design:** each task runs `-m T1w bold` with ~10–14 BOLD runs per session → long runtimes even when healthy (completed tasks typically finished in roughly ~1h class; exact mean depends on session size).
4. **Inode pressure** amplifies failures and may contribute to nipype result-file loss.

## Failed tasks

| Task | Subject | Session | Elapsed | Likely cause |
| ---: | --- | --- | --- | --- |
| 21 | sub-011 | ses-02 | 49 min | `Disk quota exceeded` writing summary log; some outputs exist |
| 41 | sub-023 | ses-02 | 4 s | Exit `0:53` / batch CANCELLED (immediate) |
| 42 | sub-024 | ses-01 | 1 s | Exit `0:53` / batch CANCELLED (immediate) |
| 43 | sub-024 | ses-02 | 1 s | Exit `0:53` / batch CANCELLED (immediate) |

## Stuck tasks (cancel candidates)

Tasks **22–40** (sub-012 … sub-023 ses-01): Slurm state RUNNING, wallclock ~17h, **stdout mtime ~16h old**. Examples of last errors:

- sub-012 ses-01: missing `EPI2MNI/result_EPI2MNI.pklz`
- sub-021 ses-02 / sub-022 ses-01 / sub-023 ses-01: missing `fMRI_HMC/.../result_*.pklz`

Many already produced **T1w IQM JSON** but little/no BOLD completion.

## Quota

```
/lustre07/scratch  space: 2.739T / 18.63T
                   files: 870684 / 1000000   ← critical
```

MRIQC work trees under `tmp_processing/mriqc/` create huge numbers of small nipype files and are the first place to reclaim inodes.

## Recommended actions (in order)

1. **Cancel zombies** to free the array:
   ```bash
   scancel 66078951_[22-40]
   ```
2. **Reclaim inodes** (after cancel):
   ```bash
   # inspect then remove finished/stuck workdirs
   ls ~/scratch/tmp_processing/mriqc | wc -l
   # carefully: rm -rf selected sub-*_ses-* work dirs for stuck/completed tasks
   ```
3. **Retry** failed + cancelled tasks once quota headroom exists:
   ```bash
   sbatch --array=21,22-43 scripts/run_mriqc_array.slurm
   # or a dedicated retry list
   ```
4. Consider a **T1w-only** MRIQC pass for publication structural QC if BOLD IQMs are secondary (much faster, far fewer files).
5. Leave task **61** and pending **62–124** alone after freeing slots — they should resume under the same array job.

## Monitor

```bash
squeue -u $USER -n mriqc_array
sacct -j 66078951 --format=JobID,State,ExitCode,Elapsed -P | head
ls ~/scratch/reports/mriqc_array_audit.tsv
```
