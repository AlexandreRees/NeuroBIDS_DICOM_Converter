# Movie protocol summary (MATLAB / Psychtoolbox)

**Generated:** `2026-07-28T13:38:16.751305+00:00`  
**Source of truth:** majority-hash copies of `main.m` / `Show_movie.m` under `**/3-Movie_Data/` in `raw_original/` (read-only audit).

## Overview

Participants viewed predefined movie clips during fMRI acquisition. The released metadata provide the mapping between BIDS functional runs and MATLAB movie identifiers. Precise stimulus onset timing was not released because scanner-locked presentation timestamps were not consistently recoverable. Therefore, no BIDS `events.tsv` files were generated. Movie scripts are provided to document stimulus presentation logic. Movie files are not included because of copyright restrictions.

Technically, naturalistic monocular stimulation was delivered with Psychtoolbox-3 under MATLAB. Operators launched `main.m`, selected a `run_id` (1–4), which selected a movie file and stimulated eye, then `Show_movie.m` waited for the scanner FORP trigger key `t` and streamed the clip with a binocular fixation overlay.

## Acquisition workflow

1. Operator confirms Results folder housekeeping (`questdlg`).
2. Operator enters subject initials (saved into Results filename only; not used for timing).
3. Operator selects `run_id` 1–4 via dialog.
4. `main.m` **immediately saves** `Results/<datetime>_Subject_is_<initials>_selected_run_id_<N>.mat` containing selection metadata (`run_id`, comment, timestamps) — **before** playback.
5. `main.m` calls `Show_movie(moviename, eye)`.
6. `Show_movie` opens a stereo PTB window, shows “The experiment will start shortly”, opens the movie, starts the playback engine, creates a keyboard queue for `t`, then `KbQueueWait` blocks until the scanner trigger.
7. Frames are drawn to the stimulated eye buffer with a blue/red fixation cross until the movie ends (or space aborts).

## Synchronization

- Intended sync: first scanner TTL mapped to keyboard `t` (FORP device index 0).
- **Limitation (critical):** `Screen('PlayMovie', movie, 1)` is invoked **before** `KbQueueWait`. No `triggerTimes`, VBL timestamps, or frame indices are written to disk.
- Therefore scanner-locked onsets/durations **cannot** be reconstructed without inventing timing.

## Stimulus selection

| matlab_run_id | File (as coded) | Stimulated eye (with default `change_eye=0`) |
|---:|---|---|
| 1 | Movie1A.mp4 | left (`eye = change_eye`) |
| 2 | Movie2A.mp4 | right (`eye = ~change_eye`) |
| 3 | Movie1B.mp4 | right |
| 4 | Movie2B.mp4 | left |

`change_eye` may be flipped from FOV/eye-check notes (commented in `main.m`).

## Movie assignment / Run selection

BIDS functional series use `ProtocolName` / `SeriesDescription` `Movie1_AP`…`Movie4_AP`. Documentation maps:

- `Movie1_*` ↔ matlab `run_id=1` ↔ Movie1A  
- `Movie2_*` ↔ `run_id=2` ↔ Movie2A  
- `Movie3_*` ↔ `run_id=3` ↔ Movie1B  
- `Movie4_*` ↔ `run_id=4` ↔ Movie2B  

Assignments are emitted only when this ProtocolName match is **unique** within a session.

## Scanner interaction

- Start: wait for `t`.
- Abort: space closes movie and screen.
- Design length referenced in prior paradigm docs: ~210 volumes at TR ≈ 0.937 s (~197 s). Not re-derived from MP4 (videos not ingested).

## Known limitations

1. No measured event timing → **no `events.tsv`** (fail-closed).
2. Absolute Windows stimulus-PC paths in raw scripts (sanitized in public `code/task-movie/`).
3. Results `.mat` store identity (`run_id`) only.
4. MP4s are copyright-sensitive and are **not** copied into the public tree.

## Scientific relevance

Documents which naturalistic clip and eye were intended per BIDS `task-movie` run, supporting reuse and QC without fabricating onsets. Aligns with Scientific Data / OpenNeuro expectations for transparent withholding of non-recoverable timing.
