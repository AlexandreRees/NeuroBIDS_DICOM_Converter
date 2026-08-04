# BIDS events integration

Generated: `2026-07-27T21:55:08.635510+00:00`

## Policy (safe only)

- Integrate **HIGH** confidence `task-fmri` events with unique BIDS run mapping and existing magnitude BOLD.
- **Do not** integrate movie events (no measured timing).
- **Do not** integrate resting-state events (not required).
- **Do not** integrate `desc-matlabFMRI*` collision files (ambiguous ProtocolName→run).
- Leave pre-existing BIDS events that are not in the safe set untouched.

## Actions

| Action | n |
|--------|--:|
| create | 39 |
| overwrite | 323 |
| unchanged (already identical) | 85 |
| SKIP_no_bold | 7 |
| SKIP_run_mapping_collision | 16 |

- Safe set present in BIDS after sync: **447**
- Log: `bids_events_integration_log.tsv`
