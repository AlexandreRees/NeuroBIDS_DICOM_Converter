# MRIQC figure legends (PI / publication)

All figures: `reports/mriqc_publication_audit/figures/` (300 dpi PNG + vector PDF).  
Regenerate: `python3 code/mriqc_publication_audit/generate_mriqc_pi_figures.py`

---

### Figure 1 — Cohort coverage
**File:** `Fig01_MRIQC_coverage_summary`  
**Caption:** MRIQC coverage on 24 July 2026 for complete sessions, T1w IQMs, magnitude BOLD IQMs, and all T1w+BOLD scans. The four missing IQMs correspond to truncated or out-of-protocol acquisitions.

### Figure 2 — Progression after ACF fix
**File:** `Fig02_MRIQC_coverage_progression`  
**Message:** Sessions 78.2% → 96.8%; BOLD 91.4% → 99.9% after AFNI `3dFWHMx` ACF correction.

### Figure 3 — BOLD distributions (quality)
**File:** `Fig03_BOLD_fd_tsnr_distributions`  
**Message:** Median fd_mean = 0.176 mm; median tSNR = 20.9 (n≈1357). Highlights overall functional quality.

### Figure 4 — T1w quality (all protocols)
**File:** `Fig04_T1w_cnr_cjv_snr`  
**Message:** CNR / CJV / SNR_total — all T1w IQMs pooled (n≈354). Bimodal because two protocols are mixed.

### Figure 4a — T1w_MPR only
**File:** `Fig04a_T1w_MPR_cnr_cjv_snr`  
**Message:** Standard MPRAGE (`T1w_MPR`, typically run-01/02, 0.8 mm).

### Figure 4a1 / 4a2 / by-run — T1w_MPR split by run
**Files:** `Fig04a1_T1w_MPR_run-01_cnr_cjv_snr`, `Fig04a2_T1w_MPR_run-02_cnr_cjv_snr`, `Fig04a_T1w_MPR_by_run_cnr_cjv_snr`  
**Message:** Same protocol; run-02 has Siemens `ImageType` **NORM** (intensity normalize) vs run-01 `ND` only — higher CNR/SNR, lower CJV on run-02. See `T1w_MPR_run01_vs_run02_IQM.md`.  
**Regen:** `python3 code/mriqc_publication_audit/make_fig04a_by_run.py`

### Figure 4b — WMn_MPRAGE only
**File:** `Fig04b_WMn_MPRAGE_cnr_cjv_snr`  
**Message:** White-matter-nulled MPRAGE (`WMn_MPRAGE_sagittal`, typically run-03, 1.0 mm).

### Figure 5 — Quality by paradigm
**File:** `Fig05_BOLD_quality_by_task`  
**Message:** Motion and tSNR for `control`, `fmri`, `movie`, `rest` (boxplots).

### Figure 6 — Completeness (donut)
**File:** `Fig06_MRIQC_completeness_donut`  
**Message:** **99.8%** of scans with IQM (1848/1852).

### Figure 7 — High-motion subjects
**File:** `Fig07_high_motion_subjects`  
**Message:** Transparency — top 10 subjects by mean fd_mean; exploratory flags, not exclusions.

### Figure 8 — Four acquisitions without IQM
**File:** `Fig08_four_missing_acquisitions`  
**Message:** BIDS evidence (volumes / FOV) justifying missing IQMs for publication.

### Figure 9 — PI one-pager
**File:** `Fig09_PI_onepager_quality_summary`  
**Use:** open the PI meeting with this single slide.

---


### Figure 10 — Complete IQM means (all metrics)
**File:** `Fig10_MRIQC_IQM_means_complete`  
**Message:** Full cohort means for **30 T1w + 20 BOLD** MRIQC IQMs (n=354 / 1494). Use for appendix / detailed PI slide.

### Figure 10b — Headline IQM means (PI slide)
**File:** `Fig10b_MRIQC_IQM_means_headline`  
**Message:** Compact 12-metric table (fd_mean, tSNR, CNR, CJV, …) for the main PI presentation.

---

## Suggested slide order (8–10 min)

1. Fig09 (1 min)  
2. Fig01 + Fig06 (2 min)  
3. Fig10b (IQM means) + Fig03/Fig04 (3–4 min)
3b. Fig10 if the PI wants the full metric list  
4. Fig08 (2 min)  
5. Fig02 if technical questions (1–2 min)  
6. Fig07 only if the PI asks about “bad” subjects
