# Movie timing recovery audit

Generated: `2026-07-28T14:38:55Z`  
Scope: **read-only** feasibility assessment. No `events.tsv` were created.  
Outputs: `reports/movie_timing_recovery_audit/` only.

## Summary

| Item | Count |
| --- | ---: |
| Magnitude `task-movie` BOLD runs (release inventory) | 536 |
| MATLAB/Psychtoolbox files audited (.m + .mat) | 862 |
| MATLAB classified `RECOVERABLE_TIMING` | 0 |
| MATLAB classified `PARTIAL` (run_id identity) | 706 |
| MATLAB classified `NO_TIMING` | 156 |
| Movie PhysioLog series audited | 538 |
| PhysioLog with EXT samples extracted | 504 |
| PhysioLog EXT usable for **scanner volume** sync (TR-like train) | 0 |
| PhysioLog EXT usable for **stimulus onset** | 0 |
| Peripheral physio files | 642 (ext/ext2=216) |
| Peripheral run-mapping possible | 0 |
| Movie BOLD DICOM series summarized | 1607 |
| DICOM-derived stimulus onset recoverable | 0 |

### Cross-map classifications (`movie_bold_inventory.tsv`)

| Classification | n |
| --- | ---: |
| `INSUFFICIENT_FOR_EVENTS` | 536 |


## Source evaluation

| Source | n audited | Can reconstruct stimulus-locked `events.tsv`? | Why |
| --- | ---: | --- | --- |
| MATLAB Results `.mat` | 550 | **No** | Variables are `run_id` / `change_eye` / operator `t` datestr — **zero** `triggerTimes` / `vbl` / frame clocks |
| Psychtoolbox `.m` | 312 | **No** | `Show_movie.m` uses `KbQueueWait` for key `t` but **does not save** trigger or Flip timestamps |
| PhysioLog EXT | 538 | **No** (for events) | EXT present on most Movie PhysioLogs, but transitions are **sparse** (median trigger_count=1.0; max=1) — not a TR-locked volume train and not a stimulus-onset marker log. `usable_for_stimulus_onset=FALSE` for all series |
| Peripheral `.ext`/`.ext2` | 216 | **No** | Session-wide PMU exports without absolute timestamps or per-run segmentation (`run_mapping_possible=NO`) |
| DICOM CSA / TriggerTime | 1607 | **No** | `TriggerTime` (when present) is **within-volume slice timing**, not movie onset |

## What would be required for recoverable movie events

1. A logged stimulus clock at movie start (e.g. `GetSecs` / VBL after `KbQueueWait`), **or** an external TTL recorded at onset with known alignment to BOLD volume 0  
2. Unique mapping of that clock to the BIDS magnitude run  
3. Explicit policy that onsets are **measured**, not assumed as `volume_index * TR`

## Explicit non-actions (policy compliance)

- No `events.tsv` written  
- No onset = `volume * TR` assumption  
- No assumption that the film starts at the first volume  
- `run_id` treated as **identity only**, never as timing  
- `bids/` and `release_dataset/` not modified  

## Conclusion

**Movie events.tsv cannot be reconstructed because stimulus onset timing relative to scanner acquisition is unavailable.**

## Artifacts

- `PSYCHTOOLBOX_MATLAB_AUDIT.tsv`
- `PHYSIOLOG_EXT_AUDIT.tsv`
- `PERIPHERAL_EXT_AUDIT.tsv`
- `DICOM_CSA_TRIGGER_AUDIT.tsv`
- `movie_bold_inventory.tsv`
- `MOVIE_TIMING_RECOVERY_REPORT.md` (this file)
