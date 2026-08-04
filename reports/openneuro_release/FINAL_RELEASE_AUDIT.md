# Final OpenNeuro release audit

Generated: 2026-07-22 20:50:42 UTC
Mode: **DRY_RUN**

## Verdict: **WARNING**

## Counts

- Subjects (BIDS source): **84**
- Sessions (subject×session): **124**
- T1w expected: **356**
- Defaced T1w available: **356**
- T1w replacements applied/planned: **356**
- Missing defaced T1w: **0**
- JSON files cleaned (InstitutionalDepartmentName removals): **0**
- JSON scan actions logged: **0**
- Release directory: `/lustre07/scratch/alexrees/release_dataset`
- Source BIDS (untouched): `/lustre07/scratch/alexrees/bids`

- Duplicate README resolved: **True**
- Participants validation: **PASS**

## Failures

- None

## Warnings

- Authors contained 'Neuro BIDS Pipeline'; replaced with ['AUTHOR_PLACEHOLDER'] — MANUAL REPLACEMENT REQUIRED before upload.
- dataset_description changes: ["License: None -> 'CC0'", "Authors placeholder -> ['AUTHOR_PLACEHOLDER']"]

## PASS criteria

- defacing complete for all T1w
- JSON valid after cleaning
- no duplicate README
- participants columns clean

