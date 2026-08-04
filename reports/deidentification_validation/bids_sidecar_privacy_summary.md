# BIDS sidecar privacy audit (READ-ONLY)

**Generated (UTC):** 2026-07-22T19:35:50.011618+00:00
**BIDS dir:** `/lustre07/scratch/alexrees/bids`
**Dry-run:** False

## Counts

- JSON files scanned: **7958**
- Invalid / non-object JSON: **0**
- Findings rows (non-SAFE forbidden/free-text): **0**
- Classification PHI_RISK: **0**
- Classification REVIEW_REQUIRED: **0**

## Forbidden / sensitive field hits

| Field | Hits | Default classification |
| --- | ---: | --- |
| `PatientName` | 0 | PHI_RISK |
| `PatientID` | 0 | PHI_RISK |
| `PatientBirthDate` | 0 | PHI_RISK |
| `PatientAge` | 0 | PHI_RISK |
| `PatientSex` | 0 | REVIEW_REQUIRED |
| `InstitutionName` | 0 | PHI_RISK |
| `InstitutionalDepartmentName` | 0 | PHI_RISK |
| `DeviceSerialNumber` | 0 | PHI_RISK |
| `StationName` | 0 | PHI_RISK |
| `OperatorsName` | 0 | PHI_RISK |
| `PhysicianName` | 0 | PHI_RISK |
| `ReferringPhysicianName` | 0 | PHI_RISK |
| `PerformingPhysicianName` | 0 | PHI_RISK |
| `AcquisitionDate` | 0 | PHI_RISK |
| `AcquisitionTime` | 0 | REVIEW_REQUIRED |
| `SeriesDate` | 0 | PHI_RISK |
| `StudyDate` | 0 | PHI_RISK |

## Free-text fields

| Field | Unique values | Notes |
| --- | ---: | --- |
| `SeriesDescription` | 65 | see `bids_sidecar_freetext_unique.tsv` |
| `ProtocolName` | 29 | see `bids_sidecar_freetext_unique.tsv` |
| `SequenceName` | 8 | see `bids_sidecar_freetext_unique.tsv` |
| `PulseSequenceDetails` | 7 | see `bids_sidecar_freetext_unique.tsv` |

## Verdict

**PASS**

Interpretation:
- `PASS`: no PHI_RISK keys and no invalid JSON.
- `PASS_WITH_REVIEW`: free-text or PatientSex flagged for manual review.
- `FAIL`: residual direct identifiers or invalid JSON.

Prior cleaning (`clean_bids_metadata.py`) removed `InstitutionalDepartmentName` from BIDS sidecars; this audit confirms current state.

TSV findings: `bids_sidecar_phi_audit.tsv`
Unique free-text: `bids_sidecar_freetext_unique.tsv`

