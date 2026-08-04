# Data Record

## Repository and access

The dataset will be publicly available through [repository name] under accession [accession number] (DOI: [dataset DOI to be inserted upon deposition]). The release is organised according to the Brain Imaging Data Structure (BIDS) specification (BIDSVersion 1.9.0; DatasetType `raw`), as recorded in `dataset_description.json`. Dataset versioning will follow the hosting repository’s conventions; a top-level `CHANGES` file documents the BIDS package history. The conversion workflow used to generate the organised release is recorded in `dataset_description.json` (`GeneratedBy`: neuro_pipeline, version 2.1.0).

The dataset will be distributed under [licence to be inserted upon deposition].

Software used for DICOM-to-BIDS conversion, metadata handling, quality-control summarisation, anatomical defacing, and release preparation is provided with the `neuro_pipeline` package and accompanying project scripts. The public code repository location and version tag are [code repository URL / version to be inserted upon deposition].

---

## Overview of contents and formats

The release comprises multimodal MRI data organised as a BIDS dataset. Imaging volumes are distributed as gzip-compressed NIfTI files (`*.nii.gz`). Each imaging series is accompanied by a JSON sidecar (`*.json`) containing acquisition and scanner metadata generated during DICOM-to-BIDS conversion. Diffusion series additionally include gradient tables as plain-text `*.bval` and `*.bvec` files. Tabular metadata are provided as tab-separated values (TSV) files, including the participant table (`participants.tsv`) and, where released, functional event timing files (`*_events.tsv`).

The BIDS tree contains 84 participant folders (`sub-*`) and 124 subject–session folders (`ses-01`: 83; `ses-02`: 41). Longitudinal follow-up is incomplete by design of recruitment and retention: 40 participants have both sessions, 43 have `ses-01` only, and 1 has `ses-02` only. Empty placeholder session folders were not created for unavailable visits.

**Table 1.** Inventory of primary imaging NIfTI files in the BIDS release.

| Data type (BIDS suffix) | NIfTI files (*n*) |
| --- | ---: |
| Functional BOLD (`*_bold.nii.gz`) | 2992 |
| Single-band reference (`*_sbref.nii.gz`) | 2892 |
| Spin-echo EPI field maps (`*_epi.nii.gz`) | 982 |
| Diffusion (`*_dwi.nii.gz`) | 361 |
| T1-weighted (`*_T1w.nii.gz`) | 356 |
| B1 / turbo-flash related anatomical (`*_TB1TFL.nii.gz`) | 248 |
| FLAIR (`*_FLAIR.nii.gz`) | 125 |

BOLD acquisitions use the task labels `task-rest`, `task-fmri`, `task-movie`, and `task-control` (250, 1015, 989, and 738 `*_bold.nii.gz` files, respectively). Validated event timing files (`*_events.tsv`) are released for 456 `task-fmri` runs. Physiological recordings from the source archive are not distributed as BIDS physiology files in the present release.

---

## Dataset organisation

The raw BIDS layout is as follows:

```text
bids/
├── dataset_description.json
├── participants.tsv
├── participants.json
├── README
├── CHANGES
└── sub-<ID>/
    └── ses-01/   and/or   ses-02/
        ├── anat/
        ├── func/
        ├── dwi/
        └── fmap/
```

Each participant is identified by a pseudonymous folder `sub-<ID>` (for example, `sub-001`). Imaging visits are stored under `ses-01` (baseline) and, when available, `ses-02` (follow-up). Within each session, modality folders contain:

- `anat/` — anatomical MRI (defaced images in the public release; see Anatomical MRI)
- `func/` — functional BOLD MRI, single-band reference images, and event tables when released
- `dwi/` — diffusion-weighted MRI with accompanying gradient tables
- `fmap/` — spin-echo EPI field-map acquisitions for distortion correction

Dataset-level metadata files include `dataset_description.json`, `participants.tsv`, `participants.json`, and a `README` summarising reuse notes.

Derivative products prepared for the release (anatomical defacing provenance outputs, MRIQC image-quality metrics, and group-level QC summary tables) are provided under a companion `derivatives/` tree (see Derivative data).

---

## Participant metadata

Participant-level metadata are provided in `participants.tsv`, with column definitions in `participants.json`. The table contains one row per participant and the following columns:

| Column | Description |
| --- | --- |
| `participant_id` | Pseudonymous BIDS subject identifier (`sub-<ID>`) |
| `cohort` | Study cohort label |
| `sex` | Participant sex as recorded from source DICOM `PatientSex` (`F` or `M`) |

Cohort labels used in this dataset are:

