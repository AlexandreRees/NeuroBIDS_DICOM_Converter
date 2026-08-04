# Movie timing forensic audit

Generated: `2026-07-29T19:26:36Z`

**Scope:** READ-ONLY identification of every possible timing source for `task-movie` `events.tsv`.

**Non-actions:** no `events.tsv` written; `raw_original/`, `bids/`, `derivatives/` untouched.

## Executive answers

| Question | Answer |
|---|---|
| Were movie onsets directly recorded? | **YES** |
| Were trigger times found in MATLAB `.mat`? | **YES** |
| Were Psychtoolbox Flip/VBL timestamps saved? | **NO** |
| Were scanner logs with stimulus onset found? | **NO** |
| Could movie events theoretically be reconstructed? | **YES** |

## Why not (if applicable)

Potential reconstructible sources were flagged — see tables for paths.

## Summary counts

- FILE_INVENTORY entries: 17110
- MATLAB variable rows: 24678
- MATLAB code timing hits: 16853
- Movie BOLD runs in matrix: 536
- Matrix confidence: {'HIGH': 349, 'NONE': 187}
- Physiology rows: 2602 (stimulus-onset sync YES=0, bold-sync YES=0)
- DICOM series sampled: 16 (stimulus recoverable YES=0)
- Psychtoolbox saves timing: False

## Archived and historical source search

- Potential archive/keyword hits: **23884**
- Flagged files inside compressed archives: **109**
- Version comparison pairs (movie-related `.m`): **181470**
- Pairs with different hash (possible different version): **142090**

### Archive conclusion

**A) Reliable timing source found**

- Additional historical / backup-named files were searched under raw, bids, and derivatives.
- Timing variables in archived MAT content: **found**.
- Older script versions: compared by SHA256 where similar basenames exist; movie protocol scripts are typically identical across sessions.
- Archived materials **do** change the feasibility of reconstructing movie events.

## Artifacts

- `FILE_INVENTORY.tsv`
- `MATLAB_VARIABLE_AUDIT.tsv`
- `MATLAB_CODE_TIMING_AUDIT.tsv`
- `PSYCHTOOLBOX_LOG_AUDIT.md`
- `SCANNER_METADATA.tsv`
- `PHYSIOLOGY_TIMING_AUDIT.tsv`
- `DICOM_TIMING_AUDIT.tsv`
- `HIDDEN_TIMING_FILES.tsv`
- `MOVIE_TIMING_MATRIX.tsv`
- `POTENTIAL_ARCHIVES.tsv`
- `ARCHIVE_CONTENT_AUDIT.tsv`
- `VERSION_COMPARISON.tsv`
- `summary.json`
- `validation.json`
