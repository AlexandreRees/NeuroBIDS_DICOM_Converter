# Physiology conversion readiness

## Decision

**Recommended option: 3. Impossible without external scanner information.**

No physiology conversion is authorized. No BIDS physiology files were created.

## Modality decisions

### A) Can ECG be converted?

**NO.** No explicit ECG acquisition `SamplingFrequency` was recovered, no BIDS-relative `StartTime` was recovered, and no physiology recording has a HIGH or MEDIUM-confidence BOLD run association. Separately, waveform validation found the available ECG channels flat; waveform conversion was outside this metadata-only audit.

### B) Can respiration be converted?

**NO.** No explicit respiration acquisition `SamplingFrequency` was recovered. Literal MDH/MPCU clock ticks cannot be promoted to BIDS `StartTime` without a validated clock transformation, and run association remains session-only.

### C) Can pulse be converted?

**NO.** No explicit pulse acquisition `SamplingFrequency` was recovered. `PULS Freq Per` is heart-rate/period metadata, not an ADC sampling rate. No validated run-relative start or run mapping was recovered.

## Recovered facts

- Target files audited: **224** (`.ecg` 74, `.resp` 75, `.puls` 75).
- Synchronization metadata inventory rows: **2385**.
- Relevant MATLAB variable rows: **3813**.
- Accepted explicit sampling-frequency candidates: **0**.
- HIGH/MEDIUM run associations: **0**.
- Literal `LogStartMDHTime` coverage: ECG 74/74, respiration 71/75, pulse 71/75.
- Structurally complete PMU footers: ECG 74/74, respiration 71/75, pulse 71/75.
- MATLAB `scan.runs.triggerTimes` values exist for many task runs, but they are Psychtoolbox-clock timestamps. No documented transformation to the PMU MDH/MPCU clock was found.
- Current BOLD JSON sidecars contain no `AcquisitionTime` or `AcquisitionDateTime` field.

## Uncertain hypotheses (not accepted)

- Unlabelled Siemens PMU preamble numbers may encode device settings, but they are not accepted as sampling rates.
- Trigger spacing in MATLAB may validate a BOLD TR, but it does not establish physiology ADC sampling or a PMU clock mapping.
- Protocol names and filename/run proximity may narrow candidate runs, but without a shared clock or explicit mapping they remain LOW confidence.

## Unavailable information

- Explicit ECG/RESP/PULS acquisition sampling frequency with units.
- A documented conversion between MDH/MPCU ticks and seconds.
- A run-relative physiology start time (`StartTime`).
- An explicit PMU recording-to-BOLD run or trigger mapping.
- BOLD `AcquisitionTime`/`AcquisitionDateTime` in current sidecars.

## Missing requirements

- **SamplingFrequency:** missing for all target files.
- **StartTime:** missing for all target files. `LogStartMDHTime` is not equivalent to BIDS `StartTime`.
- **Run association:** no HIGH or MEDIUM-confidence association.

## Recommended next step

Obtain external scanner documentation or original scanner exports that explicitly provide the PMU acquisition sampling rates and the MDH/MPCU clock definition. Recover unstripped DICOM acquisition timestamps and/or the original run-specific PhysioLog DICOM objects, then validate a trigger/clock transformation on representative sessions before authorizing any BIDS conversion.

## Provenance and interpretation rules

- `sampling_frequency_candidates.tsv` accepts only explicitly labelled acquisition sampling rates with units; heart rate, respiratory rate, period, TR, display `fps`, and nearby generic `Hz` were rejected.
- `run_association_candidates.tsv` records session-only possibilities as `LOW`; these rows are explicitly not usable.
- `pmu_header_report.tsv` contains literal metadata only; no waveform payload was decoded.
- Facts, hypotheses, and unavailable requirements are separated above. No missing value was inferred or replaced by a Siemens default.
