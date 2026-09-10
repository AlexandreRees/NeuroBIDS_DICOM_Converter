# MRIQC statistical audit and manuscript plan

generated_for: Data in Brief / Scientific Data
status: AUDIT ONLY — no models were refit, no historical outputs overwritten
canonical_mriqc: study/metadata/mriqc_iqm_physical_acquisition.tsv (133 rows)
joined_anatomy: study/metadata/mriqc_iqm_physical_acquisition_freesurfer.tsv (133 rows)

This document is the Phase 1 deliverable. Costly analyses must not be launched
until the plan below is validated.

---

## 1. What already exists (inventory)

Two generations of analyses coexist. They must stay on disk. Only the
physical-acquisition generation is eligible as **primary** for the manuscript.

### Generation A — reconstruction-level (264 T1w rows)

Pseudoreplicated: most sessions contribute NORM + non-NORM reconstructions of
one physical T1w_MPR. Files remain as historical record.

| Analysis | Script | Status for manuscript |
|---|---|---|
| Master table (380 rows T1w+WMn) | `mriqc_iqm_master.py` | Provenance only |
| Cleaning, outliers flagged not dropped | `mriqc_iqm_cleaning.py` | Keep methods; 264-row stats not primary |
| Spearman T1w/WMn (264 / 116) | `mriqc_iqm_correlation.py` | Historical |
| PCA T1w 264-row | `mriqc_iqm_pca.py` | Historical / comparison |
| Cohort tests on PCs (264) | `mriqc_iqm_cohort_analysis.py` | Historical |
| Longitudinal 264-row | `mriqc_iqm_longitudinal.py` | Historical (interaction hits did not replicate) |
| Session-level 132-row (one FS-selected T1w) | `mriqc_iqm_session_level.py` | Alternate unit; not the 133-row physical unit |
| Acquisition metadata on session table | `mriqc_iqm_acquisition_analysis.py` | Inventory useful; unit is 132 not 133 |

### Generation B — physical-acquisition (133 rows) — current scientific unit

| Analysis | Script / output | Assessment |
|---|---|---|
| Reconstruction audit; 133-row table | `mriqc_iqm_physical_acquisition_table.py` | **Correct and must remain the unit of analysis** |
| Table QC audit | `mriqc_iqm_physical_acq_table_audit.py` | Correct |
| Spearman 133-row | `mriqc_iqm_physical_acq_correlation.py` | Correct structure analysis |
| PCA 133-row + loading summary | `mriqc_iqm_pca_physical_acq*.py` | Correct as **structure**, not as hypothesis test |
| PCA 264 vs 133 comparison | `mriqc_iqm_pca_physical_acq_comparison.py` | Keep as justification of the 133-row unit |
| PCA-as-outcome cohort MixedLM | `mriqc_iqm_pca_cohort_physical_acq.py` | Exploratory; MixedLM FDR none |
| Longitudinal MixedLM 133-row | `mriqc_iqm_longitudinal_physical_acq.py` | Correct sensitivity; interaction FDR 0/56 |
| NORM vs non-NORM paired descriptive | `mriqc_iqm_norm_reconstruction_sensitivity.py` | Correct sensitivity (not independent n) |
| Acquisition MixedLM (platform, SAR, TxRefAmp) | `mriqc_iqm_acquisition_physical_acq.py` | Correct inventory; XA30 n=6 exploratory |
| Cohort after software_platform MixedLM | same | Closest existing Model 1; no anatomy |
| Family robustness MixedLM | `mriqc_iqm_family_robustness_physical_acq.py` | Useful sensitivity of FDR families |
| Nakagawa R² acquisition vs cohort | `mriqc_iqm_variance_explained_physical_acq.py` | Useful but **anatomy absent**; R² includes age+sex+session in the “acquisition” block |
| Elastic Net Control vs Glaucoma | `mriqc_iqm_elastic_net_physical_acq.py` | Already nested, subject-grouped CV — keep as **predictive/exploratory** |
| FreeSurfer 7.4.1 extract | `extract_freesurfer_anatomy.py` | Correct source restriction |
| FS join + OLS anatomy adjustment | `mriqc_iqm_freesurfer_anatomical_adjustment.py` | Scientifically right question; **OLS is statistically inadequate as primary** |

No project README exists under `study/`. There is no `statistics/`,
`figures/`, or `tables/` split. ~79 PNG/PDF live in `qc_reports/mriqc_iqm/`.

---

## 2. Definitions that must be frozen

