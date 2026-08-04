# Release dataset audit

**Generated (UTC):** 2026-07-24T13:22:47Z
**Verdict:** **WARNING**

## Paths

- Release: `/lustre07/scratch/alexrees/release_dataset`
- Source BIDS (reference only): `/lustre07/scratch/alexrees/bids`
- Defacing (reference only): `/lustre07/scratch/alexrees/derivatives/defacing`

## Inventory

| Metric | N |
|---|---:|
| Subjects | 84 |
| Sessions | 124 |
| Files | 17101 |
| BOLD NIfTI (all tasks / phase) | 2992 |
| task-fmri magnitude BOLD (events-eligible) | 507 |
| task-fmri events.tsv | 456 |
| task-fmri BOLD with events | 456 |
| task-fmri BOLD without events | 51 |
| DWI NIfTI | 361 |
| Fieldmap NIfTI | 982 |
| Anat T1w | 356 |
| Anat T2w | 0 |
| Anat FLAIR | 125 |
| JSON sidecars | 7960 |
| `desc-defaced` filenames | 0 |

Events coverage is evaluated only against non-phase `task-fmri` magnitude BOLD (grating paradigm). Other tasks (`movie`, `control`, `rest`) and `part-phase` BOLD are out of scope for these `events.tsv` files.

## Check summary

| PASS | WARN | FAIL |
|---:|---:|---:|
| 28 | 4 | 0 |

| Check | Status | Detail |
|---|---|---|
| `release_exists` | PASS |  |
| `source_bids_untouched_present` | PASS | /lustre07/scratch/alexrees/bids |
| `source_defacing_untouched_present` | PASS | /lustre07/scratch/alexrees/derivatives/defacing |
| `source_raw_original_untouched_present` | WARN | missing: /home/alexrees/scratch/raw_original |
| `subject_count` | PASS | 84 |
| `session_count` | PASS | 124 |
| `no_desc_defaced_filenames` | PASS |  |
| `no_forbidden_trees` | PASS |  |
| `root_dataset_description.json` | PASS |  |
| `root_participants.tsv` | PASS |  |
| `root_README` | PASS |  |
| `participants_columns` | PASS |  |
| `participants_vs_folders` | PASS | n=84 |
| `dataset_description_json` | PASS |  |
| `authors_publication_ready` | WARN | Authors=['Neuro BIDS Pipeline'] — replace before OpenNeuro upload |
| `dataset_name_publication_ready` | WARN | Name='Neuro BIDS Pipeline Dataset' — set final dataset title before upload |
| `license_field` | WARN | License missing (OpenNeuro typically needs CC0/CC-BY) |
| `manifest_file` | PASS |  |
| `manifest_copy_present` | PASS | 16620 COPY files present |
| `anatomical_replacements` | PASS | reused (--skip-expensive) |
| `anat_nifti_json_pairs` | PASS | reused (--skip-expensive) |
| `anatomical_count_quick` | PASS | 481 structural NIfTIs |
| `json_parse_all` | PASS | reused (--skip-expensive) |
| `sensitive_json_keys` | PASS | reused (--skip-expensive) |
| `func_events_task_scope` | PASS | all events.tsv are task-fmri |
| `func_events_pairing` | PASS | 456 events↔BOLD pairs |
| `func_events_coverage` | PASS | 456/507 task-fmri magnitude BOLD have events (89.9%); intentionally missing=51 — matches stimulus validation (456/507; 51 irrecoverable) |
| `count_anat_t1w` | PASS | 356 |
| `count_anat_flair` | PASS | 125 |
| `count_anat_t2w` | PASS | 0 |
| `count_func_bold` | PASS | 2992 |
| `count_func_bold_task_fmri` | PASS | 507 |

## Failures

- None

## Warnings

- source_raw_original_untouched_present: missing: /home/alexrees/scratch/raw_original
- authors_publication_ready: Authors=['Neuro BIDS Pipeline'] — replace before OpenNeuro upload
- dataset_name_publication_ready: Name='Neuro BIDS Pipeline Dataset' — set final dataset title before upload
- license_field: License missing (OpenNeuro typically needs CC0/CC-BY)

## Deliverables

| File | Description |
|---|---|
| `RELEASE_DATASET_AUDIT.md` | This report |
| `RELEASE_DATASET_AUDIT.tsv` | Check results |
| `RELEASE_ANAT_IDENTITY_CHECK.tsv` | Per-anat size/hash vs defacing |
| `RELEASE_MANIFEST_CHECK.tsv` | Manifest gaps (if any) |

## Notes

- Anatomical identity: release NIfTI must match `derivatives/defacing` (skipped this run).
- Source trees `bids/`, `derivatives/`, `raw_original/` are not modified by this audit.

