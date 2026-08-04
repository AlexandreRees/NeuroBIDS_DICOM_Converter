# Mapping audit

- Generated: `2026-07-16T02:23:02.237424+00:00`
- Mapping: `/lustre07/scratch/alexrees/metadata/session_mapping.csv`
- Schema: **series**
- Status: **WARNING**
- Errors: **0**
- Warnings: **2**
- Recommendation: **Safe to launch neuro_convert after reviewing warnings**

## File integrity

- Exists/readable: True / True
- Rows: 10026
- Missing required columns: none

## Path validation

- Forbidden root hits: 0
- Prefix mismatches: 0

## Subject consistency

- Participants: 84
- Sessions: 135
- Mapped rows/series: 10026
- Missing subject labels: 0

## Sequence consistency

- Available: True
- Family counts: `{"SpinEcho_AP": 7465, "SpinEcho_PA": 1170, "Unknown": 599, "T1w": 387, "Diffusion": 264, "FLAIR": 137, "Movie": 4, "FieldMap": 0, "REST": 0}`
- Unmapped sequences: 17

## Duplicates

- Duplicate SeriesInstanceUID: 0
- Duplicate BIDS stems/targets: 0

## Missing mandatory acquisitions

- Sessions checked: 135
- Incomplete sessions: 135

## BIDS naming

- Invalid participant IDs: none
- Invalid session IDs: none
- Invalid filename stems: 0

## Findings

- **WARNING** [sequence_consistency]: 17 unique unmapped/unknown series_description value(s)
- **WARNING** [missing_acquisitions]: 135/135 session(s) missing mandatory acquisition families

## Method note

This audit inspects the mapping CSV only. It does not read DICOM files, modify mapping outputs, or regenerate mapping.
