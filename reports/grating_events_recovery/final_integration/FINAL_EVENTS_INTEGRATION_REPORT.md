# Final events integration report — Grating task-fmri

Generated: `2026-07-28T14:55:45.615271+00:00`

**Mode:** EXECUTION MODE : fichiers copiés dans BIDS

## Summary

| Metric | n |
|--------|--:|
| ACCEPT initial (mapping + DICOM resolved) | 20 |
| Integrated (validated) | 19 |
| Failed | 0 |
| Held for REVIEW | 1 |

## Runs added / ready

- `sub-002/ses-01/func/sub-002_ses-01_task-fmri_run-09_events.tsv`
- `sub-011/ses-01/func/sub-011_ses-01_task-fmri_run-07_events.tsv`
- `sub-011/ses-01/func/sub-011_ses-01_task-fmri_run-05_events.tsv`
- `sub-012/ses-01/func/sub-012_ses-01_task-fmri_run-03_events.tsv`
- `sub-016/ses-02/func/sub-016_ses-02_task-fmri_run-09_events.tsv`
- `sub-020/ses-01/func/sub-020_ses-01_task-fmri_run-05_events.tsv`
- `sub-023/ses-01/func/sub-023_ses-01_task-fmri_run-09_events.tsv`
- `sub-024/ses-02/func/sub-024_ses-02_task-fmri_run-07_events.tsv`
- `sub-024/ses-02/func/sub-024_ses-02_task-fmri_run-11_events.tsv`
- `sub-025/ses-01/func/sub-025_ses-01_task-fmri_run-09_events.tsv`
- `sub-038/ses-02/func/sub-038_ses-02_task-fmri_run-04_events.tsv`
- `sub-040/ses-01/func/sub-040_ses-01_task-fmri_run-07_events.tsv`
- `sub-040/ses-01/func/sub-040_ses-01_task-fmri_run-09_events.tsv`
- `sub-041/ses-01/func/sub-041_ses-01_task-fmri_run-09_events.tsv`
- `sub-043/ses-02/func/sub-043_ses-02_task-fmri_run-12_events.tsv`
- `sub-043/ses-02/func/sub-043_ses-02_task-fmri_run-02_events.tsv`
- `sub-043/ses-02/func/sub-043_ses-02_task-fmri_run-06_events.tsv`
- `sub-061/ses-01/func/sub-061_ses-01_task-fmri_run-07_events.tsv`
- `sub-083/ses-01/func/sub-083_ses-01_task-fmri_run-09_events.tsv`

## Failed / review

| participant | session | fMRI# | run | status | message |
|-------------|---------|------:|----:|--------|---------|
| sub-046 | ses-01 | 1 | 07 | REVIEW | TRIGGER_VOLUME_MISMATCH triggers=226 volumes=219 |

## Safety

- `raw_original/` not modified
- NIfTI / acquisition JSON not modified
- Existing events backed up before overwrite (execute mode only)
- No synthetic onsets: timings from MATLAB `triggerTimes` only
- Ambiguous mappings excluded (ACCEPT / DICOM-resolved only)

## Coverage impact (task-fmri magnitude BOLD)

| Metric | n |
|--------|--:|
| Missing events before | 57 |
| Missing events after | 39 |
| Net reduction | 18 |

Note: 19 files written; 1 destination already had events (backed up) so missing count dropped by 18.

## Held REVIEW

- `sub-046 ses-01 fMRI1 run-07`: MATLAB triggers=226 but BOLD volumes=219. Twin `run-09` has 226 volumes — mapping not auto-corrected (fail-closed).
