# Movie run eye assignment

Monocular movie-run assignment for `task-movie`. Each magnitude run presented one movie segment with a fixation overlay. The contralateral eye was occluded.

Scanner series use ProtocolName `Movie1_AP`…`Movie4_AP` (and rare `_redo` variants). In typical sessions these map to BIDS **magnitude** runs `run-01`, `run-03`, `run-05`, `run-07` (even run indices are usually `part-phase`). Always prefer `ProtocolName` / `events.tsv` over assuming sequential `run-01`…`run-04`.

Design-level `*_events.tsv` are included for all magnitude movie BOLD runs (`onset = 0` under protocol sync; duration = measured MP4 length). See `code/task-movie/README.md`.

| matlab_run_id | ProtocolName family | Movie segment (`stim_file`) | Stimulated eye (`change_eye=0`) | Typical mag BIDS run | Volumes | Duration (s) |
| ---: | --- | --- | --- | --- | ---: | ---: |
| 1 | Movie1_* | Movie1A.mp4 | left | run-01 | 210 | 196.821 |
| 2 | Movie2_* | Movie2A.mp4 | right | run-03 | 210 | 196.821 |
| 3 | Movie3_* | Movie1B.mp4 | right | run-05 | 210 | 196.821 |
| 4 | Movie4_* | Movie2B.mp4 | left | run-07 | 210 | 196.821 |

Sessions with duplicate ProtocolName (16 magnitude runs, mapping confidence MEDIUM) are listed in `code/task-movie/task-movie_medium_confidence_runs.tsv`.
