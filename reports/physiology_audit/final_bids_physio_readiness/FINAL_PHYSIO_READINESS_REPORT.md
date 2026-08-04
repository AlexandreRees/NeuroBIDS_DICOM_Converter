# Siemens PhysioLog BIDS readiness audit

Generated: `2026-07-24T17:58:25.968486+00:00`

**READ-ONLY.** No modifications to `raw_original/`, `bids/`, `derivatives/`, or `release_dataset/`. No `*_physio.tsv.gz` created.

## Dataset inventory

Total PhysioLog objects: **1626**

READY after forensic filtering: **1302** (80.1%)

FAILED: **324**

## Metadata completeness

Sampling frequency available (PASS among forensic READY): **1254 / 1302**

StartTime available (PASS): **1302 / 1302**

Unique BOLD association (PASS): **1302 / 1302**

Waveform quality (PASS): **1302 / 1302**

Final BIDS-eligible (`READY_FOR_BIDS_CONVERSION`): **1302**

## Final conversion recommendation

### OPTION A

PhysioLog data meeting all four gates (SampleTime-derived SamplingFrequency, CSA-derived StartTime, unique BOLD mapping, valid waveform) are ready for a gated BIDS conversion step (**1302** series). Peripheral PMU logs remain excluded. This audit did not write any `*_physio.tsv.gz`.

## Exclusion reasons

| Reason | Number |
| --- | ---: |
| Failed forensic READY filter | 324 |

## Method notes

- SamplingFrequency_Hz = 1000 / CSA `SampleTime` (ms); Freq Per and Siemens default guesses rejected.
- StartTime = (first channel ACQ_TIME_TICS − vol0 ACQ_START_TICS) × 0.0025 s/tick (Siemens CSA convention; confidence MEDIUM).
- Run mapping requires subject/session/ProtocolName unique BOLD match with existing `*_bold.nii.gz`.
- Waveform PASS requires ≥1 VALID non-flat channel extracted from CSA payload.

## Outputs

- `sampling_frequency_validation.tsv`
- `starttime_validation.tsv`
- `run_mapping_validation.tsv`
- `waveform_quality_validation.tsv`
- `FINAL_PHYSIO_CONVERSION_DECISION.tsv`
- `FINAL_PHYSIO_READINESS_REPORT.md`
- `SCIENTIFIC_DATA_PHYSIO_METHODS_DRAFT.md`
- figures `physio_recovery_summary.png`, `sampling_frequency_distribution.png`, `physio_duration_distribution.png`, `recoverable_runs_by_task.png`
