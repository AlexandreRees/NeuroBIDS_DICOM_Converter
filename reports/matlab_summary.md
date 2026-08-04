# MATLAB content inventory summary

Generated: 2026-07-17T14:14:03.346173+00:00

Read-only inspection of `.mat` files listed in `reports/associated_data_inventory.tsv`.
**Source MATLAB files were not modified.**

## Overview

| Item | Value |
|---|---|
| `.mat` files inspected | 2885 |
| Read/inspect errors | 0 |

## Classification counts

- **stimulus definition**: 278
- **task timing**: 2498
- **behavioral data**: 0
- **eye tracking**: 109
- **physiological data**: 0
- **preprocessing output**: 0
- **unknown**: 0

## File families (by name/content role)

- `dated_seq`: 558
- `fMRI_N`: 558
- `dated_scan`: 556
- `dated_selected_run`: 550
- `GreenLevel`: 139
- `RedLevel`: 139
- `runs_random`: 138
- `runs_random_record`: 138
- `dated_eye`: 109

## Required for BIDS conversion

These MATLAB products are the ones that carry task structure / timing needed to build `func/*_events.tsv` (and related sourcedata provenance):

- **`*scan_info*.mat` (dated scan structs)** — contain `scan.runs` with `triggerTimes` / `vbl`; primary source for precise task onsets and triggers (556 files).
- **`fMRI_N.mat` and dated `sequence_of_stimuli` files** — `Stim_order_selected` (12-condition order per run); needed to label events (558 + 558 files). Prefer one canonical copy per run (usually `fMRI_N.mat`).
- **`runs_random.mat` workspace dumps** — include full-run `vbl` frame timing, `paradigm` / `runParadigmFinal`, and stim order (138 files). Use when `scan_info` is missing or to cross-check onsets; also holds sparse keypress logs.
- **`runs_random_record*.mat`** — session run-order randomization (138 files); needed to map run index to paradigm.

## Laboratory intermediate files

Keep for provenance / QC; do not treat as primary BIDS imaging sidecars:

- **`GreenLevel.mat` / `RedLevel.mat`** — display RGB calibration (278 files). Lab stimulus-setup intermediates; keep in sourcedata only if documenting display settings.
- **Dated `selected_run_id` logs** — operator run selection / comments (550 files). Useful provenance, not event timing.
- **FOV / eye-check `*eye*.mat` workspace dumps** — store which eye was selected and fixation geometry, not gaze samples (109 files). True eye-tracking (if present) is in EDF/ASC, not these MAT files.

## Can be ignored (for BIDS events / physio / eyetrack conversion)

- Duplicate dated `sequence_of_stimuli` copies when the matching `fMRI_N.mat` already exists for the same run (same `Stim_order_selected`).
- Psychtoolbox UI/color workspace variables inside eye-check and run dumps (screen rects, color triples, window pointers) — not BIDS derivatives.
- No MATLAB files in this inventory are physiological recordings (`.resp`/`.puls`/`.ecg` are separate) or neuroimaging preprocessing outputs.

## Scientific roles (quick reference)

| Family | Typical variables | Role |
|---|---|---|
| GreenLevel / RedLevel | `GreenLevel`/`RedLevel` float RGB | Stimulus definition (display calib) |
| fMRI_N / sequence_of_stimuli | `Stim_order_selected` (1×12) | Task timing (condition order) |
| runs_random_record* | `runs_random_record` | Task timing (run order) |
| *scan_info* | `scan` struct (`triggerTimes`, `vbl`) | Task timing (onsets/triggers) |
| runs_random | `vbl`, `paradigm`, keys, stim | Task timing (+ sparse behavior) |
| *selected_run_id* | `run_id`, `t`, subject cells | Task timing (operator log) |
| *eye* FOV checks | `eye`, fixRects, colors | Eye tracking setup only |

## Outputs

- `reports/matlab_content_inventory.tsv`
- `reports/matlab_summary.md`
