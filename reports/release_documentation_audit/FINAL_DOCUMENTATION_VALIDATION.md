# Final documentation validation

Generated: `2026-07-29T19:27:41Z`

Release dir: `/lustre07/scratch/alexrees/release_dataset`

## Checks

| Check | Status | Detail |
| --- | --- | --- |
| README_exists | PASS |  |
| dataset_description_json_valid | PASS |  |
| participants_tsv_readable | PASS |  |
| docs_acquisition_protocol.md | PASS |  |
| docs_task_descriptions.md | PASS |  |
| docs_physiology_methods.md | PASS |  |
| docs_quality_control.md | PASS |  |
| docs_data_dictionary.md | PASS |  |
| docs_provenance.md | PASS |  |
| docs_limitations.md | PASS |  |
| docs_software_versions.md | PASS |  |
| LICENSE_exists | PASS |  |
| CHANGES_exists | PASS |  |
| no_absolute_paths_in_docs | PASS | 0 files:  |
| phi_sample_sidecars | PASS | 0 sampled sidecars with sensitive keys |
| bids_validator | SKIPPED | --skip_bids_validator set |

## Live counts (post-audit)

- Subjects: {'subject_directories': 84, 'participants_tsv_rows': 84}
- Modalities: `{"bold": 3243, "sbref": 3118, "epi": 1066, "dwi": 399, "T1w": 385, "TB1TFL": 270, "FLAIR": 136}`
- Tasks: `{"magnitude_bold_by_task": {"control": 399, "fmri": 553, "movie": 536, "rest": 135}, "events_tsv_by_task": {"fmri": 514, "movie": 536}}`
- Physio tsv.gz: 3620

## Update manifest

- Backup: `/lustre07/scratch/alexrees/release_dataset_backup_before_documentation_update_20260729T192711Z`
- Updated files: 13

  - `/lustre07/scratch/alexrees/release_dataset/README.md`
  - `/lustre07/scratch/alexrees/release_dataset/dataset_description.json`
  - `/lustre07/scratch/alexrees/release_dataset/docs/acquisition_protocol.md`
  - `/lustre07/scratch/alexrees/release_dataset/docs/task_descriptions.md`
  - `/lustre07/scratch/alexrees/release_dataset/docs/physiology_methods.md`
  - `/lustre07/scratch/alexrees/release_dataset/docs/quality_control.md`
  - `/lustre07/scratch/alexrees/release_dataset/docs/data_dictionary.md`
  - `/lustre07/scratch/alexrees/release_dataset/docs/provenance.md`
  - `/lustre07/scratch/alexrees/release_dataset/docs/limitations.md`
  - `/lustre07/scratch/alexrees/release_dataset/docs/software_versions.md`
  - `/lustre07/scratch/alexrees/release_dataset/CHANGES.md`
  - `/lustre07/scratch/alexrees/release_dataset/CHANGES`
  - `/lustre07/scratch/alexrees/release_dataset/docs/Protocols/Movie.md`

### Manual review

- release_dataset/dataset_description.json (Authors/Funding/DOI/Acknowledgements)
- Confirm LICENSE matches investigator intent (existing file preserved)

## Summary

- FAIL: **0**
- WARN: **0**
- PASS/SKIPPED: **16**

## Note

`bids-validator` was skipped in this documentation pass for runtime. Prior reports: `reports/bids_validation_scientific_data/`. To run:

```bash
python3 code/audit_and_update_release_documentation.py --update
# (omit --skip_bids_validator)
```

