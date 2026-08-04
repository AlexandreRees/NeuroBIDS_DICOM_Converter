# DICOM de-identification audit (READ-ONLY)

**Generated (UTC):** 2026-07-22T19:08:32.777574+00:00
**DICOM root:** `/lustre07/scratch/alexrees/raw_original` *(empty at audit time; canonical live root is now `/project/def-amirs/raw_original`)*
**Live files scanned:** **0** (directory empty or inaccessible)
**Dry-run:** False

## Critical finding

The path `/home/alexrees/scratch/raw_original` contained **no DICOM instances** at audit time (empty scratch mirror). A live tag-level re-scan from that path was therefore **not possible**. Cohort DICOM live under `/project/def-amirs/raw_original`. This package reuses prior READ-ONLY audits and pipeline documentation rather than inventing live tag statistics.

## Reused prior evidence

- `/home/alexrees/scratch/reports/privacy_audit/PUBLICATION_PRIVACY_READINESS.md`
- `/home/alexrees/scratch/reports/privacy_audit/burned_in_annotation_summary.md`
- `/home/alexrees/scratch/reports/privacy_audit/dicom_demographic_summary.md`
- `/home/alexrees/scratch/reports/deidentification_ps315_openneuro_audit.md`
- `/home/alexrees/scratch/reports/deidentification_report.md`
- `/home/alexrees/scratch/metadata/deidentify_date_shifts.csv`

## Counts (live scan)

- Files scanned: **0**
- Number with identifiers: **n/a (no live DICOM)**
- Number with residual demographics: **n/a (no live DICOM)**

## Private tag statistics (from pipeline policy + prior reports)

- Conversion-path policy retains Siemens CSA private group **0x0029** when required for dcm2niix BIDS conversion (`mri_anonymization/constants.py`).
- Upstream permanent de-id path strips private tags (CSA off) when used.
- Prior privacy audit discovered **83154** DICOM candidates / **1133** series representatives under `raw_original/` before the archive was emptied.

## UID remapping status

- **Status:** DOCUMENTED_IN_PIPELINE (not re-verified on live objects)
- Engine: deterministic SHA-256 → `2.25.*` remap for Study/Series/SOP/FrameOfReference UIDs (`UidRemapper`).
- Empirical historical check (see `reports/deidentification_report.md`): raw PatientName/IDs replaced with canonical IDs; dates shifted; UIDs remapped to `2.25.*`.

## Date shifting

- Date-shift table present: **True** (`/home/alexrees/scratch/metadata/deidentify_date_shifts.csv` when available; **not for public release**).

## Interpretation for Scientific Data

- **Do not distribute DICOM.** The public package is BIDS (+ defaced anatomicals).
- Absence of `raw_original/` content in the working tree reduces accidental DICOM leakage risk for packaging, but means residual-PHI claims for DICOM objects must cite **prior audits + code policy**, not a fresh live scan.
- Do **not** claim certified full DICOM PS3.15 Basic Profile compliance.
- Supported claim: **PS3.15-oriented custom de-identification workflow with documented privacy audits.**

TSV (policy stub): `dicom_phi_audit.tsv`

