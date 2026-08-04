# BIDS validation after events + SliceTiming + longitudinal docs

- Date (UTC): `2026-07-21T20:34:31.618912+00:00`
- Validator: bids-validator 1.15.0
- Dataset valid (0 errors): **YES**
- Error file hits: **0**
- Warning file hits: **17486**
- Subjects: 84; sessions: ['01', '02']; files: 16194

## Fixes in this pass

1. Joined **51** verified `task-fmri` `*_events.tsv` from `release_candidate_level1/` (BOLD destination verified; no invented onsets).
2. Recovered **SliceTiming** for **104/104** XA30 `*_bold.json` from Enhanced DICOM `FrameAcquisitionDateTime` + `InStackPositionNumber`.
3. Documented incomplete longitudinal coverage (`bids/README`, `LONGITUDINAL_COVERAGE.md`, `longitudinal_session_coverage.tsv`).
4. Filled missing fmap `PhaseEncodingDirection`/`TotalReadoutTime` on `sub-054/ses-02/..._dir-AP_run-02_epi` from same-series sibling.

## Remaining errors

_None._

## Remaining warnings

| Code | files | Reason |
|---|---:|---|
| `EVENTS_TSV_MISSING` | 2691 | Task scans should have a corresponding events.tsv file. If this is a resting state scan you can ignore this warning or rename the task to include the word "rest". |
| `INCONSISTENT_SUBJECTS` | 14451 | Not all subjects contain the same files. Each subject should contain the same number of files with the same naming unless some files are known to be missing. |
| `INCONSISTENT_PARAMETERS` | 299 | Not all subjects/sessions/runs have the same scanning parameters. |
| `MISSING_SESSION` | 44 | Not all subjects contain the same sessions. |
| `TOO_FEW_AUTHORS` | 1 | The Authors field of dataset_description.json should contain an array of fields - with one author per field. This was triggered based on the presence of only one author field. Please ignore if all contributors are alread |

## Notes

- `SLICE_TIMING_NOT_DEFINED`: cleared (was 100).
- `EVENTS_TSV_MISSING`: reduced by the 51 joined files; remaining are intentional withholdings (movie/control + unverified fmri mappings).
- `MISSING_SESSION` / `INCONSISTENT_SUBJECTS`: expected; documented longitudinal incompleteness.

## Outputs

- `bids_validator_report_after_events_st.json`
- `events_slicetiming_longitudinal_log.tsv`
- `LONGITUDINAL_COVERAGE.md`
