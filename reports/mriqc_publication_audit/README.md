# MRIQC publication audit — index

**Date:** 2026-07-24  
**Release verdict:** GO (99.8% of T1w+BOLD scans have IQMs)  
**Folder:** `reports/mriqc_publication_audit/`

## Documents

| File | Purpose |
| --- | --- |
| [MRIQC_PUBLICATION_AUDIT.md](MRIQC_PUBLICATION_AUDIT.md) | Full audit (PI + project archive) |
| [MRIQC_WARNINGS_AND_JUSTIFICATIONS.md](MRIQC_WARNINGS_AND_JUSTIFICATIONS.md) | **All warnings** with publication justifications |
| [Technical_Validation_MRIQC_EN.md](Technical_Validation_MRIQC_EN.md) | English text ready for Scientific Data |
| [FIGURES_README.md](FIGURES_README.md) | Figure legends for PI slides |
| [../mriqc_coverage_audit/MRIQC_PI_AUDIT_2026-07-24.md](../mriqc_coverage_audit/MRIQC_PI_AUDIT_2026-07-24.md) | Short PI briefing |

## PI figures (PNG + PDF)

Directory: `figures/`

| Figure | Key message |
| --- | --- |
| `Fig09_PI_onepager_quality_summary` | **Single slide** for the PI |
| `Fig01_MRIQC_coverage_summary` | Coverage 96.8–99.9% |
| `Fig02_MRIQC_coverage_progression` | Gain after AFNI ACF patch |
| `Fig06_MRIQC_completeness_donut` | 99.8% scans with IQM |
| `Fig03_BOLD_fd_tsnr_distributions` | BOLD quality (motion + tSNR) |
| `Fig04_T1w_cnr_cjv_snr` | T1w quality |
| `Fig05_BOLD_quality_by_task` | Quality by paradigm |
| `Fig07_high_motion_subjects` | High-motion subjects (exploratory) |
| `Fig08_four_missing_acquisitions` | Four justified exclusions |

Regenerate: `python3 code/mriqc_publication_audit/generate_mriqc_pi_figures.py`

## Tables

| File | Content |
| --- | --- |
| `tables/mriqc_iqm_current.tsv` | group_qc IQM table (n=1707; distributions) |
| `tables/warning_missing_iqms.tsv` | 4 missing IQMs + evidence |
| `tables/warning_high_motion_runs.tsv` | 23 runs with fd_mean ≥ 0.5 mm |
| `tables/warning_outlier_flag_counts_by_subject.tsv` | Outlier flag counts |
| `tables/warning_iqm_outliers_full.tsv` | Full outlier catalogue (736 flags) |

## Raw sources

- `derivatives/mriqc/` — HTML + JSON IQMs (1848 reports)
- `derivatives/mriqc/group_qc/` — cohort aggregate 2026-07-23
- `reports/mriqc_coverage_audit/` — coverage 2026-07-24
- `code/audit_mriqc_coverage.py`
