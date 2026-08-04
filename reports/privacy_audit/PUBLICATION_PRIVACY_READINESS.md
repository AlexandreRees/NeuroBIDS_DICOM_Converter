# Publication privacy readiness

**Generated (UTC):** 2026-07-22T16:58:35.505052+00:00
**Mode:** READ-ONLY (no modifications to `bids/` or `raw_original/`)
**DICOM root audited:** `/lustre07/scratch/alexrees/raw_original`
**De-identified DICOM available:** no

## 1. Executive summary

This pre-publication privacy audit evaluated (i) burned-in annotations and overlays in DICOM headers, (ii) residual demographic DICOM attributes, and (iii) free-text BIDS sidecar fields. The audit does not replace institutional ethics review or a full DICOM PS3.15 Annex E conformance claim.

| Question | Answer |
| --- | --- |
| Evidence of burned-in PHI? | No affirmative BurnedInAnnotation=YES, overlay, or graphic-annotation evidence in the inspected set; tag absence remains inconclusive and visual spot-checks are still advised. |
| Should PatientAge be removed? | De-identified DICOM mirror (`deid_dicom/`) was not available; demographics were audited on source DICOM. For any public DICOM objects, PatientAge should be removed. BIDS sidecars already omit PatientAge on the conversion scrub path. |
| Are SeriesDescription/ProtocolName safe? | SeriesDescription=REVIEW_REQUIRED, ProtocolName=REVIEW_REQUIRED. Manual review of flagged values is required before asserting safety. |
| Remaining privacy blockers besides defacing? | No `deid_dicom/` mirror found — confirm the public package contains only BIDS (+ defaced anatomicals) and not source DICOM. Structural defacing coverage remains a separate OpenNeuro/Scientific Data sharing requirement (not re-audited here). Free-text SeriesDescription/ProtocolName flags require manual clearance. |

## 2. Burned-in annotation risk

- Candidates discovered: **83154**
- Files inspected: **1133**
- Sampling: one representative instance per series directory (1133 series dirs from 83154 files)
- BurnedInAnnotation YES / NO / absent: **0** / **0** / **1133**
- Overlays: **0**; graphic annotations: **0**

See `burned_in_annotation_summary.md` and `burned_in_annotation_audit.tsv`.

## 3. Remaining DICOM demographic identifiers

- Source class: **Only source DICOMs were available (`~/scratch/deid_dicom` missing or empty). Burned-in and demographic audits therefore reflect **source** DICOM under `/lustre07/scratch/alexrees/raw_original`, not a release mirror.**
- Files scored: **0**

| Tag | Non-empty count |
| --- | ---: |
| `PatientAge` | 0 |
| `PatientBirthDate` | 0 |
| `PatientSex` | 0 |
| `PatientName` | 0 |
| `PatientID` | 0 |
| `OtherPatientIDs` | 0 |
| `OtherPatientNames` | 0 |

See `dicom_demographic_summary.md` and `dicom_demographic_audit.tsv`.

## 4. BIDS metadata free-text assessment

- JSON sidecars parsed: **7958**
- Suspicious unique values (heuristic): **6**

| Field | Classification |
| --- | --- |
| `SeriesDescription` | REVIEW_REQUIRED |
| `ProtocolName` | REVIEW_REQUIRED |
| `SequenceName` | SAFE_TO_KEEP |
| `PulseSequenceDetails` | SAFE_TO_KEEP |
| `ScanningSequence` | SAFE_TO_KEEP |
| `InstitutionalDepartmentName` | REVIEW_REQUIRED |
| `Manufacturer` | SAFE_TO_KEEP |
| `ManufacturersModelName` | SAFE_TO_KEEP |

See `bids_freetext_summary.md` and `bids_freetext_values.tsv`.

## 5. Recommended actions before Scientific Data submission

1. **Do not distribute `raw_original/`** in the public package.
2. Complete **anatomical defacing** for all shared structural derivatives.
3. If any DICOM objects are shared, remove **PatientAge** and verify direct identifiers are absent.
4. Manually review flagged free-text values in `bids_freetext_values.tsv`.
5. Visually spot-check anatomical series for burned-in text even when tags are absent/NO.
6. Document de-identification as a **PS3.15-oriented subset**, not a certified full Basic Profile.

## Software provenance

See `audit_provenance.json` and `privacy_audit.log`.
