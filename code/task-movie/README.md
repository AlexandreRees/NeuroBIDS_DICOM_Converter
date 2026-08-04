# Movie task

Participants viewed predefined movie clips during fMRI acquisition.

The released metadata provide the mapping between BIDS functional runs and MATLAB movie identifiers.

Movie scripts are provided to document stimulus presentation logic.

Movie files are not included because of copyright restrictions.

---

## Events (`*_task-movie_*_events.tsv`)

Design-level BIDS events were generated for all magnitude `task-movie` BOLD runs.

| Column | Value |
|---|---|
| `onset` | `0` — protocol assumption that scanner acquisition and movie playback started together |
| `duration` | `196.821333` s — ffprobe duration of archived MP4 clips (all four identical), **or** `n_volumes×TR` when the BOLD series is shorter (truncated/aborted runs) |
| `trial_type` | `movie` |
| `stim_file` | e.g. `Movie1A.mp4` |
| `eye` | `left` / `right` |
| `movie_label` | `Movie1`…`Movie4` (ProtocolName family) |
| `matlab_run_id` | `1`…`4` |

### Why this timing is used

1. **Lab confirmation (fMRI lead):** the scanner started at the same time as the movie clips; `TR × n_volumes` should roughly equal clip length; no other timing files were acquired.
2. **Empirical QC:** typical BOLD = **210 volumes × TR 0.937 s = 196.770 s**; MP4 duration = **196.821333 s** (Δ ≈ **51 ms** ≈ 0.05 TR). That leaves no room for several saved pre-movie wait volumes in the archived NIfTI.
3. **Archive limitation:** MATLAB `Show_movie.m` waited for FORP key `t` but **did not save** `triggerTimes`, VBL, or frame timestamps. Results `.mat` files contain selection metadata only (`run_id`, `change_eye`, …).

These events are appropriate for **run-level / continuous-movie** models. They are **not** millisecond TTL-locked onsets.

Column definitions: dataset-level `task-movie_events.json`.  
Per-run provenance: matching `*_events.json` sidecars (`timing_basis`, mapping confidence, ProtocolName).

Generator: `code/bids_fixes/generate_movie_events.py`  
Report: `reports/movie_events_generation/MOVIE_EVENTS_GENERATION_REPORT.md`

### Mapping confidence

- **HIGH** — unique ProtocolName → matlab_run_id assignment (`task-movie_run_assignments.tsv`), usually with matching `selected_run_id*.mat`.
- **MEDIUM** — ProtocolName MovieN fallback when assignment was ambiguous (duplicate ProtocolName in session). Clip/eye still follow the MovieN dictionary. Listed in `task-movie_medium_confidence_runs.tsv`.

### Truncated runs

Seven magnitude BOLD series have fewer than 210 volumes. For those runs, events `duration` is capped to `n_volumes × TR` (`duration_capped_to_scan` in the sidecar). See `task-movie_truncated_runs.tsv`.

Results `.mat` files that may contain operator-entered initials in filenames are **not** redistributed. Published `main.m` retains the original initials prompt only to document laboratory procedure.

---

## Technical documentation

Sanitized publication copies of the laboratory Psychtoolbox entry points (`main.m`, `Show_movie.m`). Absolute stimulus-PC paths from the raw archive were replaced with relative MP4 basenames.

### Scanner synchronization

`Show_movie.m` opens the movie, starts the playback engine, then blocks on `KbQueueWait` for the FORP keyboard event `t` (scanner trigger). Frame drawing proceeds after the trigger. **No trigger timestamps are saved.**

### Stimulus presentation (`run_id`)

| run_id | Clip | Default eye (`change_eye=0`) | BIDS ProtocolName family |
|---:|---|---|---|
| 1 | Movie1A.mp4 | left | Movie1_* |
| 2 | Movie2A.mp4 | right | Movie2_* |
| 3 | Movie1B.mp4 | right | Movie3_* |
| 4 | Movie2B.mp4 | left | Movie4_* |

See `task-movie_run_dictionary.tsv` and `task-movie_run_assignments.tsv`.

### Dependencies

- MATLAB
- Psychtoolbox-3 (`Screen`, `KbQueue*`, stereo mode)
- Movie files on the stimulus PC (**not** redistributed)

### Provenance

`reports/movie_protocol/CODE_COPY_VALIDATION.tsv`
