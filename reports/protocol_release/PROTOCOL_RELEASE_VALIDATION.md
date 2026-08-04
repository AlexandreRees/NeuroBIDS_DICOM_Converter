# Protocol release validation

Generated: `2026-07-28T13:33:29Z`

## Checks

| Check | Result |
| --- | --- |
| Published scripts | 15 |
| HIGH PHI in published byte-identical files | PASS |
| HIGH PHI hits (unique content, pre-sanitize) | 15 |
| MEDIUM PHI hits (unique content) | 15 |
| Duplicate basenames published per task | PASS (one each) |
| README files present | PASS |
| docs/Protocols present | PASS |
| task-rest.json | PASS |
| Movie assignments mapped / unmapped | 536 / 0 |
| Synthetic events created | PASS (none) |
| MP4 copied | PASS (none) |
| NIfTI / acquisition JSON modified | PASS (not touched) |

## Path / username scan on published tree

PASS — no internal absolute paths or usernames in published code/docs scanned.

## SHA-256 verification

- `code/task-grating/main.m` published=7b6e48e0242beb02… (yes)
- `code/task-grating/presentStimParams.m` published=a27ac8fca0d2d39e… (yes)
- `code/task-grating/RandomGenerator.m` published=2792bc41f6ebab87… (yes)
- `code/task-grating/GratingStimulus1.m` published=1bb67cee02e61bb0… (yes)
- `code/task-grating/GratingStimulus2.m` published=3162e00be9173d91… (yes)
- `code/task-grating/GratingStimulus3.m` published=a1be718f9b2a06b5… (yes)
- `code/task-grating/GratingStimulus4.m` published=c5131f08f019fe78… (yes)
- `code/task-grating/GratingStimulus5.m` published=a2bba53c71aee643… (yes)
- `code/task-grating/CheckerFlickerSine.m` published=ecabb3cc084a1001… (yes)
- `code/task-grating/CheckerFlickerSquare.m` published=8b86145749ab438c… (yes)
- `code/task-grating/CheckerMoveSine.m` published=efbde7f7ed1e2f98… (yes)
- `code/task-grating/CheckerMoveSquare.m` published=29be5c7f2fd2ced0… (yes)
- `code/task-movie/main.m` published=a41562310aa0ee45… (no_sanitized)
- `code/task-movie/Show_movie.m` published=83ade79574081031… (yes)
- `code/task-rest/main.m` published=cbf1d5c8c657920e… (yes)
