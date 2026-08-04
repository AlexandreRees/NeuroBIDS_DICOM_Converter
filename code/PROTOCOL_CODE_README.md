# Experimental protocol code

This folder contains the **Psychtoolbox / MATLAB** stimulus protocols that generated the functional paradigms in this BIDS dataset.

| Folder | BIDS task | Events |
| --- | --- | --- |
| [`task-grating/`](task-grating/) | `task-fmri` | Yes — measured scanner triggers + stimulus order → `*_events.tsv` |
| [`task-movie/`](task-movie/) | `task-movie` | **No** — clip identity documented; no volume-locked timing logs |
| [`task-rest/`](task-rest/) | `task-rest` | **No** — continuous fixation; no trial structure |

## Why some paradigms have `events.tsv` and others do not

- **Grating (`task-fmri`).** The protocol recorded scanner trigger times (`triggerTimes`) and the per-run stimulus order. Those measurements support verified onset/duration tables. Event files are released only when a unique mapping to a BIDS magnitude BOLD run could be established.
- **Movie (`task-movie`).** Participants viewed predefined movie clips during fMRI. Released metadata map BIDS functional runs to MATLAB movie identifiers. Precise onset timing was not released because scanner-locked presentation timestamps were not consistently recoverable; therefore **no** `events.tsv` were generated. Scripts document presentation logic; movie files are omitted due to copyright restrictions (`task-movie_run_dictionary.tsv`, `task-movie_run_assignments.tsv`).
- **Rest (`task-rest`).** The protocol shows continuous fixation for a fixed number of TRs. There are no discrete conditions to tabulate; missing `events.tsv` is expected.

## Relationship to the Scientific Data manuscript

Paradigm descriptions, acquisition parameters, and validation counts are summarized in the dataset root [`README.md`](../README.md) and in [`docs/Protocols/`](../docs/Protocols/).

## task-fmri stimulus condition dictionary

| File | Role |
| --- | --- |
| `task-fmri_condition_dictionary.tsv` | Mapping of `stim-01`…`stim-12` to pathway, spatial/temporal parameters, contrast, colour mode, and MATLAB renderer |
| `task-fmri_condition_dictionary.json` | Column data dictionary for the TSV |
| `presentStimParams.m` | Companion copy of the grating design helper (canonical content also in `task-grating/presentStimParams.m`) |

Event files (`*_task-fmri_*_events.tsv`) use `trial_type` values `baseline` and `stim-01`…`stim-12`. Column definitions also appear in the dataset-root sidecar `task-fmri_events.json`. Labels `stim-07`…`stim-12` intentionally duplicate `stim-01`…`stim-06`.

## Provenance

Canonical scripts were selected as the **modal SHA-256** content across sessions for each basename. Movie entry scripts containing absolute stimulus-PC paths were **sanitized** for public release (scientific logic unchanged). Internal curator audits are retained outside the public deposit.

*Generated: 2026-07-28T13:33:29Z*
