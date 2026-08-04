# Events validation report

**Generated:** 2026-07-23T20:22:57Z  
**Scope:** All `task-fmri` `*_events.tsv` under `bids/` (read-only).  
**BIDS imaging / events files were not modified.**

## Overall outcome: **PASS**

| Metric | Count |
|---|---:|
| Events files validated | 452 |
| PASS | 452 |
| WARNING | 0 |
| FAIL | 0 |

## Checks performed

For each events file:

1. Corresponding `*_bold.nii.gz` exists  
2. Corresponding `*_bold.json` exists  
3. Required columns: `onset`, `duration`, `trial_type`  
4. No duplicated rows  
5. No missing values  
6. All onsets ≥ 0  
7. All durations > 0  
8. Rows sorted by onset  
9. Last event ends within acquisition duration (`RepetitionTime × n_volumes`)  
10. No overlapping events (edge-touching blocks allowed)  
11. All `trial_type` labels are documented (`baseline`, `stim-01`…`stim-12`)

## Error tallies

| Error code | Count |
|---|---:|
| (none) | 0 |

## Warning tallies

| Warning code | Count |
|---|---:|
| (none) | 0 |

## Detail table

See `events_validation.tsv`.
