# Methods — Automated T1w quality screening (Pizarro et al., 2023)

## Overview

An automated deep-learning classifier (Pizarro et al., 2023) was applied to
T1-weighted structural MRI as an additional quality-screening tool. Predictions
were used exclusively to prioritize targeted visual inspection and were not
employed as automatic exclusion criteria. MRIQC remained the primary quantitative
QC framework for the dataset.

## Image selection

Only BIDS anatomical T1-weighted NIfTI files matching `*_T1w.nii.gz` were
analysed. FLAIR, T2-weighted, T2*, proton-density, diffusion, susceptibility-weighted,
fieldmap, functional, and all other modalities were excluded from inference and
from all publication tables and figures.

## Model and inference

The publicly described Pizarro ONNX model (`model.FINAL.onnx`) was executed with
CPU-only ONNX Runtime. Preprocessing followed the vendor production utilities
(reorientation, intensity normalization, padding/resizing to the network input
shape). For each T1w volume, Monte Carlo (MC) dropout inference was performed with
10 stochastic forward passes (fixed seed 1010). Softmax outputs were collated by
majority vote across MC runs.

## Continuous screening scores

Rather than reporting binary pass/fail decisions, three continuous quantities were
retained for each T1w image:

1. **Artifact probability** — percentage of MC runs assigning the artifact class
   (0–100).
2. **Confidence** — majority-class agreement across MC runs (0–100).
3. **Uncertainty** — binary Shannon entropy (bits) of the MC artifact-vote
   fraction; values near 1 bit indicate highly discordant MC votes and motivate
   manual review regardless of the majority label.

These scores served solely as prioritization indices for visual quality control.
No subject was excluded based solely on the deep-learning model.

## Cohort coverage (this dataset)

In the present release, 387 T1-weighted images from 83 subjects
were successfully processed. Inference completed without errors for the scored
T1w set. Priority lists of the ten highest artifact-probability and ten highest
uncertainty T1w scans are provided to guide targeted visual inspection.

## Relationship to MRIQC

Image quality metrics from MRIQC constitute the primary quantitative QC summary
for structural MRI in this dataset. Pizarro outputs are complementary and are
reported only as screening aids for manual review workflows.

## Software and reproducibility

- Pipeline module: `neuro_pipeline.qc.pizarro_qc`
- Model label: `Pizarro2023-FINAL`
- MC runs: 10; seed: 1010
- Revised Scientific Data package builder:
  `scripts/build_pizarro_scientific_data_report.py`
- Outputs: `reports/pizarro_qc_revised/`

## Citation

Pizarro et al. (2023). Deep learning detects MRI artifacts.
