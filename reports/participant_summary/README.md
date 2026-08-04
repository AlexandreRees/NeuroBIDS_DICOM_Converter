# Participant summary tables

Auto-generated from pipeline metadata (no DICOM re-read).
Clinical baseline-characteristics layout: variables as rows, cohorts as columns.

## Sources

- `metadata/participant_mapping.csv`
- `metadata/sessions.tsv`
- `metadata/participants_preview.tsv` (sex cross-check when present)

## Tables

1. **Participant_Demographics** — Demographics with ses-01/ses-02 attendance n
2. **Participant_Demographics_no_age** — Same as (1) without the age row
3. **Participant_Demographics_by_Session** — Demographics with ses-01/ses-02 columns per cohort
4. **Participant_Demographics_by_Session_no_age** — Same as (3) without the age row
5. **Longitudinal_Summary** — Longitudinal data availability
6. **Participant_Session_List** — Per-participant session counts (supplementary)

## Cohort column labels

| Pipeline label | Manuscript column |
|---|---|
| Control | Control |
| Data_ON | Optic neuritis (ON) |
| Data_TON | Traumatic optic neuropathy (TON) |
| Glaucoma | Glaucoma |

## Regenerate

```bash
python ~/scratch/reports/participant_summary/build_participant_summary.py
```

## Notes

- Age is loaded from `metadata/participant_age.tsv` when present; cells are not fabricated.
- One Control participant (sub-043) has ses-02 only (no ses-01), so Total ses-01 n = 83.
- Participants: **84**; sessions: **135**.
