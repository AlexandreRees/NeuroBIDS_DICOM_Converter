# Publication audit — Grating (`task-fmri`) & Resting-state (`task-rest`)

**Updated:** 2026-07-29 (post-sync)  
**Status:** Release package prepared for publication documentation.

## Actions completed

1. Synced **58** grating event sets (`events.tsv` + `events.json` where present) and **2** missing magnitude BOLD families from `bids/` → `release_dataset/` (`code/sync_grating_rest_for_publication.py`).
2. Restored parity: **553 / 553** mag `task-fmri` BOLD; **514 / 514** events (bids = release).
3. Wrote machine-readable coverage tables under `release_dataset/docs/Protocols/` (mirrored here).
4. Updated `release_dataset/README.md`, `CHANGES`, `docs/Protocols/{Grating,Rest,README}.md`, and `code/task-*/` notes.

## Current release headline counts

| Metric | Value |
| --- | ---: |
| Grating mag BOLD | 553 |
| Grating events | 514 (92.9%) |
| Grating without events | 39 |
| Rest mag BOLD | 135 |
| Rest events | 0 (by design) |
| Rest physio (any) | 82.2% |
| Dual rest sessions | 3 |
| Incomplete subjects | sub-055 (no rest), sub-063 (no grating) |

## Remaining documented limitations (not blockers if disclosed)

- **39** grating runs without recoverable events (see `grating_events_exclusions.tsv`)
- Physio not universal; trigger channel not for TR jitter
- Extra redo grating runs in some sessions; dual rest → use primary
- Further MATLAB remapping of ambiguous twins is optional / manual (`physiology`/`grating` mapping recovery audits)

## Tables

See `docs/Protocols/` in the release package, or copies in this folder.
