# Final privacy readiness report

**Generated (UTC):** 2026-07-22T20:05:00+00:00  
**Package:** `reports/deidentification_validation/`  
**Mode:** READ-ONLY audits + documentation (dataset not modified)

## Executive statuses

| Domain | Status | Rationale |
| --- | --- | --- |
| DICOM privacy | **READY** *(BIDS-only release)* | Scratch `raw_original/` empty (removed); cohorts on `/project/def-amirs/raw_original`; no DICOM in public package. Prior audits + PS3.15-oriented pipeline policy documented. **BLOCKED** if any DICOM were to be distributed without a fresh de-id mirror audit. |
| BIDS privacy | **READY** | 7958 JSON scanned; 0 PHI_RISK fields; 0 invalid JSON; free-text technical. `InstitutionalDepartmentName` absent from BIDS. `participants.tsv` reviewed (minimal columns only). |
| Defacing | **READY** | Coverage complete (356/356), geometry OK, and `InstitutionalDepartmentName` confirmed **absent** from all **726** derivative JSON under `derivatives/defacing/`. |
| Scientific Data submission | **READY** *(pending PI sign-off)* | README updated with PS3.15-oriented wording; checklist privacy items complete. Remaining: PI/steward acceptance and package content verification. |

## Supported publication claim

> Imaging data were de-identified using a DICOM PS3.15-oriented workflow, with additional BIDS metadata cleaning and anatomical defacing validation.

**Do not claim:** full certified DICOM PS3.15 Basic Profile anonymization.

## Audit inventory

| Artifact | Path |
| --- | --- |
| DICOM PHI TSV | `dicom_phi_audit.tsv` |
| DICOM summary | `dicom_deidentification_summary.md` |
| BIDS PHI TSV | `bids_sidecar_phi_audit.tsv` |
| BIDS free-text unique | `bids_sidecar_freetext_unique.tsv` |
| BIDS summary | `bids_sidecar_privacy_summary.md` |
| Defacing TSV | `defacing_validation.tsv` |
| Defacing summary | `defacing_validation_summary.md` |
| Technical Validation text | `Scientific_Data_Technical_Validation_Deidentification.md` |
| Checklist | `release_privacy_checklist.md` |

## Scripts (reproducible)

```bash
python code/audit_dicom_deidentification.py --dicom-dir /project/def-amirs/raw_original
python code/audit_bids_sidecar_privacy.py --bids-dir /home/alexrees/scratch/bids
python code/audit_defacing_release.py \
  --bids-dir /home/alexrees/scratch/bids \
  --defaced-dir /home/alexrees/scratch/derivatives/defacing
```

Dry-run first with `--dry-run` on each script.

## Key quantitative results

### DICOM

- Live files scanned: **0** (archive empty)
- Reused: privacy_audit (83 154 candidates / 1 133 series historically), PS3.15 audit, deidentification_report, date-shift table present

### BIDS sidecars

- JSON scanned: **7958**
- Invalid: **0**
- PHI_RISK hits: **0**
- Verdict: **PASS**

### Defacing

- T1w expected / defaced / missing: **356 / 356 / 0**
- Geometry failures: **0**
- Median % voxels changed (`|Δ|>0.5`): **24.08**
- Derivative JSON with PHI-like keys: **352** (`InstitutionalDepartmentName`)
- Verdict: **PASS_WITH_METADATA_REVIEW**

## Remaining items before upload

1. PI / data steward acceptance of this report.
2. Verify public package contents (BIDS + defaced anatomicals only).
3. Keep date-shift CSV and any source DICOM **out** of the public archive.

## Confirmed (2026-07-22 follow-up)

- README: PS3.15-oriented workflow wording (no full Basic Profile claim).
- `participants.tsv`: reviewed — `participant_id`, `cohort`, `sex` only (`participants_tsv_review.md`).
- `derivatives/defacing/**/*.json`: `InstitutionalDepartmentName` count = **0**.

## Safety statement

No files under `bids/`, `raw_original/`, or existing NIfTI/TSV inventories were modified by this validation package. Outputs were written only to `reports/deidentification_validation/` and `code/` (new audit scripts).
