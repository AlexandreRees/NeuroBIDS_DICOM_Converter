# Defacing audit summary

Generated: 2026-07-22 19:22:36 UTC
Mode: **FULL**

## Paths (read-only)

- BIDS root: `/lustre07/scratch/alexrees/bids`
- Defacing derivatives: `/lustre07/scratch/alexrees/derivatives/defacing`
- Report output: `/lustre07/scratch/alexrees/reports/defacing_audit`

## Executive verdict

**WARNING**

- PHI-like keys in derivative JSON (352)

### Can the defaced anatomical derivatives be included in a Scientific Data public release?

**YES, with documented caveats**

Verdict rules:

- **PASS**: coverage complete, metadata clean, spatial integrity preserved
- **WARNING**: missing provenance, missing subjects, or metadata differences
- **FAIL**: missing defaced images, corrupted files, or geometry mismatch

## 1. Coverage

- Subjects with T1w: **83**
- Sessions with T1w: **122**
- T1w images expected: **356**
- Defaced T1w found: **356**
- PASS pairs: **356**
- Missing: **0**
- Duplicates: **0**
- Unexpected: **0**

## 2. Derivatives structure

- `dataset_description.json` exists: **True**
- Has Name / BIDSVersion / GeneratedBy: **True** / **True** / **True**
- Structure violations: **0**

## 3. Spatial integrity

- Paired images QC'd: **356** / **356**
- Flag counts: `{}`

## 4. Image difference (quantitative only)

- Median changed voxel %: **24.082**
- Mean changed voxel %: **24.026**
- Median max |Δ|: **4095.00**

## 5. Derivative metadata

- Derivative JSONs checked: **356**
- Total PHI-like key detections: **352**
- Acquisition-parameter preservation failures: **0**

## 6. Provenance

- Software: `neuro_pipeline.modules.defacing.run_defacing_session`
- Version: `None`
- Command/description: `pydeface on T1w+FLAIR and face/head-FOV TB1TFL; original BIDS never modified.`
- Date: `None`
- provenance_missing: **False**

## Safety

- This audit is **read-only**.
- No BIDS or derivative files were modified, overwritten, or deleted.
- No new images were written inside BIDS.
- Outputs written only under `reports/defacing_audit/`.

## Output files

- `defacing_subject_inventory.tsv`
- `defacing_missing_subjects.tsv`
- `defacing_image_comparison.tsv`
- `defacing_qc_metrics.tsv`
- `figures/defacing_coverage.png`
- `figures/before_after_examples.png` (if pairs available)
- `figures/voxel_difference_summary.png`
