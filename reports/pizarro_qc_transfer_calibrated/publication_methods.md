# Methods — Pizarro QC with dataset-specific transfer calibration

## Overview

Pizarro et al. (2023) was applied to T1-weighted MRI as a complementary
quality-screening tool. In addition to the original Monte Carlo artifact score,
a lightweight transfer model was calibrated on frozen intermediate embeddings for
local run-01 vs run-02 (non-NORM vs NORM) discrimination.

## Transfer calibration

- Frozen extractor: `Pizarro2023-FINAL` (`model.FINAL.onnx`)
- Embedding node: `activation_22/Relu:0` (128-D)
- Transfer model: logistic regression with feature standardization
- Training set: 264 T1w images (run-01/02)
- Decision threshold: Youden-optimized probability = 0.8241
- Deep weights were not updated

## Reporting

For each T1w image we retain the original `artifact_probability`, `confidence`,
and `uncertainty`, plus `transfer_proba_nonNORM` / `screening_priority` when
embeddings are available. Outputs are used only to prioritize manual review.
MRIQC remains the primary quantitative QC framework.

## Provenance

- Source QC package: `/lustre07/scratch/alexrees/reports/pizarro_qc_revised_mc50`
- Transfer learning outputs: `/lustre07/scratch/alexrees/pizarro_transfer_learning/output/with_embeddings`
- Generated: 2026-08-04
