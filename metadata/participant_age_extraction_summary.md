# Participant age extraction summary

Age was extracted from the first imaging session using a cascading strategy: preferred T1-weighted anatomical DICOM → alternative anatomical sequences (e.g. FLAIR) → same-session non-anatomical metadata fallback (e.g. Localizer). Age is never imputed.

## Counts

- Participants processed: **84**
- Age extracted from preferred T1 anatomical: **83**
- Age extracted from alternative anatomical sequence: **0**
- Age extracted from same-session non-anatomical fallback: **1**
- Age unavailable from predefined anatomical T1 extraction strategy: **0**
  - no readable DICOM age metadata: **0**
  - missing eligible imaging data: **0**
- Errors: **0**

## Summary by cohort

### Data_ON

- processed: 7
- from T1: 7
- from alternative anatomical: 0
- from same-session fallback: 0
- Age unavailable from predefined anatomical T1 extraction strategy: 0
- errors: 0

### Data_TON

- processed: 2
- from T1: 2
- from alternative anatomical: 0
- from same-session fallback: 0
- Age unavailable from predefined anatomical T1 extraction strategy: 0
- errors: 0

### Glaucoma

- processed: 19
- from T1: 19
- from alternative anatomical: 0
- from same-session fallback: 0
- Age unavailable from predefined anatomical T1 extraction strategy: 0
- errors: 0

### Control

- processed: 56
- from T1: 55
- from alternative anatomical: 0
- from same-session fallback: 1
- Age unavailable from predefined anatomical T1 extraction strategy: 0
- errors: 0

## Status / source vocabulary

- `preferred_t1_anatomical` — preferred T1-weighted anatomical DICOM
- `alternative_anatomical_sequence` — FLAIR / other anatomical in the same session
- `same_session_non_anatomical_fallback` — Localizer / functional / other same-session DICOM
- `age_unavailable_no_dicom_age_metadata` — readable DICOMs lacked PatientAge/BirthDate
- `missing_eligible_imaging` — participant missing eligible imaging data
