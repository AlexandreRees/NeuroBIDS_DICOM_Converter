# FreeSurfer anatomy hypotheses for MRIQC T1w IQMs (M0–M4)

This note specifies future mixed models. It is not a results document.
No model in this file has been fit. Extraction lives in
`study/code/extract_freesurfer_anatomy.py` and writes
`study/metadata/freesurfer_anatomy.tsv` from **FreeSurfer 7.4.1** only
(`derivatives/freesurfer/`). FreeSurfer 6.0.1 / HCP outputs in
`aim2_processed_data` are out of scope and must not be merged.

The MRIQC analysis unit remains
`study/metadata/mriqc_iqm_physical_acquisition.tsv` (133 physical
acquisitions). That table is not modified. Anatomy is stored at
**subject × session** (one recon-all). `sub-043` `ses-02` has two
physical MRIQC rows that share one FreeSurfer reconstruction.

An anatomy–IQM association is not a biological pathology effect. The
goal is to separate (1) acquisition/scanner variation, (2) reconstruction
quality, (3) global brain size, (4) cortical morphometry, and (5) a
pre-specified visual-cortex secondary term.

## Source campaign

| Item | Value |
| --- | --- |
| FreeSurfer | 7.4.1 (`recon-all -all`) |
| Input | original `bids/` T1w_MPR, lowest remaining run per session |
| Output | `derivatives/freesurfer/sub-XXX_ses-YY` |
| Atlas for M4 | Desikan–Killiany `lh/rh.aparc.stats` |
| Not used | DKT, a2009s, HCP `recon-all.v6.hires`, `sub-C##` / `sub-G##` |

The FreeSurfer T1 is often **not** the NORM reconstruction kept in the
IQM table. Future models join on `subject_id` + `session`, not on run.

Completed physical-acquisition MixedLM models also included `session`.
M0 below follows the anatomy plan (no `session` in the formula). When
M1–M4 are fit, keep `session` if the scientific comparison is to those
already-run models; drop it only with a pre-specified reason. This
extraction does not decide that.

## M0 — reference (already run; do not refit here)

```
IQM ~ acquisition + age + sex + cohort + (1 | subject)
```

Acquisition is the existing physical-acquisition factor (e.g.
`software_platform`, or SAR / TxRefAmp in separate models — not a
joint collinear block). Demographics come from the MRIQC table.

M0 is the baseline that attributes IQM variation to acquisition and
demography, with a subject random intercept.

## M1 — reconstruction quality

```
IQM ~ acquisition + Euler_mean + age + sex + cohort + (1 | subject)
```

Primary added term: **`Euler_mean`**.

`Euler_L` and `Euler_R` are extracted for completeness. Do **not**
enter `Euler_mean` together with `Euler_L` and/or `Euler_R`.
`Euler_asymmetry` is secondary and is not the default M1 term.

Euler numbers are derived from `aseg.stats` `lhSurfaceHoles` /
`rhSurfaceHoles` (pre-topology-fix), equivalent to
`mris_euler_number` on `surf/?h.orig.nofix`. No Euler cutoff is applied
and no subject is dropped by this extraction. A stub `recon-all.done`
without `SUBJECT`/`END_TIME` is not counted as success (see
`sub-019` `ses-01`, which also has `recon-all.error`).

M1 asks whether IQM associations with acquisition remain after a
standard FreeSurfer surface-defect summary.

## M2 — global brain size

```
IQM ~ acquisition + Euler_mean + eTIV + age + sex + cohort + (1 | subject)
```

Primary size term: **`eTIV`**, when a single global-size covariate is
appropriate.

Also extracted, not auto-entered: `BrainSegVol`, `CortexVol`,
`CerebralWhiteMatterVol`. Do not dump all four into one model. They are
collinear size/tissue summaries, not independent biological effects.

M2 is not for every IQM. It is most relevant where the IQM can scale
with head or tissue amount (morphology / tissue fractions, some
intensity summaries). It is not a default covariate for smoothness,
entropy, or artifact IQMs unless a specific mechanism is stated.

## M3 — global cortical morphometry

```
IQM ~ acquisition + Euler_mean + mean_cortical_thickness + age + sex + cohort + (1 | subject)
```

Primary morphology term: **`mean_cortical_thickness`**.

`total_cortical_volume` and `total_cortical_surface_area` are stored as
separate columns because thickness, volume, and area are related
(`volume ≈ thickness × area`) and must not be thrown into the same
model by default. `total_cortical_volume` is the same FreeSurfer
`CortexVol` value as the M2 column `CortexVol`; do not enter both.

M3 is aimed at IQMs that can track cortical gray-matter geometry or
partial-volume (e.g. tissue-class families). It is not a blanket
adjustment for all 56 IQMs.

## M4 — secondary visual cortex

```
IQM ~ acquisition + Euler_mean + visual_cortex_mean_thickness + age + sex + cohort + (1 | subject)
```

Primary M4 term: **`visual_cortex_mean_thickness`**, the pre-specified
equal-weight mean of bilateral Desikan–Killiany thickness in
pericalcarine, cuneus, lingual, and lateraloccipital.

The four regional columns are available for description or a planned
follow-up. This is **not** a mass-univariate test of all aparc labels.

M4 is pathology-relevant only in the weak sense that this study
concerns the visual system. A significant M4 term does **not** mean the
IQM is a glaucoma or optic-neuropathy biomarker.

## What not to do

- Do not mix FreeSurfer 6.0.1/HCP metrics with this table.
- Do not treat Euler as an automatic exclusion rule.
- Do not enter Euler mean + left + right together.
- Do not enter eTIV + BrainSegVol + CortexVol + WM volume together.
- Do not enter thickness + cortical volume + surface area together.
- Do not add anatomy covariates indiscriminately to every IQM.
- Do not interpret anatomy–IQM coefficients as disease effects.
- Do not rerun MRIQC or rewrite the 133-row physical-acquisition table.
