# Extracted metrics for Scientific Data documentation

**Purpose:** Source ledger for `bids/README.md` and `manuscript/technical_validation.md`.  
**Rule:** Only values found in existing reports or inspected BIDS sidecars. Missing items are flagged explicitly.  
**Generated:** 2026-07-22 (documentation pass)

---

## Cohort and organization

| Metric | Value | Source |
| --- | --- | --- |
| Subjects in BIDS tree | 84 | `reports/bids_validation_scientific_data/LONGITUDINAL_COVERAGE.md`; `bids/participants.tsv` |
| `participants.tsv` rows | 84 (`participant_id`, `cohort`, `sex`) | Inspected `bids/participants.tsv` |
| Sessions with both ses-01 and ses-02 | 40 | `LONGITUDINAL_COVERAGE.md` |
| ses-01 only | 43 | same |
| ses-02 only | 1 | same |
| Subject×session pairs with any NIfTI (inspected) | 124 | Live BIDS scan during documentation |
| BIDSVersion (dataset_description) | 1.9.0 | `bids/dataset_description.json` |
| Pipeline / GeneratedBy | neuro_pipeline 2.1.0 | same |
| Tasks present | task-control, task-fmri, task-movie, task-rest | Live BIDS scan; validator summary |

## Modality inventory (raw BIDS NIfTI counts)

| Modality | Count | Source |
| --- | ---: | --- |
| bold | 2992 | Live BIDS inventory (exclude derivatives) |
| sbref | 2892 | same |
| epi (fieldmaps) | 982 | same |
| dwi | 361 | same |
| T1w | 356 | same |
| TB1TFL | 248 | same |
| FLAIR | 125 | same |
| `*_events.tsv` | 51 | Live BIDS count |
| BIDS physiology sidecars | 0 | Live BIDS search (`*physio*`) |

## Acquisition metadata (representative sidecars)

| Item | Value | Source |
| --- | --- | --- |
| Manufacturer | Siemens | `sub-001` T1w/BOLD/DWI/FLAIR/fmap JSON |
| Model | Prisma | same |
| Field strength | 3 T | same |
| Software (sampled) | syngo MR E11 | same (methods draft also notes XA30 sessions) |
| T1w_MPR TR/TE/FA | 2.5 s / 0.00222 s / 8° | `sub-001` T1w JSON |
| FLAIR TR/TE/FA | 6 s / 0.357 s / 120° | `sub-001` FLAIR JSON |
| Rest BOLD TR/TE/FA / MB | 0.937 s / 0.037 s / 52° / MB=8 | `sub-001` task-rest BOLD JSON |
| DWI example protocol | gsld_76dir_b2000_1mmiso_AP; TR 3.5 s; TE 0.075 s; MB=2 | `sub-001` DWI JSON |
| Fieldmap example | SpinEchoFieldMap_PA; TR 9.71 s; TE 0.066 s | `sub-001` fmap JSON |
| Conversion software in sidecars | dcm2niix v1.0.20230411 | Manuscript methods draft + typical sidecars |

## BIDS validation

| Metric | Value | Source |
| --- | --- | --- |
| Validator | bids-validator **1.15.0** (npx) | `VALIDATION_AFTER_EVENTS_ST.md` (latest) |
| Latest status | **0 errors** (valid) | same (2026-07-21T20:34:31Z) |
| Warning file hits (latest) | 17486 | same |
| Files scanned (latest) | 16194 | same |
| Earlier baseline (pre-fix) | 195 errors; NOT READY | `VALIDATION_SUMMARY_SCIENTIFIC_DATA.md` |
| After priority fixes | 0 errors; 17363 warnings | `VALIDATION_AFTER_PRIORITY_FIXES.md` |
| Remaining warning classes | EVENTS_TSV_MISSING, INCONSISTENT_SUBJECTS, INCONSISTENT_PARAMETERS, MISSING_SESSION, TOO_FEW_AUTHORS | `VALIDATION_AFTER_EVENTS_ST.md` |
| SliceTiming recovery | 104/104 XA30 bold JSON | same |

## MRIQC

| Metric | Value | Source |
| --- | --- | --- |
| Configured modalities | T1w, bold (`-m T1w bold`) | `mriqc_array_audit.md`; methods draft |
| MRIQC version (derivatives metadata) | 24.1.0.dev0+gd5b13cb5.d20240826 | `reports/mriqc/README.md` |
| Container target in scripts | nipreps/mriqc:24.0.2 | methods draft |
| Cohort summary report | **Pilot only**: 1 subject, 6 scans (T1w=2, bold=4) | `reports/mriqc/README.md` |
| Array tasks planned | 124 participant×session | `mriqc_array_audit.md` |
| Array COMPLETE (audit snapshot) | 37 | same (2026-07-22 morning audit) |
| Current derivative JSON counts | T1w=269; bold=892; subjects with any=58 | Live `derivatives/mriqc` scan |
| HTML reports present | 1130 | same |
| Status for publication wording | **Incomplete / in progress** — do not claim full-cohort MRIQC | Flag |

