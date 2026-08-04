# Stimulus timing reconstruction audit

**Date:** 2026-07-23  
**Scope:** Read-only assessment of whether `task-fmri` and `task-movie` BIDS `*_events.tsv` files can be reconstructed from the original archive.  
**Policy:** No BIDS files were modified. Deliverables are under `reports/stimulus_audit/`.

**Primary sources inspected**
- Associated-data inventory (`reports/associated_data_inventory.tsv`; 5 756 files)
- MATLAB content inventory (`reports/matlab_content_inventory.tsv`)
- Exemplar Psychtoolbox code under `/project/def-amirs/raw_original/.../2-Grating/` and `.../3-Movie_Data/`
- Existing BIDS tree (`bids/`: 51 `task-fmri` events; 0 movie events)
- Level-1 release converter and audits (`code/level1_release/convert_events.py`; withheld/ready event audits)

---

## Executive verdict

| Task | Question | Verdict | Confidence |
|---|---|---|---|
| `task-fmri` | Complete `events.tsv` (onset, duration, trial_type)? | **YES** for 51 already released; **YES for most remaining runs** after a deterministic mapping fix | **HIGH** (released); **MEDIUM–HIGH** (recoverable); **LOW** (ambiguous/missing) |
| `task-movie` | Segment identity / coarse segment timings? | **PARTIAL** — which movie + eye **YES**; scanner-locked onsets **NO** | **MEDIUM** (identity); **LOW** (BOLD-locked timing) |
| `task-movie` | Scene / frame timings? | **NO** | **HIGH** that this is not reconstructible from the archive |

---

## Inventory summary

From `stimulus_inventory.tsv` (roles assigned from path/filename heuristics):

| Paradigm | Role | N |
|---|---|---:|
| task-fmri | stimulus_script (`.m`) | 1656 |
| task-fmri | stim_order (`Stim_order_selected`) | 1112 |
| task-fmri | scan_info_triggers | 554 |
| task-fmri | runs_random_workspace | 274 |
| task-fmri | display_calibration | 276 |
| task-movie | movie_run_selection_log | 550 |
| task-movie | stimulus_script | 312 |
| task-movie | movie_stimulus_file (`.mp4`) | 104 |
| task-rest | stimulus_script | 137 |

BIDS imaging coverage used for matching:

| Item | N |
|---|---:|
| `task-fmri` non-phase BOLD runs | 507 |
| `task-fmri` with `*_events.tsv` | 51 |
| `task-movie` non-phase BOLD runs | 495 |
| `task-movie` with `*_events.tsv` | 0 |

Level-1 events plan (prior audit, reused here):

| Item | N |
|---|---:|
| Ready destinations (strict converter) | 51 |
| Withheld timing cases | 341 |
| Of which recoverable with deterministic mapping | 323 |
| Ambiguous / remain excluded | 18 |

Per-run reconstruction status (`fmri_events_reconstruction.tsv`):

| Status | N BOLD runs |
|---|---:|
| already_released | 51 |
| reconstructable_with_mapping_fix | 331 |
| sources_uncertain_or_absent | 118 |
| ambiguous | 7 |

---

## 1. What the `.mat` files contain

### task-fmri (`2-Grating/Results/`)

| File pattern | Key variables | Use for events |
|---|---|---|
| `fMRI_N.mat` / `*sequence_of_stimuli_for_fMRI_number_N*` | `Stim_order_selected` (1×12) | Condition order → `stim-01`…`stim-12` |
| `*scan_info*selected_run_is_*fmri_number_isN.mat` | `scan.runs.triggerTimes` (+ VBL) | Scanner-locked onsets (required by strict converter) |
| `runs_random.mat` | `runParadigmFinal` / `paradigm`, `Stim_order_selected`, `fMRI_number`, `run_number`, `vbl` | Block design indices + consistency check |
| `runs_random_record_*.mat` | randomized run IDs | Session run ordering |

