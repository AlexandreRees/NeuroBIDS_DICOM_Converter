# Anatomical defacing validation (READ-ONLY)

**Generated (UTC):** 2026-07-22T19:57:42.263134+00:00
**BIDS:** `/lustre07/scratch/alexrees/bids`
**Defaced derivatives:** `/lustre07/scratch/alexrees/derivatives/defacing`
**Dry-run:** False

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

- Pairs with % changed voxels computed: **356**
- Median % voxels changed: **24.082**
- Mean % voxels changed: **24.026**
- Range: **9.641–37.862**
- Method: material intensity change `|Δ| > 0.5` (validated full-cohort table
  `reports/defacing_audit/defacing_image_comparison.tsv`). An initial exact `!=`
  comparison was discarded because many defaced NIfTI are stored as float64 while
  originals are int16, inflating apparent change toward ~99%.

## Metadata

- Derivative JSON invalid: **0**
- Sidecars with GeneratedBy: **0**
- dataset_description GeneratedBy present: **True**
- Sidecars with ≥1 PHI-like field (at audit time): **352** (`InstitutionalDepartmentName`)

**Follow-up (2026-07-22):** Re-scan of all **726** JSON under `derivatives/defacing/` found **`InstitutionalDepartmentName` = 0**. Derivative sidecars are scrubbed for public release.

Note: `GeneratedBy` for this cohort is recorded at `derivatives/defacing/dataset_description.json` (pydeface via `neuro_pipeline.modules.defacing.run_defacing_session`). Per-sidecar GeneratedBy may be absent.

## Status counts (original audit run)

- `OK_PHI_METADATA`: 352 *(resolved by subsequent scrub — see follow-up above)*
- `OK`: 4

## Verdict

**PASS** *(after derivative JSON scrub confirmation)*

No fixed voxel-change threshold is applied. Coverage completeness and geometry preservation are the primary release gates. `InstitutionalDepartmentName` is confirmed absent from derivative JSON.

TSV: `defacing_validation.tsv`

