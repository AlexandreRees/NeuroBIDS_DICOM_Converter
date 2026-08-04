# Technical Validation — MRIQC (English draft for Scientific Data)

Ready-to-adapt manuscript text. Numbers audited 2026-07-24.

---

## Suggested subsection

**Automated image quality control (MRIQC).**  
Anatomical (T1-weighted) and functional (BOLD) acquisitions were evaluated with MRIQC 24.0.2. Participant-level HTML reports and JSON image-quality metric (IQM) files are released under `derivatives/mriqc/`. Group-level summary tables, within-dataset reference ranges, and exploratory outlier flags are provided under `derivatives/mriqc/group_qc/`.

At the time of release packaging, MRIQC IQMs were available for **1848 / 1852** expected magnitude T1w and BOLD scans (**99.8%**), covering **84 / 84** participants. Session-level completeness (all expected T1w and magnitude BOLD IQMs present) was achieved for **120 / 124** sessions (**96.8%**).

Four acquisitions lacked IQM outputs after repeated processing. Inspection of the corresponding BIDS NIfTI files showed that these series were incomplete or out of protocol rather than MRIQC software failures: two `task-fmri` BOLD runs contained only 3–4 volumes (protocol length ≈226 volumes), and two T1-weighted series showed abnormal field-of-view and intensity ranges relative to co-session anatomical siblings. MRIQC terminated for these inputs with an empty inhomogeneity-corrected volume error. These four series are retained in the raw BIDS tree for provenance and are explicitly noted here; they are not interpreted as general dataset failure.

Cohort IQM distributions were summarised within-dataset (group aggregation dated 2026-07-23; n = 1707 scored acquisitions at aggregation time). For BOLD runs, median framewise displacement (`fd_mean`) was **0.176 mm** (95th percentile 0.375 mm) and median temporal SNR was **20.9**. For T1-weighted images, median contrast-to-noise ratio was **1.51** and median coefficient of joint variation was **0.629**. Exploratory outlier labels were computed using robust within-cohort statistics (absolute z-score > 3 and Tukey interquartile fences). These labels are provided to support transparent reuse and are **not** used as automatic exclusion criteria for the public release.

A transient AFNI `3dFWHMx` autocorrelation-function (ACF) failure initially prevented IQM JSON generation for a subset of runs; this was addressed in the release workflow by forcing classic FWHM estimation (`acf=False`) in the fault-tolerant MRIQC entrypoint, after which coverage rose to the values reported above.

---

## Optional one-sentence Methods (short)

MRIQC 24.0.2 IQMs are released for 99.8% of expected T1w and magnitude BOLD scans (1848/1852); four incomplete/out-of-protocol acquisitions without IQMs are documented, and within-dataset IQM summaries with exploratory outlier flags are provided under `derivatives/mriqc/`.

---

## Optional Limitations bullet

- Four acquisitions (two truncated BOLD runs; two atypical T1-weighted series) could not be scored by MRIQC and are listed in the Technical Validation / release notes.
- Group IQM summary tables reflect the aggregation available at packaging; absolute IQM cut-offs from other sites should not be applied without justification.
