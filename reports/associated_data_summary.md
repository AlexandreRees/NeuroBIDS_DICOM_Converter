# Associated data summary

Generated: 2026-07-17T13:51:40.590839+00:00

Read-only audit of non-DICOM files under `raw_original/`.  
**No source files were modified.**

## Overview

| Item | Value |
|---|---|
| Files inventoried | 5756 |
| Total size | 19.260 GB (20679774102 bytes) |
| Subjects (inferred) | 84 |
| Subject–session pairs | 139 |
| Source root | `/lustre07/scratch/alexrees/raw_original` |

## Classification

- **eye_tracking**: 448
- **physiology**: 339
- **stimulus**: 3716
- **behavior**: 0
- **task_timing**: 1108
- **unknown**: 145

## Extensions

- `.mat`: 2885
- `.m`: 2428
- `.puls`: 114
- `.resp`: 114
- `.ecg`: 111
- `.mp4`: 104

## Subjects with most associated files

- SUBC012: 143
- SUBC031: 121
- SUBC041: 106
- SUBC006: 93
- SUBC005: 92
- SUBC009: 91
- SUBC007: 91
- SUBC011: 91
- SUBC008: 90
- SUBC003: 90
- SUBC001: 90
- SUBC050: 88
- SUBG016: 87
- SUBC017: 87
- SUBG003: 85

## Category definitions

| Category | Typical content |
|---|---|
| eye_tracking | Eyelink EDF/ASC, eye-tracking MATLAB results |
| physiology | RESP/PULS/ECG and related physio logs |
| stimulus | Movies, audio, presentation media, stimulus `.mat` |
| behavior | Behavioral logs, response tables, Results CSVs |
| task_timing | Onsets, events, triggers, timing logs |
| unknown | Matched extension without clear heuristic |

## Outputs

- `reports/associated_data_inventory.tsv`
- `reports/associated_data_summary.md`

Potential BIDS destinations in the inventory are **suggestions only**; this module does not copy or convert associated files.
