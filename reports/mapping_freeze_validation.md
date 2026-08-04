# Mapping freeze validation

- Generated: `2026-07-20T20:37:51.808633+00:00`
- Data root: `/lustre07/scratch/alexrees`
- Freeze file: `/lustre07/scratch/alexrees/metadata/mapping_freeze.json`
- Status: **PASS**

## Freeze record

- Created: `2026-07-20T20:37:50.931097+00:00`
- Participant mapping: `participant_mapping.csv`
- Session mapping: `session_mapping.csv`
- Participant SHA-256: `92ec85adfb4c5c804872a1d64eb56542ff237d8f1926f681820f89f5de4cc180`
- Session SHA-256: `e4320014bb0e3eb4b65c34554fe1c55a86db8b271a6911b16ae445ebc825502a`
- Subjects: **84**
- Freeze status: `FROZEN`

## Interpretation

- `PASS`: mapping tables match the freeze hashes and subject count.
- `MAPPING_MODIFIED_ERROR`: mapping files changed after freeze — do not convert.
- `MAPPING_NOT_FROZEN`: freeze file missing — run freeze before production conversion.
