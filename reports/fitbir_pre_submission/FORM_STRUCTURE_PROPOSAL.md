# FITBIR Form Structure proposal (inferred)

Generated: `2026-07-30T14:52:05.823942+00:00`

READ-ONLY inference from existing files. Not a submission package.

Dataset subjects: **84**; tasks: control, fmri, movie, rest.

## Participant

**Purpose:** One row per participant; demographics / cohort labels.

**Variable count (sampled inventory):** 4

**Example variables:**

- `age`
- `cohort`
- `participant_id`
- `sex`

**Dependencies:** Participant / Session identifiers; BIDS paths; software versions from GeneratedBy / reports.

## Session

**Purpose:** One row per subject–session visit.

**Variable count (sampled inventory):** 2

**Example variables:**

- `session`
- `session_id`

**Dependencies:** Participant / Session identifiers; BIDS paths; software versions from GeneratedBy / reports.

## Scanner

**Purpose:** Scanner identity and software from sidecars.

**Variable count (sampled inventory):** 8

**Example variables:**

- `ProtocolName`
- `SeriesNumber`
- `SiemensProtocolNames`
- `bids_ProtocolName`
- `bids_SeriesNumber_json`
- `bids_runs_matching_ProtocolName`
- `in_bids_ProtocolName`
- `matched_SeriesNumber`

**Dependencies:** Participant / Session identifiers; BIDS paths; software versions from GeneratedBy / reports.

## Acquisition

**Purpose:** Sequence parameters shared across modalities.

**Variable count (sampled inventory):** 8

**Example variables:**

- `ProtocolName`
- `SeriesNumber`
- `SiemensProtocolNames`
- `bids_ProtocolName`
- `bids_SeriesNumber_json`
- `bids_runs_matching_ProtocolName`
- `in_bids_ProtocolName`
- `matched_SeriesNumber`

**Dependencies:** Participant / Session identifiers; BIDS paths; software versions from GeneratedBy / reports.

## Structural MRI

**Purpose:** T1w / FLAIR / TB1TFL acquisitions.

**Variable count (sampled inventory):** 69

**Example variables:**

- `AcquisitionMatrixPE`
- `AcquisitionNumber`
- `BaseResolution`
- `BodyPartExamined`
- `CoilCombinationMethod`
- `ConsistencyInfo`
- `ConversionSoftware`
- `ConversionSoftwareVersion`
- `EchoTime`
- `EchoTrainLength`
- `FlipAngle`
- `ImageOrientationPatientDICOM`
- `ImageType`
- `ImagingFrequency`
- `InPlanePhaseEncodingDirectionDICOM`
- `InversionTime`
- `MRAcquisitionType`
- `MagneticFieldStrength`
- `MatrixCoilMode`
- `Modality`
- `NonlinearGradientCorrection`
- `PartialFourier`
- `PatientPosition`
- `PercentPhaseFOV`
- `PercentSampling`

**Dependencies:** Participant / Session identifiers; BIDS paths; software versions from GeneratedBy / reports.

## Functional MRI

**Purpose:** BOLD runs and shared func metadata.

**Variable count (sampled inventory):** 35

**Example variables:**

- `Category`
- `Count`
- `DerivedVendorReportedEchoSpacing`
- `Description`
- `EchoTime1`
- `EchoTime2`
- `EffectiveEchoSpacing`
- `Percentage`
- `ReconstructionMethod`
- `RepetitionTime`
- `SliceTiming`
- `Source`
- `SpacingBetweenSlices`
- `TaskName`
- `TotalReadoutTime`
- `WipMemBlock`
- `all_bold_protocols`
- `all_mag_fmri_bolds`
- `bold`
- `bold_destination`
- `bold_file`
- `bold_path`
- `bold_target`
- `confidence_level`
- `duration`

**Dependencies:** Participant / Session identifiers; BIDS paths; software versions from GeneratedBy / reports.

## Movie

**Purpose:** task-movie runs and design-level events.

**Variable count (sampled inventory):** 37

**Example variables:**

- `CogAtlasID`
- `Instructions`
- `TaskDescription`
- `TaskName`
- `TimingDisclosure`
- `duration`
- `duration_cap_note`
- `duration_capped_to_scan`
- `events_duration_seconds`
- `expected_RepetitionTime`
- `expected_volumes`
- `eye`
- `eye.Description`
- `eye.Levels.left`
- `eye.Levels.right`
- `mapping_confidence`
- `mapping_method`
- `matlab_run_id`
- `matlab_run_id.Description`
- `movie_label`
- `movie_label.Description`
- `movie_label.Levels.Movie1`
- `movie_label.Levels.Movie2`
- `movie_label.Levels.Movie3`
- `movie_label.Levels.Movie4`

**Dependencies:** Participant / Session identifiers; BIDS paths; software versions from GeneratedBy / reports.

## Rest

**Purpose:** task-rest runs (no trial events by design).

**Variable count (sampled inventory):** 0