**Unit of analysis (primary):** one physical T1w_MPR acquisition.
Canonical n = 133, subjects = 83, subject×session = 132.
Exception kept: `sub-043 ses-02` contributes two independent physical scans
(two MRIQC rows, one FreeSurfer recon).

**Not an independent observation:** Siemens NORM vs non-NORM of the same
k-space. Prefer-NORM selection is sidecar/DICOM-based, never IQM-based.

**Session:** BIDS `ses-01` / `ses-02`. 49 subjects have both sessions
(Control 39, Glaucoma 8, Data_ON 1, Data_TON 1).

**Cohort:** Control (55 subjects / 95 acq), Glaucoma (19 / 27), Data_ON (7 / 8),
Data_TON (2 / 3). Reference = Control. Data_ON and Data_TON are too small for
population inference; coefficients may be shown as descriptive only.

**IQMs for statistics:** 56 non-constant T1w IQMs from
`pca_physical_acq_loadings.tsv`. Zero-variance `qi_1` and `summary_bg_p05`
documented, not modelled. IQM missingness on the 133-row table = 0.

**Acquisition that actually varies:**

| Candidate | Status on 133-row table |
|---|---|
| MagneticFieldStrength | constant 3 T |
| TR / TE / TI / FA | constant (2.5 / 0.00222 / 1.0 / 8) |
| voxel size / matrix / FOV | constant 0.8 mm, 208×300×320 |
| ProtocolName | constant T1w_MPR |
| coil | HeadNeck_64 (missing on 6 XA30 rows) |
| software_platform E11 vs XA30 | **only categorical acquisition split**, XA30 n=6; collinear with scanner, SoftwareVersions, and non-NORM in this selected table |
| SAR, TxRefAmp | vary within E11 (n=127); missing exactly on the 6 XA30 rows |

A rich “acquisition + voxel + FOV + field strength” model **cannot be fit**.
The manuscript must say the protocol is homogeneous; residual acquisition
signal is software platform (underpowered) and within-E11 transmit/SAR
(exploratory technical sensitivity).

**Anatomy (FreeSurfer 7.4.1 only):** 131/132 recon-all complete. Failure:
`sub-019 ses-01`. HCP-FS 6.0.1 unused. Primary covariates after VIF:
`icv_etiv`, `total_wm`, `mean_cortical_thickness`. `total_cortical_gm` dropped
(VIF 5.75). Hippocampus and aseg CSF (SegId 24) extracted, not in primary
model. FreeSurfer input T1w is often the lowest-run T1w_MPR, **not** the NORM
row kept in MRIQC — join is subject×session, not run.

**Wording (already correct, keep):**
“the cohort association was attenuated after anatomical adjustment.”
Never: biology/anatomy *caused* the IQM difference.

---

## 3. What is statistically adequate vs not

### Adequate (reuse)

- Physical-acquisition unit and reconstruction audit.
- Outliers flagged, never auto-deleted.
- Anatomy-sensitive-by-construction annotation (definition-based, not r-based).
- Elastic Net: StratifiedGroupKFold by `subject_id`, scaler inside folds,
  Control vs Glaucoma only, Data_ON/TON excluded. Treat as predictive only
  (pooled OOF AUC 0.691).
- PCA on 133 z-scored IQMs as redundancy/structure (PC1 26.6% intensity/contrast/SNR;
  PC3 FWHM-loaded). Do not use PC scores as the primary cohort test.
- Longitudinal MixedLM without anatomy: cohort×session FDR 0/56 after moving
  to 133 rows. That negative result should be preserved.
- XA30 n=6 already labelled exploratory in acquisition reports.
- Canonical table hash lock (`be1d89fd…`).

### Statistically inadequate as *primary* (keep files; demote)

- **OLS anatomical models** (`anatomical_adjustment_models.tsv`, ΔR², cohort
  before/after figures): ignore within-subject correlation (49 returners).
  Primary must be MixedLM with `(1 | subject_id)`. OLS becomes sensitivity.
- **Variance class “acquisition-associated = none”** is an OLS artefact.
  Model A was `IQM ~ software_platform` only. MixedLM
  `software_platform + age + sex + session + (1|subject)` already FDR-hits
  FWHM. Classification must not rest on that OLS R² threshold.
- **Attenuation = beta_after / beta_before** is not the measure requested
  for the paper. Also missing explicit Model 0 (cohort only) vs Model 1
  (+acquisition) vs Model 2 (+anatomy). Age/sex are currently mixed into
  the acquisition path.
