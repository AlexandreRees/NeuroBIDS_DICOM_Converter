# BIDS metadata cleaning — pre-check (READ-ONLY)

**Generated (UTC):** 2026-07-22T17:12:37.030425+00:00
**BIDS dir:** `/lustre07/scratch/alexrees/bids`
**Backup path:** `/lustre07/scratch/alexrees/bids_metadata_backup_before_cleaning`
**Cleaning script:** `/home/alexrees/scratch/code/clean_bids_metadata.py`

This pre-check does **not** modify any files under `bids/`.

## VERDICT

SAFE_TO_APPLY = TRUE

## 1. BIDS structure

- Subjects (`sub-*`): **84**
- Sessions (`ses-*` under subjects): **124**
- JSON sidecars: **7958**
- NIfTI (`.nii` / `.nii.gz`): **7956**
- TSV files: **52**
- `dataset_description.json`: present
- `participants.tsv`: present

## 2. Backup path safety

- Outside BIDS: **yes**
- Already exists: **no**

## 3. JSON / REMOVE_FIELDS

- Invalid JSON: **0**
- JSON containing ≥1 REMOVE field: **7956**
- REMOVE_FIELDS policy: `['InstitutionalDepartmentName']`
- Field occurrence counts: `{'InstitutionalDepartmentName': 7956}`

### Example paths

- `sub-042/ses-01/fmap/sub-042_ses-01_dir-AP_run-04_part-phase_epi.json`
- `sub-042/ses-01/fmap/sub-042_ses-01_dir-AP_run-01_epi.json`
- `sub-042/ses-01/fmap/sub-042_ses-01_dir-PA_run-03_epi.json`
- `sub-042/ses-01/fmap/sub-042_ses-01_dir-PA_run-02_part-phase_epi.json`
- `sub-042/ses-01/fmap/sub-042_ses-01_dir-PA_run-01_epi.json`
- `sub-042/ses-01/fmap/sub-042_ses-01_dir-AP_run-02_part-phase_epi.json`
- `sub-042/ses-01/fmap/sub-042_ses-01_dir-AP_run-03_epi.json`
- `sub-042/ses-01/fmap/sub-042_ses-01_dir-PA_run-04_part-phase_epi.json`
- `sub-042/ses-01/dwi/sub-042_ses-01_run-01_dwi.json`
- `sub-042/ses-01/dwi/sub-042_ses-01_run-02_dwi.json`
- `sub-042/ses-01/dwi/sub-042_ses-01_run-05_dwi.json`
- `sub-042/ses-01/anat/sub-042_ses-01_run-01_TB1TFL.json`
- `sub-042/ses-01/anat/sub-042_ses-01_run-02_T1w.json`
- `sub-042/ses-01/anat/sub-042_ses-01_run-03_T1w.json`
- `sub-042/ses-01/anat/sub-042_ses-01_run-01_FLAIR.json`
- `sub-042/ses-01/anat/sub-042_ses-01_run-01_T1w.json`
- `sub-042/ses-01/anat/sub-042_ses-01_run-02_TB1TFL.json`
- `sub-042/ses-01/func/sub-042_ses-01_task-rest_run-01_sbref.json`
- `sub-042/ses-01/func/sub-042_ses-01_task-fmri_run-03_bold.json`
- `sub-042/ses-01/func/sub-042_ses-01_task-control_run-01_part-phase_sbref.json`

## 4. Scientific field presence (read-only rates among `sub-*/**/*.json`)

Sidecars scored: **0**

| Field | Present | Rate |
| --- | ---: | ---: |
| `RepetitionTime` | 0 | 0.0% |
| `EchoTime` | 0 | 0.0% |
| `FlipAngle` | 0 | 0.0% |
| `MagneticFieldStrength` | 0 | 0.0% |
| `Manufacturer` | 0 | 0.0% |
| `ManufacturersModelName` | 0 | 0.0% |
| `SliceTiming` | 0 | 0.0% |
| `PhaseEncodingDirection` | 0 | 0.0% |
| `TotalReadoutTime` | 0 | 0.0% |
| `EffectiveEchoSpacing` | 0 | 0.0% |

## 5. Cleaning script provenance

- Path: `/home/alexrees/scratch/code/clean_bids_metadata.py`
- MD5: `141729e1f43f2c0916f99d702c0182a9`
- mtime (UTC): `2026-07-22T16:32:19+00:00`

## 6. Automatic gate

SAFE_TO_APPLY = TRUE only if: BIDS exists with minimal structure, all JSON valid, backup path outside BIDS, cleaning script present, and NIfTI/TSV are not cleaning targets.

**Final:** SAFE_TO_APPLY = TRUE