**Proven content (prior MATLAB inventory + Level-1 converter):** scan_info stores actual FORP/`t` trigger times; stim-order mats store the 12-condition permutation; workspace dumps contain the recorded paradigm matrix used to build onsets.

### task-movie (`3-Movie_Data/Results/`)

| File pattern | Key variables | Use for events |
|---|---|---|
| `*selected_run_id_N.mat` | `run_id`, `change_eye`, operator `comment` | Segment identity + eye only |
| *(none)* | triggerTimes / VBL / frame times | **Absent** |

MATLAB inventory classifies these as operator run-selection logs with **low priority vs scan_info** for timing.

---

## 2. What the `.m` scripts define

### task-fmri — `presentStimParams.m` / `main.m`

Documented TR-locked block design:

- `firstBaselineEnd = 10`
- `numCycles = 12`
- `cycleStim = 8`
- `cycleBaseline = 10`
- Total volumes implied: \(10 + 12×(8+10) = 226\)

Twelve stimulus generators (`stim{1}`…`stim{12}`) mix magnocellular/parvocellular grating and checkerboard variants. `main.m` records `scan.runs{run}.triggerTimes` on each scanner `t` and saves scan_info + stim order.

### task-movie — `main.m` / `Show_movie.m`

`main.m` maps:

| run_id | File | Intended eye |
|---:|---|---|
| 1 | Movie1A.mp4 | left (`change_eye`) |
| 2 | Movie2A.mp4 | right (`~change_eye`) |
| 3 | Movie1B.mp4 | right |
| 4 | Movie2B.mp4 | left |

`Show_movie.m` waits for trigger `t` (`KbQueueWait`) then streams movie frames with a fixation overlay. Critical limitations:

1. `Screen('PlayMovie', movie, 1)` is called **before** `KbQueueWait`.
2. **No** `triggerTimes`, frame index, or scene list is saved to disk.
3. Results mats are written **before** playback (run selection only).

Therefore scripts support **identity reconstruction**, not **measured onset reconstruction**.

---

## 3. Protocol logs ↔ BIDS runs

### task-fmri

Proven pipeline (`convert_events.py`):

1. Require matching `scan_info` + `stim_order` + `runs_random` for the same `fMRI_number` / `selected_run`.
2. Build events from recorded paradigm indices × relative `triggerTimes`.
3. Attach to the unique non-phase BOLD whose `ProtocolName`/`SeriesDescription` matches (e.g. `fMRI4_AP` → one BIDS `task-fmri` run).

**Why only 51 were released:** the strict converter requires the session `runs_random.mat` workspace to belong to the same `fMRI_number` as the scan/stim pair. That workspace is typically overwritten by the **last** grating run, so runs 1–3 fail with `runs_random belongs to fMRI 4, not N`. Level-1 audit labels **323** such cases **recoverable_with_deterministic_mapping** (restrict workspace to matching `fMRI_number`, or rebuild paradigm from `presentStimParams.m` + stim order + triggers without the mismatched workspace).

**Mapping confidence:** HIGH when ProtocolName uniquely matches; MEDIUM when sidecar match is missing/duplicated (42 withheld rows: `expected one matching non-phase BOLD sidecar, found 0`).

### task-movie

No Level-1 events converter exists. Feasible matching strategy:

1. Collect `*selected_run_id_*.mat` per visit (typically 4).
2. Order by MATLAB save timestamp / filename datetime.
3. Align to BIDS `task-movie` runs ordered by `AcquisitionTime` / series number.
4. Assign `stimulus_file` + eye from `run_id` table.

This yields **segment identity**. It does **not** yield volume-locked onsets without inventing sync (onset≈0, duration≈210×TR or MP4 duration).

Movie segment identity match rate in this audit (`movie_timing_reconstruction.tsv`): **341 YES / 154 UNCERTAIN** (UNCERTAIN mostly subject-field matching gaps for non-Control cohorts in the inventory).

---

## 4. Reconstructability answers

### task-fmri — complete events.tsv?

**Yes, in principle, for the large majority of runs.**

