# Staging final report

Generated (UTC): 2026-08-04T13:57:02.788116Z

## Summary

- Total staged files: **1488**
- Total size: **197.0 MB** (187.9 MiB)

## Top 20 largest staged files

| MB | Path |
|----|------|
| 14.75 | `reports/movie_timing_forensic_audit/HIDDEN_TIMING_FILES.tsv` |
| 14.71 | `metadata/archive/session_mapping_2026-07-16T02-04-35Z.csv` |
| 14.71 | `metadata/archive/session_mapping_2026-07-16T01-59-53Z.csv` |
| 14.45 | `metadata/archive/session_mapping_2026-07-16T01-51-58Z.csv` |
| 14.38 | `metadata/session_mapping.csv` |
| 12.98 | `metadata/inventory_narval.csv` |
| 10.90 | `reports/fitbir_pre_submission/DATASET_INVENTORY.tsv` |
| 5.69 | `reports/movie_timing_forensic_audit/POTENTIAL_ARCHIVES.tsv` |
| 5.38 | `reports/associated_data_audit/file_level_audit.tsv` |
| 4.98 | `reports/movie_timing_forensic_audit/MATLAB_VARIABLE_AUDIT.tsv` |
| 4.84 | `reports/movie_timing_forensic_audit/MATLAB_CODE_TIMING_AUDIT.tsv` |
| 3.48 | `reports/master_manifest.tsv` |
| 3.19 | `reports/openneuro_release/FILE_COPY_MANIFEST.tsv` |
| 2.90 | `reports/physiology_audit/physio_run_mapping_candidates.tsv` |
| 2.86 | `reports/stimulus_audit/stimulus_inventory.tsv` |
| 2.85 | `metadata/processing_manifest.csv` |
| 2.67 | `reports/movie_timing_forensic_audit/FILE_INVENTORY.tsv` |
| 2.52 | `reports/physiology_audit/physiology_metadata_report.tsv` |
| 2.00 | `reports/matlab_content_inventory.tsv` |
| 1.94 | `reports/associated_data_audit/phi_report.md` |

## Imaging / raw data confirmation

- `"0 NIfTI staged"` — count=0
- `"0 DICOM staged"` — count=0
- `"0 raw imaging staged"` — data-tree paths=0

All imaging/raw checks passed.

## Cached stat (tail)

```
 scripts/run_dmriqc_smoke.sh                        |    53 +
 scripts/run_dwi_motion_snr_qc.slurm                |    26 +
 scripts/run_dwi_qc.slurm                           |    25 +
 scripts/run_dwi_qc_fill_array.slurm                |    50 +
 scripts/run_dwi_qc_fill_login_safe.sh              |    68 +
 scripts/run_dwi_qc_fill_masks.slurm                |    34 +
 scripts/run_dwi_qc_fill_pending.slurm              |    33 +
 scripts/run_dwi_qc_merge.slurm                     |    22 +
 scripts/run_dwi_technical_validation.sh            |    20 +
 scripts/run_ext_recovery_audit.slurm               |    23 +
 scripts/sub016_ses02_physio_qc.py                  |   733 +
 scripts/wait_and_run_dmriqc_dwi.sh                 |    56 +
 scripts/watchdog_scilus.sh                         |   131 +
 tests/test_physiology_qc.py                        |   183 +
 1488 files changed, 697944 insertions(+)
```

