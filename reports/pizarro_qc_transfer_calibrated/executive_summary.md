# Pizarro QC — Executive Summary (transfer-calibrated)

**Date:** 2026-08-04  
**Scope:** `*_T1w.nii.gz` only  
**Role:** automated quality-screening / manual-review prioritization  
**Not used as:** automatic exclusion or final quality classifier  

## Transfer-learning update

A lightweight logistic regression was fit on frozen Pizarro latent embeddings
(`activation_22/Relu:0`, 128-D) from **264** run-01/run-02 T1w images,
using the local acquisition proxy labels (run-01 = non-NORM, run-02 = NORM).
The deep network weights were **not** retrained.

- Transfer decision threshold (Youden, probability): **0.8241**
- Images with transfer score: **264 / 387**
- Images with original Pizarro score only (mostly run-03+): **123**
- Mean transfer P(non-NORM) on scored subset: **0.500**
- CV reference AUC (embeddings LR): **0.964** vs original score AUC **0.678**

## Statement for Scientific Data

An automated deep-learning classifier (Pizarro et al., 2023) was applied to
T1-weighted structural MRI as an additional quality-screening tool. A
dataset-specific calibration on intermediate embeddings was used only to
improve prioritization of manual review. Predictions were not employed as
automatic exclusion criteria.

## Processing status

- **387** T1w images from the MC50 QC package.
- Transfer calibration applied to **264** images with embeddings.
- Predictions are used **only** to prioritize manual review.
- **No subject was excluded** based solely on the deep-learning / transfer model.
- **MRIQC remains the primary quantitative QC framework**.

## Continuous screening metrics

Cohort image-level artifact probability: mean = **69.7**, median = **80.0**.

### Top 10 — highest transfer P(non-NORM) (run-01/02 only)

| Rank | Subject | Session | Filename | Orig P | Transfer P(%) | Flag |
| ---: | --- | --- | --- | ---: | ---: | --- |
| 1 | sub-037 | ses-01 | sub-037_ses-01_run-01_T1w.nii.gz | 68 | 100.0 | yes |
| 2 | sub-028 | ses-01 | sub-028_ses-01_run-01_T1w.nii.gz | 60 | 100.0 | yes |
| 3 | sub-033 | ses-01 | sub-033_ses-01_run-01_T1w.nii.gz | 64 | 100.0 | yes |
| 4 | sub-001 | ses-01 | sub-001_ses-01_run-01_T1w.nii.gz | 8 | 100.0 | yes |
| 5 | sub-023 | ses-01 | sub-023_ses-01_run-01_T1w.nii.gz | 70 | 100.0 | yes |
| 6 | sub-038 | ses-02 | sub-038_ses-02_run-01_T1w.nii.gz | 90 | 100.0 | yes |
| 7 | sub-036 | ses-01 | sub-036_ses-01_run-01_T1w.nii.gz | 100 | 100.0 | yes |
| 8 | sub-022 | ses-01 | sub-022_ses-01_run-01_T1w.nii.gz | 84 | 100.0 | yes |
| 9 | sub-083 | ses-01 | sub-083_ses-01_run-01_T1w.nii.gz | 94 | 100.0 | yes |
| 10 | sub-052 | ses-01 | sub-052_ses-01_run-01_T1w.nii.gz | 90 | 100.0 | yes |

### Top 10 — mixed screening priority (transfer ×100 if available, else original P)

| Rank | Subject | Session | Filename | Orig P | Transfer P | Priority | Source |
| ---: | --- | --- | --- | ---: | ---: | ---: | --- |
| 1 | sub-001 | ses-01 | sub-001_ses-01_run-03_T1w.nii.gz | 100 |  | 100.0 | original_pizarro_score |
| 2 | sub-001 | ses-02 | sub-001_ses-02_run-03_T1w.nii.gz | 100 |  | 100.0 | original_pizarro_score |
| 3 | sub-002 | ses-01 | sub-002_ses-01_run-03_T1w.nii.gz | 100 |  | 100.0 | original_pizarro_score |
| 4 | sub-002 | ses-02 | sub-002_ses-02_run-03_T1w.nii.gz | 100 |  | 100.0 | original_pizarro_score |
| 5 | sub-003 | ses-01 | sub-003_ses-01_run-03_T1w.nii.gz | 100 |  | 100.0 | original_pizarro_score |
| 6 | sub-004 | ses-01 | sub-004_ses-01_run-03_T1w.nii.gz | 100 |  | 100.0 | original_pizarro_score |
| 7 | sub-004 | ses-02 | sub-004_ses-02_run-03_T1w.nii.gz | 100 |  | 100.0 | original_pizarro_score |
| 8 | sub-006 | ses-02 | sub-006_ses-02_run-03_T1w.nii.gz | 100 |  | 100.0 | original_pizarro_score |
| 9 | sub-007 | ses-01 | sub-007_ses-01_run-03_T1w.nii.gz | 100 |  | 100.0 | original_pizarro_score |
| 10 | sub-008 | ses-01 | sub-008_ses-01_run-03_T1w.nii.gz | 100 |  | 100.0 | original_pizarro_score |

## Outputs

- `image_level_predictions.tsv`
- `manual_review_top10_transfer_proba.tsv`
- `manual_review_top10_screening_priority.tsv`
- `manual_review_top10_uncertainty.tsv`
- `subject_level_summary.tsv`
- `transfer_logistic_regression.joblib`
- `figures/`

## Limitations

- Proxy labels (NORM vs non-NORM runs) are not expert visual QC grades.
- Transfer scores are currently available for run-01/02 only; run-03+
  fall back to the original Pizarro score until embeddings are extracted.
- Intended for triage / ranking, not automatic exclusion.
