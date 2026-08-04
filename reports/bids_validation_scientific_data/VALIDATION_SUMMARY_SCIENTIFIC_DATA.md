# BIDS validation for Scientific Data readiness

- Date (UTC): `2026-07-21T19:14:30.586460+00:00`
- Validator: official `bids-validator` **1.15.0** via `npx`
- Dataset: `/home/alexrees/scratch/bids`
- Scope: **all subjects**, sessions **ses-01** and **ses-02**
- Command exit code: **1** (failed — errors present)

## Scientific Data verdict

**NOT READY for Scientific Data publication as currently structured.**

The official BIDS validator reports schema/content errors on both sessions. Scientific Data expects a BIDS-compliant release; these errors must be resolved (or explicitly justified and documented) before submission.

## Dataset coverage

- Subject directories: **84**
- Subjects listed in `participants.tsv`: **29**
- Missing from `participants.tsv`: **55**
- ses-01 present: **83**
- ses-02 present: **41**
- Both sessions: **40**
- Validator summary subjects: **84**
- Validator summary sessions: **['01', '02']**
- Total files scanned: **16575**
- Tasks: **control, fmri, movie, rest**

## Issue counts

| Severity | Total file hits | ses-01 | ses-02 | dataset-level |
|---|---:|---:|---:|---:|
| Errors | 195 | 133 | 62 | 0 |
| Warnings | 18261 | 9459 | 8801 | 1 |

## Errors (must fix for Scientific Data)

| Code | ses-01 | ses-02 | other | Meaning |
|---|---:|---:|---:|---|
| `INTENDED_FOR` | 0 | 8 | 0 | 'IntendedFor' field needs to point to an existing file. |
| `NOT_INCLUDED` | 2 | 0 | 0 | Files with such naming scheme are not part of BIDS specification. This error is most commonly caused by typos in file names that make them not BIDS compatible. Please consult the specification and make sure your files are named correctly. If this is not a file naming issue (for example when including files not yet covered by the BIDS specification) you should include a ".bidsignore" file in your dataset (see https://github.com/bids-standard/bids-validator#bidsignore for details). Please note that derived (processed) data should be placed in /derivatives folder and source data (such as DICOMS or behavioural logs in proprietary formats) should be placed in the /sourcedata folder. |
| `PHASE_ENCODING_DIRECTION_MUST_DEFINE` | 28 | 7 | 0 | You have to define 'PhaseEncodingDirection' for this file. |
| `TOTAL_READOUT_TIME_MUST_DEFINE` | 28 | 7 | 0 | You have to define 'TotalReadoutTime' for this file. |
| `VOLUME_COUNT_MISMATCH` | 75 | 40 | 0 | The number of volumes in this scan does not match the number of volumes in the corresponding .bvec and .bval files. |

### Error interpretation

1. **VOLUME_COUNT_MISMATCH** (DWI): NIfTI volume count ≠ `.bval`/`.bvec` entries — affects both sessions heavily.
2. **TOTAL_READOUT_TIME_MUST_DEFINE** / **PHASE_ENCODING_DIRECTION_MUST_DEFINE** (fmap): required sidecar fields missing for fieldmaps.
3. **INTENDED_FOR** (fmap, mainly ses-02): points to non-existent files.
4. **NOT_INCLUDED** (ses-01): invalid filenames `*_bold_pha.*` (should likely be `part-phase`).

## Warnings (should address / document)

| Code | ses-01 | ses-02 | other | Meaning |
|---|---:|---:|---:|---|
| `EVENTS_TSV_MISSING` | 1818 | 915 | 0 | Task scans should have a corresponding events.tsv file. If this is a resting state scan you can ignore this warning or rename the task to include the word "rest". |
| `INCONSISTENT_PARAMETERS` | 268 | 146 | 0 | Not all subjects/sessions/runs have the same scanning parameters. |
| `INCONSISTENT_SUBJECTS` | 7292 | 7684 | 0 | Not all subjects contain the same files. Each subject should contain the same number of files with the same naming unless some files are known to be missing. |
| `MISSING_SESSION` | 1 | 43 | 0 | Not all subjects contain the same sessions. |
| `SLICE_TIMING_NOT_DEFINED` | 80 | 13 | 0 | You should define 'SliceTiming' for this file. If you don't provide this information slice time correction will not be possible. 'Slice Timing' is the time at which each slice was  |
| `TOO_FEW_AUTHORS` | 0 | 0 | 1 | The Authors field of dataset_description.json should contain an array of fields - with one author per field. This was triggered based on the presence of only one author field. Plea |

## Publication blockers vs acceptable caveats

| Item | Status for Scientific Data |
|---|---|
| Official validator passes with 0 errors | **FAIL** |
| Both ses-01 and ses-02 present in validated tree | **YES** (validated together) |
| Complete `participants.tsv` for all subjects | **FAIL** (29/84 listed) |
| DWI bval/bvec consistency | **FAIL** |
| Fieldmap required metadata | **FAIL** |
| Functional events.tsv completeness | WARNING (many missing; rest tasks OK to ignore) |
| Cross-subject file consistency | WARNING (expected if incomplete longitudinal coverage) |

## Outputs

- Full JSON: `/home/alexrees/scratch/reports/bids_validation_scientific_data/bids_validator_report.json`
- Flat issue table: `/home/alexrees/scratch/reports/bids_validation_scientific_data/bids_validator_issues_flat.tsv`
- This summary: `/home/alexrees/scratch/reports/bids_validation_scientific_data/VALIDATION_SUMMARY_SCIENTIFIC_DATA.md`

## Recommended next fixes (priority order)

1. Rebuild/complete `participants.tsv` (+ `participants.json`) for all 84 subjects.
2. Repair DWI `VOLUME_COUNT_MISMATCH` (re-export or truncate/align bval/bvec).
3. Add `PhaseEncodingDirection` and `TotalReadoutTime` to fmap JSON sidecars.
4. Fix broken `IntendedFor` paths (especially ses-02).
5. Rename invalid `*_bold_pha.*` files to BIDS `part-phase` convention.
6. Add or justify missing `events.tsv` / `SliceTiming` where required for task fMRI.