| `cohort` value | Description |
| --- | --- |
| `Control` | Healthy participants with normal visual function aged 18–50 years |
| `DataON` | Participants with optic neuritis according to inclusion criteria |
| `DataTON` | Participants with traumatic optic neuropathy according to inclusion criteria |
| `Glaucoma` | Participants recruited with glaucoma |

The current table comprises 56 Control, 7 DataON, 2 DataTON, and 19 Glaucoma participants (84 rows in total). Additional demographic or clinical phenotype variables beyond `participant_id`, `cohort`, and `sex` are not distributed in the public `participants.tsv`.

---

## Anatomical MRI

Anatomical images are stored under `sub-*/ses-*/anat/`. Available anatomical modalities include:

- T1-weighted MRI (`*_T1w.nii.gz` with matching `*_T1w.json`)
- fluid-attenuated inversion recovery (FLAIR; `*_FLAIR.nii.gz` / `*_FLAIR.json`)
- turbo-flash B1-mapping / related anatomical series labelled `TB1TFL` (`*_TB1TFL.nii.gz` / `*_TB1TFL.json`)

All anatomical images included in the public release underwent defacing before distribution. Original non-defaced anatomical images were retained only in the private source archive.

NIfTI files store the image volumes. JSON sidecars store acquisition parameters exported during conversion (for example field strength, manufacturer and model, repetition time, echo time, flip angle, and protocol or series names when present).

---

## Functional MRI

Functional MRI data are stored under `sub-*/ses-*/func/`. Four complementary BOLD paradigms are included. Shared acquisition parameters for these BOLD series are TR 937 ms, TE 37 ms, flip angle 52°, 2 mm isotropic resolution, and multiband acceleration factor 8. Stimulation was monocular; the non-stimulated eye was occluded. Each BOLD series is distributed as `*_bold.nii.gz` with a corresponding `*_bold.json` sidecar. Matching single-band reference images (`*_sbref.nii.gz` / `*_sbref.json`) are included when acquired. Phase images, when present, follow BIDS `part-phase` naming.

### Resting-state fixation (`task-rest`)

Resting-state BOLD data were acquired under fixation-only conditions. Participants viewed a uniform grey background with a white fixation cross under monocular viewing. Each resting-state run comprises 320 BOLD volumes (approximately 5 minutes at the shared functional TR).

### Naturalistic movie stimulation (`task-movie`)

Naturalistic movie stimulation was acquired as four functional runs corresponding to movie segments Movie1A, Movie2A, Movie1B, and Movie2B (scanner ProtocolName `Movie1`–`Movie4`). Monocular eye assignment by protocol was: Movie1 / Movie1A, left eye; Movie2 / Movie2A, right eye; Movie3 / Movie1B, right eye; Movie4 / Movie2B, left eye (default `change_eye=0`). A fixation cross was superimposed during movie presentation. Each movie run comprises approximately 210 BOLD volumes (approximately 3.3 minutes). Design-level event files are included for all magnitude movie BOLD runs (`onset = 0` under a lab-confirmed scan↔movie co-start assumption; duration = measured MP4 length). Movie video files are not redistributed because of copyright restrictions; clip identity is recorded in `events.tsv` and `code/task-movie/`.

### Block-design visual stimulation (`task-fmri`)

Visually driven task BOLD data were acquired using a block-design grating and checkerboard stimulation paradigm synchronised to MRI scanner triggers. After an initial baseline of 10 TRs, the design comprised 12 cycles of 8 TR stimulus presentation alternating with 10 TR baseline periods, for a total of 226 BOLD volumes per run. Twelve stimulus conditions (`stim-01` to `stim-12`) encompassed magnocellular and parvocellular variants and grating and checkerboard conditions. During presentation, a fixation marker consisting of a blue/red oval with a central cross was displayed. Stimulus order was randomised across subjects.

Validated event timing files (`*_events.tsv`) are released for 456 `task-fmri` runs. Event files were only generated when stimulus timing could be reconstructed with sufficient confidence from original experimental records and when a unique correspondence between protocol records and one BIDS BOLD acquisition could be established. Released event tables include the columns `onset` (seconds relative to the start of the BOLD run), `duration` (seconds), and `trial_type` (condition label). Observed `trial_type` values are `baseline` and `stim-01` … `stim-12`. Column definitions are provided in `task-fmri_events.json`; a machine-readable parameter dictionary for `stim-01`…`stim-12` is provided in `code/task-fmri_condition_dictionary.tsv`.

### Control functional runs (`task-control`)

Short control functional runs were acquired under the BIDS task label `task-control`. Each control run comprises 20 BOLD volumes (approximately 19 seconds). Detailed stimulus content for these control runs could not be fully reconstructed from the available documentation; corresponding event timing files are therefore not released.

