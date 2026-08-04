# MRIQC IQMs — cohort means (PI table)

**Source:** `derivatives/mriqc/` participant JSON (MRIQC 24.0.2)  
**Date:** 2026-07-24  
**Coverage:** 354 T1w + 1494 BOLD IQM files (**1848/1852** scans = **99.8%**)  

Means across all available IQM outputs. Direction = typical MRIQC interpretation (cohort-specific; not hard cut-offs).

## Headline metrics (slides)

| IQM | Modality | Unit | n | Mean | Median | SD | Dir. |
| --- | --- | --- | ---: | ---: | ---: | ---: | --- |
| `fd_mean` | BOLD | mm | 1494 | 0.1977 | 0.1758 | 0.1111 | ↓ better |
| `tsnr` | BOLD | a.u. | 1494 | 21.17 | 20.64 | 5.259 | ↑ better |
| `dvars_nstd` | BOLD | a.u. | 1494 | 65.99 | 64.96 | 12.31 | ↓ better |
| `fd_perc` | BOLD | % | 1494 | 36.33 | 37.08 | 24.29 | ↓ better |
| `cnr` | T1w | a.u. | 354 | 1.402 | 1.512 | 0.3845 | ↑ better |
| `cjv` | T1w | a.u. | 354 | 0.6913 | 0.6283 | 0.1705 | ↓ better |
| `snr_total` | T1w | a.u. | 354 | 4.638 | 5.520 | 2.131 | ↑ better |
| `qi_2` | T1w | a.u. | 354 | 0.000717 | 0.000572 | 0.000535 | ↓ better |

## T1w anatomical IQMs (complete)

| IQM | Description | Dir. | Unit | n | Mean | Median | SD | Min | Max |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `cjv` | Coefficient of joint variation (GM/WM) | ↓ better | a.u. | 354 | 0.6913 | 0.6283 | 0.1705 | 0.4022 | 1.167 |
| `cnr` | Contrast-to-noise ratio | ↑ better | a.u. | 354 | 1.402 | 1.512 | 0.3845 | 0.5301 | 2.174 |
| `efc` | Entropy focus criterion | ↓ better | a.u. | 354 | 0.5448 | 0.5440 | 0.0432 | 0.4117 | 0.6614 |
| `fber` | Foreground–background energy ratio | ↑ better | a.u. | 354 | 6856.4 | 6442.8 | 6466.7 | 43.57 | 27062.5 |
| `fwhm_avg` | Spatial smoothness (FWHM average) | context | mm | 354 | 4.157 | 4.559 | 0.8718 | 2.569 | 6.003 |
| `fwhm_x` | Spatial smoothness FWHM x | context | mm | 354 | 4.108 | 4.501 | 0.8485 | 2.506 | 5.872 |
| `fwhm_y` | Spatial smoothness FWHM y | context | mm | 354 | 4.128 | 4.485 | 0.8229 | 2.644 | 5.818 |
| `fwhm_z` | Spatial smoothness FWHM z | context | mm | 354 | 4.235 | 4.661 | 0.9537 | 2.520 | 6.320 |
| `icvs_csf` | Intracranial volume fraction CSF | context | fraction | 354 | 0.2611 | 0.2606 | 0.009527 | 0.2233 | 0.2877 |
| `icvs_gm` | Intracranial volume fraction GM | context | fraction | 354 | 0.3752 | 0.3749 | 0.0119 | 0.3135 | 0.3997 |
| `icvs_wm` | Intracranial volume fraction WM | context | fraction | 354 | 0.3637 | 0.3605 | 0.0129 | 0.3401 | 0.4632 |
| `inu_med` | Intensity non-uniformity (median) | ↓ better | a.u. | 354 | 0.8449 | 0.9804 | 0.2515 | 0.3581 | 1.353 |
| `inu_range` | Intensity non-uniformity (range) | ↓ better | a.u. | 354 | 0.4143 | 0.2254 | 0.3807 | 0.0167 | 1.259 |
| `qi_1` | Mortamet QI1 (air artifact) | ↓ better | a.u. | 354 | 0.000000 | 0.000000 | 0.000000 | 0.000000 | 0.000000 |
| `qi_2` | Mortamet QI2 (air artifact) | ↓ better | a.u. | 354 | 0.000717 | 0.000572 | 0.000535 | 0.000020 | 0.002442 |
| `rpve_csf` | Residual partial volume CSF | ↓ better | a.u. | 354 | 6.496 | 6.429 | 0.6504 | 5.036 | 8.480 |
| `rpve_gm` | Residual partial volume GM | ↓ better | a.u. | 354 | 6.393 | 6.348 | 0.6424 | 4.974 | 8.379 |
| `rpve_wm` | Residual partial volume WM | ↓ better | a.u. | 354 | 6.498 | 6.478 | 0.6302 | 5.148 | 8.458 |
| `snr_csf` | SNR in CSF | ↑ better | a.u. | 354 | 1.943 | 1.936 | 0.1838 | 1.191 | 2.645 |
| `snr_gm` | SNR in GM | ↑ better | a.u. | 354 | 4.534 | 5.104 | 1.713 | 1.237 | 7.724 |
| `snr_total` | SNR total | ↑ better | a.u. | 354 | 4.638 | 5.520 | 2.131 | 1.007 | 8.583 |
| `snr_wm` | SNR in WM | ↑ better | a.u. | 354 | 7.438 | 9.524 | 4.787 | 0.1872 | 16.36 |
| `snrd_csf` | Dietrich SNR CSF | ↑ better | a.u. | 354 | 17.48 | 15.16 | 13.03 | 1.230 | 69.27 |
| `snrd_gm` | Dietrich SNR GM | ↑ better | a.u. | 354 | 26.51 | 19.66 | 23.57 | 2.361 | 123.52 |
| `snrd_total` | Dietrich SNR total | ↑ better | a.u. | 354 | 23.69 | 15.75 | 22.63 | 2.175 | 118.40 |
| `snrd_wm` | Dietrich SNR WM | ↑ better | a.u. | 354 | 27.07 | 12.68 | 34.55 | 0.2458 | 162.41 |
| `tpm_overlap_csf` | Tissue probability map overlap CSF | ↑ better | Dice-like | 354 | 0.2248 | 0.2131 | 0.0353 | 0.1548 | 0.2914 |
| `tpm_overlap_gm` | Tissue probability map overlap GM | ↑ better | Dice-like | 354 | 0.5303 | 0.5294 | 0.0134 | 0.4202 | 0.5667 |
| `tpm_overlap_wm` | Tissue probability map overlap WM | ↑ better | Dice-like | 354 | 0.5264 | 0.5355 | 0.0289 | 0.4194 | 0.5726 |
| `wm2max` | WM median / max intensity | context | ratio | 354 | 0.4395 | 0.4033 | 0.3203 | 0.0112 | 0.9053 |