- **No a priori classification rule** combining FDR family, effect size, CI,
  ΔR², and sensitivity. Current bins use post-hoc R² cutoffs (0.05 / 0.10).
- **No OLS/LMM diagnostics** (Cook, leverage, residual plots, mixed-model
  singularity) as a reported step.
- **No systematic sensitivity suite** (exclude XA30, exclude FS failure only
  vs complete-case, robust SE, Control+Glaucoma only, influential points).
- **FDR families differ by script** (56 IQMs; CORE vs TISSUE; separate
  software_platform / SAR / TxRefAmp families). Must be pre-specified once.

### Redundant (do not delete; exclude from primary results)

- All 264-row PCA, Spearman, cohort, longitudinal.
- Session-level 132-row models that pick a different T1w than the 133-row table.
- Duplicate PCA scatter pages (PC1–PC2, PC1–PC3, PC2–PC3 × two generations).
- WMn heatmaps for a T1w_MPR physical-acquisition paper.
- Visual-cortex M4 terms in `freesurfer_anatomy.tsv` (out of scope unless a
  named secondary analysis is approved).
- Planned “FreeSurfer extension not implemented” paragraphs that are now stale
  in older reports (leave historical text; do not present as current).

### Missing for a defensible manuscript

1. One pre-registered-style analysis plan (this document, then a frozen
   `analysis_parameters.json`).
2. MixedLM primary hierarchy: acquisition → anatomy → cohort.
3. Partial R² / Nakagawa incremental R² for the three families.
4. Explicit attenuation metric and Model 0/1/2 table.
5. IQM clustering (hierarchical, Spearman) + decision table
   (domain × evidence level).
6. Diagnostics + sensitivity matrix.
7. Curated 7-figure / 10-table manuscript set (not 79 files).
8. Reproducibility folder layout and run log.
9. `MANUSCRIPT_STATISTICAL_SUMMARY.md` after the validated rerun.

---

## 4. Proposed primary statistical framework

**Question:** To what extent are MRIQC anatomical IQMs associated with
acquisition characteristics, anatomical characteristics, and cohort, and are
cohort-associated IQM differences attenuated after accounting for subject
anatomy?

Not a causal biological study.

### Exposure blocks (hierarchy)

**A. Acquisition (inferential, exploratory because of n)**  
Primary categorical: `software_platform` (E11 vs XA30), always labelled
n_XA30=6. Do not co-enter scanner / SoftwareVersions / NORM.  
Secondary technical (E11-only n=127): SAR or TxRefAmp (not both; r≈0.70).  
Constants (3 T, voxel, FOV, TR/TE/FA, protocol) reported in Table 1, not modelled.

**B. Anatomy**  
`icv_etiv + total_wm + mean_cortical_thickness`. Hippocampus = named
secondary. Do not re-enter `total_cortical_gm`.

**C. Cohort**  
`C(cohort, Treatment("Control"))`. Data_ON / Data_TON coefficients
descriptive. Inferential cohort claims restricted to Control vs Glaucoma
unless a sensitivity that drops small cohorts is shown.

**Demographics (adjustment, not an exposure family):** age + sex.
**Repeated measures:** session as a fixed factor when scientifically comparing
visits; random intercept `(1 | subject_id)` always in the primary LMM.

### Primary models per IQM (MixedLM, complete-case anatomy n=132)

Keep OLS as sensitivity only.

- **M_acq:** `IQM ~ software_platform + age + sex + session + (1|subject)`
- **M_anat:** `IQM ~ icv_etiv + total_wm + mean_cortical_thickness + age + sex + session + (1|subject)`
- **M0:** `IQM ~ cohort + age + sex + session + (1|subject)`
- **M1:** `IQM ~ cohort + software_platform + age + sex + session + (1|subject)`  *(already exists)*
- **M2:** `IQM ~ cohort + software_platform + age + sex + session + anatomy + (1|subject)`

Report: beta, SE, 95% CI, p, Nakagawa R²_m / R²_c, incremental R² for each
block, FDR within a pre-specified family.

**Attenuation (Control vs Glaucoma only), if |β_M0| > 0:**

`attenuation = 1 − |β_M2| / |β_M0|`

Also report `|β_M1| / |β_M0|` (acquisition path) vs `|β_M2| / |β_M1|`
(anatomy path). Do not interpret as mediation.

### FDR families (freeze before rerun)

