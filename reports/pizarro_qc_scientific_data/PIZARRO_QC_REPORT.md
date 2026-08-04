# Pizarro automated QC screening report (Scientific Data)

**Dataset role:** automated structural MRI quality screening and prioritization  
**Modality scope:** `*_T1w.nii.gz` only  
**Report generated:** 2026-07-24T17:40:07Z

## Statements for the Data Descriptor

> The Pizarro model was used as an automated structural MRI quality screening tool. Model outputs were not used for exclusion decisions but rather to prioritize images for targeted visual inspection. Quantitative MRI quality assessment remains provided by MRIQC.

> No image or subject was excluded based solely on the Pizarro model output. Predictions were used exclusively to prioritize targeted manual visual inspection.

## Scope and exclusions

Only BIDS anatomical T1-weighted NIfTI files matching `*_T1w.nii.gz` were analysed.
FLAIR, T2-weighted, diffusion, functional, fieldmap, and all other modalities were
excluded from this package and must not enter the analysis tables or figures.

| Item | Count |
| --- | ---: |
| T1w images included in analysis | 385 |
| Non-T1w rows excluded from current subject TSVs | 0 |
| Legacy non-T1w rows in historical aggregate (informational) | 0 |
| T1w inference/load errors among scored inputs | 0 |
| Subjects represented | 83 |

Validation: the analysis set is asserted to contain **T1w only**; presence of any
non-T1w modality raises an error at report generation time.

## Continuous screening metrics

For each T1w image the following continuous quantities are retained:

| Metric | Definition |
| --- | --- |
| Model-estimated artifact probability | Percentage of Monte Carlo (MC) dropout runs voting for the artifact class (0–100) |
| Model confidence | Majority-class agreement across MC runs (0–100) |
| Model uncertainty | Binary Shannon entropy (bits) of the MC artifact-vote fraction; maximal (1 bit) when votes are evenly split |

These quantities are **screening / prioritization indices** for manual visual
inspection. They are not automatic exclusion criteria.

### Prioritization thresholds used for review queues

| Criterion | Threshold | Interpretation |
| --- | --- | --- |
| High model-estimated artifact probability | ≥ 90% | Prioritize for visual review |
| High model uncertainty | ≥ 0.9 bit | Prioritize for visual review regardless of majority vote |

Under these thresholds:

- T1w images prioritized for visual review: **246**
- via high model-estimated artifact probability: **169**
- via high model uncertainty: **77**
- subjects prioritized for visual review (≥1 prioritized image): **78**

These counts describe **screening priority** for targeted manual inspection.
They are not pass/fail labels, exclusion tallies, or a dataset failure rate.

## Subject-level descriptive summary

Subject tables report:

- number of T1w images
- median model-estimated artifact probability
- interquartile range (IQR)
- number of images requiring prioritized review

Mean model-estimated artifact probability is intentionally **not** reported as a
cohort quality indicator.

## Images prioritized for visual inspection based on high model-estimated artifact probability

Full ranked list: `tables/pizarro_visual_review_priority.tsv`
(`priority_basis = high_model_estimated_artifact_probability`).

Preview (first 25):

