# Events generation report

Generated: `2026-07-27T21:27:03Z` (updated after layout + validator)

## Policy

- Read-only on MATLAB sources and BOLD NIfTIs (never modified).
- No invented timing: events only when measured `triggerTimes` exist.
- Full reconstructed events live under `tmp_processing/events_validation/all_events/` (validation staging, not integrated into `bids/`).
- `events_preview/` holds a few human-inspection examples only.

## Counts

| Metric | Value |
|--------|------:|
| MATLAB inventory rows | 2174 |
| Validation units analyzed | 957 |
| Grating (`task-fmri`) events files generated | **470** unique on disk |
| Total event rows written | 11750 |
| Movie events written | 0 |
| Rest events written | 0 |
| Units without usable timing / identity-only | 486 |
| Problem rows (non-unique sources / missing triggers) | 13 fmri |
| BIDS run-mapping collisions (rescued) | 8 pairs → 16 files with `desc-matlabFMRI*` |

> When ProtocolName→`run-XX` was ambiguous, files were written as `*_run-XX_desc-matlabFMRI{N}_events.tsv` (confidence MEDIUM) instead of overwriting.

## By task

- **fmri (Grating → `task-fmri`)**: 483 runs analyzed, **470** with events created, confidence **HIGH** when written (measured `triggerTimes` + stim order).
- **movie**: 473 run units, **0** events (no `triggerTimes` / VBL; `run_id` identity only → `MEDIUM_IDENTITY_ONLY` / marked not created).
- **rest**: no events (see `RESTING_STATE_EVENTS_ASSESSMENT.md`).

## Problems detected (fmri, no events)

| Reason | n |
|--------|--:|
| Non-unique or missing `scan_info` / stim sources | 11 |
| No usable `triggerTimes` (n&lt;2) | 2 |

## Movie

Movie Results `.mat` provide `selected_run_id` / `run_id` (and often `answer`) but **no scanner-locked `triggerTimes`**. Writing `onset`/`duration` would invent timing → **no `*_task-movie_*_events.tsv`**.

## Resting state

See `RESTING_STATE_EVENTS_ASSESSMENT.md` — **events.tsv not required / not generated** (0 rest `.mat` in inventory).

## Traceability

| Artifact | Role |
|----------|------|
| `MATLAB_EVENTS_SOURCE_INVENTORY.tsv` | Source inventory + `source_sha256_16` |
| `events_validation.tsv` | Per-run create/skip decision |
| `tmp_processing/events_validation/all_events/*_events.json` | Provenance (MATLAB paths + SHA16 + confidence) |
| `events_preview/` | 4 example TSV+JSON pairs |

## bids-validator (mini tree `sub-001/ses-01`)

Command: `bids-validator@1.14.6` on `tmp_processing/events_validation_bids/`.

| Class | Key | Notes |
|-------|-----|-------|
| error | `VOLUME_COUNT_MISMATCH` | Pre-existing DWI (`run-07_dwi`), **not** events-related |
| warning | `EVENTS_TSV_MISSING` | `task-control` + `task-fmri` **part-phase** BOLD (expected; no events for phase/control) |
| warning | `INCONSISTENT_PARAMETERS`, `README_FILE_MISSING`, `TOO_FEW_AUTHORS` | Dataset meta, unrelated to events |

**No events.tsv schema errors** reported for the reconstructed `task-fmri` magnitude events overlaid in the mini tree.

## Outputs layout

```
reports/events_reconstruction/
  MATLAB_EVENTS_SOURCE_INVENTORY.tsv
  events_validation.tsv
  events_generation_report.md
  RESTING_STATE_EVENTS_ASSESSMENT.md
  events_preview/          # few examples
  bids_validator_events_preview*.json
  reconstruct_events_from_matlab.py

tmp_processing/events_validation/all_events/   # full *_events.tsv + provenance JSON
tmp_processing/events_validation_bids/         # mini BIDS hardlink tree for validator
```
