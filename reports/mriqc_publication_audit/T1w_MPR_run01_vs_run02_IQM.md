# Why T1w_MPR run-01 vs run-02 have different MRIQC IQMs

Not FLAIR / not a different BIDS suffix: both runs are `ProtocolName=T1w_MPR` with suffix `T1w`.

Paired sessions with both runs: **119** (CNR is higher on run-02 in **100%** of pairs).

| Run | n | CNR median | CJV median | SNR median |
|---|---:|---:|---:|---:|
| run-01 | 121 | 0.926 | 0.905 | 5.506 |
| run-02 | 120 | 1.601 | 0.606 | 6.334 |

Paired medians (n=119): CNR **0.926 vs 1.603**; CJV **0.906 vs 0.606**; SNR **5.502 vs 6.333**.

## Root cause (metadata)

Acquisition geometry and contrast parameters match across runs:

- Same `ProtocolName` / `SeriesDescription` (`T1w_MPR`)
- Same `SequenceName` (`*tfl3d1_16ns`), `ScanOptions` (`IR\WE`), TR/TE/FA/TI (2.5 / 0.00222 / 8 / 1)
- Same matrix / voxel size: shape `(208, 300, 320)`, zooms `(0.8, 0.8, 0.8)` mm

The **systematic** difference is Siemens reconstruction flag **`NORM`** in `ImageType`:

| Run | Typical `ImageType` | Count (paired) |
|---|---|---:|
| run-01 | `['ORIGINAL', 'PRIMARY', 'M', 'ND']` | 115 vs NORM on run-02 |
| run-02 | `['ORIGINAL', 'PRIMARY', 'M', 'ND', 'NORM']` | 115 |

`NORM` = Siemens **prescan normalize / coil-sensitivity intensity normalization**. That changes the intensity histogram (tissue contrast and noise appearance), so MRIQC **CNR / CJV / SNR** shift even though the pulse-sequence recipe is unchanged. Run-01 is distortion-corrected (`ND`) but **not** intensity-normalized; run-02 is `ND` **plus** `NORM`.

Minor exceptions (do not drive the cohort IQM gap): a few `_ND` / `ImageType`=`NONE` sidecars and rare same-ImageType pairs.

## Figures

- `figures/Fig04a1_T1w_MPR_run-01_cnr_cjv_snr` — run-01 only
- `figures/Fig04a2_T1w_MPR_run-02_cnr_cjv_snr` — run-02 only
- `figures/Fig04a_T1w_MPR_by_run_cnr_cjv_snr` — 2-row panel (run-01 top, run-02 bottom)

Regenerate: `python3 code/mriqc_publication_audit/make_fig04a_by_run.py`
