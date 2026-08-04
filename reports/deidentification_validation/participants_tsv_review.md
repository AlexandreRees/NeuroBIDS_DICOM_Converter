# participants.tsv review

**Date (UTC):** 2026-07-22  
**File:** `/home/alexrees/scratch/bids/participants.tsv`  
**Sidecar:** `/home/alexrees/scratch/bids/participants.json`

## Verdict

**PASS — suitable for public BIDS release** (minimal demographics only).

## Columns

| Column | Present | Notes |
| --- | --- | --- |
| `participant_id` | yes | Pseudonymized `sub-###` IDs only |
| `cohort` | yes | Study labels: Control, DataON, DataTON, Glaucoma |
| `sex` | yes | `F` / `M` only in this file; levels documented in `participants.json` |

No additional columns (no age, DOB, name, site ID, MRN, or free-text notes).

## Counts

- Rows: **84** (matches BIDS subject inventory)
- Sex: F=46, M=38
- Cohort: Control=56, Glaucoma=19, DataON=7, DataTON=2

## Privacy notes

- `sex` is retained as a low-risk demographic commonly shared in BIDS; it is not treated as a scrub target for this release.
- Cohort labels are study-design categories, not personal names.
- No empty or malformed `participant_id` values observed in the reviewed table.

## Action

None required for privacy. Optional: expand `participants.json` cohort level descriptions if desired for clarity (not a privacy blocker).
