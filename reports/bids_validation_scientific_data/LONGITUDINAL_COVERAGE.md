# Incomplete longitudinal coverage

- Generated (UTC): `2026-07-21T20:10:25.381687+00:00`
- Subjects in `bids/`: **84**
- Both `ses-01` and `ses-02`: **40**
- `ses-01` only: **43**
- `ses-02` only: **1**
- Neither: **0**

## Interpretation

This study is longitudinal (`ses-01`, `ses-02`), but **not every participant completed both sessions**. Missing sessions are real absences (not conversion failures to invent). BIDS validator warnings `MISSING_SESSION` and `INCONSISTENT_SUBJECTS` are therefore expected for this release.

Do **not** fabricate empty session folders or placeholder scans for missing visits.

## Machine-readable table

See `longitudinal_session_coverage.tsv` in this directory.
