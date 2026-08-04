# 3. Data Records

The dataset is organised according to the Brain Imaging Data Structure (BIDS) specification (BIDS version 1.9.0; `DatasetType`: `raw`) and will be made publicly available through [repository name] under accession [accession number] (DOI: [dataset DOI to be inserted upon deposition]). Dataset versioning follows the hosting repository’s conventions. A top-level `CHANGES` file documents BIDS package history. The conversion workflow is recorded in `dataset_description.json` (`GeneratedBy`: neuro_pipeline, version 2.1.0). The licence under which the data are distributed is [licence to be inserted upon deposition].

## 3.1 Dataset organization

The release comprises a raw BIDS tree with dataset-level metadata files (`dataset_description.json`, `participants.tsv`, `participants.json`, `README`, `CHANGES`), optional dataset-level event data dictionaries (`task-fmri_events.json`, `task-movie_events.json`), a `code/` directory with reusable stimulus dictionaries, participant folders (`sub-<ID>`), and companion derivative folders under `derivatives/` (anatomical defacing and MRIQC outputs). Imaging visits are stored under `ses-01` and, when available, `ses-02`. Within each session, modality folders are `anat/` (anatomical MRI), `func/` (BOLD, single-band references, event tables when released, and physiology when converted), `dwi/` (diffusion-weighted MRI), and `fmap/` (spin-echo field maps).

```text
dataset/
├── dataset_description.json
├── participants.tsv
├── participants.json
├── task-fmri_events.json
├── task-movie_events.json
├── README
├── CHANGES
├── code/
├── sub-<ID>/
│   └── ses-01/ and/or ses-02/
│       ├── anat/
│       ├── func/
│       ├── dwi/
│       └── fmap/
└── derivatives/
    ├── defacing/
    └── mriqc/
```

The BIDS tree contains 84 participant folders and 135 subject–session folders (`ses-01`: 83; `ses-02`: 52). Longitudinal follow-up is incomplete by recruitment and retention: 51 participants have both sessions, 32 have `ses-01` only, and 1 has `ses-02` only. Empty placeholder session folders were not created for unavailable visits. The file `participants.tsv` lists `participant_id`, `cohort` (`Control`, `DataON`, `DataTON`, or `Glaucoma`), and `sex`, with column definitions in `participants.json`. Derivative products under `derivatives/` support public anatomical sharing and quality documentation; they are not completed analysis products (for example, they do not include group statistical maps or fully preprocessed functional time series ready for modelling).

## 3.2 Imaging data formats

Imaging volumes are distributed as gzip-compressed NIfTI files (`*.nii.gz`). Each imaging series is accompanied by a JSON sidecar (`*.json`) containing acquisition and scanner metadata generated during DICOM-to-BIDS conversion.

Anatomical images under `anat/` include T1-weighted volumes (`*_T1w.nii.gz`; standard MPRAGE and white-matter-nulled MPRAGE, distinguished in sidecars by `SeriesDescription` / `ProtocolName`), FLAIR (`*_FLAIR.nii.gz`), and turbo-flash B1-related series (`*_TB1TFL.nii.gz`). Functional images under `func/` include magnitude BOLD series (`*_bold.nii.gz`) for tasks `rest`, `fmri`, `movie`, and `control`, together with single-band reference images (`*_sbref.nii.gz`) when acquired. Phase images, when present, follow BIDS `part-phase` naming. Shared functional EPI parameters (including TR, TE, flip angle, voxel size, and multiband factor) are recorded in each BOLD JSON sidecar; paradigm design is described in Methods. Diffusion series under `dwi/` are released as `*_dwi.nii.gz` with matching `*_dwi.json`, `*.bval`, and `*.bvec` files. Field maps under `fmap/` are spin-echo EPI acquisitions with opposing phase-encode directions (`dir-AP`, `dir-PA`), including magnitude and phase images where acquired; sidecars include phase-encoding direction, total readout time, and `IntendedFor` references when available.

