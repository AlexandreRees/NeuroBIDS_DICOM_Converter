# Technical Validation — Diffusion MRI

Generated: 2026-07-23 14:41:03 UTC

This section summarises read-only technical validation of diffusion-weighted MRI (DWI) acquisitions in the distributed BIDS dataset. No modifications were applied to `bids/`, `raw_original/`, or `derivatives/`.

## Dataset integrity

A total of **361** DWI acquisitions from **82** participants (**120** sessions) were inventoried. NIfTI, bval, bvec and JSON sidecars were present for **361/361** scans with matching volume / gradient table lengths. Missing sidecars: **0**; duplicate NIfTI paths: **0**.

## Acquisition consistency

Automated protocol clustering identified **6** acquisition protocol(s):

- **Protocol A**: b=`0,1000,2000`, 365 directions, 1×1×5 mm, n=232
- **Protocol B**: b=`0,1000`, 11 directions, 1.38×1.38×1.82 mm, n=121
- **Protocol C**: b=`0,1000,2000`, 144 directions, 1×1×5 mm, n=2
- **Protocol D**: b=`0,1000,2000`, 7 directions, 1×1×5 mm, n=2
- **Protocol E**: b=`0,1000,2000`, 365 directions, 0.982×0.982×6.75 mm, n=2
- **Protocol F**: b=`0,1000,2000`, 104 directions, 0.982×0.982×6.75 mm, n=2

## Gradient validation

`dwigradcheck` (MRtrix3) yielded PASS **250**, REVIEW **111**, FAIL **0**. REVIEW cases were classified as axis flip, axis swap, combined flip+swap, or other. Suggested orientation corrections were **not applied** to the distributed data.

## Geometry

Geometry differs across **6** protocols (voxel size / matrix / FOV / orientation summarised in `Geometry_QC.tsv`).

## Signal quality

Robust within-mask metrics (median b0 / diffusion signal, percentiles, coefficient of variation, background level, MAD-based b0 SNR and CNR) were computed for **216** scans with available brain masks. Distributions (not only means) are reported in `Signal_Report.md` and publication figures.

## Brain masks

Automated brain-mask metrics were available for **361/361** scans (median brain fraction 0.215).

## Motion

FSL eddy / eddy_quad motion summaries were **not available** in the audited derivatives tree for this release (see `Motion_QC.md`).

## Distortion pairs

Opposite phase-encoding EPI fieldmaps (AP/PA) were present for **120/120** sessions (see `PE_pairs.tsv`).

## Visual inspection

Representative multi-planar snapshots (b0, b≈1000, highest b-value; axial / coronal / sagittal with mask overlay) are stored under `visual_examples/` and summarised in `Visual_QC_Figure.png`.

## Summary

**Overall technical validation: PASS**

| QC item | Status |
| --- | --- |
| BIDS consistency | PASS |
| NIfTI integrity | PASS |
| b-values | PASS |
| b-vectors | PASS |
| JSON metadata | PASS |
| Gradient orientation | PASS* |
| Brain mask | PASS |
| Signal quality | PASS |
| Motion estimates | N.A. |
| Susceptibility pairs | PASS |
| Visual inspection | PASS |
| Overall technical validation | PASS |

## Output files

- `integrity_summary.tsv`, `Integrity_Report.md`
- `Protocol_Consistency.tsv`, `Acquisition_Consistency_Report.md`
- `Geometry_QC.tsv`, `Geometry_QC_Report.md`
- `Gradient_QC.tsv`, `Gradient_Report.md`
- `BrainMask_QC.tsv`, `BrainMask_Report.md`
- `Signal_QC.tsv`, `Signal_Report.md`
- `Motion_QC.md`, `PE_pairs.tsv`, `PE_pairs_Report.md`
- `TechnicalValidation_Table.tsv` / `.docx` / `.pdf`
- Publication figures (PNG/PDF/SVG) under `publication/`