## BOLD functional IQMs (complete)

| IQM | Description | Dir. | Unit | n | Mean | Median | SD | Min | Max |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `aor` | AFNI outlier ratio | ↓ better | fraction | 1494 | 0.004099 | 0.000992 | 0.005762 | 0.000235 | 0.0795 |
| `aqi` | AFNI quality index | ↓ better | a.u. | 1494 | 0.0125 | 0.009549 | 0.009682 | 0.004056 | 0.1131 |
| `dummy_trs` | Non-steady-state volumes dropped | context | volumes | 1494 | 1.68 | 2.00 | 1.29 | 0.00 | 9.00 |
| `dvars_nstd` | DVARS (non-standardized) | ↓ better | a.u. | 1494 | 65.99 | 64.96 | 12.31 | 41.08 | 148.00 |
| `dvars_std` | DVARS (standardized) | ↓ better | a.u. | 1494 | 1.059 | 1.048 | 0.0572 | 0.8941 | 1.516 |
| `dvars_vstd` | DVARS (voxel-wise standardized) | ↓ better | a.u. | 1494 | 1.036 | 1.004 | 0.0725 | 0.9138 | 1.626 |
| `efc` | Entropy focus criterion | ↓ better | a.u. | 1494 | 0.4733 | 0.4688 | 0.0266 | 0.4225 | 0.5748 |
| `fber` | Foreground–background energy ratio | ↑ better | a.u. | 1494 | 397.33 | 390.76 | 94.38 | 189.74 | 678.48 |
| `fd_mean` | Framewise displacement (mean) | ↓ better | mm | 1494 | 0.1977 | 0.1758 | 0.1111 | 0.0490 | 1.524 |
| `fd_num` | Number of frames with FD > 0.2 mm | ↓ better | count | 1494 | 67.75 | 60.00 | 60.08 | 0.00 | 262.00 |
| `fd_perc` | Percent frames with FD > 0.2 mm | ↓ better | % | 1494 | 36.33 | 37.08 | 24.29 | 0.000000 | 97.79 |
| `fwhm_avg` | Spatial smoothness (FWHM average) | context | mm | 1494 | 3.719 | 3.772 | 0.3936 | 2.591 | 5.367 |
| `fwhm_x` | Spatial smoothness FWHM x | context | mm | 1494 | 3.485 | 3.525 | 0.3507 | 2.427 | 4.577 |
| `fwhm_y` | Spatial smoothness FWHM y | context | mm | 1494 | 3.847 | 3.884 | 0.4068 | 2.463 | 5.850 |
| `fwhm_z` | Spatial smoothness FWHM z | context | mm | 1494 | 3.825 | 3.858 | 0.4563 | 2.511 | 6.073 |
| `gcor` | Global correlation | ↓ better | a.u. | 1494 | 0.003560 | 0.002754 | 0.002734 | 0.000206 | 0.0252 |
| `gsr_x` | Ghost-to-signal ratio (x) | ↓ better | ratio | 1494 | 0.006269 | 0.003633 | 0.0209 | -0.0573 | 0.1200 |
| `gsr_y` | Ghost-to-signal ratio (y) | ↓ better | ratio | 1494 | 0.0482 | 0.0408 | 0.0322 | -0.001128 | 0.2024 |
| `snr` | Signal-to-noise ratio | ↑ better | a.u. | 1494 | 1.449 | 1.394 | 0.2337 | 1.069 | 2.416 |
| `tsnr` | Temporal SNR | ↑ better | a.u. | 1494 | 21.17 | 20.64 | 5.259 | 6.666 | 36.67 |

