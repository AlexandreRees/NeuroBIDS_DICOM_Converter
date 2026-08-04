# Dataset pre-production audit

Generated: 2026-07-17T15:14:06.671725+00:00

Read-only audit. **No** modifications to `raw_original/`, MATLAB sources, or existing BIDS outputs.

## Dataset overview

- Subjects (from bids_plan): **84**
- Sessions: **135**
- Modalities: anat, dwi, extra, fmap, func
- Plan rows: **10026**

## Functional paradigm readiness

Metrics are separated by paradigm. Production recommendation uses **only** production-selected grating task-fMRI timing (`selected_for_conversion=True`).

### Task-fMRI / grating (events required — production-selected only)

One primary bold series per fMRI1–4 slot. Excludes duplicate DICOM series, phase (`_Pha`), rerun/redo, and failed/non-production labels.

- Total production runs: **536**
- READY: **358**
- RESOLVED_SOURCE_CONFLICT: **20**
- MISSING_TIMING: **158**
- UNRESOLVED_SOURCE_CONFLICT: **0**
- Coverage (ready + resolved): **70.5%**

Traceability: `task_fmri_timing_traceability.tsv`.

### Control (reported separately; not in grating production coverage)

- Total runs: **802**
- READY / MISSING / RESOLVED: 356 / 424 / 22
- Coverage: **47.1%**

### Movie (events optional)

- Total runs: **1070**
- Events READY / MISSING / RESOLVED: 0 / 0 / 0
- Stimulus availability (coverage_percentage): **70.4%** of movie runs have stimulus files for the subject/session

### Resting-state (events not applicable)

- Total runs: **270**
- Events status: not applicable (coverage=not_applicable)

Source priority for task-fMRI: scan_info → fMRI_N → runs_random → dated_sequence_of_stimuli.

## Associated data readiness

- Subject–session pairs with associated data rows: **140**
- Pairs with timing_count=0: **5**
- Pairs with stimulus_count>0: **135**

## Missing data

- T1w missing in **3** / 135 sessions
- REST missing in **3** / 135 sessions
- MOVIE1 missing in **1** / 135 sessions
- TASK1 missing in **1** / 135 sessions
- DWI missing in **4** / 135 sessions
- FIELDMAP missing in **0** / 135 sessions

## Potential issues before release

- Check 1 `every_subject_has_mapping_entry`: **PASS** (issues=0)
- Check 2 `valid_session_identifiers`: **PASS** (issues=0)
- Check 3 `no_duplicated_subject_session_series`: **PASS** (issues=0)
- Check 4 `no_missing_bids_plan_filenames`: **PASS** (issues=0)
- Check 5 `no_acquisition_without_modality`: **PASS** (issues=0)
- Check 6 `no_unresolved_matlab_timing_conflict`: **PASS** (issues=0)
- Expected-output DUPLICATE_SOURCE rows: **0**
- Expected-output MISSING_SOURCE rows: **0**
- Events-required MISSING_TIMING (task-fMRI/grating only): **158**
- Events-required UNRESOLVED_SOURCE_CONFLICT: **0**

## Recommendation

**REQUIRES REVIEW**

Recommendation criteria: logic-check failures, expected-output duplicates, and **missing/unresolved timing on production-selected grating runs only** (`selected_for_conversion=True`). Movie/rest/control gaps and excluded duplicate DICOM series do not block this grating readiness gate.

### Artefacts

- `acquisition_events_coverage.tsv`
- `functional_timing_summary.tsv`
- `task_fmri_timing_traceability.tsv`
- `selected_timing_source.tsv`
- `dataset_completeness.tsv`
- `associated_data_availability.tsv`
- `bids_expected_outputs_audit.tsv`
- `preproduction_checks.tsv`
- `figures/preproduction/Figure_dataset_completeness.png`
- `figures/preproduction/Figure_events_coverage.png`
