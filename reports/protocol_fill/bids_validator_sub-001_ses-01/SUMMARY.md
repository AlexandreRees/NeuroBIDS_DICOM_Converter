# BIDS validator — sub-001 / ses-01 (protocol fill check)

- Tool: `bids-validator@1.14.6` (npx), mini-dataset hardlinked from full BIDS
- Date: 2026-07-27
- Files validated: 163

## Errors (2 types)

1. **NOT_INCLUDED (code 1)** — 6 files  
   All `anat/*_localizer_i0000{1,2,3}.{nii.gz,json}`  
   Cause: `localizer` is **not** a standard BIDS anat suffix. Expected if we keep scouts in the raw tree.

2. **VOLUME_COUNT_MISMATCH (code 29)** — 1 file  
   `dwi/sub-001_ses-01_run-07_dwi.nii.gz` (3D 160×160×32, bval/bvec length 1)  
   Pre-existing / unrelated to Localizer·gsld_75·resolve_PA additions.

## Warnings

- EVENTS_TSV_MISSING (func tasks) — pre-existing
- INCONSISTENT_PARAMETERS — includes new short DWI (gsld_75 run-03/04, resolve_PA run-11) vs long gsld_76; expected different geometry
- TOO_FEW_AUTHORS — dataset_description

## Protocol-fill additions

| Addition | Validator status |
|---|---|
| Localizer (`*_localizer_i#####`) | **Error** NOT_INCLUDED (nonstandard suffix) |
| gsld_75TE_PA_3b0 as `*_dwi` | OK (naming); warning INCONSISTENT_PARAMETERS only |
| resolve_*_PA as `*_dwi` | OK (naming); warning INCONSISTENT_PARAMETERS only |

To silence Localizer in the official validator without removing files, add to `.bidsignore`:
```
*_localizer*
*_localizer_*.*
```

**Done (2026-07-27):** `*_localizer*` added to `bids/.bidsignore` (and mirrored in `release_dataset/.bidsignore`). Scouts remain on disk; validator should ignore them.
