# Grating protocol — technical summary

## Design

- Initial baseline, then 12 cycles of stimulus + baseline (canonical laboratory design: 10 TR baseline segments and 8 TR stimulus segments; 226 volumes at TR ≈ 0.937 s).
- Dichoptic / stereo Psychtoolbox presentation (`stereoMode` as configured in `main.m`).
- Operator confirms run index; Results store `scan_info` / sequence metadata per fMRI number.

## Dependencies

- MATLAB with Psychtoolbox-3
- FORP (or compatible) device mapping scanner TTL to key `t`
- Display calibration files (`GreenLevel.mat` / `RedLevel.mat`) used at acquisition time — **not** redistributed (lab-local calibration)

## What is not included

- Per-session `Results/*.mat` (contain operator logs and may embed identifying filenames)
- Unused FOV / eye-check utilities from other MATLAB folders
