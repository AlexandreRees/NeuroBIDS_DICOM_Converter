# FreeSurfer anatomical integration

generated_utc: 2026-09-10T16:14:46.389005+00:00
FreeSurfer version: 7.4.1 (fs_t1w_mpr / derivatives/freesurfer).
HCP-FS 6.0.1 was not used.
Canonical MRIQC table was not modified.

## Counts before models
- N MRIQC physical acquisitions: 133
- N MRIQC subjects: 83
- N MRIQC subject×session cells: 132
- N FreeSurfer subject×session rows: 132
- N FreeSurfer complete (aseg+aparc, 7.4.1): 131
- N subject×session matches MRIQC∩manifest: 132
- Duplicate physical_acquisition_id after JOIN: 0
- JOIN rows: 133 (must be 133)
- JOIN rows with FreeSurfer anatomy: 132 (131 complete sessions; sub-043 ses-02 has 2 physical acquisitions)
- JOIN rows without FreeSurfer: 1 (sub-019 ses-01 recon-all failed)

## Anatomical variables
Primary candidates: ICV (eTIV), total cortical GM (CortexVol), total WM
(CerebralWhiteMatterVol), mean cortical thickness.
Selected after VIF (threshold 5): icv_etiv, total_wm, mean_cortical_thickness
Dropped for collinearity: total_cortical_gm (VIF=5.75)
Hippocampal volumes and FreeSurfer CSF (SegId 24) were extracted and not
entered in the primary model.

Missingness on the 133-row JOIN:
- icv_etiv: 0.008
- brainseg_vol: 0.008
- total_cortical_gm: 0.008
- total_wm: 0.008
- total_csf: 0.008
- mean_cortical_thickness: 0.008
- left_hippocampal_volume: 0.008
- right_hippocampal_volume: 0.008

## Variance classes (OLS R²; not causal, not 'pure biology')
- anatomy-associated: 26  icvs_gm, icvs_wm, rpve_csf, rpve_gm, rpve_wm, snr_gm, snr_total, snr_wm, summary_bg_mad, summary_bg_median, summary_csf_k, summary_csf_mad, summary_csf_mean, summary_csf_p05, summary_csf_p95, summary_gm_mad, summary_gm_p05, summary_gm_p95, summary_gm_stdv, summary_wm_mad, summary_wm_mean, summary_wm_p05, summary_wm_p95, summary_wm_stdv, tpm_overlap_csf, tpm_overlap_wm
- acquisition-associated: 0  none
- mixed: 3  fwhm_avg, fwhm_y, fwhm_z
- low-explained-variance: 27

Largest ΔR² anatomy:
- rpve_csf: ΔR²=0.540  R2_A=0.000  class=anatomy-associated
- rpve_gm: ΔR²=0.532  R2_A=0.000  class=anatomy-associated
- rpve_wm: ΔR²=0.532  R2_A=0.000  class=anatomy-associated
- summary_gm_mad: ΔR²=0.245  R2_A=0.000  class=anatomy-associated
- icvs_gm: ΔR²=0.178  R2_A=0.021  class=anatomy-associated
- summary_gm_stdv: ΔR²=0.177  R2_A=0.013  class=anatomy-associated
- snr_gm: ΔR²=0.176  R2_A=0.015  class=anatomy-associated
- summary_gm_p95: ΔR²=0.154  R2_A=0.010  class=anatomy-associated

Largest R² acquisition (Model A):
- fwhm_z: R2_A=0.076  ΔR² anatomy=0.051
- fwhm_y: R2_A=0.073  ΔR² anatomy=0.062
- fwhm_avg: R2_A=0.071  ΔR² anatomy=0.058
- summary_csf_stdv: R2_A=0.049  ΔR² anatomy=0.082
- summary_csf_p95: R2_A=0.045  ΔR² anatomy=0.101
- fwhm_x: R2_A=0.044  ΔR² anatomy=0.047
- summary_wm_k: R2_A=0.032  ΔR² anatomy=0.055
- wm2max: R2_A=0.031  ΔR² anatomy=0.011

## Cohort association (Glaucoma vs Control)
Wording: the cohort association was attenuated after anatomical adjustment.
Do not read this as 'biology caused the IQM difference'.
- persistent after anatomy (FDR): summary_bg_mad, summary_bg_mean, summary_bg_median, summary_bg_p95, summary_bg_stdv
- attenuated after anatomy: cjv, cnr, efc, icvs_wm, inu_med, inu_range, summary_gm_k, summary_gm_p95, summary_gm_stdv, summary_wm_p95
- appearing after anatomy: none

## Circularity
IQM whose MRIQC definition uses tissue segmentation, a brain mask, or
GM/WM/CSF estimates are flagged anatomy_sensitive_by_construction=TRUE.
rpve_*, icvs_* and tissue intensity summaries are anatomy-sensitive by
construction; their ΔR² is not independent biological evidence.

## Limitations
- FreeSurfer-derived anatomy is not an independent ground truth of biology.
- Some MRIQC IQMs are themselves dependent on tissue segmentation/brain masks.
- Cohorts are unbalanced.
- Data_ON and Data_TON are small.
- Scanner platform effect E11 vs XA30 is based on only n=6 XA30 acquisitions.
- Cross-sectional anatomical adjustment cannot establish causality.
- Missing FreeSurfer outputs reduce the analytical sample if applicable.
- OLS R² ignores repeated sessions within subject; MixedLM is a sensitivity check only.

## Files
- study/qc_reports/mriqc_iqm/freesurfer_integration_audit.tsv
- study/metadata/freesurfer_anatomical_summary.tsv
- study/qc_reports/mriqc_iqm/freesurfer_qc_summary.tsv
- study/metadata/mriqc_iqm_physical_acquisition_freesurfer.tsv
- study/qc_reports/mriqc_iqm/anatomical_adjustment_models.tsv
- study/qc_reports/mriqc_iqm/cohort_effect_anatomical_adjustment.tsv
- study/qc_reports/mriqc_iqm/anatomical_variance_decomposition.tsv
- study/qc_reports/mriqc_iqm/longitudinal_anatomical_adjustment.tsv
- study/qc_reports/mriqc_iqm/figure_anatomical_variance.pdf
- study/qc_reports/mriqc_iqm/figure_cohort_anatomical_adjustment.pdf
- study/qc_reports/mriqc_iqm/figure_iqm_predictor_heatmap.pdf