| Rank | Image identifier | Model-estimated artifact probability | Uncertainty | Confidence |
| ---: | --- | ---: | ---: | ---: |
| 1 | `sub-084_ses-01_run-03_T1w.nii.gz` | 100.0 | 0.0 | 100.0 |
| 2 | `sub-084_ses-01_run-02_T1w.nii.gz` | 100.0 | 0.0 | 100.0 |
| 3 | `sub-084_ses-01_run-01_T1w.nii.gz` | 100.0 | 0.0 | 100.0 |
| 4 | `sub-083_ses-01_run-03_T1w.nii.gz` | 100.0 | 0.0 | 100.0 |
| 5 | `sub-083_ses-01_run-02_T1w.nii.gz` | 100.0 | 0.0 | 100.0 |
| 6 | `sub-082_ses-01_run-03_T1w.nii.gz` | 100.0 | 0.0 | 100.0 |
| 7 | `sub-082_ses-01_run-02_T1w.nii.gz` | 100.0 | 0.0 | 100.0 |
| 8 | `sub-082_ses-01_run-01_T1w.nii.gz` | 100.0 | 0.0 | 100.0 |
| 9 | `sub-081_ses-01_run-03_T1w.nii.gz` | 100.0 | 0.0 | 100.0 |
| 10 | `sub-080_ses-01_run-03_T1w.nii.gz` | 100.0 | 0.0 | 100.0 |
| 11 | `sub-076_ses-01_run-01_T1w.nii.gz` | 100.0 | 0.0 | 100.0 |
| 12 | `sub-075_ses-01_run-03_T1w.nii.gz` | 100.0 | 0.0 | 100.0 |
| 13 | `sub-074_ses-02_run-03_T1w.nii.gz` | 100.0 | 0.0 | 100.0 |
| 14 | `sub-074_ses-02_run-01_T1w.nii.gz` | 100.0 | 0.0 | 100.0 |
| 15 | `sub-074_ses-01_run-03_T1w.nii.gz` | 100.0 | 0.0 | 100.0 |
| 16 | `sub-073_ses-02_run-03_T1w.nii.gz` | 100.0 | 0.0 | 100.0 |
| 17 | `sub-073_ses-01_run-03_T1w.nii.gz` | 100.0 | 0.0 | 100.0 |
| 18 | `sub-072_ses-02_run-01_T1w.nii.gz` | 100.0 | 0.0 | 100.0 |
| 19 | `sub-072_ses-01_run-03_T1w.nii.gz` | 100.0 | 0.0 | 100.0 |
| 20 | `sub-072_ses-01_run-01_T1w.nii.gz` | 100.0 | 0.0 | 100.0 |
| 21 | `sub-071_ses-01_run-03_T1w.nii.gz` | 100.0 | 0.0 | 100.0 |
| 22 | `sub-071_ses-01_run-02_T1w.nii.gz` | 100.0 | 0.0 | 100.0 |
| 23 | `sub-071_ses-01_run-01_T1w.nii.gz` | 100.0 | 0.0 | 100.0 |
| 24 | `sub-070_ses-01_run-02_T1w.nii.gz` | 100.0 | 0.0 | 100.0 |
| 25 | `sub-070_ses-01_run-01_T1w.nii.gz` | 100.0 | 0.0 | 100.0 |


## Images prioritized for visual inspection based on high model uncertainty

Full ranked list: `tables/pizarro_visual_review_priority.tsv`
(`priority_basis = high_model_uncertainty`).

