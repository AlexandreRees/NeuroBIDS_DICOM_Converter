# BIDS validation after priority fixes

- Date (UTC): `2026-07-21T19:30:54.849659+00:00`
- Validator: bids-validator 1.15.0
- Dataset valid (0 errors): **YES**
- Error file hits: **0**
- Warning file hits: **17363**
- Subjects: 84; sessions: ['01', '02']; files: 16133

## Fixes applied

1. Rebuilt `participants.tsv` (**84/84**) from `metadata/participant_mapping.csv`.
2. Moved Siemens TRACEW derived DWI out of raw BIDS → `derivatives/bids_priority_fixes/siemens_tracew/`.
3. Completed fmap `PhaseEncodingDirection` + `TotalReadoutTime`; renamed `dir-unknown` using `SeriesDescription`.
4. Quarantined invalid `*_bold_pha.*` → `derivatives/bids_priority_fixes/invalid_filenames/`.
5. Pruned non-existent `IntendedFor` targets when present.

## Remaining errors

_None._

## Remaining warnings

| Code | files | ses-01 | ses-02 | Reason |
|---|---:|---:|---:|---|
| `INCONSISTENT_SUBJECTS` | 14180 | 7094 | 7086 | Not all subjects contain the same files. Each subject should contain the same number of files with the same naming unless some files are known to be missing. |
| `EVENTS_TSV_MISSING` | 2739 | 1818 | 921 | Task scans should have a corresponding events.tsv file. If this is a resting state scan you can ignore this warning or rename the task to include the word "rest". |
| `INCONSISTENT_PARAMETERS` | 299 | 193 | 106 | Not all subjects/sessions/runs have the same scanning parameters. |
| `SLICE_TIMING_NOT_DEFINED` | 100 | 80 | 20 | You should define 'SliceTiming' for this file. If you don't provide this information slice time correction will not be possible. 'Slice Timing' is the time at which each slice was acquired within each |
| `MISSING_SESSION` | 44 | 1 | 43 | Not all subjects contain the same sessions. |
| `TOO_FEW_AUTHORS` | 1 | 0 | 0 | The Authors field of dataset_description.json should contain an array of fields - with one author per field. This was triggered based on the presence of only one author field. Please ignore if all con |

## Scientific Data residual risk

Official validator now passes with **0 errors**. Remaining warnings should be addressed or explicitly justified in the data descriptor:

- **EVENTS_TSV_MISSING**: many task BOLD runs lack events.tsv
- **INCONSISTENT_SUBJECTS / MISSING_SESSION / INCONSISTENT_PARAMETERS**: expected longitudinal incompleteness, but must be documented
- **SLICE_TIMING_NOT_DEFINED**: some bold JSON lack SliceTiming
- **TOO_FEW_AUTHORS**: dataset_description Authors needs real author list

## Outputs

- `/home/alexrees/scratch/reports/bids_validation_scientific_data/VALIDATION_AFTER_PRIORITY_FIXES.md`
- `/home/alexrees/scratch/reports/bids_validation_scientific_data/bids_validator_report_after_fixes.json`
- `/home/alexrees/scratch/reports/bids_validation_scientific_data/bids_validator_issues_after_fixes.tsv`
- `/home/alexrees/scratch/reports/bids_validation_scientific_data/priority_fixes_log.tsv`
