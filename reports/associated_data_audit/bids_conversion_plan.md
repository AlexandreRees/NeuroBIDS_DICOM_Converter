# Associated data BIDS conversion plan

Generated: `2026-07-21T15:28:20.500755+00:00`

## Status overview

- **Convertible to BIDS**: 2699
- **Requires custom converter**: 864
- **Should remain as auxiliary data**: 2193

## Categories that should become BIDS files

- **Physiology (`.resp`, `.puls`, `.ecg`, `.pmu`, `.ext*`)**: parse channels and scanner triggers; write run-linked `func/*_physio.tsv.gz` and JSON sidecars with sampling frequency, start time, and column units.
- **Task timing / behavior**: convert MATLAB/text presentation logs to run-linked `func/*_events.tsv`; include onset, duration, trial_type, response, and reaction_time where available.
- **Eye tracking (`.edf`, `.asc`, eye-tracking MATLAB)**: use a validated custom converter for gaze, pupil, blink, fixation, and saccade streams; write compressed tabular data and metadata sidecars following the applicable BIDS eye-tracking extension.

## Categories that should remain auxiliary

- MATLAB source workspaces and scripts needed for provenance should remain under de-identified `sourcedata/` or `code/` after primary events are generated.
- Calibration/setup workspaces without continuous gaze or task events are auxiliary provenance.
- Scanner metadata not required for interpretation should be removed from public derivatives.
- Audiovisual stimuli belong in `stimuli/` only when redistribution rights are documented.

## Manual inspection

- Files with automated read errors, unsupported structures, ambiguous run mappings, or publication status `Cannot determine`.
- Every audiovisual stimulus for copyright, license, faces/voices, and embedded author metadata.
- Detections based only on generic date/UID patterns to separate true PHI from harmless protocol constants.

## Cannot be redistributed

- Copyrighted movie/audio without explicit redistribution permission.
- Files retaining direct identifiers after attempted de-identification.
- Files whose scientific value and consent/ownership cannot be established.

## Category/status matrix

| Category | Status | Files |
|---|---|---:|
| eye_tracking | Requires custom converter | 448 |
| physiology | Convertible to BIDS | 339 |
| stimulus | Convertible to BIDS | 1252 |
| stimulus | Requires custom converter | 416 |
| stimulus | Should remain as auxiliary data | 2048 |
| task_timing | Convertible to BIDS | 1108 |
| unknown | Should remain as auxiliary data | 145 |
