# Git pre-commit audit

Generated (UTC): 2026-08-04T13:55:58.599527Z

## Scope

Audit of the staging area before the initial Scientific Data / GitHub commit.
Imaging trees (`bids/`, `sourcedata/`, `raw_original/`, `derivatives/`, `release_dataset/`) remain untracked by policy.

## Staging snapshot (before cleanup)

- Staged files: **2060**
- Total bytes: **406.1 MB**
- Files >50 MB: **1**

### Files >50 MB

- `metadata/deidentify_report.csv` (52.6 MB) — **exclude from GitHub** (generated deidentification inventory)

## Files to exclude (cleanup)

| Path | Reason |
|------|--------|
| `metadata/deidentify_report.csv` | Generated, >50 MB, may retain internal IDs |
| `metadata/deidentify_manifest.json` | Generated large manifest |
| `reports/movie_timing_forensic_audit/VERSION_COMPARISON.tsv` | Large generated forensic TSV |
| `reports/physiology_audit/dicom_timing_inventory.tsv` | Already gitignored; >100 MB |
| `reports/physiology_audit/_dicom_scan_checkpoint.tsv` | Already gitignored; >100 MB |

## Binary / non-text under consideration

- `reports/dwi_qc/TechnicalValidation_Table.docx`
- `reports/mri_acquisition_table/MRI_Acquisition_Table.docx`
- `reports/functional_mri_paradigm_figures/Table1_Functional_paradigm_summary.docx`
- `reports/functional_mri_paradigm_figures/Table2_Movie_run_eye_assignment.docx`
- `reports/deidentification_figures/Supplementary_Table_DICOM_Deidentification.xlsx`
- `reports/participant_summary/Participant_Session_List.xlsx`
- `reports/participant_summary/Participant_Demographics_by_Session.xlsx`
- `reports/participant_summary/Participant_Demographics_by_Session_no_age.xlsx`
- `reports/participant_summary/Participant_Demographics.xlsx`
- `reports/participant_summary/Longitudinal_Summary.xlsx`
- `reports/participant_summary/Participant_Demographics_no_age.xlsx`

Detected with binary-ish suffixes: **53**
- `reports/dwi_qc/TechnicalValidation_Table.docx` (0.04 MB, `.docx`)
- `metadata/generate_mapping.log` (0.04 MB, `.log`)
- `reports/pizarro_qc_scientific_data/Pizarro_QC_PI_Report_Scientific_Data_2026-07-22.log` (0.03 MB, `.log`)
- `reports/pi_pipeline_briefing/OpenNeuro_Publication_Readiness_PI_Briefing.log` (0.03 MB, `.log`)
- `reports/mri_acquisition_table/MRI_Acquisition_Table.docx` (0.01 MB, `.docx`)
- `reports/functional_mri_paradigm_figures/Table1_Functional_paradigm_summary.docx` (0.01 MB, `.docx`)
- `reports/functional_mri_paradigm_figures/Table2_Movie_run_eye_assignment.docx` (0.01 MB, `.docx`)
- `reports/protocol_fill/auto_retry.log` (0.01 MB, `.log`)
- `reports/privacy_audit/privacy_audit_console.log` (0.01 MB, `.log`)
- `reports/privacy_audit/privacy_audit.log` (0.01 MB, `.log`)
- `metadata/inventory_Control.log` (0.01 MB, `.log`)
- `reports/protocol_fill/monitor.log` (0.01 MB, `.log`)
- `reports/physiology_audit/forensic_audit_run.log` (0.01 MB, `.log`)
- `metadata/inventory_Glaucoma.log` (0.01 MB, `.log`)
- `reports/deidentification_figures/Supplementary_Table_DICOM_Deidentification.xlsx` (0.01 MB, `.xlsx`)
- `metadata/inventory_Data_ON.log` (0.00 MB, `.log`)
- `reports/physiology_audit/forensic_audit_console.log` (0.00 MB, `.log`)
- `reports/physiology_audit/final_bids_physio_readiness/high_mapping_recovery/convert.log` (0.00 MB, `.log`)
- `reports/dwi_qc/warning_audit/audit_console.log` (0.00 MB, `.log`)
- `reports/participant_summary/Participant_Session_List.xlsx` (0.00 MB, `.xlsx`)
- `metadata/neuro_protocol_sample.log` (0.00 MB, `.log`)
- `reports/pizarro_qc_scientific_data/Pizarro_QC_PI_Report_Scientific_Data_2026-07-22.out` (0.00 MB, `.out`)
- `metadata/inventory_Data_TON.log` (0.00 MB, `.log`)
- `reports/participant_summary/Participant_Demographics_by_Session.xlsx` (0.00 MB, `.xlsx`)
- `reports/participant_summary/Participant_Demographics_by_Session_no_age.xlsx` (0.00 MB, `.xlsx`)
- `reports/participant_summary/Participant_Demographics.xlsx` (0.00 MB, `.xlsx`)
- `reports/participant_summary/Longitudinal_Summary.xlsx` (0.00 MB, `.xlsx`)
- `reports/dwi_qc/technical_validation_console.log` (0.00 MB, `.log`)
- `reports/participant_summary/Participant_Demographics_no_age.xlsx` (0.00 MB, `.xlsx`)
- `reports/physiology_audit/final_bids_physio_readiness/conversion_run/full_convert.log` (0.00 MB, `.log`)

