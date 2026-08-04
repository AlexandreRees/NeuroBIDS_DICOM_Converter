# Why 118 `sources_uncertain_or_absent`?

**Date:** 2026-07-23  
**Input:** `reports/stimulus_audit/` (esp. `_audit_summary.json` counts) + Level-1 `withheld_events_summary.tsv`

## Short answer

The 118 are **not** mostly “MATLAB timing missing”. They are **BIDS `task-fmri` runs whose `(participant, session)` was never in the Level-1 events dry-run**. The stimulus audit labeled any such run `sources_uncertain_or_absent`.

## How the original label was assigned

For each of 507 non-phase `task-fmri` BOLD runs:

1. events present → `already_released`
2. else if Level-1 withheld rows exist for that session → `reconstructable…` or `ambiguous`
3. else → **`sources_uncertain_or_absent`**

So “uncertain” = **outside Level-1 plan coverage**, not a content audit of `scan_info` / `Stim_order`.

## Who are the 118?

| | N |
|---|---:|
| Uncertain BOLD runs | **118** |
| Distinct sessions | **29** |
| Glaucoma sessions | 19 |
| DataON sessions | 6 |
| DataTON sessions | 2 |
| Control sessions | 2 (`sub-004/ses-02`, `sub-051/ses-01`) |

Level-1 withheld subjects were only **sub-001…056** (55 subjects; **sub-051 absent**). Glaucoma / ON / TON were never in that events plan.

## Re-check of MATLAB sources for those 29 sessions

| Status | Sessions | Runs | Meaning |
|---|---:|---:|---|
| `HAS_SOURCES` | 25 | **102** | `scan_info` + stim-order present (same recipe as recoverable Level-1 cases) |
| `HAS_SOURCES_SESSION_LABEL_MISMATCH` | 3 | **12** | Sources exist but under `Session2` path labels inside the visit folder (`sub-076`, `sub-078`, `sub-084`) |
| `TRUE_MISSING_GRATING_RESULTS` | 1 | **4** | `sub-051` / SUBC52: visit folder on disk, **no** `2-Grating/Results` |

## Implication

- **~114/118** should be treated like Level-1 **recoverable** (extend `convert_events` / mapping to non-Control + missing sessions), not as permanently lost.
- **4/118** (`sub-051`) look like a true gap until grating Results are found elsewhere.
- Note: `fmri_events_reconstruction.tsv` had been emptied (0 bytes); it was regenerated during this follow-up. Live BIDS now has far more than 51 events files; the **118** count is still the set of sessions never covered by the Level-1 withheld table.

## Deliverables

- `uncertain_118_session_breakdown.tsv` — per-session detail  
- `uncertain_118_summary.json` — machine-readable summary  
- this file
