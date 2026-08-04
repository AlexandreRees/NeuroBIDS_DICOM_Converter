# Physiological data recovery audit

Generated: `2026-07-23T21:56:42.307667+00:00`

Read-only deep audit. **No files under `raw_original/` or `bids/` were modified.**
**No `*_physio.tsv.gz` files were created.**

## Summary

Total files: **678**

- ECG (`.ecg`): **111**
- RESP (`.resp`): **114**
- PULS (`.puls`): **114**
- EXT (`.ext`): **114**
- EXT2 (`.ext2`): **114**
- PMU (`.pmu`): **111**
- Other / text: **0**

## Format detection

- `siemens_ascii_pmu`: **561**
- `siemens_binary_pmu_vsn`: **108**
- `text_unclassified`: **6**
- `siemens_binary_pmu_or_unknown`: **3**

Siemens ASCII PMU footers commonly expose `Freq Per`, Min/Max/Avg, `LogStartMDHTime` / `LogStopMDHTime`, and `NrTrig`. Binary `.pmu` files were not waveform-decoded without a validated parser.

## Sampling frequency recovery

| Status | Files (best confidence per file) |
| --- | ---: |
| Recovered (HIGH/MEDIUM) | 0 |
| Not recovered (LOW/INVALID only) | 678 |

Candidate-row confidence counts:

- HIGH: **0**
- MEDIUM: **0**
- LOW: **346**
- INVALID: **670**

**Rule enforced:** Siemens `Freq Per: <rate> <period_ms>` is physiological rate metadata and is classified **INVALID** as SamplingFrequency.

## Timestamp recovery

- Rows analysed: **678**
- Confidence INVALID: **127**
- Confidence LOW: **551**
- Confidence MEDIUM/HIGH: **0**

Literal `LogStartMDHTime` / `LogStartMPCUTime` ticks were recorded but **not converted** to BIDS `StartTime`. Current BOLD JSON sidecars generally lack `AcquisitionTime` / `AcquisitionDateTime`.

## Physio-BOLD association

| Class | Physio files (best class) |
| --- | ---: |
| CONFIRMED | 0 |
| LIKELY | 0 |
| AMBIGUOUS | 610 |
| NO_MATCH / FAILED | 68 |

CONFIRMED requires subject/session concordance **and** a recovered compatible StartTime **and** a unique BOLD target.

## BIDS conversion readiness

- Files meeting full recovery criterion (SF + StartTime + unique run): **0**
- Files impossible under current metadata: **678**

### Option B: Insufficient metadata, keep excluded

No physiology file simultaneously provides:

1. explicit ADC `SamplingFrequency` (HIGH/MEDIUM),
2. validated BIDS-relative `StartTime`,
3. a unique CONFIRMED BOLD run mapping.

Therefore **no Level-1 BIDS physiology conversion is authorized**. Keep ECG/RESP/PULS/EXT/PMU excluded from the public release until external scanner documentation or original PhysioLog DICOM objects supply the missing metadata.

## Outputs

- `physio_inventory.tsv`
- `physio_format_analysis.tsv`
- `physio_sampling_rate_analysis.tsv`
- `timestamp_reconstruction.tsv`
- `physio_run_mapping_candidates.tsv`
- `physio_recovery_report.md`
- `PHYSIO_RECOVERY_DECISION.md`
- `figures/sampling_rate_distribution.png`
- `figures/physio_duration_distribution.png`
- `figures/example_traces.png`
