# ses-02 retry11 — Defacing

**Job:** `66381003` (array 1–10)
**Tool:** pydeface via `neuro_pipeline.modules.defacing.run_defacing_session`
**Input:** `bids/` (read-only) · **Output:** `derivatives/defacing/`

## Per-session

| Subject | BIDS anat | Defaced | PASS | FAIL | Status |
|---|---:|---:|---:|---:|---|
| sub-057 | 6 | 6 | 6 | 0 | OK |
| sub-064 | 5 | 5 | 5 | 0 | OK |
| sub-066 | 6 | 6 | 6 | 0 | OK |
| sub-067 | 6 | 6 | 6 | 0 | OK |
| sub-068 | 6 | 6 | 6 | 0 | OK |
| sub-069 | 6 | 6 | 6 | 0 | OK |
| sub-072 | 6 | 6 | 6 | 0 | OK |
| sub-073 | 6 | 6 | 6 | 0 | OK |
| sub-074 | 6 | 6 | 6 | 0 | OK |
| sub-078 | 0 | 0 | 0 | 0 | N/A (no anat) |
| sub-081 | 9 | 9 | 9 | 0 | OK |

## Notes

- `sub-078/ses-02` has no `anat/` in BIDS (PASS conversion without anatomicals) — nothing to deface.
- Global BIDS T1w/FLAIR/TB1TFL vs defaced: **788/791** present.
- Master task list updated: `metadata/defacing_array_tasks.tsv` now 132 rows.
