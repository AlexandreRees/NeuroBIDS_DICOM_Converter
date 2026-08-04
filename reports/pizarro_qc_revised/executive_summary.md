# Pizarro QC — Executive Summary (T1-weighted only)

**Date:** 2026-07-24  
**Scope:** `*_T1w.nii.gz` only  
**Role:** automated quality-screening / manual-review prioritization  
**Not used as:** automatic exclusion or final quality classifier  

## Statement for Scientific Data

An automated deep-learning classifier (Pizarro et al., 2023) was applied to T1-weighted structural MRI as an additional quality-screening tool. Predictions were used exclusively to prioritize targeted visual inspection and were not employed as automatic exclusion criteria.

## Processing status

- **385** intended T1-weighted images from **83** subjects were successfully processed.
- Inference completed without errors (0 load/inference errors among scored T1w images).
- Non-T1w rows present in legacy subject TSVs (**0**, including archived FLAIR) were **excluded** from this publication package.
- Predictions are used **only** to prioritize manual review.
- **No subject was excluded** based solely on the deep-learning model.
- **MRIQC remains the primary quantitative QC framework** for this dataset; Pizarro is complementary screening only.

## Continuous screening metrics (descriptive)

For each T1w image the following continuous quantities are reported (see `image_level_predictions.tsv`):

| Metric | Definition |
| --- | --- |
| `artifact_probability` | Percentage of Monte Carlo (MC) dropout runs voting for the artifact class (0–100) |
| `confidence` | Majority-class agreement across MC runs (0–100) |
| `uncertainty` | Binary Shannon entropy (bits) of the MC artifact-vote fraction; maximal (1 bit) when votes are evenly split |

Cohort image-level artifact probability: mean = **65.8**, median = **80.0** (descriptive only; not a failure rate).

## Manual review priority (visual QC recommendations only)

These lists identify T1w scans for **targeted visual inspection**. They are **not** exclusion lists.

### Top 10 — highest artifact probability

| Rank | Subject | Session | Filename | Artifact P | Uncertainty | Confidence |
| ---: | --- | --- | --- | ---: | ---: | ---: |
| 1 | `sub-084` | ses-01 | `sub-084_ses-01_run-03_T1w.nii.gz` | 100 | 0 | 100 |
| 2 | `sub-084` | ses-01 | `sub-084_ses-01_run-02_T1w.nii.gz` | 100 | 0 | 100 |
| 3 | `sub-084` | ses-01 | `sub-084_ses-01_run-01_T1w.nii.gz` | 100 | 0 | 100 |
| 4 | `sub-083` | ses-01 | `sub-083_ses-01_run-03_T1w.nii.gz` | 100 | 0 | 100 |
| 5 | `sub-083` | ses-01 | `sub-083_ses-01_run-02_T1w.nii.gz` | 100 | 0 | 100 |
| 6 | `sub-082` | ses-01 | `sub-082_ses-01_run-03_T1w.nii.gz` | 100 | 0 | 100 |
| 7 | `sub-082` | ses-01 | `sub-082_ses-01_run-02_T1w.nii.gz` | 100 | 0 | 100 |
| 8 | `sub-082` | ses-01 | `sub-082_ses-01_run-01_T1w.nii.gz` | 100 | 0 | 100 |
| 9 | `sub-081` | ses-01 | `sub-081_ses-01_run-03_T1w.nii.gz` | 100 | 0 | 100 |
| 10 | `sub-080` | ses-01 | `sub-080_ses-01_run-03_T1w.nii.gz` | 100 | 0 | 100 |

### Top 10 — highest uncertainty

| Rank | Subject | Session | Filename | Artifact P | Uncertainty | Confidence |
| ---: | --- | --- | --- | ---: | ---: | ---: |
| 1 | `sub-081` | ses-01 | `sub-081_ses-01_run-02_T1w.nii.gz` | 50 | 1 | 50 |
| 2 | `sub-078` | ses-01 | `sub-078_ses-01_run-02_T1w.nii.gz` | 50 | 1 | 50 |
| 3 | `sub-073` | ses-01 | `sub-073_ses-01_run-02_T1w.nii.gz` | 50 | 1 | 50 |
| 4 | `sub-069` | ses-02 | `sub-069_ses-02_run-01_T1w.nii.gz` | 50 | 1 | 50 |
| 5 | `sub-067` | ses-01 | `sub-067_ses-01_run-01_T1w.nii.gz` | 50 | 1 | 50 |
| 6 | `sub-065` | ses-01 | `sub-065_ses-01_run-02_T1w.nii.gz` | 50 | 1 | 50 |
| 7 | `sub-058` | ses-01 | `sub-058_ses-01_run-03_T1w.nii.gz` | 50 | 1 | 50 |
| 8 | `sub-058` | ses-01 | `sub-058_ses-01_run-01_T1w.nii.gz` | 50 | 1 | 50 |
| 9 | `sub-057` | ses-02 | `sub-057_ses-02_run-02_T1w.nii.gz` | 50 | 1 | 50 |
| 10 | `sub-051` | ses-01 | `sub-051_ses-01_run-02_T1w.nii.gz` | 50 | 1 | 50 |

## What this package intentionally omits

- Subject pass/fail or “flagged” tallies
- Cohort “failure rates” or percentages of “bad subjects”
- Binary artifact decisions in the executive narrative
- Any FLAIR / T2 / DWI / functional or other non-T1w results

## Deliverables

| File | Description |
| --- | --- |
| `executive_summary.md` | This document |
| `publication_methods.md` | Methods text for Scientific Data |
| `image_level_predictions.tsv` | Continuous scores per T1w image |
| `subject_level_summary.tsv` | Descriptive subject aggregates |
| `manual_review_top10_artifact_probability.tsv` | Visual QC priority |
| `manual_review_top10_uncertainty.tsv` | Visual QC priority |
| `figures/T1_probability_histogram.pdf` | Image-level probability histogram |
| `figures/uncertainty_distribution.pdf` | Uncertainty histogram |
| `figures/subject_probability_heatmap.pdf` | Subject × session heatmap |
| `figures/cohort_subject_mean_probability.pdf` | Cohort subject-mean distribution |

## FLAIR deprecation

Any previously generated FLAIR Pizarro outputs are archived under `reports/pizarro_qc/archive_flair_deprecated/` and marked **DEPRECATED**. They do not appear in any table or figure of this revised package.
