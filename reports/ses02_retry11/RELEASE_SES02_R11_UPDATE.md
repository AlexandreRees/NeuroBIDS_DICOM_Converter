# ses-02 retry11 — release_dataset incremental update

**Generated (UTC):** 2026-07-27T15:30:11Z
**Mode:** APPLY
**Targets:** 11
**Plan READY / SKIP / BLOCK+FAIL:** 11 / 0 / 0

## Policy

- Source: `bids/<sub>/ses-02` (read-only)
- Defaced anatomicals: `derivatives/defacing/` for T1w / T2w / FLAIR
- TB1TFL kept from BIDS (same as existing release_dataset)
- `bids/`, `derivatives/`, `raw_original/` never modified

## Per-session plan

| Subject | Status | bids files | structural | defaced ready | missing | notes |
|---|---|---:|---:|---:|---:|---|
| sub-057 | READY | 140 | 4 | 4 | 0 |  |
| sub-064 | READY | 138 | 3 | 3 | 0 |  |
| sub-066 | READY | 140 | 4 | 4 | 0 |  |
| sub-067 | READY | 140 | 4 | 4 | 0 |  |
| sub-068 | READY | 140 | 4 | 4 | 0 |  |
| sub-069 | READY | 140 | 4 | 4 | 0 |  |
| sub-072 | READY | 140 | 4 | 4 | 0 |  |
| sub-073 | READY | 140 | 4 | 4 | 0 |  |
| sub-074 | READY | 132 | 4 | 4 | 0 |  |
| sub-078 | READY | 54 | 0 | 0 | 0 | no anat (sparse session); copy non-structural only |
| sub-081 | READY | 90 | 5 | 5 | 0 |  |

## Apply results

| Subject | Status | notes |
|---|---|---|
| sub-057 | APPLIED | copied session; replaced 4 anatomicals |
| sub-064 | APPLIED | copied session; replaced 3 anatomicals |
| sub-066 | APPLIED | copied session; replaced 4 anatomicals |
| sub-067 | APPLIED | copied session; replaced 4 anatomicals |
| sub-068 | APPLIED | copied session; replaced 4 anatomicals |
| sub-069 | APPLIED | copied session; replaced 4 anatomicals |
| sub-072 | APPLIED | copied session; replaced 4 anatomicals |
| sub-073 | APPLIED | copied session; replaced 4 anatomicals |
| sub-074 | APPLIED | copied session; replaced 4 anatomicals |
| sub-078 | APPLIED | copied session; replaced 0 anatomicals |
| sub-081 | APPLIED | copied session; replaced 5 anatomicals |

## Verification (11/11 PASS)

| Subject | exists | n_files | n_struct | verify | notes |
|---|---|---:|---:|---|---|
| sub-057 | True | 140 | 4 | PASS |  |
| sub-064 | True | 138 | 3 | PASS |  |
| sub-066 | True | 140 | 4 | PASS |  |
| sub-067 | True | 140 | 4 | PASS |  |
| sub-068 | True | 140 | 4 | PASS |  |
| sub-069 | True | 140 | 4 | PASS |  |
| sub-072 | True | 140 | 4 | PASS |  |
| sub-073 | True | 140 | 4 | PASS |  |
| sub-074 | True | 132 | 4 | PASS |  |
| sub-078 | True | 54 | 0 | PASS |  |
| sub-081 | True | 90 | 5 | PASS |  |