## Pizarro (T1w-only)

| Metric | Value | Source |
| --- | --- | --- |
| Model | Pizarro et al. (2023); `model.FINAL.onnx` | `reports/pizarro_qc_scientific_data/PIZARRO_QC_REPORT.md` |
| Model SHA256 | cb84f2b90f7de452331ed9ba5152335b873aba95d0ca3766adfffecdafe5178a | same |
| Scope | `*_T1w.nii.gz` only | same |
| Images screened | 356 | same |
| Subjects | 83 | same |
| Inference errors | 0 | same |
| MC dropout runs / seed | 10 / 1010 | same |
| Prioritized for visual review | 229 images; 78 subjects | same |
| Role | Prioritization only; **not** exclusion | same |
| Primary quantitative QC | MRIQC (as stated in Pizarro report) | same |

## DWI QC

| Metric | Value | Source |
| --- | --- | --- |
| Inventory DWI scans | 361; all sidecars `OK` | `reports/dwi_qc/dwi_inventory.tsv` |
| Full QC rows completed (checkpoint) | 20 gradient / b-value / mask / signal; 20 dwigradcheck | live TSV line counts during documentation |
| Gradient consistency (completed subset) | 20/20 PASS | `dwi_gradient_consistency.tsv` |
| b-value schemes (subset) | `0,1000,2000` (14); `0,1000` (6) | `dwi_bvalue_summary.tsv` |
| dwigradcheck (subset) | PASS 14; REVIEW 6 | `dwigradcheck_results.tsv` |
| Tools | MRtrix3 `dwigradcheck`, `dwi2mask` | `code/run_dwi_qc.py` |
| Final cohort report | **Not yet complete** (`DWI_QC_REPORT.md` absent; job still running) | Flag |
| Smoke-test example | 1 scan PASS (sub-001) | `reports/dwi_qc_smoke/` |

## Defacing

| Metric | Value | Source |
| --- | --- | --- |
| Tool | pydeface via `neuro_pipeline.modules.defacing.run_defacing_session` | `defacing_audit_summary.md`; dataset_description GeneratedBy |
| T1w expected / defaced (dry-run audit) | 356 / 352 | `reports/defacing_audit/defacing_audit_summary.md` |
| Missing T1w at audit time | 4 | same (`defacing_missing_subjects.tsv`) |
| Structure / dataset_description | OK (Name, BIDSVersion, GeneratedBy) | same |
| Geometry flags (dry-run sample n=4) | none | same |
| Changed voxel % (dry-run median) | 21.898 | same |
| Derivative PHI-like key | `InstitutionalDepartmentName` | same |
| Retry status at documentation time | Slurm `66222082` tasks 61 & 63 running | live `squeue` |
| Full-cohort geometry audit | **Incomplete** (dry-run only) | Flag |

## Privacy / de-identification

| Metric | Value | Source |
| --- | --- | --- |
| Approach | PS3.15-oriented **custom subset** (not certified full Basic Profile) | `deidentification_ps315_openneuro_audit.md` |
| BIDS PHI scrub sample | Patient*/InstitutionName/dates/DeviceSerial absent in 250 sidecars | same |
| `InstitutionalDepartmentName` | Present (often `"Department"`) | same; privacy audit |
| Burned-in audit | 0 YES / 0 NO / 1133 absent (sampled series) | `privacy_audit/PUBLICATION_PRIVACY_READINESS.md` |
| Free-text review | SeriesDescription/ProtocolName REVIEW_REQUIRED | same |
| Public DICOM mirror | Not available (`deid_dicom/` missing) | same |
| Report path note | Reports live under `reports/privacy_audit/` (not `reports/privacy/`) | Flag path mismatch |

## Associated / non-DICOM source data

| Metric | Value | Source |
| --- | --- | --- |
| Files inventoried under raw_original | 5756 (19.260 GB) | `reports/associated_data_summary.md` |
| Categories | eye_tracking 448; physiology 339; stimulus 3716; task_timing 1108; unknown 145 | same |
| BIDS conversion of physio | Not distributed as BIDS physio (metadata gaps) | methods draft |

---

## Missing / incomplete (do not invent)

1. Full-cohort MRIQC IQM summary tables (only pilot `reports/mriqc/` + partial array).  
2. Completed DWI QC report for all 361 scans.  
3. Full-cohort defacing geometry/difference audit (dry-run sample only); 4 T1w still missing at audit snapshot.  
4. Repository DOI, license, and citation (placeholders required).  
5. Author list beyond placeholder `Neuro BIDS Pipeline` in `dataset_description.json`.  
6. Site/institution address (intentionally removed by de-id).  
7. BIDS physiology files (none present).  
8. Certified DICOM PS3.15 Basic Profile conformance (explicitly **not** claimed).