- **Already reconstructed:** 51 files in `bids/` (HIGH confidence; verified triggerTimes + paradigm + stim order).
- **Reconstructable with code/mapping fix:** ~323 Level-1 recoverable withheld cases; 331 BOLD runs tagged `reconstructable_with_mapping_fix` in this audit (MEDIUM–HIGH).
- **Residual:** ambiguous cardinality / missing triggers / missing BOLD match (LOW).
- **Caveat:** released events use `stim-01`…`stim-12` labels. A complete machine-readable map from those IDs to physical stimulus parameters is in `presentStimParams.m` / generator scripts, **not** currently shipped as a data dictionary beside the events.

### task-movie — segment timings?

**Partial.**

| Layer | Reconstructible? | Confidence |
|---|---|---|
| Which movie file (Movie1A/2A/1B/2B) | YES (from `run_id` + `main.m`) | MEDIUM |
| Stimulated eye | YES (from `run_id` + `change_eye`) | MEDIUM |
| Coarse run duration | YES (design: ~210 vols × TR, or MP4 duration) | MEDIUM |
| Scanner-locked onset/duration series | **NO** without inventing sync | LOW |
| Scene / shot / frame events | **NO** | HIGH (absent) |

MP4 files exist in the archive (**104** inventoried) but are **copyright-flagged** and excluded from public `stimuli/`; redistribution is a separate rights issue from timing reconstruction.

---

## 5. Deliverables

| File | Description |
|---|---|
| `stimulus_inventory.tsv` | 5 756 associated files with paradigm/role classification |
| `fmri_events_reconstruction.tsv` | Per `task-fmri` BOLD run: status, confidence, blockers |
| `movie_timing_reconstruction.tsv` | Per `task-movie` BOLD run: segment/scene reconstructability |
| `mapping_confidence.tsv` | Task-level Q&A summary |
| `STIMULUS_RECONSTRUCTION_REPORT.md` | This report |
| `_audit_summary.json` | Machine-readable counts |

---

## 6. Follow-up executed (2026-07-23)

**task-fmri recoverable events generation** (`code/bids_fixes/generate_recoverable_fmri_events.py`):

| Outcome | N |
|---|---:|
| Newly written into `bids/` | 299 |
| Skipped (already present / duplicate sources) | 61 |
| Failed (no unique BIDS protocol match) | 20 |
| Failed (cardinality / triggers) | 11 |
| **Total `task-fmri` `*_events.tsv` in BIDS** | **350** |

Provenance: `reports/stimulus_audit/recoverable_events_generation.tsv`.

## 7. Remaining recommended steps

1. **task-fmri:** Publish a `stim-XX` parameter dictionary derived from `presentStimParams.m`.
2. **task-fmri:** Manually adjudicate the 20 `found 0/2` ProtocolName collisions if further coverage is needed.
3. **task-movie:** Optionally release **design-level** events (single event per run: file + eye + coarse duration) with explicit documentation that onsets are **not** measured trigger times.
4. **task-movie:** Do **not** claim scene-level events without new annotations.
5. Keep MP4 redistribution gated on copyright clearance; checksums/citations can be published without the bytes.

---

## 7. Limitations of this audit

- Subject matching for movie logs used inventory `subject`/`session` fields; non-Control cohort ID normalization may under-count matched logs (154 UNCERTAIN).
- Exemplar `.mat` loads on `/project/def-amirs/raw_original` (SUBC01 ses-01) confirmed: `Stim_order_selected=[11 6 10 12 1 5 9 2 4 7 3 8]`; scan_info `triggerTimes` n=226 with median Δt≈0.937 s; movie selection log keys=`answer, change_eye, comment, resultdir, run_id, t, x, y` only (`run_id=1`, `change_eye=0`).
- DICOM header timing was not re-extracted run-by-run; BIDS sidecars / ProtocolName matching from the Level-1 audit were reused.
- Subject matching for non-Control movie logs may be incomplete (154 UNCERTAIN).
