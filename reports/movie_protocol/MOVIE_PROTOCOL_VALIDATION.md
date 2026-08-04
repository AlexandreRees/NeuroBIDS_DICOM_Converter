# Movie protocol validation

**Generated:** `2026-07-28T13:38:16.807617+00:00`

| Metric | N |
|---|---:|
| BIDS `task-movie` magnitude BOLD | 536 |
| MATLAB `selected_run_id*.mat` logs found | 531 |
| Unique ProtocolName→run assignments written | 520 |
| Manual review rows | 8 |
| Sessions with ≥1 movie BOLD | 134 |
| Sessions with ≥1 assignment | 132 |
| Assignment coverage (assigned / BOLD) | 97.0% |

## Ambiguities / missing

See `MANUAL_REVIEW_REQUIRED.tsv` for per-session reasons (`AMBIGUOUS_PROTOCOL_MATCH`, `MISSING_MOVIE_INDEX_IN_PROTOCOL`, …).

## Duplicates

Script inventory duplicate counts are in `MATLAB_PROTOCOL_INVENTORY.tsv` (`duplicate_hash`).