Approximate inventory counts in the current tree are: 387 T1w, 137 FLAIR, 272 TB1TFL, 1625 magnitude BOLD (3248 including phase), 3124 SBRef, and 1090 field-map EPI NIfTI files. Diffusion NIfTI and gradient tables are provided for each inventoried DWI series (see Technical Validation for integrity checks).

## 3.3 Metadata and tabular records

Dataset-level tabular metadata are provided as tab-separated values (TSV) files with JSON data dictionaries where applicable. Participant-level metadata are in `participants.tsv`. Acquisition parameters for every imaging series are in the corresponding JSON sidecars. Task event files, when released, are stored beside the linked BOLD run as `*_events.tsv`, with column definitions in dataset-root `task-fmri_events.json` and `task-movie_events.json` and, when present, per-run `*_events.json` provenance sidecars. Physiological time series are stored as gzip-compressed TSV files with JSON sidecars (Section 3.5).

Reusable stimulus lookup tables are distributed under `code/` so that condition labels in event files can be interpreted without laboratory MATLAB: `code/task-fmri_condition_dictionary.tsv` (with `code/task-fmri_condition_dictionary.json`) maps `stim-01`…`stim-12` to pathway and stimulus parameters; `code/task-movie/` provides movie run, clip, and eye-assignment tables and a README. The dataset `README` summarises reuse caveats (longitudinal coverage, intentional missing events, copyright restrictions on movie media).

## 3.4 Task-related records

Functional BOLD runs use BIDS task labels `task-rest`, `task-movie`, `task-fmri`, and `task-control`. Acquisition design, viewing conditions, and stimulus content are described in Methods; this section records what task-related files are present in the deposit.

For `task-rest` and `task-control`, no `*_events.tsv` files are released (rest has no task events by design; control stimulus content could not be fully reconstructed from available documentation). For `task-fmri`, 514 event tables are released with columns `onset`, `duration`, and `trial_type` (`baseline` or `stim-01`…`stim-12`). Event files were generated only when a unique correspondence between protocol records and a magnitude BOLD acquisition could be established; unmatched grating runs intentionally lack events. Condition semantics are defined in `task-fmri_events.json` and `code/task-fmri_condition_dictionary.tsv`.

For `task-movie`, design-level `*_events.tsv` files are released for all 536 magnitude movie BOLD runs. Columns include `onset`, `duration`, `trial_type` (`movie`), `stim_file`, `eye`, `movie_label`, and `matlab_run_id` (definitions in `task-movie_events.json`). Timing uses `onset = 0` under a laboratory protocol assumption that acquisition and clip playback started together, with `duration` equal to the measured MP4 length or capped to scan length for truncated runs; these events support run-level continuous-movie models and are not millisecond TTL-locked onsets. Movie video files are not redistributed because of copyright restrictions. Run-to-clip and eye-assignment maps are provided under `code/task-movie/`.

## 3.5 Physiological records

Siemens physiological monitoring acquired during functional EPI was converted, where release gates were met, into BIDS physiology files colocated with the corresponding BOLD run under `func/`, named `*_recording-<channel>_physio.tsv.gz` with matching `*_physio.json` sidecars. Channels present in the release include `pulse` (cardiac), `respiratory`, `trigger`, and rarely `ecg`. The current tree contains 3620 physiology TSV.GZ files spanning 77 participants. Sidecars report `SamplingFrequency`, `SampleTime_ms`, `SiemensChannel`, `StartTime` (seconds relative to the start of the linked BOLD series), `StartTimeMethod`, and `StartTimeConfidence` (commonly `MEDIUM`). Approximately 78% of magnitude BOLD runs have at least one physiology file; absence of physiology for a given run indicates failed conversion gates or no archived PhysioLog for that acquisition, not an invalid BOLD series.

Session-wide peripheral PMU logs without unique run linkage under the release policy, eye-tracking time series, and copyrighted movie media are not included in this BIDS package. Users should consult each run’s `*_physio.json` before assuming high-precision synchronisation.
