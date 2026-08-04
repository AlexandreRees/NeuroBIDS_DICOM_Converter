# Anatomical defacing validation (READ-ONLY)

**Generated (UTC):** 2026-07-22T19:12:44.571230+00:00
**BIDS:** `/lustre07/scratch/alexrees/bids`
**Defaced derivatives:** `/lustre07/scratch/alexrees/derivatives/defacing`
**Dry-run:** True

## Coverage

- Expected T1w (BIDS anat): **356**
- Defaced T1w found: **356**
- Matched pairs: **356**
- Missing: **0**
- Unexpected: **0**
- Entity/filename consistency issues: **0**

## Spatial integrity

- Geometry mismatches / load errors: **0**

## Voxel modification (report only; no pass/fail threshold)

- Pairs with % changed voxels computed: **12**
- Median % voxels changed: **99.284**
- Mean % voxels changed: **97.953**

## Metadata

- Derivative JSON invalid: **0**
- Sidecars with GeneratedBy: **0**
- dataset_description GeneratedBy present: **True**
- Sidecars with ≥1 PHI-like field: **12**

Note: `GeneratedBy` for this cohort is recorded at `derivatives/defacing/dataset_description.json` (pydeface via `neuro_pipeline.modules.defacing.run_defacing_session`). Per-sidecar GeneratedBy may be absent.

## Status counts

- `COVERAGE_ONLY`: 344
- `OK_PHI_METADATA`: 12

## Verdict

**PASS_WITH_METADATA_REVIEW**

No fixed voxel-change threshold is applied. Coverage completeness and geometry preservation are the primary release gates; residual `InstitutionalDepartmentName` (or similar) in derivative JSON is flagged for metadata scrub before packaging if those JSON files are distributed.

TSV: `defacing_validation_dryrun.tsv`

