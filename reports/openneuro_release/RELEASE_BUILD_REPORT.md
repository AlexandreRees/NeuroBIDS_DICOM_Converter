# Public BIDS release build report

**Generated (UTC):** 2026-07-23T23:50:18Z
**Mode:** `APPLY`

## Paths

- Source BIDS (never modified): `/lustre07/scratch/alexrees/bids`
- Defacing derivatives (never modified): `/lustre07/scratch/alexrees/derivatives/defacing`
- Release output: `/lustre07/scratch/alexrees/release_dataset`

## Dataset summary

| Metric | Value |
|---|---:|
| Subjects | 84 |
| Sessions | 124 |
| Files planned to copy | 16620 |
| Original anatomicals excluded | 481 |
| Anatomical replacements ready/applied | 481 |
| Anatomical replacements missing/failed | 0 |
| Release dataset size | 1000.54 GB |
| Functional BOLD NIfTI | 2992 |
| Functional events.tsv | 456 |
| DWI NIfTI | 361 |
| Fieldmap NIfTI | 982 |
| Anat T1w (source inventory) | 356 |
| Anat T2w (source inventory) | 0 |
| Anat FLAIR (source inventory) | 125 |

## Anatomical replacement status

| Status | N |
|---|---:|
| `REPLACED` | 481 |

## Validation

| Check | Result |
|---|---|
| No failed anatomical replacements | PASS |
| NIfTI/JSON pairs for anatomicals | PASS |
| JSON validity | PASS |
| participants.tsv | PASS |
| BIDS validator | NOT_AVAILABLE |

### Failures

- None

### Warnings

- bids-validator not found on PATH; structural/manual checks only

## Safety

- `bids/` was not modified.
- `derivatives/` was not modified.
- `raw_original/` was not modified.

## Deliverables

| File | Description |
|---|---|
| `ANATOMICAL_REPLACEMENT_AUDIT.tsv` | Per-anatomical original → defaced mapping |
| `FILE_COPY_MANIFEST.tsv` | Copy / exclude plan |
| `RELEASE_BUILD_REPORT.md` | This report |

