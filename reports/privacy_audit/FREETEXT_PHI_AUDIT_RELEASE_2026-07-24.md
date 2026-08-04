# Free-text & PHI metadata audit — release package

**Generated (UTC):** 2026-07-24T16:25:19.326248+00:00
**Tree audited:** `/home/alexrees/scratch/release_dataset`
**JSON sidecars:** 7960 (parse errors: 0)

## Verdict

**PASS — no residual direct-identifier fields in release JSON sidecars.**

Free-text (`SeriesDescription` / `ProtocolName` / etc.): values are **protocol / sequence labels**.
Prior heuristic flags on `Sag Flair 3D-0.8*` are **false positives** (radiology term “FLAIR”, not a person name).
Operator notes like `*_redo*`, `*_gogle_moved*` are technical redo labels, not participant identifiers.

## Forbidden / sensitive keys

| Field | Hits |
| --- | ---: |
| `PatientName` | 0 |
| `PatientID` | 0 |
| `PatientBirthDate` | 0 |
| `PatientAge` | 0 |
| `PatientSex` | 0 |
| `InstitutionName` | 0 |
| `InstitutionalDepartmentName` | 0 |
| `DeviceSerialNumber` | 0 |
| `StationName` | 0 |
| `OperatorsName` | 0 |
| `PhysicianName` | 0 |
| `ReferringPhysicianName` | 0 |
| `PerformingPhysicianName` | 0 |
| `AcquisitionDate` | 0 |
| `SeriesDate` | 0 |
| `StudyDate` | 0 |
| `AccessionNumber` | 0 |
| `ImageComments` | 0 |
| `PatientComments` | 0 |
| `StudyComments` | 0 |

## Free-text unique-value counts

| Field | Unique values |
| --- | ---: |
| `ProtocolName` | 29 |
| `PulseSequenceDetails` | 7 |
| `ScanningSequence` | 5 |
| `SequenceName` | 8 |
| `SeriesDescription` | 65 |
| `SeriesNumber` | 84 |

## Manual review of previously flagged strings

| Value | Field(s) | Assessment |
| --- | --- | --- |
| `Sag Flair 3D-0.8` (+ `_ND`, `_usethisone`) | SeriesDescription / ProtocolName | **SAFE** — FLAIR protocol name; heuristic false positive |
| `Movie4_AP_redo_cuz_gogle_moved` | SeriesDescription / ProtocolName | **SAFE** — operator redo note (typo “gogle”); no participant ID |
| `*_REDO` / `*_Rerun` / `*_redo` | SeriesDescription / ProtocolName | **SAFE** — acquisition redo labels |
| `WMn_MPRAGE_sagittal` | SeriesDescription / ProtocolName | **SAFE** — white-matter-nulled MPRAGE |

Automated REVIEW classifications on release free-text uniques: **0** (after radiology-aware filter; see TSV).

## Other string-valued sidecar keys (inventory)

Top non-forbidden / non-core-freetext string keys (presence counts):

- `BodyPartExamined`: 7956
- `ConversionSoftware`: 7956
- `ConversionSoftwareVersion`: 7956
- `InPlanePhaseEncodingDirectionDICOM`: 7956
- `MRAcquisitionType`: 7956
- `Manufacturer`: 7956
- `ManufacturersModelName`: 7956
- `Modality`: 7956
- `PatientPosition`: 7956
- `SoftwareVersions`: 7956
- `CoilCombinationMethod`: 7763
- `ConsistencyInfo`: 7763
- `MatrixCoilMode`: 7763
- `ReceiveCoilActiveElements`: 7763
- `ReceiveCoilName`: 7763
- `SequenceVariant`: 7763
- `ScanOptions`: 7535
- `PhaseEncodingDirection`: 7455
- `WipMemBlock`: 6961
- `TaskName`: 5884
- `DiffusionScheme`: 350
- `CoilString`: 193
- `PulseSequenceName`: 193
- `PhaseEncodingAxis`: 171
- `ParallelAcquisitionTechnique`: 33

## Comparison: research `bids/` vs `release_dataset/`

| Metric | bids | release |
| --- | ---: | ---: |
| JSON | 8619 | 7960 |
| Forbidden-field hits (sum) | 659 | 0 |
| Free-text REVIEW uniques | 0 | 0 |

## Recommendation for OpenNeuro

1. **Keep** SeriesDescription / ProtocolName as technical protocol labels (option B4-A).
2. No scrub required for PHI; optional style cleanup of redo notes is cosmetic only.
3. Confirm Institutional* / Patient* / date keys remain absent after any future sidecar edits.
4. Age: keep **out** of public `participants.tsv`; do not publish individual ages; qualify/remove aggregate age in manuscript.

Full free-text table: `freetext_phi_audit_release_2026-07-24.tsv`