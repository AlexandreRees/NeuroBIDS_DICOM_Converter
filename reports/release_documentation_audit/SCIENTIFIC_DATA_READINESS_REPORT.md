# Scientific Data readiness report

Generated: `2026-07-29T19:27:42Z`

Assessment is based only on existing release metadata, QC outputs, and reports.
No scientific claims were invented.

**Documentation readiness score:** 21/22 (95.5%)

- HIGH inconsistencies: **2**
- Missing critical documents: **0** (none)

## Dimensions

| Dimension | Status | Score | Evidence | Gaps |
| --- | --- | ---: | --- | --- |
| Dataset description | PARTIAL | 1/2 | Name=Neuro BIDS Pipeline Dataset; BIDSVersion=1.9.0; Authors=['Neuro BIDS Pipeline'] | Complete Authors/Funding/DOI/HowToAcknowledge if still placeholders |
| Acquisition documentation | READY | 2/2 | Sidecar-derived examples available; docs/acquisition_protocol.md present |  |
| BIDS compliance | READY | 2/2 | Prior validator reports under reports/bids_validation_scientific_data/ | Re-run bids-validator on current release_dataset for FINAL validation |
| Quality control | READY | 2/2 | MRIQC T1w JSON=384, bold JSON=1623; DWI report=True; physio QC=True | Ensure QC narrative docs cite live counts; MRIQC may still be partial vs full cohort |
| Physiology documentation | READY | 2/2 | Live physio.tsv.gz=3620; methods doc=yes |  |
| Diffusion documentation | READY | 2/2 | DWI NIfTI=399; DWI_QC_REPORT present=True | Summarize DWI QC in quality_control.md / acquisition_protocol.md |
| Functional validation | READY | 2/2 | Tasks={'control': 399, 'fmri': 553, 'movie': 536, 'rest': 135}; events={'fmri': 514, 'movie': 536} | Align task_descriptions.md with movie events timing policy |
| Code availability | READY | 2/2 | release_dataset/code/ present with task protocol materials |  |
| Provenance | READY | 2/2 | dataset_description GeneratedBy + optional provenance.md |  |
| Limitations | READY | 2/2 | README known limitations section and/or docs/limitations.md |  |
| Reproducibility | READY | 2/2 | Software versions in README/reports; dedicated software_versions.md present | Create software_versions.md from verified sources only |

## Live dataset snapshot

- Subjects (directories): **84**
- participants.tsv rows: **84**
- Cohorts: `{"Control": 56, "Glaucoma": 19, "DataON": 7, "DataTON": 2}`
- Session coverage: `{"both_sessions": 51, "ses-01_only": 32, "ses-02_only": 1, "neither": 0, "subject_session_dirs": 135}`
- Modalities: `{"bold": 3243, "sbref": 3118, "epi": 1066, "dwi": 399, "T1w": 385, "TB1TFL": 270, "FLAIR": 136}`
- Magnitude BOLD by task: `{"control": 399, "fmri": 553, "movie": 536, "rest": 135}`
- Events by task: `{"fmri": 514, "movie": 536}`
- Physio `*_physio.tsv.gz`: **3620**
- DWI NIfTI: **399**
- Derivatives available: bids_priority_fixes, defacing, dmriqc, group_qc, mriqc, neuro_pipeline, physiology_characterization, physiology_qc, physiology_reproducibility

## Publication blockers (from this audit)

- No missing critical documentation filenames (content quality still requires review).
- Resolve **2** HIGH inconsistencies in `DOCUMENTATION_INCONSISTENCIES.tsv`.
- Replace placeholder Authors in `dataset_description.json`.

## Sources consulted

- `participants_tsv`: `release_dataset/participants.tsv`
- `dataset_description_json`: `release_dataset/dataset_description.json`
- `longitudinal_report`: `reports/bids_validation_scientific_data/LONGITUDINAL_COVERAGE.md`
- `extracted_metrics`: `reports/scientific_data_docs/extracted_metrics.md`
- `movie_events_generation`: `reports/movie_events_generation/MOVIE_EVENTS_GENERATION_REPORT.md`
- `physio_conversion_summary`: `reports/physiology_audit/final_bids_physio_readiness/conversion_run/CONVERSION_SUMMARY.md`
- `dwi_qc_report`: `reports/dwi_qc/DWI_QC_REPORT.md`
