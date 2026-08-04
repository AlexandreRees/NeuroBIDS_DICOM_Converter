# Mapping repair report

- Generated: `2026-07-16T02:17:37.041469+00:00`
- Input mapping: `/lustre07/scratch/alexrees/metadata/mapping.csv`
- Session mapping: `/lustre07/scratch/alexrees/metadata/session_mapping.csv`
- Inventory: `/lustre07/scratch/alexrees/metadata/inventory_narval.csv`
- Output mapping: `/lustre07/scratch/alexrees/metadata/mapping_narval_fixed.csv`

## Summary

- Rows processed: **141**
- Missing participant IDs detected: **6**
- Participant IDs recovered: **6**
- Participant IDs unrecoverable: **0**
- Session labels normalized: **6**
- Duplicate rows removed: **0**
- Conflicts detected: **1**
- Final row count: **141**

## Validation summary

- Status: **WARNING**
- Errors: 0
- Warnings: 4
- Missing participant IDs: 0
- Invalid session IDs: none
- Forbidden `/mnt/d` hits: 0
- Missing required columns: none
- Duplicate participant/session groups: 1

Note: neuro_convert consumes series-level session_mapping.csv; this aggregated mapping repair does not modify that file. Session-level WARNINGs for sequence/acquisition checks are expected.

## Participant ID recoveries

| row | original | recovered | source | canonical | folder |
|---|---|---|---|---|---|
| 135 | `(empty)` | `sub-012` | session_mapping.canonical_subject_id | `SUBC012` | `SUBC12-Session1-2023JUL12` |
| 136 | `(empty)` | `sub-032` | session_mapping.canonical_subject_id | `SUBC033` | `SUBC33_Session02_2024AUG15` |
| 137 | `(empty)` | `sub-042` | session_mapping.canonical_subject_id | `SUBC043` | `SUBC43_SESSION02_2024NOV13_2` |
| 138 | `(empty)` | `sub-043` | session_mapping.canonical_subject_id | `SUBC044` | `SUBC44_SESSION01_2024JUL25` |
| 139 | `(empty)` | `sub-053` | session_mapping.canonical_subject_id | `SUBC054` | `SUBC54_SESSION02_2025MAY27` |
| 140 | `(empty)` | `sub-082` | session_mapping.canonical_subject_id | `SUBG17` | `SUBG17_SESSION02_2025AUG19` |

## Session label normalizations

| row | original | normalized | participant_id | canonical |
|---|---|---|---|---|
| 135 | `Session1` | `ses-01` | `sub-012` | `SUBC012` |
| 136 | `Session02` | `ses-02` | `sub-032` | `SUBC033` |
| 137 | `SESSION02` | `ses-02` | `sub-042` | `SUBC043` |
| 138 | `SESSION01` | `ses-01` | `sub-043` | `SUBC044` |
| 139 | `SESSION02` | `ses-02` | `sub-053` | `SUBC054` |
| 140 | `SESSION02` | `ses-02` | `sub-082` | `SUBG17` |

## Duplicate / conflict actions

- **conflict_kept** `sub-012` / `ses-01` rows [26, 135]: 2 rows share participant/session but differ in metadata; kept all rows

## Validation findings

- **WARNING** [subject_consistency]: 1 duplicate participant/session row(s)
- **WARNING** [sequence_consistency]: Session-level mapping lacks series_description/protocol columns; sequence audit skipped. Prefer session_mapping.csv for convert readiness.
- **WARNING** [duplicates]: 1 duplicate participant/session mapping row(s)
- **WARNING** [missing_acquisitions]: Cannot verify mandatory acquisitions without series-level mapping columns
