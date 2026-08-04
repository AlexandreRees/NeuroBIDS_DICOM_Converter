# Resting-state protocol — technical summary

## Display

- Pre-scan message, then white fixation cross (horizontal + vertical limbs)
- Stereo draw buffers; fixation shown to both eyes
- Fixation size derived from visual angle

## Timing model

- Trigger-counted, not wall-clock logged
- Parameter `trs = 320`
- Escape aborts the run

## Dependencies

- MATLAB + Psychtoolbox-3
- FORP-compatible trigger → key `t`
