# Missing task-fMRI event files

**Generated:** 2026-07-23T20:22:57Z  
**task-fMRI BOLD runs:** 507  
**With events:** 452  
**Without events:** 55

## Why omission is preferable

Uncertain or non-unique protocol→BOLD mappings were **not** used to invent timings. Publishing no `events.tsv` is preferable to releasing ambiguous onsets that could silently misalign stimulus regressors with BOLD volumes.

## Reason categories

| Category | Count | Percentage of missing |
|---|---:|---:|
| No unique ProtocolName mapping | 28 | 50.9% |
| No unique verified mapping | 18 | 32.7% |
| Incomplete MATLAB logs | 9 | 16.4% |

## Per-run listing

See `missing_events.tsv` for subject, session, run, protocol, and detailed reason.

### Category definitions

- **No unique ProtocolName mapping** — zero or multiple non-phase BOLD sidecars matched the experimental `fMRI{N}` label.  
- **Incomplete trigger recordings** — fewer than two finite scanner `triggerTimes`.  
- **Incomplete MATLAB logs** — missing/duplicated `scan_info` or `fMRI_N` sources.  
- **Ambiguous correspondence** — conflicting identifiers across logs.  
- **No events generated (no unique verified mapping)** — run not covered by a successful unique conversion path.
