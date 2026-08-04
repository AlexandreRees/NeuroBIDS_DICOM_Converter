# Movie events.tsv feasibility — final report

**Generated:** `2026-07-28T14:40:01.813631+00:00`  
**Decision:** **NOT FEASIBLE** (`RECONSTRUCTABLE = NO`)

## Criteria (all required for YES)

| Criterion | Status |
|---|---|
| Scanner trigger **data** recovered (`triggerTimes` or equivalent saved) | FAIL |
| Stimulus timestamp **data** recovered (VBL / frame / onset arrays) | FAIL |
| Temporal relationship preserved on disk | FAIL |

## Code behavior vs saved data

| Capability | In `Show_movie.m` code | Persisted to `.mat` / logs |
|---|---|---|
| Wait for scanner key `t` | FOUND | NO (`triggerTimes` absent) |
| `Screen('Flip')` timestamps | NOT FOUND | NO |
| Frame timestamps | NOT FOUND | NO |
| Explicit timing `save(...)` | NOT FOUND | NO |

## Source matrix

| Source | Available | Usable for scanner-locked events.tsv |
|---|---|---|
| MATLAB `.m` | Yes (protocol logic) | No — describes wait/`Flip` but does not record times |
| MATLAB `Results/*.mat` | Yes | No — identity only (`run_id`, …); `SCANNER_LOCKED_TIMING` rows = 0; `FRAME_TIMING` rows = 0 |
| `output.txt` | Yes | No — `REAL_TIMING` lines = 0; remainder PTB warnings / debug |
| MP4 | Sometimes present | No — media only, not onset logs |
| PhysioLog / BIDS physio | Partial | No alone — EXT/trigger channel may exist for Movie BOLD, but alone cannot define stimulus onsets. |
| DICOM | BOLD series exist | No — volumes ≠ stimulus event table without locked onsets |

## Scientific answers

1. **Do Movie MATLAB scripts record scanner triggers?**  
   They **wait** for a FORP/`t` key at runtime, but **do not save** trigger timestamps.

2. **Do they record Psychtoolbox `Screen('Flip')` timestamps?**  
   `Flip` is called; return timestamps are **not assigned/saved**.

3. **Frame-by-frame presentation times?**  
   Frames are drawn in a loop; times are **not logged**.

4. **IRM↔stimulus temporal link on disk?**  
   **No** conserved numeric link suitable for BIDS `events.tsv`.

## Publication stance

Release Movie BOLD **without** `events.tsv`. Provide protocol code and stimulus mapping only. **No synthetic onset generation.**
