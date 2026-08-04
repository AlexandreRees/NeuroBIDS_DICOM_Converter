# Diffusion MRI technical validation

Generated: 2026-07-24 17:28:46 UTC

## Dataset

- Number of subjects: **82**
- Number of sessions (subject×session): **130**
- Number of DWI scans: **399**

## Integrity

- Missing gradients / sidecars: **0** (see `dwi_inventory.tsv`)
- Volume / bval / bvec mismatches: **37** (see `dwi_gradient_consistency.tsv`)

## Diffusion scheme

### b-values distribution

- `0,1000,2000`: 241 scans
- `0,1000`: 121 scans
- `nan`: 37 scans

### Directions distribution

- 1 directions (9 scans); 7 directions (2 scans); 11 directions (131 scans); 104 directions (2 scans); 144 directions (2 scans); 239 directions (2 scans); 270 directions (2 scans); 287 directions (2 scans); 365 directions (247 scans)

## Gradient QC

- `dwigradcheck` PASS: **250**
- `dwigradcheck` REVIEW (suggested correction reported, not applied): **112**
- `dwigradcheck` FAIL: **0**

No gradient corrections were applied to the distributed dataset.

## Image quality

### Mask coverage

- Scans with automated masks: **362** / 399
- Mean brain fraction: **0.3117**
- Median brain fraction: **0.2157**

### Signal metrics (within mask)

- Mean overall signal (cohort mean): **257.27**
- Mean b0 signal (cohort mean): **605.43**
- Mean diffusion signal (cohort mean): **208.99**

Visual snapshots (central axial b0 and diffusion slices) are stored in `figures/`.

## Conclusion

Diffusion MRI data were technically validated through BIDS consistency checks, diffusion gradient verification, b-value assessment and automated signal quality metrics. No modifications were applied to the distributed dataset.

## Output files

- `dwi_inventory.tsv`
- `dwi_gradient_consistency.tsv`
- `dwi_bvalue_summary.tsv`
- `dwigradcheck_results.tsv`
- `dwi_mask_metrics.tsv`
- `dwi_signal_metrics.tsv`
- `figures/`
- `tmp/` (temporary masks; not part of the BIDS release)
