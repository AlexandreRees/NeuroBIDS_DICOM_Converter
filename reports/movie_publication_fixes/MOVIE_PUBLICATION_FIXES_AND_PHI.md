# Movie publication fixes + PHI check

**Date (UTC):** 2026-07-29

## Fixes applied

| Item | Status |
| --- | --- |
| `bids/README.md` + `release_dataset/README.md` movie events docs | Updated |
| Stub `bids/README` removed (`MULTIPLE_README_FILES`) | Done (backup under this folder) |
| `task-movie.json` in bids + release | Synced |
| `code/task-movie/` → bids + release | Synced (incl. medium-confidence TSV) |
| License CC0 + `LICENSE` file | Set (both trees) |
| Table2 movie eye assignment (md/tex) | Corrected ProtocolName mapping |
| Manuscript / SD drafts movie wording | Updated |
| Authors real names | **NOT set** (unknown; placeholder remains) |
| Defaced anat upload tree | **NOT rebuilt** (still required for OpenNeuro) |

## PHI / identity scan (public movie artifacts)

Scanned: `code/task-movie` (bids+release), dataset `task-movie*.json`, 100 random movie `events.json`, 80 random mag `bold.json`, assignments TSV.

| Pattern | Hits |
| --- | ---: |


### Critical identity findings

**0 critical hits** (patterns: email/phone/Patient* keys/Windows user paths/raw_original paths/bold identity fields).

None found in scanned public movie artifacts.

### Notes

- Published `main.m` still contains an **operator initials dialog** (protocol documentation only). No Results `.mat` with initials are in the public trees.
- `PatientPosition` / `ManufacturersModelName` / `ProtocolName` are acquisition metadata, not subject identifiers.
- `participants.tsv` columns are `participant_id`, `cohort`, `sex` only (no names/DOB/MRN).

## Remaining human gates

1. Replace placeholder `Authors` in `dataset_description.json`.
2. Build OpenNeuro upload tree with **defaced** anatomicals.
3. Optional: regenerate Table2 PDF/PNG from updated `.tex`.

## Follow-up (subagent audit) — truncated runs

[Audit movie fMRI publication](7fcd7aa4-6d19-4955-94d6-98084e448bd3) flagged 7 magnitude runs with `duration` > scan length.

**Fix:** `duration = min(MP4, n_volumes×TR)` in bids/ and release_dataset/; sidecars set `duration_capped_to_scan=true`.

Table: `movie_truncated_runs_duration_cap.tsv` and `code/task-movie/task-movie_truncated_runs.tsv`.
Generator updated to apply the same cap when NIfTI volumes are read.
