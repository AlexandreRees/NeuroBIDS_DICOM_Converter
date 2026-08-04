# DICOM residual demographic identifier audit

**Generated (UTC):** 2026-07-22T16:51:44.302970+00:00
**DICOM root scanned:** `/lustre07/scratch/alexrees/raw_original`
**Source class:** Only source DICOMs were available (`~/scratch/deid_dicom` missing or empty). Burned-in and demographic audits therefore reflect **source** DICOM under `/lustre07/scratch/alexrees/raw_original`, not a release mirror.
**Files with demographic scan rows:** 0

Read-only audit. Values are **not** printed; only presence/absence and redacted placeholders.

## Important

Only source DICOMs were available (`~/scratch/deid_dicom` missing or empty). Burned-in and demographic audits therefore reflect **source** DICOM under `/lustre07/scratch/alexrees/raw_original`, not a release mirror.

## Tag presence frequencies

| Tag | Non-empty present | Absent/empty |
| --- | ---: | ---: |
| `PatientAge` | 0 | 0 |
| `PatientBirthDate` | 0 | 0 |
| `PatientSex` | 0 | 0 |
| `PatientName` | 0 | 0 |
| `PatientID` | 0 | 0 |
| `OtherPatientIDs` | 0 | 0 |
| `OtherPatientNames` | 0 | 0 |

## Recommendation — PatientAge

**No non-empty `PatientAge` observed in the scanned set.** If public DICOM derivatives are later exported, keep `PatientAge` on the removal list as a preventive control.

## Direct identifiers

No non-empty PatientName / PatientID / PatientBirthDate values were observed in the scanned set.

Detailed TSV: `dicom_demographic_audit.tsv`
