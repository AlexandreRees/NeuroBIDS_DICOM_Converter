# task-grating — contrast / grating protocol (`task-fmri`)

## Objective

Present a block-design visual stimulation sequence (oriented gratings and checkerboard variants) during BOLD fMRI. In the BIDS dataset this paradigm is labelled **`task-fmri`**.

## Stimuli

Twelve stimulus conditions (`stim-01`…`stim-12`) are defined in `presentStimParams.m` via Psychtoolbox classes:

- `GratingStimulus1`…`GratingStimulus5`
- `CheckerMoveSquare`, `CheckerFlickerSquare`, `CheckerMoveSine`, `CheckerFlickerSine`

Conditions `stim-07`…`stim-12` intentionally repeat `stim-01`…`stim-06` within each run. Parameterized labels for open analysis are in `../task-fmri_condition_dictionary.tsv`.

## Scanner synchronization

`main.m` listens for the FORP / keyboard trigger key **`t`**, records trigger times, and advances the block design in lock-step with the scanner. Timing products used for BIDS events live in laboratory `Results/` MATLAB files (not redistributed here).

## Events reconstruction

Verified `sub-*_task-fmri_run-*_events.tsv` files combine:

1. Measured `triggerTimes` from grating Results
2. Stimulus order / paradigm metadata
3. A unique ProtocolName ↔ BIDS magnitude BOLD mapping

Runs without an unambiguous mapping intentionally have **no** events file.

## Scripts in this folder

| File | Role |
| --- | --- |
| `main.m` | Entry point; trigger sync; run loop |
| `presentStimParams.m` | Block design + `generateStim()` condition list |
| `RandomGenerator.m` | Run-order randomization helper |
| `GratingStimulus1.m`…`5.m` | Grating stimulus classes |
| `Checker*.m` | Checkerboard stimulus classes |

Canonical SHA-256 (`main.m`): `7b6e48e0242beb02cd4d6ba2771ca5ff18a6c6ebeb5e4cd8408518f4796076a2`

See also [`task-grating_protocol.md`](task-grating_protocol.md) and [`../../docs/Protocols/Grating.md`](../../docs/Protocols/Grating.md).
