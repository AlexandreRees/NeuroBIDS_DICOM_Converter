# Mapping Report

## Dataset scope summary

- Before filtering: 10079 inventory entries
- Excluded: 47 inventory entries
- Mapped: 82 participants
- Allowed cohorts: Control, Data_ON, Data_TON, Glaucoma

## Approved subject resolution overrides

| Path | Canonical subject | Session | Override type | Status | Confidence | Reason |
|------|-------------------|---------|---------------|--------|------------|--------|
| /lustre07/scratch/alexrees/raw_original/Control/SUBC41_Session02_2024OCT04 | SUBC041 | ses-02 | dicom_identifier | approved_override | high | DICOM PatientName truncated subject identifier; folder naming and longitudinal session chronology confirm same participant. |

## Excluded non-dataset directories

| Path | Detected name | Reason | Category | Inventory entries |
|------|---------------|--------|----------|-------------------|
| /lustre07/scratch/alexrees/raw_original/Control/SUBC56-test-2025JUN12 | SUBC56-test-2025JUN12 | non_dataset_directory:test | test | 47 |
