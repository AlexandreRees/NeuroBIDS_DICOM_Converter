# Figure 2 generation report

**Generated (UTC):** 2026-07-22T20:53:31.448089+00:00
**BIDS root:** read-only inventory under project `bids/`
**BIDSVersion:** 1.9.0
**Dataset Name:** Neuro BIDS Pipeline Dataset
**Pipeline GeneratedBy:** [{'Description': 'DICOM to BIDS conversion', 'Name': 'neuro_pipeline', 'Version': '2.1.0'}]
**Script:** `/lustre07/scratch/alexrees/code/generate_dataset_overview_figure.py`

## Cohort

- Subjects: **84** (participants.tsv: 84)
- Sessions: **124**

## Modalities detected (NIfTI suffixes)

| Suffix | Subjects | Sessions | Files |
| --- | ---: | ---: | ---: |
| `bold` | 84 | 124 | 2992 |
| `sbref` | 80 | 119 | 2892 |
| `epi` | 84 | 124 | 982 |
| `dwi` | 82 | 120 | 361 |
| `T1w` | 83 | 122 | 356 |
| `TB1TFL` | 81 | 118 | 248 |
| `FLAIR` | 80 | 118 | 125 |

## BOLD tasks (magnitude bold only)

- `task-control`: 369 files · 84 subjects
- `task-fmri`: 507 files · 83 subjects
- `task-movie`: 495 files · 83 subjects
- `task-rest`: 125 files · 83 subjects

## Representative files selected

- **T1w:** `/home/alexrees/scratch/bids/sub-001/ses-01/anat/sub-001_ses-01_run-01_T1w.nii.gz`
- **FLAIR:** `/home/alexrees/scratch/bids/sub-001/ses-01/anat/sub-001_ses-01_run-01_FLAIR.nii.gz`
- **T2w:** not available
- **DWI:** `/home/alexrees/scratch/bids/sub-001/ses-01/dwi/sub-001_ses-01_run-01_dwi.nii.gz`
- **BOLD:** `/home/alexrees/scratch/bids/sub-001/ses-01/func/sub-001_ses-01_task-rest_run-01_bold.nii.gz`

## Outputs

- png: `/home/alexrees/scratch/reports/dataset_overview_figure/Figure2_multimodal_MRI_overview.png`
- pdf: `/home/alexrees/scratch/reports/dataset_overview_figure/Figure2_multimodal_MRI_overview.pdf`
- svg: `/home/alexrees/scratch/reports/dataset_overview_figure/Figure2_multimodal_MRI_overview.svg`

## Limitations

- No T2w suffix was detected; Panel A omits T2w.
- Panel images are single mid-axial slices from one representative subject/session (`sub-001` preferred when present) and are not quality-control pass/fail decisions.
- BOLD time course is a demeaned whole-brain mean signal for illustration only (no nuisance regression, GLM, or activation maps).
- Auxiliary physiology / eye-tracking / stimulus files exist primarily in the source archive inventory; only a subset of `*_events.tsv` is currently in BIDS.
- Counts exclude `derivatives/`.

## Safety

- BIDS inputs were not modified.
- No new preprocessing derivatives were written into the BIDS tree.

