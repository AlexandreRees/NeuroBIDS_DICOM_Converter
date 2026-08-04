# Recovered events — Phase 2 (all cohorts)

**Date (UTC):** 2026-07-23T20:25:48Z
**Scope:** Control, DataON, DataTON, Glaucoma — same reconstruction logic as Phase 1 / Level-1.
**Policy:** No invented timing. No interpolation. No inferred triggers. Write `events.tsv` only when `scan_info` + stimulus order + BOLD ProtocolName mapping are each unique.

## Final coverage table

| Metric | N |
|---|---:|
| `task-fmri` non-phase BOLD runs | 507 |
| Events present **before** Phase 2 | 350 |
| **New events written (Phase 2 cumulative)** | **106** |
| Events present **after** Phase 2 (**Recovered**) | **456** |
| **Remaining impossible under strict rules** | **51** |
| **Coverage %** | **89.94%** |

| Cohort | Events after Phase 2 | Remaining missing |
|---|---:|---:|
| Control | 354 | 43 |
| DataON | 23 | 2 |
| DataTON | 8 | 0 |
| Glaucoma | 71 | 6 |

### Compact final table

| Recovered | Remaining impossible | Coverage % |
|---:|---:|---:|
| 456 | 51 | 89.94% |

## Method

1. Bind each BIDS `(participant_id, session_id)` to freeze `session_mapping` visit folder(s).
2. Discover grating Results under those visits (`2-Grating/Results`, `2-Grating_rerun/Results`). Session1/Session2 *subdirectory labels* are ignored when they sit inside the mapped visit.
3. **Date-unique rescue (no guessing):** if the mapped visit has no Results, accept exactly one Results tree under any visit folder of the **same participant** whose `scan_info` filename dates are a non-empty subset of that session’s `acquisition_date`. Used for `sub-004/ses-02` (MATLAB physically stored under the Session1 tree).
4. Require unique `scan_info` (`triggerTimes`) and unique stim order (`fMRI_N.mat` or dated `sequence_of_stimuli`) per `fMRI_number`.
5. Build events via matching `runs_random` when identity matches; else canonical `presentStimParams.m` paradigm + measured triggers (terminal boundary = last trigger + measured median TR only when TR is stable).
6. Attach to BIDS only when ProtocolName/SeriesDescription yields **exactly one** non-phase `task-fmri` BOLD sidecar.

## Previous events

Before Phase 2, **350** `task-fmri` events files were present (Level-1 release + Phase-1 Control recovery). Phase 2 never overwrites existing files.

## New events (Phase 2)

**106** new files written across Phase-2 passes:

- Pass 1 (cohort expansion / subject-ID padding fix via visit binding): **102** (DataON 23, DataTON 8, Glaucoma 71)
- Pass 2 (date-unique Session1/2 rescue): **4** (`sub-004/ses-02`)

Methods used among Phase-2 writes (from generation logs): `canonical_paradigm` and `strict_runs_random` (same as Phase 1).

Detail: `phase2_events_generation.tsv`.

## Remaining missing

**51** BOLD runs still lack events.

### Reason summary

| Reason class | N runs |
|---|---:|
| ProtocolName↔BOLD not unique (or absent) | 34 |
| non-unique scan_info / stim_order cardinality | 9 |
| no grating Results (true archive gap or unmapped visit) | 8 |

Per-run table: `phase2_remaining_missing.tsv`.

### Non-Control remaining (after Phase 2)

| Participant | Session | Run | Cohort | Protocol |
|---|---|---:|---|---|
| sub-061 | ses-01 | 05 | DataON | fMRI1_AP |
| sub-061 | ses-01 | 07 | DataON | fMRI1_AP |
| sub-078 | ses-01 | 01 | Glaucoma | fMRI3_AP |
| sub-078 | ses-01 | 03 | Glaucoma | fMRI4_AP |
| sub-078 | ses-01 | 05 | Glaucoma | fMRI1_AP |
| sub-078 | ses-01 | 07 | Glaucoma | fMRI2_AP |
| sub-083 | ses-01 | 07 | Glaucoma | fMRI1_AP |
| sub-083 | ses-01 | 09 | Glaucoma | fMRI1_AP |

Typical causes: duplicate ProtocolName (`fMRI1_AP` on two BOLD runs — `sub-061`, `sub-083`), or no grating Results in the mapped visit (`sub-078` Session1 visit has imaging only; MATLAB lives on Session02 visit with a different acquisition date — not linked without guessing).

## sub-051 (SUBC052) — remaining impossible?

**Yes — 4 / 51 remaining runs belong to `sub-051`, but it is not the only remaining gap.**

Precise cause for `sub-051`:

- BIDS: `sub-051/ses-01` has four grating BOLD series (`fMRI1_AP`…`fMRI4_AP`).
- Canonical ID: `SUBC052` (Control).
- Mapped visit: `/project/def-amirs/raw_original/Control/SUBC52_SESSION01_2024NOV05` (acquisition_date `20241105`).
- On disk: DICOM + peripheral recording only.
- **No `2-Grating/Results` (and no dated rescue hit)** → no `scan_info.triggerTimes`, no `Stim_order_selected`.
- Phase-2 status: `failed_no_grating_results`. Timing was **not** invented.

This is a true archive gap for stimulus timing, independent of the cohort-coverage bug that originally produced the “118 uncertain” label.

## Also documented: `sub-078` (SUBG13)

`sub-078/ses-01` (4 runs) maps to visit `SUBG13-Session1-2024NOV25`, which has **no** grating Results.
MATLAB Results exist only under `SUBG13_SESSION02_2025MAY22` (acquisition ~20250522).
Linking that MATLAB tree to the Nov 2024 BIDS session would require cross-date guessing and was **refused**.

## Deliverables

| File | Description |
|---|---|
| `RECOVERED_EVENTS_PHASE2.md` | This report |
| `phase2_events_generation.tsv` | Per attempted fMRI_number provenance (last pass) |
| `phase2_events_generation_summary.json` | Machine-readable counts (last pass) |
| `phase2_remaining_missing.tsv` | Per remaining BOLD run + reason |
| `code/bids_fixes/generate_recoverable_fmri_events_phase2.py` | Phase-2 pipeline |

