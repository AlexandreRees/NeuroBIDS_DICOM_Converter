# BIDS sidecar privacy audit (READ-ONLY)

**Generated (UTC):** 2026-07-22T19:07:42.084879+00:00
**BIDS dir:** `/lustre07/scratch/alexrees/bids`
**Dry-run:** True

## Counts

- JSON files scanned: **100**
- Invalid / non-object JSON: **0**
- Findings rows (non-SAFE forbidden/free-text): **34**
- Classification PHI_RISK: **0**
- Classification REVIEW_REQUIRED: **34**

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
| `SeriesDescription` | 36 | see `bids_sidecar_freetext_unique_dryrun.tsv` |
| `ProtocolName` | 22 | see `bids_sidecar_freetext_unique_dryrun.tsv` |
| `SequenceName` | 8 | see `bids_sidecar_freetext_unique_dryrun.tsv` |
| `PulseSequenceDetails` | 7 | see `bids_sidecar_freetext_unique_dryrun.tsv` |

## Example paths

### `ProtocolName`
- `sub-001/ses-01/fmap/sub-001_ses-01_dir-AP_run-01_epi.json :: SpinEchoFieldMap_AP`
- `sub-001/ses-01/fmap/sub-001_ses-01_dir-AP_run-02_part-phase_epi.json :: SpinEchoFieldMap_AP`
- `sub-001/ses-01/fmap/sub-001_ses-01_dir-AP_run-03_epi.json :: SpinEchoFieldMap_AP`
- `sub-001/ses-01/fmap/sub-001_ses-01_dir-AP_run-04_part-phase_epi.json :: SpinEchoFieldMap_AP`
- `sub-001/ses-01/fmap/sub-001_ses-01_dir-PA_run-01_epi.json :: SpinEchoFieldMap_PA`
### `PulseSequenceDetails`
- `sub-001/ses-01/anat/sub-001_ses-01_run-01_FLAIR.json :: %SiemensSeq%\tse_vfl`
- `sub-001/ses-02/anat/sub-001_ses-02_run-01_FLAIR.json :: %SiemensSeq%\tse_vfl`
### `SeriesDescription`
- `sub-001/ses-01/fmap/sub-001_ses-01_dir-AP_run-01_epi.json :: SpinEchoFieldMap_AP`
- `sub-001/ses-01/fmap/sub-001_ses-01_dir-AP_run-02_part-phase_epi.json :: SpinEchoFieldMap_AP`
- `sub-001/ses-01/fmap/sub-001_ses-01_dir-AP_run-03_epi.json :: SpinEchoFieldMap_AP`
- `sub-001/ses-01/fmap/sub-001_ses-01_dir-AP_run-04_part-phase_epi.json :: SpinEchoFieldMap_AP`
- `sub-001/ses-01/fmap/sub-001_ses-01_dir-PA_run-01_epi.json :: SpinEchoFieldMap_PA`

## Verdict

**PASS_WITH_REVIEW**

Interpretation:
- `PASS`: no PHI_RISK keys and no invalid JSON.
- `PASS_WITH_REVIEW`: free-text or PatientSex flagged for manual review.
- `FAIL`: residual direct identifiers or invalid JSON.

Prior cleaning (`clean_bids_metadata.py`) removed `InstitutionalDepartmentName` from BIDS sidecars; this audit confirms current state.

TSV findings: `bids_sidecar_phi_audit_dryrun.tsv`
Unique free-text: `bids_sidecar_freetext_unique_dryrun.tsv`

