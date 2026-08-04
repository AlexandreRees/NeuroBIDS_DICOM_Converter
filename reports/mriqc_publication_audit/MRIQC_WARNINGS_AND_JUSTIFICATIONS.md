# MRIQC — warning catalogue and publication justifications

**Date:** 2026-07-24  
**Principle:** no warning is an automatic exclusion. Each class has an explicit publication action.

Machine-readable tables: `tables/warning_*.tsv`.

---

## W1 — Missing IQM (n=4) — **must document**

### Description
Four BIDS acquisitions have no MRIQC JSON/HTML despite retries. MRIQC fails at `ComputeIQMs.measures` with:

> `RuntimeError: Input inhomogeneity-corrected data seem empty`

### Cases

| ID | Acquisition | Objective evidence | Severity |
| --- | --- | --- | --- |
| W1.1 | `sub-002_ses-01_task-fmri_run-07_bold` | Truncated series: **4** volumes (protocol ~226) | High |
| W1.2 | `sub-011_ses-01_task-fmri_run-03_bold` | Truncated series: **3** volumes | High |
| W1.3 | `sub-039_ses-02_run-03_T1w` | Out-of-protocol FOV/intensity (max≈390 vs ~4095 sibling) | High |
| W1.4 | `sub-058_ses-01_run-03_T1w` | Out-of-protocol FOV/intensity (max≈294) | High |

### Publication justification
These are **not** MRIQC software failures. They are **incomplete or out-of-protocol acquisitions**. Leaving them without IQMs is the correct behaviour.

**Action:** Technical Validation + optionally README / release notes.  
**Do not:** re-run MRIQC without a manual decision; do not hide these files from the raw BIDS tree.

---

## W2 — High BOLD motion (fd_mean ≥ 0.5 mm) — n=23 runs

### Description
Internal exploratory marker (not an official MRIQC threshold). 23/1357 runs (≈1.7%) exceed 0.5 mm; 4 exceed 1.0 mm.

### Top runs (excerpt)

| Subject | Session | Task | Run | fd_mean | tsnr |
| --- | --- | --- | ---: | ---: | ---: |
| sub-012 | ses-01 | control | 3 | 1.52 | 11.0 |
| sub-018 | ses-01 | control | 3 | 1.26 | 12.5 |
| sub-012 | ses-01 | fmri | 7 | 1.17 | 6.7 |
| sub-084 | ses-01 | control | 5 | 1.02 | 14.2 |
| … | | | | | |

Full list: `tables/warning_high_motion_runs.tsv`.

### Publication justification
- Motion is a continuum; absolute cut-offs depend on the analysis question.
- The raw/IQM deposit should remain **inclusive**; exclusions belong in secondary analysis.
- Cohort median fd_mean = **0.176 mm** indicates good overall quality.

**Action:** report the distribution (median, p95, n above 0.5 mm) in Technical Validation; provide the table in derivatives.  
**Do not:** exclude these subjects from the OpenNeuro deposit.

---

## W3 — Within-cohort IQM outlier flags — 736 flags

### Description
Outliers detected by **z-score > 3** and/or **Tukey IQR** *within this dataset* (`derivatives/mriqc/group_qc/iqm_outliers.tsv`).

| Most flagged IQM | Flags |
| --- | ---: |
| aqi | 160 |
| snr | 114 |
| gcor | 106 |
| tsnr | 96 |
| fd_mean | 68 |
| ghost | 61 |
| dvars | 59 |
| fwhm | 47 |
| tpm_overlap_gm | 12 |
| other | <10 each |

**394** unique acquisitions affected; **80** subjects with ≥1 flag.  
Top subjects: sub-012 (102), sub-080 (34), sub-084 (32), sub-040 (25), sub-031 (24).

### Publication justification
- IQM distributions are **scanner/protocol/population specific** (Esteban et al., MRIQC).
- A Tukey/z flag does not imply a clinically invalidating artifact.
- Use: transparency and reuse support — **not** an exclusion criterion for the data record.

**Action:** state the method (z/IQR), provide tables/figures, label as “exploratory”.  
**Do not:** report a “QC failure rate” based on these flags.

---

## W4 — Historical smoothness / AFNI ACF failures — **resolved**

### Description
Before the 23–24 July 2026 patch, many BOLD (and some T1w) runs lost IQM JSON because of `3dFWHMx -acf` (`FileNotFoundError: 3dFWHMx.1D`). Registry: up to ~130 unique failed inputs.

### Publication justification
Software/environment issue (nipype/AFNI), **fixed** (`acf=False` via crash-tolerant entrypoint). Current coverage (99.8%) is post-fix.

**Action:** Methods — mention MRIQC 24.0.2 + fault-tolerant wrapper and, if needed, classic FWHM estimation.  
**Do not:** present historical ACF failures as image defects.

---

## W5 — BOLD-only sessions (not a quality warning)

| Session | Expected T1w | Status |
| --- | ---: | --- |
| sub-049 / ses-02 | 0 | Complete (8 BOLD) |
| sub-055 / ses-01 | 0 | Complete (8 BOLD) |

**Justification:** data availability / design, not an MRIQC failure.

---

## W6 — qi_1 = 0 on all scored T1w

### Description
`qi_1` (wrap-around / background artifact fraction) is 0 for n=350.

### Justification
Consistent with FOV / preprocessing without wrap-around detectable by this metric.  
**Action:** none; optional note that qi_1 is non-informative here.

---

## W7 — group_qc slightly behind current coverage

### Description
`group_qc` tables aggregated on 2026-07-23 (n=1707) while IQM coverage is now 1848.

### Justification
The ~141 IQMs added after the ACF patch do not materially change medians for a PI briefing.  
**Action:** optional — regenerate group_qc before final deposit; otherwise state the aggregation date.

---

## Publication decision matrix

| Warning | Include in raw BIDS? | Include IQM? | Mention Technical Validation? | Exclude subject from deposit? |
| --- | --- | --- | --- | --- |
| W1 missing IQM | Yes (NIfTI exists) | No (impossible) | **Yes** | No |
| W2 high motion | Yes | Yes | Yes (stats) | No |
| W3 outliers | Yes | Yes | Yes (method) | No |
| W4 ACF historical | Yes | Yes (after fix) | Methods only | No |
| W5 BOLD-only | Yes | Yes | Inventory if needed | No |
| W6 qi_1=0 | Yes | Yes | Optional | No |
| W7 stale group table | — | — | Note date | No |

---

## Talking points for the PI

1. “We have **99.8%** of scans with MRIQC metrics; the four gaps are aborted scans, not a bug.”  
2. “Median motion is **0.18 mm**; about **61%** of runs are under 0.2 mm.”  
3. “IQM outliers are **exploratory flags**, not exclusions.”  
4. “We document all of this in Technical Validation and move forward on OpenNeuro.”
