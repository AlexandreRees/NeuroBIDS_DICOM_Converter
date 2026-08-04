# MATLAB protocol audit

Generated: `2026-07-28T13:33:29Z`

## Scope

Read-only audit of Psychtoolbox scripts for **Grating**, **Movie**, and **Resting state**.
Source trees were not modified. Absolute filesystem paths are retained only in internal TSV tokens, not in the public deposit.

## Inventory summary

- Total `.m` files classified: **2105**

### grating
- Script files audited: **1656**
- Basenames: CheckerFlickerSine.m, CheckerFlickerSquare.m, CheckerMoveSine.m, CheckerMoveSquare.m, GratingStimulus1.m, GratingStimulus2.m, GratingStimulus3.m, GratingStimulus4.m, GratingStimulus5.m, RandomGenerator.m, main.m, presentStimParams.m
- `CheckerFlickerSine.m`: n=138, unique_versions=1, canonical=ecabb3cc084a1001… (n=138)
- `CheckerFlickerSquare.m`: n=138, unique_versions=1, canonical=8b86145749ab438c… (n=138)
- `CheckerMoveSine.m`: n=138, unique_versions=1, canonical=efbde7f7ed1e2f98… (n=138)
- `CheckerMoveSquare.m`: n=138, unique_versions=1, canonical=29be5c7f2fd2ced0… (n=138)
- `GratingStimulus1.m`: n=138, unique_versions=2, canonical=1bb67cee02e61bb0… (n=137)
- `GratingStimulus2.m`: n=138, unique_versions=1, canonical=3162e00be9173d91… (n=138)
- `GratingStimulus3.m`: n=138, unique_versions=1, canonical=a1be718f9b2a06b5… (n=138)
- `GratingStimulus4.m`: n=138, unique_versions=1, canonical=c5131f08f019fe78… (n=138)
- `GratingStimulus5.m`: n=138, unique_versions=1, canonical=a2bba53c71aee643… (n=138)
- `RandomGenerator.m`: n=138, unique_versions=1, canonical=2792bc41f6ebab87… (n=138)
- `main.m`: n=138, unique_versions=6, canonical=7b6e48e0242beb02… (n=121)
- `presentStimParams.m`: n=138, unique_versions=1, canonical=a27ac8fca0d2d39e… (n=138)

### movie
- Script files audited: **276**
- Basenames: Show_movie.m, main.m
- `Show_movie.m`: n=138, unique_versions=2, canonical=83ade79574081031… (n=137)
- `main.m`: n=138, unique_versions=5, canonical=1aab337d9f67bc7f… (n=127)

### movie_fov
- Script files audited: **36**
- Basenames: Show_movie.m, main.m
- `Show_movie.m`: n=18, unique_versions=1, canonical=88923aeac42f475d… (n=18)
- `main.m`: n=18, unique_versions=1, canonical=fa01b62dff72ec1d… (n=18)

### rest
- Script files audited: **137**
- Basenames: main.m
- `main.m`: n=137, unique_versions=21, canonical=cbf1d5c8c657920e… (n=94)

## Scripts required vs unused

### Grating — published (required)

- `main.m`
- `presentStimParams.m`
- `RandomGenerator.m`
- `GratingStimulus1.m`
- `GratingStimulus2.m`
- `GratingStimulus3.m`
- `GratingStimulus4.m`
- `GratingStimulus5.m`
- `CheckerFlickerSine.m`
- `CheckerFlickerSquare.m`
- `CheckerMoveSine.m`
- `CheckerMoveSquare.m`

All listed files are referenced by `main.m` / `presentStimParams.m` for the released `task-fmri` design.

### Movie — published

- `main.m` (entry; may be sanitized)
- `Show_movie.m` (playback + trigger)

Excluded: FOV-nested `1-Check_FOV*/3-Movie_Data` copies; `Results/`; MP4 stimuli.

### Rest — published

- Single canonical `main.m`

## Dependencies (runtime)

- MATLAB
- Psychtoolbox-3 (Screen, KbQueue, PsychHID, stereo rendering; OpenMovie for movie)
- FORP-compatible scanner trigger mapped to key `t`

## Canonical selection policy

For each basename, publish the **modal SHA-256** across primary paradigm folders.
If content is identical, publish **one** exemplar only.

## Related tables

- `MATLAB_PROTOCOL_INVENTORY.tsv`
- `CANONICAL_SELECTION.tsv`
- `MATLAB_PHI_REPORT.tsv`
- `CODE_COPY_VALIDATION.tsv`
