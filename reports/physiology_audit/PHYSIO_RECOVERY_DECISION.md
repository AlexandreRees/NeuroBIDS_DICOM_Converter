# PHYSIO_RECOVERY_DECISION

Generated: `2026-07-23T21:56:42.308883+00:00`

Number recoverable: **0**
Number impossible: **678**

## Reasons

- Siemens Freq Per fields are physiological rates/periods, not ADC SamplingFrequency.
- No HIGH/MEDIUM explicit SamplingFrequency recovered for conversion gating (0 HIGH candidate rows).
- MDH/MPCU LogStart* ticks were not converted to BIDS StartTime (no validated transform).
- BOLD JSON sidecars lack AcquisitionTime/AcquisitionDateTime for clock alignment.
- Physio logs are session-wide vs many BOLD runs → AMBIGUOUS mapping dominates.
- Binary .pmu payloads were not decoded without a validated format-specific parser.

## Recommendation for Scientific Data release

Do **not** include physiology in the Scientific Data Level-1 BIDS release. State in the Data Record that source PMU logs exist but lack validated SamplingFrequency, StartTime, and unique run linkage.

Decision gate: SamplingFrequency recovered + StartTime computed + unique BOLD run.
No `*_physio.tsv.gz` were written by this audit.