| Rank | Image identifier | Model-estimated artifact probability | Uncertainty | Confidence |
| ---: | --- | ---: | ---: | ---: |
| 1 | `sub-081_ses-01_run-02_T1w.nii.gz` | 50.0 | 1.0 | 50.0 |
| 2 | `sub-078_ses-01_run-02_T1w.nii.gz` | 50.0 | 1.0 | 50.0 |
| 3 | `sub-073_ses-01_run-02_T1w.nii.gz` | 50.0 | 1.0 | 50.0 |
| 4 | `sub-069_ses-02_run-01_T1w.nii.gz` | 50.0 | 1.0 | 50.0 |
| 5 | `sub-067_ses-01_run-01_T1w.nii.gz` | 50.0 | 1.0 | 50.0 |
| 6 | `sub-065_ses-01_run-02_T1w.nii.gz` | 50.0 | 1.0 | 50.0 |
| 7 | `sub-058_ses-01_run-03_T1w.nii.gz` | 50.0 | 1.0 | 50.0 |
| 8 | `sub-058_ses-01_run-01_T1w.nii.gz` | 50.0 | 1.0 | 50.0 |
| 9 | `sub-057_ses-02_run-02_T1w.nii.gz` | 50.0 | 1.0 | 50.0 |
| 10 | `sub-051_ses-01_run-02_T1w.nii.gz` | 50.0 | 1.0 | 50.0 |
| 11 | `sub-046_ses-01_run-02_T1w.nii.gz` | 50.0 | 1.0 | 50.0 |
| 12 | `sub-038_ses-01_run-01_T1w.nii.gz` | 50.0 | 1.0 | 50.0 |
| 13 | `sub-037_ses-01_run-01_T1w.nii.gz` | 50.0 | 1.0 | 50.0 |
| 14 | `sub-031_ses-01_run-01_T1w.nii.gz` | 50.0 | 1.0 | 50.0 |
| 15 | `sub-029_ses-01_run-02_T1w.nii.gz` | 50.0 | 1.0 | 50.0 |
| 16 | `sub-026_ses-02_run-01_T1w.nii.gz` | 50.0 | 1.0 | 50.0 |
| 17 | `sub-024_ses-02_run-01_T1w.nii.gz` | 50.0 | 1.0 | 50.0 |
| 18 | `sub-022_ses-02_run-01_T1w.nii.gz` | 50.0 | 1.0 | 50.0 |
| 19 | `sub-017_ses-02_run-02_T1w.nii.gz` | 50.0 | 1.0 | 50.0 |
| 20 | `sub-017_ses-01_run-02_T1w.nii.gz` | 50.0 | 1.0 | 50.0 |
| 21 | `sub-012_ses-02_run-02_T1w.nii.gz` | 50.0 | 1.0 | 50.0 |
| 22 | `sub-009_ses-01_run-03_T1w.nii.gz` | 50.0 | 1.0 | 50.0 |
| 23 | `sub-008_ses-01_run-02_T1w.nii.gz` | 50.0 | 1.0 | 50.0 |
| 24 | `sub-007_ses-01_run-02_T1w.nii.gz` | 50.0 | 1.0 | 50.0 |
| 25 | `sub-003_ses-02_run-02_T1w.nii.gz` | 50.0 | 1.0 | 50.0 |
| 26 | `sub-073_ses-02_run-02_T1w.nii.gz` | 60.0 | 0.970951 | 60.0 |
| 27 | `sub-068_ses-02_run-02_T1w.nii.gz` | 60.0 | 0.970951 | 60.0 |
| 28 | `sub-068_ses-01_run-01_T1w.nii.gz` | 60.0 | 0.970951 | 60.0 |
| 29 | `sub-054_ses-02_run-01_T1w.nii.gz` | 60.0 | 0.970951 | 60.0 |
| 30 | `sub-047_ses-01_run-01_T1w.nii.gz` | 60.0 | 0.970951 | 60.0 |
| 31 | `sub-046_ses-02_run-01_T1w.nii.gz` | 60.0 | 0.970951 | 60.0 |
| 32 | `sub-039_ses-01_run-01_T1w.nii.gz` | 60.0 | 0.970951 | 60.0 |
| 33 | `sub-038_ses-01_run-02_T1w.nii.gz` | 60.0 | 0.970951 | 60.0 |
| 34 | `sub-029_ses-01_run-01_T1w.nii.gz` | 60.0 | 0.970951 | 60.0 |
| 35 | `sub-028_ses-02_run-01_T1w.nii.gz` | 60.0 | 0.970951 | 60.0 |
| 36 | `sub-027_ses-01_run-03_T1w.nii.gz` | 60.0 | 0.970951 | 60.0 |
| 37 | `sub-023_ses-01_run-01_T1w.nii.gz` | 60.0 | 0.970951 | 60.0 |
| 38 | `sub-022_ses-02_run-03_T1w.nii.gz` | 60.0 | 0.970951 | 60.0 |
| 39 | `sub-022_ses-01_run-02_T1w.nii.gz` | 60.0 | 0.970951 | 60.0 |
| 40 | `sub-022_ses-01_run-01_T1w.nii.gz` | 60.0 | 0.970951 | 60.0 |
| 41 | `sub-019_ses-02_run-01_T1w.nii.gz` | 60.0 | 0.970951 | 60.0 |
| 42 | `sub-017_ses-01_run-01_T1w.nii.gz` | 60.0 | 0.970951 | 60.0 |
| 43 | `sub-014_ses-01_run-01_T1w.nii.gz` | 60.0 | 0.970951 | 60.0 |
| 44 | `sub-007_ses-02_run-03_T1w.nii.gz` | 60.0 | 0.970951 | 60.0 |
| 45 | `sub-003_ses-02_run-01_T1w.nii.gz` | 60.0 | 0.970951 | 60.0 |
| 46 | `sub-003_ses-01_run-02_T1w.nii.gz` | 60.0 | 0.970951 | 60.0 |
| 47 | `sub-081_ses-01_run-01_T1w.nii.gz` | 40.0 | 0.970951 | 60.0 |
| 48 | `sub-078_ses-01_run-01_T1w.nii.gz` | 40.0 | 0.970951 | 60.0 |
| 49 | `sub-075_ses-01_run-01_T1w.nii.gz` | 40.0 | 0.970951 | 60.0 |
| 50 | `sub-074_ses-01_run-02_T1w.nii.gz` | 40.0 | 0.970951 | 60.0 |
| 51 | `sub-074_ses-01_run-01_T1w.nii.gz` | 40.0 | 0.970951 | 60.0 |
| 52 | `sub-072_ses-02_run-02_T1w.nii.gz` | 40.0 | 0.970951 | 60.0 |
| 53 | `sub-069_ses-01_run-01_T1w.nii.gz` | 40.0 | 0.970951 | 60.0 |
| 54 | `sub-052_ses-02_run-02_T1w.nii.gz` | 40.0 | 0.970951 | 60.0 |
| 55 | `sub-052_ses-01_run-02_T1w.nii.gz` | 40.0 | 0.970951 | 60.0 |
| 56 | `sub-043_ses-02_run-05_T1w.nii.gz` | 40.0 | 0.970951 | 60.0 |
| 57 | `sub-040_ses-02_run-02_T1w.nii.gz` | 40.0 | 0.970951 | 60.0 |
| 58 | `sub-039_ses-01_run-02_T1w.nii.gz` | 40.0 | 0.970951 | 60.0 |
| 59 | `sub-031_ses-01_run-02_T1w.nii.gz` | 40.0 | 0.970951 | 60.0 |
| 60 | `sub-030_ses-02_run-02_T1w.nii.gz` | 40.0 | 0.970951 | 60.0 |
| 61 | `sub-029_ses-02_run-02_T1w.nii.gz` | 40.0 | 0.970951 | 60.0 |
| 62 | `sub-025_ses-02_run-01_T1w.nii.gz` | 40.0 | 0.970951 | 60.0 |
| 63 | `sub-025_ses-01_run-01_T1w.nii.gz` | 40.0 | 0.970951 | 60.0 |
| 64 | `sub-021_ses-01_run-01_T1w.nii.gz` | 40.0 | 0.970951 | 60.0 |
| 65 | `sub-020_ses-01_run-03_T1w.nii.gz` | 40.0 | 0.970951 | 60.0 |
| 66 | `sub-018_ses-01_run-02_T1w.nii.gz` | 40.0 | 0.970951 | 60.0 |
| 67 | `sub-015_ses-02_run-01_T1w.nii.gz` | 40.0 | 0.970951 | 60.0 |
| 68 | `sub-011_ses-02_run-02_T1w.nii.gz` | 40.0 | 0.970951 | 60.0 |
| 69 | `sub-009_ses-01_run-01_T1w.nii.gz` | 40.0 | 0.970951 | 60.0 |
| 70 | `sub-008_ses-02_run-01_T1w.nii.gz` | 40.0 | 0.970951 | 60.0 |
| 71 | `sub-006_ses-01_run-03_T1w.nii.gz` | 40.0 | 0.970951 | 60.0 |
| 72 | `sub-006_ses-01_run-02_T1w.nii.gz` | 40.0 | 0.970951 | 60.0 |
| 73 | `sub-005_ses-02_run-03_T1w.nii.gz` | 40.0 | 0.970951 | 60.0 |
| 74 | `sub-005_ses-02_run-01_T1w.nii.gz` | 40.0 | 0.970951 | 60.0 |
| 75 | `sub-003_ses-01_run-01_T1w.nii.gz` | 40.0 | 0.970951 | 60.0 |
| 76 | `sub-002_ses-02_run-02_T1w.nii.gz` | 40.0 | 0.970951 | 60.0 |
| 77 | `sub-001_ses-02_run-01_T1w.nii.gz` | 40.0 | 0.970951 | 60.0 |


