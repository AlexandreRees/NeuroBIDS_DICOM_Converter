# Movie events.tsv feasibility report

**Generated:** `2026-07-28T13:59:15.620458+00:00`  
**Scope (read-only):** `/lustre06/project/6001995/raw_original/**/{3-Movie_Data,Movie_Data}/**/*.mat`  
**Rule:** Never invent timing from TR or volume count. Never write `events.tsv` in this audit.

## Verdict

### NOT FEASIBLE — BIDS `events.tsv` reconstruction from Movie MATLAB `.mat` files

**0 / 550** files classified as `RECONSTRUCTABLE`.

Scientifically, scanner-locked stimulus onsets suitable for BIDS `events.tsv` **cannot** be reconstructed from the Movie Results `.mat` corpus as archived: the MATLAB `main.m` workflow saves **selection metadata only** (before playback), and `Show_movie.m` does **not** write `triggerTimes`, VBL, or frame timestamps to disk.

## Counts

| Metric | N |
|---|---:|
| Movie `.mat` files audited | 550 |
| Load errors | 0 |
| `has_triggerTimes=YES` | 0 |
| `has_VBL=YES` | 0 |
| `has_movie_identity=YES` | 550 |
| RECONSTRUCTABLE | 0 |
| IDENTITY_ONLY | 550 |
| INSUFFICIENT_TIMING | 0 |
| AMBIGUOUS | 0 |

## Classification rules

| Class | Meaning |
|---|---|
| `RECONSTRUCTABLE` | Explicit scanner-locked onset array (e.g. `triggerTimes`) **and** stimulus identity → events.tsv could be built without inventing timing |
| `IDENTITY_ONLY` | Clip / `run_id` recoverable; **no** usable onset timestamps |
| `INSUFFICIENT_TIMING` | Some timing-related fields present but not sufficient for scanner-locked BIDS onsets |
| `AMBIGUOUS` | Unreadable file or no interpretable variables |

## What variables exist

### Observed variable names (frequency)

| Variable | Files |
|---|---:|
| `answer` | 550 |
| `change_eye` | 550 |
| `comment` | 550 |
| `resultdir` | 550 |
| `run_id` | 550 |
| `t` | 550 |
| `x` | 550 |
| `y` | 550 |
| `ans` | 514 |
| `outputFile` | 514 |
| `outputFileID` | 514 |

### Identity-related names seen

`run_id`

### Scanner-sync-related names seen

**None.** No `triggerTimes`, `triggers`, `TTL`, `FORP`, or `pulse` variables in any audited Movie `.mat`.

### Psychtoolbox timing-related names seen

**None.** No `vbl` / VBL / flip / frame timestamp variables in any audited Movie `.mat`.

## What information is missing

1. **`triggerTimes` (or equivalent)** — required to lock stimulus onset to scanner TTL / FORP `t`.
2. **VBL / `Screen('Flip')` timestamps** — not saved; flips occur in `Show_movie.m` but are discarded.
3. **Movie start / frame indices** — `OpenMovie` / `GetMovieImage` loop does not log times.
4. **Per-event duration tables** — `movieduration` from PTB is not persisted to `.mat`.
5. Wall-clock string `t` in Results files is **operator save time before playback**, not stimulus onset relative to the first BOLD volume.

## Examples by class


### RECONSTRUCTABLE

- *(none)*

### IDENTITY_ONLY

- `…/3-Movie_Data/Results/May-05-2023_ 3-10-18_PM_Subject_is_050_selected_run_id_1.mat` → vars: `answer;change_eye;comment;resultdir;run_id;t;x;y`
- `…/3-Movie_Data/Results/May-05-2023_ 3-14-38_PM_Subject_is_050_selected_run_id_2.mat` → vars: `answer;change_eye;comment;resultdir;run_id;t;x;y`
- `…/3-Movie_Data/Results/May-05-2023_ 3-18-37_PM_Subject_is_050_selected_run_id_3.mat` → vars: `answer;change_eye;comment;resultdir;run_id;t;x;y`

### INSUFFICIENT_TIMING

- *(none)*

### AMBIGUOUS

- *(none)*

## Examples of valid timing sources (for contrast — not present here)

A paradigm **would** be reconstructable if Results `.mat` contained, for example:

- `triggerTimes` — vector of FORP/`t` key times from `KbQueue` / `KbCheck` aligned to Psychtoolbox clock  
- paired with stimulus identity (`run_id`, `moviename`, trial list)  
- optionally `vbl` / flip times for sub-TR refinement  

The grating (`task-fmri`) protocol is an example of that pattern elsewhere in this project. **Movie Results `.mat` files do not contain these fields.**

## Implications for BIDS release

- Do **not** generate synthetic `task-movie` `events.tsv` from TR × volume count or assumed clip length.
- Continue releasing **identity-level** documentation (`run_id` ↔ clip ↔ eye; ProtocolName mapping) only.
- Fail-closed stance remains scientifically justified.

## Inventory

Full per-file table: [`MOVIE_TIMING_VARIABLE_INVENTORY.tsv`](MOVIE_TIMING_VARIABLE_INVENTORY.tsv)

---

## Addendum — full folder audit (all file types)

Audited all artifacts under Movie trees (`550 `.mat`, `129 `output.txt`, `312 `.m`, `104 `.mp4`).  
No `Outputs/` folders. UTF-16 diaries reclassified: **0** contain `triggerTimes` arrays; PTB VBL mentions are diagnostics only.  
**Verdict unchanged: NOT FEASIBLE.** Details: `MOVIE_FOLDER_CONTENTS_AUDIT.md`.
