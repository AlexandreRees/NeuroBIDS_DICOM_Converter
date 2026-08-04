# Movie events.tsv generation report

**Generated:** `2026-07-29T18:53:46Z`
**Script:** `code/bids_fixes/generate_movie_events.py` (`2026-07-29_protocol_sync_v1`)

## Timing policy

- `onset = 0` — protocol assumption: scanner start = movie start (lab fMRI lead).
- `duration = 196.821333` s — ffprobe of archived MP4 clips.
- QC: 210 volumes × TR 0.937 s = 196.770 s (Δ ≈ 51 ms vs MP4).
- No Psychtoolbox `triggerTimes` / VBL logs exist for task-movie.

## Counts

| Status | N |
|---|---:|
| `WRITTEN` | 1072 |

| mapping_confidence | N |
|---|---:|
| `HIGH` | 1040 |
| `MEDIUM` | 32 |

## Artifacts

- Per-run `*_task-movie_run-*_events.tsv` + `*_events.json`
- Dataset `task-movie_events.json` (column definitions)
- This report + `movie_events_generation.tsv`

## Limitations

- Onsets are **not** millisecond-precise TTL measurements.
- Suitable for run-level / continuous-movie models; not frame-locked analyses.
- `MEDIUM` confidence rows lack a unique MATLAB assignment (usually duplicate ProtocolName).

