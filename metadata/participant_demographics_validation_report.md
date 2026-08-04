# Participant demographic consistency validation

- Generated: `2026-07-16 15:35:50 UTC`
- `participant_age.tsv`: `/home/alexrees/scratch/metadata/participant_age.tsv`
- `participants.tsv` used: `/home/alexrees/scratch/metadata/participants_preview.tsv` *(BIDS `participants.tsv` not found; using mapping-stage preview)*
- `session_mapping.csv`: `/home/alexrees/scratch/metadata/session_mapping.csv`

## Overall verdict

**PASS** — participant IDs, cohorts, and ages are consistent across the three sources.

| Check | Result |
|---|---|
| All participant IDs match across sources | PASS |
| No duplicate participants | PASS |
| No missing age after merge | PASS |
| No cohort mismatch | PASS |
| Age values agree (age.tsv vs participants) | PASS |

## Counts

- `participant_age.tsv` unique participants: **84** (rows: 84)
- participants table unique participants: **84** (rows: 84)
- `session_mapping.csv` unique participants: **84** (series rows: 10026)

### Cohort counts (`participant_age.tsv`)

- Control: 56
- Glaucoma: 19
- Data_ON: 7
- Data_TON: 2

## Participant ID set comparison

- In age but not participants: **0**
- In participants but not age: **0**
- In age but not session_mapping: **0**
- In session_mapping but not age: **0**
- In participants but not session_mapping: **0**
- In session_mapping but not participants: **0**

## Duplicates

- Duplicate IDs in `participant_age.tsv`: none
- Duplicate IDs in participants table: none
- Participants with multiple distinct cohorts in `session_mapping.csv`: none

## Missing age

- Empty age in `participant_age.tsv`: **0**
- Empty age in participants table: **0**
- Age present in age.tsv but missing in participants: **0**
- Age present in participants but missing in age.tsv: **0**

## Cohort mismatches

No cohort mismatches after normalizing `DataON`→`Data_ON` and `DataTON`→`Data_TON`.

## Age value mismatches (age.tsv vs participants)

None.

