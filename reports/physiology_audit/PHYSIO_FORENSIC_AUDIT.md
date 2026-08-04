# Physiological forensic audit

Generated: `2026-07-24T17:07:11.279961+00:00`

**READ-ONLY AUDIT.** No modifications to `raw_original/`, `bids/`,
`derivatives/`, or `release_dataset/`. No `*_physio.tsv.gz` created.

## 1. Inventory

Source inventory rows (physio-relevant candidates): **5488**

- pmu_ecg: **107**
- pmu_puls: **110**
- pmu_pmu: **107**
- pmu_ext2: **110**
- pmu_ext: **110**
- pmu_resp: **110**
- dicom_physiolog: **1650**
- text_log: **299**
- matlab: **2885**

Full DICOM archive size scanned for timing/waveform tags: **890132**

## 2. Potential metadata sources

| Source | What it provides | Limitation |
| --- | --- | --- |
| Siemens PhysioLog DICOM (CSA `7FE1,1010`) | `SampleTime`, channel traces, `ACQUISITION_INFO` volume ticks, per-run series | Not standard Waveform IOD; requires CSA parser |
| Peripheral PMU (`.ecg/.resp/.puls/.ext/.pmu`) | Waveforms + `Freq Per` + MDH/MPCU ticks | No ADC SamplingFrequency; session-wide |
| Standard DICOM WaveformSequence | BIDS-ready sampling + waveform | **Not found** in this archive |
| MATLAB | Task triggers / Psychtoolbox clocks | Wrong clock domain for PMU ADC |
| Text PhysioLog / ScanLog | Occasional keywords | No standalone validated physio streams found beyond DICOM CSA |

## 3. Waveform DICOM audit

- Standard WaveformSequence / Waveform SOP instances: **0**
- Siemens PhysioLog DICOM objects: **1626**
- PhysioLog with explicit CSA `SampleTime`: **1585**
- PhysioLog with `ACQUISITION_INFO`: **1613**

PhysioLog objects use Siemens private SOP Class and store physiology inside CSA Data,
not DICOM WaveformSequence (`5400,0100`). Waveform *content* is present for PULS/RESP/EXT
channels inside CSA, with explicit `SampleTime` (ms) per channel type.

## 4. PMU audit

- Peripheral PMU files parsed: **684**
- With explicit SamplingFrequency/SampleRate labels: **0**

Siemens `Freq Per` fields are physiological rates/periods and are **not** ADC sampling rates.
MDH/MPCU timestamps remain scanner ticks without a validated transform in peripheral files.

## 5. MATLAB audit

- MATLAB files with physio/trigger/sampling keyword hits: **29**

Prior and current string forensics show Psychtoolbox `triggerTimes` / display timing,
not Siemens PMU ADC SamplingFrequency or MDH/MPCU clock transforms.

## 6. Timing audit

- Imaging/Physio DICOM instances with `AcquisitionTime` or `AcquisitionDateTime`: **888312**
- Instances with `SeriesTime`: **890132**

BOLD JSON sidecars generally lack AcquisitionTime; PhysioLog CSA volume ticks are the
viable route to BIDS-relative StartTime for PhysioLog-linked runs.

## 7. Run mapping audit

Peripheral PMU logs are session-wide → AMBIGUOUS.

PhysioLog series descriptions (`*_PhysioLog`) encode the parent protocol and can uniquely
match BIDS `ProtocolName` when one-to-one.

## 8. Final recoverability table

| Source | SamplingFrequency | StartTime | RunMap | Recoverable |
| --- | --- | --- | --- | --- |
| PhysioLog DICOM | MEDIUM | MEDIUM | CONFIRMED | YES |
| PMU | NONE | LOW | AMBIGUOUS | NO |
| MATLAB | NONE | LOW | NONE | NO |
| PhysioLog text | NONE | NONE | NONE | NO |
| DICOM Timing | NONE | LOW | NONE | NO |
| Waveform DICOM | NONE | NONE | NONE | NO |

Per-recording recoverability: **YES=1302**, **NO=1012**

## 9. Scientific Data recommendation

### OPTION B

**Partial conversion is possible** for **1302** Siemens PhysioLog DICOM recordings that embed CSA `SampleTime`, `ACQUISITION_INFO` volume ticks, and a unique BIDS `ProtocolName` match. Peripheral `.ecg/.resp/.puls` PMU files remain **not convertible** without inventing SamplingFrequency or run alignment. Standard DICOM Waveform IODs were not found. A gated converter (separate from this audit) would be required before any `*_physio.tsv.gz` release; this audit created none.

## 10. Confirmation of non-modification

- No files modified in `raw_original/`, `bids/`, `derivatives/`, or `release_dataset/`.
- No BIDS physio files generated (`*_physio.tsv.gz` count remains unchanged by this audit).
- No raw data altered. Audit outputs written only under `reports/physiology_audit/`.

## Outputs

- `source_inventory.tsv`
- `dicom_waveform_inventory.tsv`
- `dicom_timing_inventory.tsv`
- `pmu_metadata_inventory.tsv`
- `physiolog_inventory.tsv` / `physiolog_dicom_deep.tsv`
- `matlab_physio_inventory.tsv`
- `recoverability_evaluation.tsv`
- `PHYSIO_FORENSIC_AUDIT.md`
- `figures/Figure_A_source_overview.pdf`
- `figures/Figure_B_waveform_sources.pdf`
- `figures/Figure_C_metadata_availability.pdf`
- `figures/Figure_D_recoverability_matrix.pdf`
- `figures/Figure_E_decision_tree.pdf`
