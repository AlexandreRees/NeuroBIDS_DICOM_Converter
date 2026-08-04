# Resting-state events assessment

Generated: `2026-07-27T21:27:02.279994+00:00`

## Conclusion

**No `*_task-rest_*_events.tsv` should be created** for this dataset from MATLAB sources.

## Why

- Task-rest is fixation-only (no stimulus blocks).
- Folder `4-resting state` typically contains only `main.m` (FORP wait for trigger `t`).
- Inventory found **0** rest-related `.mat` files under resting folders; **0** with triggerTimes.
- BIDS does not require events for resting-state; inventing empty or dummy events would violate the no-invented-timing policy.

## Recommendation

- Omit rest events.tsv from the BIDS release.
- If a validator warns `EVENTS_TSV_MISSING` for `task-rest`, treat as acceptable / ignore for rest.
