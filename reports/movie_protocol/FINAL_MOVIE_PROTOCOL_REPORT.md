# Final Movie protocol documentation report

**Generated:** `2026-07-28T13:38:18+00:00`  
**Reproducible builder:** `code/audit_movie_protocol.py`

## Counts

| Item | N |
|---|---:|
| Total `.m` scripts under `**/3-Movie_Data/` | 312 |
| Unique SHA256 versions | 8 |
| Scripts copied to `code/task-movie/` (sanitized) | 2 (`main.m`, `Show_movie.m`) |
| PHI findings in raw archive (all severities) | 1446 |
| PHI HIGH findings in raw archive | 645 |
| Run dictionary rows | 4 |
| Unique HIGH-confidence run assignments | 520 |
| Manual review rows (ambiguous ProtocolName) | 8 |
| Movie BOLD magnitude | 536 |
| Assignment coverage | 520/536 (97.0%) |

## Audit PHI

Raw scripts contain **HIGH** absolute Windows user/stimulus paths (`C:\Users\…`).  
Public copies under `code/task-movie/` are **sanitized** (absolute paths → relative MP4 basenames / `output.txt`). Raw `raw_original/` was not modified. Sanitized copies contain **no** `Users\` / `Desktop\` / drive-letter paths.

## Run dictionary / assignments

- `code/task-movie/task-movie_run_dictionary.tsv` — clip/eye from `main.m`; volumes=210 & TR=0.937 s from BIDS Movie BOLD (not logged by MATLAB).
- `code/task-movie/task-movie_run_assignments.tsv` — only unique `ProtocolName MovieN_*` → `matlab_run_id N` within a session.
- Ambiguous duplicates (e.g. two `Movie4` series in one session) are listed in `MANUAL_REVIEW_REQUIRED.tsv` and **not** forced into assignments.

## Deliverables

| Path | Role |
|---|---|
| `reports/movie_protocol/MATLAB_PROTOCOL_INVENTORY.tsv` | Script inventory + hashes |
| `reports/movie_protocol/MATLAB_PHI_AUDIT.tsv` | PHI scan of raw scripts |
| `reports/movie_protocol/MOVIE_PROTOCOL_SUMMARY.md` | Protocol narrative |
| `reports/movie_protocol/MOVIE_PROTOCOL_VALIDATION.md` | Coverage metrics |
| `reports/movie_protocol/CODE_COPY_VALIDATION.tsv` | Source/dest SHA256 |
| `reports/movie_protocol/MANUAL_REVIEW_REQUIRED.tsv` | Ambiguous sessions |
| `code/task-movie/` | Sanitized code + README + dictionaries |

## Constraints respected

- No `events.tsv` created  
- No MP4 copied  
- No edits to `bids/`, `release_dataset/`, `raw_original/`, `derivatives/`  
- No invented timing  

## Recommendation

### OPTION A — PASS

Movie protocol documentation is suitable for inclusion in the public OpenNeuro / Scientific Data release.

**Rationale:** Protocol behavior and run↔clip↔eye mapping are documented without inventing `events.tsv`. Videos are not redistributed. Sanitized MATLAB entry points are provided under `code/task-movie/`. Remaining unmapped BOLD runs are listed for manual review rather than forced association.
