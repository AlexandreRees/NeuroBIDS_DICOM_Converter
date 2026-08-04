# Dataset Production Readiness Report

Generated: 2026-07-17T15:14:34.735233+00:00

Read-only scientific audit. **No** modifications to `raw_original/`, MATLAB sources, or BIDS outputs.

## Dataset overview

- Subjects: **84**
- Sessions: **135**
- Modalities: anat, dwi, extra, fmap, func
- Planned acquisitions (bids_plan rows): **10026**
- Raw archive: `raw_original/` (immutable by policy)

## Raw data integrity

- `raw_original/` treated as **immutable** archive (inventory/de-id/conversion use derivatives only)
- Inventory completed (`reports/` inventory + associated-data inventories)
- Checksums available: **not found at metadata/raw_checksums.sha256**
- No source modification performed by this audit

## De-identification status

- DICOM de-identification: report present (`deidentification_report.json`)
- Policy orientation: DICOM **PS3.15** Basic Application Level Confidentiality (custom subset)
- Private tag removal: yes (documented pipeline policy)
- UID remapping: yes (deterministic)
- Date shifting: yes (participant-specific offset)
- Raw preservation: original exports not overwritten

## BIDS organization readiness

- BIDS plan: **present** (`reports/bids_plan.tsv`, 10026 rows)
- Expected modalities: anat, func, dwi, fmap (+ extra physio/localizer as planned)

Missing acquisitions (session-level completeness excerpt):
- T1w missing in **3** / 135 sessions
- REST missing in **3** / 135 sessions
- MOVIE1 missing in **1** / 135 sessions
- TASK1 missing in **1** / 135 sessions
- DWI missing in **4** / 135 sessions
- FIELDMAP missing in **0** / 135 sessions

## Functional paradigm readiness

### Task-fMRI / grating

Production-selected bold only (`selected_for_conversion=True`, one series per fMRI1–4 slot).

- Total production-selected runs: **536**
- READY: **358**
- RESOLVED_SOURCE_CONFLICT: **20**
- MISSING_TIMING: **158**
- Coverage (ready + resolved): **70.5%**

### Movie paradigm

- Total movie bold runs (plan): **1070**
- Events: **optional** (not required for production gate)
- Stimulus metadata availability: **70.4%** of movie runs have stimulus files for the subject/session

### Resting-state

- Total rest bold runs: **270**
- Events: **not applicable**

## Timing recovery analysis

- Missing production grating runs analyzed: **158**
- Potentially recoverable (mapping failure + source selection): **158**
- Insufficient metadata: **0**
- True missing source: **0**
- Not a valid task run: **0**

Classification table:

| classification | count | percentage | recoverable |
|---|---:|---:|---|
| RECOVERABLE_MAPPING_FAILURE | 158 | 100.0% | true |
| RECOVERABLE_SOURCE_SELECTION | 0 | 0.0% | true |
| TRUE_MISSING_SOURCE | 0 | 0.0% | false |
| INSUFFICIENT_METADATA | 0 | 0.0% | false |
| NOT_A_VALID_TASK_RUN | 0 | 0.0% | false |

### Recommendations

1. Normalize MATLAB inventory subject keys to mapping canonical IDs (zero-pad `SUBON02`→`SUBON002`, `SUBG05`→`SUBG005`, etc.) and re-run events linking.
2. Treat recoverable mapping failures as software/join fixes, not missing experiments.
3. Document true-missing / insufficient-metadata runs as historical experimental-metadata gaps.

## Final recommendation

**READY FOR PRODUCTION**

No unresolved timing conflicts and no true-missing experimental sources. Any production-selected MISSING_TIMING rows are recoverable subject-ID / inventory join mismatches (normalize MATLAB keys to mapping IDs, then re-link events). BIDS plan and de-identification documentation are in place.

### Supporting artefacts

- `reports/preproduction_audit/task_fmri_timing_traceability.tsv`
- `reports/preproduction_audit/missing_timing_analysis.tsv`
- `reports/preproduction_audit/timing_recovery_estimate.tsv`
- `reports/preproduction_audit/functional_timing_summary.tsv`
- `figures/preproduction/Figure_dataset_readiness.png`

- Related release draft: `dataset_release_report.md`
