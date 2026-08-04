# EXT recovery audit

Generated (UTC): 2026-07-31T18:07:55.138834+00:00

Read-only evaluation of Siemens peripheral PMU `.ext` / `.ext2` recoverability.
No `events.tsv` created. No BIDS/raw modification.

## Dataset summary

- EXT files found: **228**
- EXT parsable waveforms: **226**
- EXT trigger-like (score≥0.5): **0**
- BOLD runs inventoried: **1625**
- DICOM series reps: **8000**
- Mappings ACCEPT: **0**
- Mappings REVIEW: **0**
- Mappings REJECT: **228**

## Scientifically usable EXT

_None. Fail-closed: no EXT met ACCEPT (score>0.95, unique, not session-wide)._

## Ambiguous EXT

_None._

## Why EXT were not integrated

1. **Session-wide recording** — peripheral `.ext` typically spans the entire visit,
   far longer than any single BOLD run (`duration_match` collapses under fail-closed rules).
2. **No run identifier** — filenames/folders do not encode BIDS task/run entities.
3. **No validated StartTime** — MDH ticks exist but absolute sync to BOLD `AcquisitionTime`
   is not assumed (would invent a clock transform).
4. **Ambiguous trigger counts** — transition counts / `NrTrig` rarely match a unique
   run's `n_volumes` within the session.
5. **SamplingFrequency** — Siemens `Freq Per` for EXT is often `0 0`; Fs is only
   derived when MDH start/stop + sample count are both present.

## Method notes

- Waveforms parsed as Siemens ASCII PMU token streams (control codes 5000/5002/5003/6000/6002/6003 excluded).
- `trigger_like_score` combines transition density, interval regularity, TR-plausible median interval, digital flip fraction.
- ACCEPT requires score>0.95, a single near-candidate, and no session-wide duration penalty.