## Potential sensitivity notes

Text audits under `reports/` and `metadata/` may mention BIDS labels (`sub-XXX`) — these are study codes, not raw DICOM PatientName.
Raw PHI-bearing paths and absolute Lustre paths must remain out of the repo via `.gitignore` + PHI scanners used in prior audits.

Candidates reviewed:

- `metadata/deidentify_report.csv`
- `metadata/deidentify_manifest.json`
- `reports/master_manifest.tsv`
- `reports/openneuro_release/FILE_COPY_MANIFEST.tsv`
- `metadata/processing_manifest.csv`
- `reports/shards/SUBC025/deidentify_report.csv`
- `reports/associated_data_audit/phi_report.md`
- `reports/shards/SUBG03/deidentify_report.csv`
- `reports/shards/SUBC011/deidentify_report.csv`
- `reports/shards/SUBC044/deidentify_report.csv`
- `reports/shards/SUBC025/deidentify_manifest.json`
- `reports/shards/SUBC049/deidentify_report.csv`
- `reports/shards/SUBC045/deidentify_report.csv`
- `reports/shards/SUBC017/deidentify_report.csv`
- `reports/shards/SUBC053/deidentify_report.csv`
- `reports/shards/SUBC047/deidentify_report.csv`
- `reports/shards/SUBC031/deidentify_report.csv`
- `reports/shards/SUBC028/deidentify_report.csv`
- `reports/shards/SUBC032/deidentify_report.csv`
- `reports/shards/SUBC030/deidentify_report.csv`
- `reports/shards/SUBC035/deidentify_report.csv`
- `reports/shards/SUBC040/deidentify_report.csv`
- `reports/shards/SUBC042/deidentify_report.csv`
- `reports/shards/SUBC027/deidentify_report.csv`
- `reports/shards/SUBC039/deidentify_report.csv`
- `reports/shards/SUBTON01/deidentify_report.csv`
- `reports/shards/SUBC037/deidentify_report.csv`
- `reports/shards/SUBC036/deidentify_report.csv`
- `reports/shards/SUBG08/deidentify_report.csv`
- `reports/shards/SUBC029/deidentify_report.csv`
- `reports/shards/SUBC041/deidentify_report.csv`
- `reports/shards/SUBG17/deidentify_report.csv`
- `reports/shards/SUBC022/deidentify_report.csv`
- `reports/shards/SUBC023/deidentify_report.csv`
- `reports/shards/SUBG09/deidentify_report.csv`
- `reports/shards/SUBON01/deidentify_report.csv`
- `reports/shards/SUBC009/deidentify_report.csv`
- `reports/shards/SUBC002/deidentify_report.csv`
- `reports/shards/SUBC020/deidentify_report.csv`
- `reports/shards/SUBC004/deidentify_report.csv`

## Files retained (policy)

- `code/` — processing, QC, BIDS conversion, audit scripts
- `scripts/` — cluster launchers (Slurm/bash)
- `reports/` — scientific audit markdown/TSV/JSON (text)
- `metadata/` — lightweight mapping tables (excluding large generated dumps)
- `manuscript/` — Scientific Data drafting materials
- `tests/` — unit tests
- `.gitignore`, `README.md`, `CITATION.cff`

## Scientific justification

Nature Scientific Data / OpenNeuro practice separates **open methods** (code + documentation + QC tables) from **imaging payloads**.
GitHub must remain a methods/reproducibility layer; volumetric MRI and DICOM stay on institutional storage and the designated public data platform.

## Confirmation (pre-cleanup intent)

- Imaging data directories ignored: yes (policy)
- Target: 0 NIfTI / 0 DICOM in commit