| Family | Tests | IQMs |
|---|---|---|
| acquisition_platform | 56 | XA30 coefficient or Wald in M_acq |
| anatomy_block | 56 | Wald / incremental R² p for anatomy in M_anat |
| cohort_glaucoma_M0 | 56 | Glaucoma vs Control in M0 |
| cohort_glaucoma_M2 | 56 | Glaucoma vs Control in M2 |
| longitudinal_interaction | 56 | cohort×session in Control+Glaucoma only, labelled underpowered |

Do not FDR Data_ON/TON as discovery. Do not pool SAR, platform, anatomy, and
cohort into one 200-test FDR.

### Classification (a priori, not p-only)

An IQM is **acquisition-associated** if (i) family FDR q<0.05 for platform
**or** a pre-specified standardized |β| threshold, **and** (ii) the sign is
stable in ≥2 sensitivities, **and** (iii) XA30 result is still called
exploratory because n=6.  
**Anatomy-associated:** incremental anatomy R² ≥ 0.10 **or** anatomy FDR,
with `anatomy_sensitive_by_construction` flagged when true.  
**Cohort-associated:** Glaucoma FDR in M0.  
**Attenuated:** cohort FDR lost or attenuation ≥ 0.30 after M2, same sign.  
**Persistent:** Glaucoma FDR in M0 and M2, attenuation < 0.30.  
**Mixed:** meets both acquisition and anatomy criteria.  
**Weak/unstable:** fails sensitivity or CI crosses 0 after robust/outlier
checks.  
rpve_* / icvs_* / tpm_overlap_* / tissue summaries: never “independent biology”.

### Longitudinal

Primary LMM already includes session. Test `cohort × session` **only** as
sensitivity in Control+Glaucoma (Glaucoma returners = 8). Do not present
random slope as primary unless it converges and AIC/LRT supports it.
Data_ON/TON trajectories: figure optional, no inferential interaction.

### PCA / Elastic Net

Do not rerun as hypothesis tests. Optional: refresh PCA figure styling;
Elastic Net already manuscript-usable as exploratory. Bootstrap CI on OOF
AUC is a cheap add-on, not mandatory for the first validated rerun.

### interpret-iqms (brainhack-ch)

Reuse the *idea* (IQMs are redundant, clustered, not quality scores), not
their pipeline. We already have Spearman + PCA. Add hierarchical clustering
on the 133-row Spearman matrix (56 IQMs). Do not add a new ML importance
model unless Elastic Net is insufficient.

---

## 5. Scripts: modify vs leave vs add

**Do not modify (historical generators):**
`mriqc_iqm_pca.py`, `mriqc_iqm_cohort_analysis.py`, `mriqc_iqm_longitudinal.py`,
`mriqc_iqm_correlation.py`, `mriqc_iqm_session_level.py`, and the physical-acq
scripts that already wrote Generation B tables.

**Do not overwrite:**
`mriqc_iqm_physical_acquisition.tsv`, `mriqc_iqm_clean.tsv`, 264-row PCA/cohort
TSVs, `robustness_variance_elastic_net_summary.txt` sections 1–9 (append only),
existing `*_physical_acq_*` result TSVs.

**New (after validation), e.g. `study/statistics/`:**
- `00_analysis_parameters.json` (n, formulas, FDR families, seeds, hashes)
- `01_iqm_structure.py` (clustering + distribution/skew table from 133-row)
- `02_primary_mixedlm.py` (M_acq, M_anat, M0, M1, M2)
- `03_classification_table.py`
- `04_sensitivity.py` (XA30 out, Control+Glaucoma, robust, Cook)
- `05_manuscript_figures_tables.py`
- `06_write_manuscript_summary.py`

`mriqc_iqm_freesurfer_anatomical_adjustment.py` stays as the OLS sensitivity
source; do not silently replace its TSVs. New MixedLM outputs get new names
(`primary_mixedlm_*.tsv`).

---

## 6. Recommended `study/` layout (additive)

```
study/
  metadata/                 # canonical tables stay here (read-only)
  code/                     # historical scripts (frozen)
  qc_reports/mriqc_iqm/     # historical reports/figures (frozen)
  statistics/               # NEW manuscript pipeline + parameters.json
  tables/manuscript/        # NEW numbered Table 1–10
  figures/manuscript/       # NEW Figure 1–7 (PDF+PNG)
  qc_reports/mriqc_iqm/     # append-only summaries
```

Do not move historical files. Point manuscript tables at copies or new
exports, never replace Generation A/B paths.

---

## 7. Decisions requested before any heavy rerun

See the chat summary: five analyses to launch, what to keep, what to demote,
figures, folder layout. No MixedLM/Elastic Net/PCA refit in this pass.