---

## Diffusion MRI

Diffusion-weighted MRI data are stored under `sub-*/ses-*/dwi/`. The release contains 361 diffusion series. Each series is distributed as:

- `*_dwi.nii.gz` — diffusion-weighted image volumes
- `*_dwi.json` — acquisition metadata sidecar
- `*.bval` — b-values (s/mm²) for each volume
- `*.bvec` — diffusion gradient directions for each volume

Diffusion acquisitions included both single-shell and multi-shell protocols. In the present release, series use either a *b* = 0/1000 s/mm² scheme or a *b* = 0/1000/2000 s/mm² scheme (121 and 240 series, respectively). The number of diffusion-encoding directions varies by acquisition and is recorded in the accompanying `.bvec` files; the single-shell (*b* = 0/1000) series consistently include 11 non-zero diffusion volumes, whereas multi-shell (*b* = 0/1000/2000) series typically comprise larger direction sets (most commonly 365 non-zero diffusion volumes). Exact *b*-value tables and gradient directions for each run are provided with the corresponding `.bval` and `.bvec` files.

---

## Field maps

Field-map images are stored under `sub-*/ses-*/fmap/`. The released field maps are spin-echo echo-planar imaging (EPI) acquisitions acquired in opposing phase-encode directions (`dir-AP` and `dir-PA`), including magnitude and phase (`part-phase`) images where acquired (982 `*_epi.nii.gz` files). These acquisitions support correction of susceptibility-related geometric distortions in co-acquired echo-planar functional and diffusion data. Sidecar JSON files include phase-encoding direction, total readout time, and `IntendedFor` references linking field maps to target functional or diffusion runs when those fields were populated during conversion.

---

## Physiological recordings

Physiological recordings were available in the source archive but were not included in the current BIDS release because validated BIDS physiological metadata were not prepared.

---

## Derivative data

Derivative products accompany the raw BIDS release to support inspection and reuse. They are not completed analysis endpoints (for example, they do not include group-level statistical maps, fully preprocessed modelling-ready functional time series, or tractography results).

**Anatomical defacing.** Defaced anatomical images and associated provenance metadata are provided under `derivatives/defacing/`, preserving the BIDS subject/session layout (`sub-*/ses-*/anat/`). Defacing was applied to T1-weighted, FLAIR, and face/head field-of-view `TB1TFL` series using pydeface as part of the release preparation workflow. As noted above, only defaced anatomical images are included in the public imaging distribution; non-defaced originals remain in the private source archive.

**MRIQC.** Automated MRI Quality Control (MRIQC) outputs are provided under `derivatives/mriqc/` for anatomical (T1-weighted) and functional (BOLD) images. These outputs include HTML visual reports and JSON image-quality metric files. Automated image-quality metrics are provided for images processed at the time of release.

**Group-level QC tables.** Summary QC tables and related documentation aids are provided under `derivatives/group_qc/` to support inventory checks and inspection of the raw release.

---

## Code availability

Conversion, validation, quality-control, anonymization, and release-preparation code used to assemble the dataset are provided with the `neuro_pipeline` package and accompanying project scripts. Available materials include routines for DICOM-to-BIDS conversion and metadata handling, BIDS validation support, anatomical defacing, MRIQC summarisation, diffusion QC inventory checks, and release packaging utilities. The public code repository URL, version tag, and preferred citation are [to be inserted upon deposition].

---

# Remaining information required before submission

*(Editorial checklist — not part of the manuscript text.)*

| Item | Action |
| --- | --- |
| Public repository name | Insert (e.g., OpenNeuro) |
| Accession number | Insert after deposition |
| Dataset DOI | Insert into text and `dataset_description.json` (`DatasetDOI`) |
| Licence | Confirm and insert (also `License` in `dataset_description.json`) |
| Code repository URL / version / citation | Insert |
| Authors list for public deposit | Replace any placeholder authors in `dataset_description.json` |
| Public packaging of anatomicals | Confirm the deposited tree contains **only defaced** anatomical NIfTI (not the private non-defaced archive) |
| Derivatives in the same deposit vs separate | State final packaging choice consistently in Repository and Derivative sections |
| `stim-01`…`stim-12` → stimulus-parameter dictionary | **Done** — `bids/task-fmri_events.json` + `bids/code/task-fmri_condition_dictionary.tsv` |
| Control age range 18–50 | Confirm against Protocol 2020-5879 inclusion criteria before submission |
| Clinical inclusion criteria wording for DataON / DataTON / Glaucoma | Confirm against protocol text if reviewers request detail |
| Duplicate README files (`README` vs `README.md`) | **Done** — single `README.md` retained |