## Figures

| Figure | File | Description |
| --- | --- | --- |
| 1 | `figures/pizarro_workflow.png` | BIDS T1w → Pizarro inference → continuous metrics → manual visual prioritization |
| 2 | `figures/pizarro_probability_distribution.png` | Histogram of model-estimated artifact probability |
| 3 | `figures/pizarro_uncertainty_probability.png` | Uncertainty vs model-estimated artifact probability (high-uncertainty highlighted) |
| 4 | `figures/pizarro_subject_coverage.png` | Distribution of number of T1w scans per subject |

Pass/fail and artifact-rate figures are intentionally omitted.

## Reproducibility

| Item | Value |
| --- | --- |
| Model name | Pizarro et al. (2023) |
| Model file | `model.FINAL.onnx` |
| Model SHA256 | `cb84f2b90f7de452331ed9ba5152335b873aba95d0ca3766adfffecdafe5178a` |
| Inference framework | ONNX Runtime |
| Monte Carlo dropout runs | 10 |
| Random seed | 1010 |
| Python version | 3.11.5 |
| ONNX Runtime version | 1.23.2 |
| Execution date | 2026-07-24 |
| Slurm array job ID | 66208403 |
| Source predictions | `/home/alexrees/scratch/neuro_pipeline/reports/pizarro_qc/subject_results/*_pizarro.tsv` |

Machine-readable copy: `metadata/model_metadata.json`.

## Deliverables

| Path | Description |
| --- | --- |
| `PIZARRO_QC_REPORT.md` | This Data Descriptor–oriented report |
| `tables/pizarro_image_level.tsv` | Continuous scores per T1w image |
| `tables/pizarro_subject_level.tsv` | Subject descriptive aggregates |
| `tables/pizarro_visual_review_priority.tsv` | Visual-review priority queues |
| `figures/` | Publication figures 1–4 |
| `metadata/model_metadata.json` | Reproducibility metadata |

## Citation

Pizarro et al. (2023). Deep learning detects MRI artifacts.
Model file: `model.FINAL.onnx`.
