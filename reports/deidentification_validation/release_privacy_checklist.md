# Release privacy checklist

Use this checklist before packaging the Scientific Data / public BIDS release. Items reflect the 2026-07-22 de-identification validation package under `reports/deidentification_validation/`.

## Distribution controls

- [x] No raw DICOM distributed (`raw_original/` empty in working tree; not part of public package)
- [x] README updated with PS3.15-oriented wording (not “full Basic Profile”) and defacing note
- [x] Technical Validation section generated (`Scientific_Data_Technical_Validation_Deidentification.md`)

## Anatomical defacing

- [x] All T1w intended for sharing defaced (**356 / 356** matched)
- [x] Defacing geometry checks passed (shape / zooms / affine / orientation)
- [x] Derivative JSON scrubbed of `InstitutionalDepartmentName` (**0 / 726** JSON retain the field; confirmed 2026-07-22)

## BIDS metadata

- [x] BIDS JSON PHI audit passed (**7958** JSON; **0** PHI_RISK; **0** invalid)
- [x] Free-text metadata reviewed (`SeriesDescription` / `ProtocolName` / sequence fields — technical labels)
- [x] `participants.tsv` reviewed — only `participant_id`, `cohort`, `sex` (see `participants_tsv_review.md`)

## DICOM / provenance

- [x] DICOM audit completed (live archive unavailable → prior audits + pipeline policy reused; see `dicom_deidentification_summary.md`)
- [x] Date-shift table kept private (`metadata/deidentify_date_shifts.csv` — do not publish)

## Final gate

- [ ] `FINAL_PRIVACY_READINESS_REPORT.md` statuses accepted by PI / data steward
- [ ] Public package contents verified (BIDS + defaced anatomicals only)
