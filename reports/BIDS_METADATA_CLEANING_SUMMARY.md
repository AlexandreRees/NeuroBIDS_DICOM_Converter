# BIDS metadata cleaning summary

**Date:** 2026-07-22
**Mode:** `apply`
**BIDS directory:** `/lustre07/scratch/alexrees/bids`

## Purpose

Publication-readiness metadata hygiene for Scientific Data submission. Administrative or potentially identifying sidecar fields are removed while scientifically relevant MRI acquisition parameters are preserved.

## Counts

- JSON files scanned: **7958**
- JSON files with target fields present: **7956**
- JSON files modified: **7956**

## Removed fields (policy)

- `InstitutionalDepartmentName` — occurrences removed/proposed: **7956**
- `InstitutionName` — occurrences removed/proposed: **0**
- `StationName` — occurrences removed/proposed: **0**
- `DeviceSerialNumber` — occurrences removed/proposed: **0**
- `PatientName` — occurrences removed/proposed: **0**
- `PatientID` — occurrences removed/proposed: **0**
- `PatientBirthDate` — occurrences removed/proposed: **0**
- `PatientAge` — occurrences removed/proposed: **0**
- `PatientSex` — occurrences removed/proposed: **0**
- `OtherPatientIDs` — occurrences removed/proposed: **0**
- `OtherPatientNames` — occurrences removed/proposed: **0**

## Preserved acquisition fields (never removed by this script)

- `Manufacturer`
- `ManufacturersModelName`
- `MagneticFieldStrength`
- `ProtocolName`
- `SeriesDescription`
- `SequenceName`
- `PulseSequenceDetails`
- `ScanningSequence`
- `RepetitionTime`
- `EchoTime`
- `FlipAngle`
- `SliceThickness`
- `SpacingBetweenSlices`
- `PhaseEncodingDirection`
- `TotalReadoutTime`

## Backup

Original JSON files copied to: `/lustre07/scratch/alexrees/bids_metadata_backup_before_cleaning`

## Example files changed (or proposed)

- `sub-001/ses-01/anat/sub-001_ses-01_run-01_FLAIR.json`
- `sub-001/ses-01/anat/sub-001_ses-01_run-01_T1w.json`
- `sub-001/ses-01/anat/sub-001_ses-01_run-01_TB1TFL.json`
- `sub-001/ses-01/anat/sub-001_ses-01_run-02_T1w.json`
- `sub-001/ses-01/anat/sub-001_ses-01_run-02_TB1TFL.json`
- `sub-001/ses-01/anat/sub-001_ses-01_run-03_T1w.json`
- `sub-001/ses-01/dwi/sub-001_ses-01_run-01_dwi.json`
- `sub-001/ses-01/dwi/sub-001_ses-01_run-02_dwi.json`
- `sub-001/ses-01/dwi/sub-001_ses-01_run-05_dwi.json`
- `sub-001/ses-01/fmap/sub-001_ses-01_dir-AP_run-01_epi.json`
- `sub-001/ses-01/fmap/sub-001_ses-01_dir-AP_run-02_part-phase_epi.json`
- `sub-001/ses-01/fmap/sub-001_ses-01_dir-AP_run-03_epi.json`
- `sub-001/ses-01/fmap/sub-001_ses-01_dir-AP_run-04_part-phase_epi.json`
- `sub-001/ses-01/fmap/sub-001_ses-01_dir-PA_run-01_epi.json`
- `sub-001/ses-01/fmap/sub-001_ses-01_dir-PA_run-02_part-phase_epi.json`
- `sub-001/ses-01/fmap/sub-001_ses-01_dir-PA_run-03_epi.json`
- `sub-001/ses-01/fmap/sub-001_ses-01_dir-PA_run-04_part-phase_epi.json`
- `sub-001/ses-01/func/sub-001_ses-01_task-control_run-01_bold.json`
- `sub-001/ses-01/func/sub-001_ses-01_task-control_run-01_part-phase_sbref.json`
- `sub-001/ses-01/func/sub-001_ses-01_task-control_run-01_sbref.json`
- `sub-001/ses-01/func/sub-001_ses-01_task-control_run-02_part-phase_bold.json`
- `sub-001/ses-01/func/sub-001_ses-01_task-control_run-02_part-phase_sbref.json`
- `sub-001/ses-01/func/sub-001_ses-01_task-control_run-02_sbref.json`
- `sub-001/ses-01/func/sub-001_ses-01_task-control_run-03_bold.json`
- `sub-001/ses-01/func/sub-001_ses-01_task-control_run-03_part-phase_sbref.json`
- … and 7931 more

## Validation

All scanned JSON sidecars remain valid JSON objects after cleaning. No NIfTI or TSV files were modified.

## Statement

> Metadata cleaning was limited to potential administrative or identifying fields and did not alter MRI acquisition parameters.

Generated (UTC): 2026-07-22T18:20:25.766510+00:00