**Example variables:**

- NOT AVAILABLE in sampled inventory

**Dependencies:** Participant / Session identifiers; BIDS paths; software versions from GeneratedBy / reports.

## Diffusion

**Purpose:** DWI volumes and gradient tables.

**Variable count (sampled inventory):** 80

**Example variables:**

- `AP_files`
- `BIDSRole`
- `BandwidthPerPixelPhaseEncode`
- `CorrectionRole`
- `DiffusionScheme`
- `Family`
- `InstitutionalDepartmentName`
- `KeyParameters_supported`
- `Manufacturer`
- `ManufacturersModelName`
- `MultibandAccelerationFactor`
- `Notes_QC`
- `PA_files`
- `PE`
- `ParallelReductionFactorInPlane`
- `PhaseEncodingDirection`
- `PixelBandwidth`
- `ProtocolName`
- `QC_item`
- `RawImage`
- `RepetitionTimeExcitation`
- `SequenceFamily`
- `Status`
- `TE_s`
- `TE_s_median`

**Dependencies:** Participant / Session identifiers; BIDS paths; software versions from GeneratedBy / reports.

## Fieldmap

**Purpose:** Spin-echo EPI field maps.

**Variable count (sampled inventory):** 8

**Example variables:**

- `ProtocolName`
- `SeriesNumber`
- `SiemensProtocolNames`
- `bids_ProtocolName`
- `bids_SeriesNumber_json`
- `bids_runs_matching_ProtocolName`
- `in_bids_ProtocolName`
- `matched_SeriesNumber`

**Dependencies:** Participant / Session identifiers; BIDS paths; software versions from GeneratedBy / reports.

## Physiology

**Purpose:** BIDS physio sidecars and derived QC.

**Variable count (sampled inventory):** 80

**Example variables:**

- `CI95_high`
- `CI95_low`
- `Columns`
- `DICOM_stimulus_trigger_available`
- `HRV_RMSSD`
- `ICC`
- `PRI_a`
- `PRI_availability`
- `PRI_b`
- `PRI_quality`
- `PRI_sampling`
- `PRI_signal`
- `PRI_total`
- `PRI_trigger`
- `PhysioLog_available`
- `PhysioQualityCategory`
- `PhysioQualityScore`
- `PulseSequenceDetails`
- `R2`
- `SampleTime_ms`
- `SamplingFrequency`
- `SiemensChannel`
- `StartTime`
- `StartTimeConfidence`
- `StartTimeMethod`

**Dependencies:** Participant / Session identifiers; BIDS paths; software versions from GeneratedBy / reports.

## MRIQC

**Purpose:** MRIQC IQMs for T1w/BOLD.

**Variable count (sampled inventory):** 80

**Example variables:**

- `CNR`
- `DVARS`
- `EchoTime`
- `FlipAngle`
- `MagneticFieldStrength`
- `Manufacturer`
- `ProtocolName`
- `RepetitionTime`
- `SNR`
- `SequenceName`
- `SeriesDescription`
- `acquisition`
- `all_mc_identical`
- `aor`
- `aqi`
- `array_task_id`
- `artifact_probability`
- `b0_SNR`
- `bids`
- `bold_complete`
- `cjv`
- `classification`
- `cnr`
- `confidence`
- `date`

**Dependencies:** Participant / Session identifiers; BIDS paths; software versions from GeneratedBy / reports.

## DWI QC

**Purpose:** Custom / MRtrix DWI QC metrics.

**Variable count (sampled inventory):** 80

**Example variables:**

- `CNR`
- `DVARS`
- `EchoTime`
- `FlipAngle`
- `MagneticFieldStrength`
- `Manufacturer`
- `ProtocolName`
- `RepetitionTime`
- `SNR`
- `SequenceName`
- `SeriesDescription`
- `acquisition`
- `all_mc_identical`
- `aor`
- `aqi`
- `array_task_id`
- `artifact_probability`
- `b0_SNR`
- `bids`
- `bold_complete`
- `cjv`
- `classification`
- `cnr`
- `confidence`
- `date`

**Dependencies:** Participant / Session identifiers; BIDS paths; software versions from GeneratedBy / reports.

## Dataset QC

**Purpose:** Pizarro, defacing, BIDS validation summaries.

**Variable count (sampled inventory):** 80

**Example variables:**

- `CNR`
- `DVARS`
- `EchoTime`
- `FlipAngle`
- `MagneticFieldStrength`
- `Manufacturer`
- `ProtocolName`
- `RepetitionTime`
- `SNR`
- `SequenceName`
- `SeriesDescription`
- `acquisition`
- `all_mc_identical`
- `aor`
- `aqi`
- `array_task_id`
- `artifact_probability`
- `b0_SNR`
- `bids`
- `bold_complete`
- `cjv`
- `classification`
- `cnr`
- `confidence`
- `date`

**Dependencies:** Participant / Session identifiers; BIDS paths; software versions from GeneratedBy / reports.

