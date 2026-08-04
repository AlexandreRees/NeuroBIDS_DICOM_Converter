# Excluded PhysioLog reasons (updated)

**Updated:** `2026-07-27T21:50Z`

Rebuilt from `FINAL_PHYSIO_CONVERSION_DECISION.tsv` (unique UIDs with `FINAL_DECISION != READY_FOR_BIDS_CONVERSION`), joined to `physio_conversion_status.tsv` for failure detail.

## Counts

| exclusion_class | N |
|---|---:|
| `EXT_ONLY_NO_STARTTIME` | 206 |
| `MAPPING_AMBIGUOUS` | 48 |
| `NO_SAMPLETIME_AND_NO_STARTTIME` | 38 |
| `NO_STARTTIME_WITH_PHYSIO_CHANNELS` | 13 |

**Total excluded unique PhysioLog UIDs:** 305

## Resolution notes

| exclusion_class | Status | Note |
|---|---|---|
| `NO_SAMPLETIME_AND_NO_STARTTIME` | **CLOSED 2026-07-29 — DEFINITIVE EXCLUSION** | Raw `raw_original` search: no recoverable alternate PhysioLog for sub-007/008/009 ses-01; sub-042 has session-wide `.puls`/`.resp` but no site-confirmed ADC SF. Not convertible to BIDS run-wise. See `manual_review_and_losses/RESOLUTION_NO_SAMPLETIME_AND_NO_STARTTIME.md`. |

## Resolved / removed from this table

`MAPPING_NOT_UNIQUE_LIKELY` (sub-024 / sub-047) was **removed**: those series UIDs are `READY_FOR_BIDS_CONVERSION` in the final decision and were converted to BIDS `*_physio` sidecars. The earlier FAILED/`runmap=LIKELY` labels in `physio_conversion_status.tsv` are stale relative to the final readiness audit.

## Files

- `EXCLUDED_physio_reasons.tsv` (canonical)
- `EXCLUDED_324_physio_reasons.tsv` (same content; filename kept for back-compat; count is no longer 324)
