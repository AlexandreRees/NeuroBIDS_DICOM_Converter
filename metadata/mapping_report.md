# Mapping Report

## Dataset scope summary

- Before filtering: 10079 inventory entries
- Excluded: 47 inventory entries
- Mapped: 84 participants
- Allowed cohorts: Control, Data_ON, Data_TON, Glaucoma

## Approved subject resolution overrides

| Path | Canonical subject | Session | Override type | Status | Confidence | Reason |
|------|-------------------|---------|---------------|--------|------------|--------|
| /lustre07/scratch/alexrees/raw_original/Control/SUBC41_Session02_2024OCT04 | SUBC041 | ses-02 | dicom_identifier | approved_override | high | DICOM PatientName truncated subject identifier; folder naming and longitudinal session chronology confirm same participant. |
| /lustre07/scratch/alexrees/raw_original/Control/SUBC44_Session02_2025FEB19 | SUBC044 | ses-02 | patient_id_raw_conflict | approved_override | high | PatientID conflict interpreted as scanner/anonymization variation. Folder name and DICOM metadata consistently identify the same participant. |
| /lustre07/scratch/alexrees/raw_original/Control/SUBC57_Session01_2025AUG11 | SUBC057 | ses-01 | patient_id_raw_conflict | approved_override | high | Same-day restudy on MAGNETOM Prisma (2025-08-11): two scanner timestamp PatientIDs (~13:54 and ~15:38) with complementary series (func/movie then anat/DWI). Folder and DICOM paths consistently identify SUBC057; not a mixed-subject collision. |

## Excluded non-dataset directories

| Path | Detected name | Reason | Category | Inventory entries |
|------|---------------|--------|----------|-------------------|
| /lustre07/scratch/alexrees/raw_original/Control/SUBC56-test-2025JUN12 | SUBC56-test-2025JUN12 | non_dataset_directory:test | test | 47 |
