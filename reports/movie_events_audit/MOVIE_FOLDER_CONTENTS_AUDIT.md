# Movie MATLAB folder contents audit (beyond `.mat`)

**Generated:** `2026-07-28T14:20:53.805743+00:00`  
**Scope (read-only):** every file under `**/3-Movie_Data/**` / `**/Movie_Data/**`, plus sibling folder names beside those trees.

## Layout observed

```
<MATLAB_session>/
  1-Check_FOV_and_EyeTracking/     (sibling)
  2-Grating/                       (sibling)
  3-Movie_Data/
    main.m
    Show_movie.m
    output.txt                     ← MATLAB diary (UTF-8 or UTF-16)
    Results/*_selected_run_id_*.mat
    [optional] *.mp4
  4-resting state/                 (sibling)
```

**No `Outputs/` directory** exists inside Movie trees, and **no sibling `Outputs/`** folders were found next to `3-Movie_Data`.

## Inventory (1095 files, 156 Movie roots)

| Extension | N | Role |
|---|---:|---|
| `.mat` | 550 | `Results/` — identity only |
| `.m` | 312 | protocol scripts |
| `.txt` | 129 | `output.txt` diaries |
| `.mp4` | 104 | stimulus media (not timing) |

### `output.txt` (MATLAB `diary`)

All **129** `output.txt` files were content-scanned (multi-encoding).

| Finding | N |
|---|---:|
| Contain Psychtoolbox console diagnostics (`PTB-INFO` / Flip warnings, refresh Hz) | 129 |
| Contain an assigned `triggerTimes = …` array / numeric onset log | **0** |

VBL / “stimulus onset” strings in these diaries are **PTB diagnostic messages**, not saved per-frame or scanner-locked onset vectors. Some diaries also echo `run_id` / dialog text (identity only).

## Sibling folders (beside Movie)

Common: `1-Check_FOV_and_EyeTracking`, `2-Grating`, `4-resting state`. Occasional top-level `Results` (18) belong to other paradigms / session layout quirks — not Movie timing stores. Full list: `MOVIE_SIBLING_FOLDERS.tsv`.

## Does this unlock `events.tsv`?

| Source | Adds identity? | Adds scanner-locked timing? |
|---|---|---|
| `Results/*.mat` | Yes (`run_id`) | **No** |
| `output.txt` | Sometimes | **No** |
| `.mp4` | Clip file only | **No** |
| `.m` | Protocol logic | **No** (not recorded) |
| `Outputs/` | — | **Absent** |

### Verdict (unchanged)

**NOT FEASIBLE** — expanding the audit beyond `.mat` does **not** provide reconstructable BIDS onset timing.

## Deliverables

- `MOVIE_ALL_FILES_INVENTORY.tsv`
- `MOVIE_FOLDER_FILETYPE_SUMMARY.tsv`
- `MOVIE_SIBLING_FOLDERS.tsv`
- `MOVIE_FOLDER_CONTENTS_AUDIT.md`
