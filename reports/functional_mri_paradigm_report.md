# Functional MRI paradigm report

**Purpose:** Repository inspection to support manuscript section **4.2.1 Functional MRI paradigm**.  
**Generated from existing metadata and visit documentation only.** No DICOM re-scan; no files modified.

**Primary sources**
- `metadata/session_mapping.csv` (coverage, naming, session organization)
- `reports/protocol_sample/sequence_parameters.json`, `scanner_summary.json`, `sequence_summary.md`, `methods_mri_acquisition.md`
- `reports/mri_acquisition_table/MRI_Acquisition_Table.md`
- `reports/protocol_completeness/protocol_completeness_summary.md`
- Stimulus / operator code under `raw_original/**/**_MATLAB/` (sampled Control visit `SUBC01-Session1-2023MAY5`)
- Operator `README.pdf` files under Data_ON / Data_TON MATLAB folders
- BIDS task naming logic in `neuro_pipeline/neuro_pipeline/convert_to_bids.py` (**no converted `bids/` tree is present**)

**Dataset scope used for counts:** 84 participants, 135 sessions.

---

# 1. Functional MRI acquisitions

Functional series are stored with Siemens-style labels ending in phase-encode direction (`_AP` or `_PA`). Each bold run is typically accompanied by a single-band reference (`*_SBRef`) and a physiological log series (`*_PhysioLog`). Coverage below counts **primary** series (exact label match; SBRef/PhysioLog excluded).

| Acquisition | Paradigm | Planned PE | Subjects with ≥1 series | Sessions with ≥1 series | Median series rows / session* | Missing subjects (IDs) | Proposed BIDS task / suffix† |
|---|---|---|---:|---:|---:|---|---|
| REST1_AP | Resting-state | AP | 83 | 132 | 2.0 | 1 (`sub-055`) | `task-rest` / `bold` |
| Movie1_AP | Movie viewing | AP | 83 | 134 | 2.0 | 1 (`sub-063`) | `task-movie` / `bold` |
| Movie2_AP | Movie viewing | AP | 82 | 132 | 2.0 | 2 (`sub-010`, `sub-063`) | `task-movie` / `bold` |
| Movie3_AP | Movie viewing | AP | 82 | 132 | 2.0 | 2 (`sub-010`, `sub-063`) | `task-movie` / `bold` |
| Movie4_AP | Movie viewing | AP | 81 | 130 | 2.0 | 3 (`sub-010`, `sub-055`, `sub-063`) | `task-movie` / `bold` |
| fMRI1_AP | Task (grating) | AP | 83 | 134 | 2.0 | 1 (`sub-063`) | `task-fmri` / `bold` |
| fMRI2_AP | Task (grating) | AP | 83 | 134 | 2.0 | 1 (`sub-063`) | `task-fmri` / `bold` |
| fMRI3_AP | Task (grating) | AP | 83 | 134 | 2.0 | 1 (`sub-063`) | `task-fmri` / `bold` |
| fMRI4_AP | Task (grating) | AP | 83 | 134 | 2.0 | 1 (`sub-063`) | `task-fmri` / `bold` |
| Control1_PA | Control | PA | 83 | 134 | 2.0 | 1 (`sub-063`) | `task-control` / `bold` |
| Control2_AP | Control | AP | 82 | 124 | 2.0 | 2 (`sub-055`, `sub-070`) | `task-control` / `bold` |
| Control2_PA | Control (variant) | PA | 7 | 7 | 2.0 | 77 | `task-control` / `bold` |
| Control3_AP | Control (variant) | AP | 7 | 7 | 2.0 | 77 | `task-control` / `bold` |
| Control3_PA | Control | PA | 81 | 121 | 2.0 | 3 (`sub-053`, `sub-055`, `sub-070`) | `task-control` / `bold` |
| SpinEchoFieldMap_AP | SE field map | AP | 84 | 135 | 4.0 | 0 | `dir-AP` / `epi` (fmap) |
| SpinEchoFieldMap_PA | SE field map | PA | 84 | 135 | 4.0 | 0 | `dir-PA` / `epi` (fmap) |

\*Many visits store **two DICOM series rows** per labelled run (consecutive series numbers with the same `SeriesDescription`); this is reflected in the median of 2.0. Field maps often appear as multiple AP/PA series per session (median 4).  
†BIDS labels come from pipeline `derive_task_name()`; **no BIDS NIfTI/JSON outputs are present in the repository**.

**Associated ancillary series (not listed as primary runs):** `*_SBRef`, `*_PhysioLog`, occasional `*_Pha`, and rare redo labels (`fMRI1_AP_REDO`, `fMRI1_AP_Rerun`, `Movie4_AP_redo_cuz_gogle_moved`, `Control2_AP_redo`, `SpinEchoFieldMap_AP_rerun`).

**Naming convention:** `{Paradigm}{Index}_{PE}` for functional runs (e.g. `Movie3_AP`, `fMRI2_AP`, `Control1_PA`); field maps use `SpinEchoFieldMap_{PE}`.

---

# 2. MRI acquisition parameters

Parameters below are taken from the protocol sample extraction (`reports/protocol_sample/sequence_parameters.json`; exemplar subject SUBC01 / session 2023-05-05) and the curated table `MRI_Acquisition_Table.md`. Values marked **Not available** were not present in those extracts.

## 2.1 Scanner (protocol sample)

| Field | Value |
|---|---|
| Manufacturer | SIEMENS (also recorded as “Siemens Healthineers” on some series) |
| Model | Prisma / MAGNETOM Prisma |
| Field strength | 3 T (one sample header entry listed field strength as Not available) |
| Software | syngo MR E11 |
| Coil | **Not available** in protocol_sample / acquisition table |

## 2.2 Shared multiband EPI parameters (REST / Movie / fMRI / Control)

| Parameter | Value in repository | Notes |
|---|---|---|
| Sequence name | `epfid2d1_104` | All functional bold series in sample |
| Pulse sequence type | EPI (FID) / multiband EPI | Inferred from Siemens sequence name; explicit “MB factor” tag **Not available** |
| TR | 937 ms | Identical across REST, Movie, fMRI, Control in sample |
| TE | 37 ms | Identical |
| Flip angle | 52° | Identical |
| Multiband factor | **Not available** | Not stored in `sequence_parameters.json` |
| Slice thickness | 2 mm | |
| Voxel size | 2 mm isotropic (`pixel_spacing` [2, 2]) | |
| Matrix (rows × columns) | 1040 × 1040 | As stored in sample DICOM extract (likely reconstruction/mosaic representation; use with caution) |
| Number of slices / volumes | See per-paradigm table | Sample field `number_of_volumes` is **Not available**; `number_of_slices` for EPI equals DICOM file count / volumes |
| Slice timing | **Not available** | No BIDS JSON sidecars on disk |
| Phase encoding direction | AP or PA from series name | Explicit DICOM PE encoding tag not exported in sample JSON |
| Effective echo spacing | **Not available** | |
| Total readout time | **Not available** | |
| Acquisition duration | Approximate = volumes × TR | REST ~5.0 min; Movie ~3.3 min; Task ~3.5 min; Control ~19 s |
| Dummy scans | **Not available** | |
| Parallel imaging | **Not available** as named factor | |
| Fat suppression | **Not available** | |
| Partial Fourier | **Not available** | |
| Bandwidth | **Not available** | |

### Per-paradigm volume counts (from sample + `MRI_Acquisition_Table.md` / `n_dicom_files`)

| Series family | Volumes (files) | Approx. duration @ TR 937 ms |
|---|---:|---|
| REST1_AP | 320 | ~5.00 min |
| Movie1–4_AP | 210 | ~3.28 min |
| fMRI1–4_AP | 226 | ~3.53 min |
| Control1–3 | 20 | ~0.31 min |

## 2.3 Spin-echo field maps

| Parameter | Value |
|---|---|
| Sequence name | `epse2d1_104` |
| TR | 9710 ms |
| TE | 66 ms |
| Flip angle | 90° |
| Voxel size | 2 mm isotropic |
| PE | AP and PA (`SpinEchoFieldMap_AP` / `_PA`) |
| Volumes | Typically 1 DICOM file per series row |

## 2.4 Parameter consistency across functional runs

Within the protocol sample, **TR, TE, flip angle, slice thickness, pixel spacing, matrix, sequence name, manufacturer, model, and software** are **identical** for REST1_AP, Movie*_AP, fMRI*_AP, and Control*_PA/AP. Differences are limited to:
- phase-encode direction encoded in the series name (AP vs PA for Control / field maps);
- number of volumes / DICOM files;
- field-map pulse sequence (`epse2d1_104` vs `epfid2d1_104`).

No dataset-wide quantitative comparison of every participant’s TR/TE was performed here (would require per-series re-extraction); completeness analysis uses series **presence**, not per-header re-reads.

---

# 3. Functional paradigms

## 3.1 Resting-state (`REST1_AP`)

- **Runs:** 1 labelled resting-state acquisition per typical session (often 2 DICOM series rows).
- **BIDS task name (planned):** `task-rest`.
- **Associated files:** `REST1_AP_SBRef`, `REST1_AP_PhysioLog`; MATLAB `4-resting state/main.m`.
- **Paradigm (from code):** 320 TRs; monocular gray background with white fixation cross (0.25°); wait for scanner trigger key `t` (FORP); non-stimulated eye black. No stimulus blocks.

## 3.2 Movie viewing (`Movie1_AP`–`Movie4_AP`)

- **Runs:** 4 movie runs per typical session.
- **BIDS task name (planned):** `task-movie` (run index 1–4).
- **Associated files:** SBRef + PhysioLog per run; MATLAB `3-Movie_Data/main.m`, `Show_movie.m`; movie files referenced as `Movie1A.mp4`, `Movie2A.mp4`, `Movie1B.mp4`, `Movie2B.mp4` on the stimulus PC.
- **Paradigm (from code/README):** run_id 1–4 maps to Movie1A (left eye), Movie2A (right), Movie1B (right), Movie2B (left); start on trigger `t`; abort with `space`; fixation overlay during playback; 210 volumes.

## 3.3 Task fMRI / grating (`fMRI1_AP`–`fMRI4_AP`)

- **Runs:** 4 scanner labels (`fMRI1`–`fMRI4`); operator README refers to up to 16 grating runs (8 left / 8 right eye) in the stimulus workflow—**scanner series inventory shows four fMRI labels per typical session**.
- **BIDS task name (planned):** `task-fmri`.
- **Associated files:** SBRef + PhysioLog; MATLAB `2-Grating/` (`main.m`, `presentStimParams.m`, `RandomGenerator.m`, grating/checker generators).
- **Paradigm (from code):** block design locked to TR via `t` trigger; `firstBaselineEnd = 10` TRs; 12 cycles of 8 TR stimulus + 10 TR baseline → **226 TRs**; 12 stimulus types (magno/parvo grating/checker variants); fixation: blue outer + red inner oval + white cross; eye stimulated depends on run configuration; run order randomized once per subject (`RandomGenerator.m` → `Results/runs_random.mat`).

## 3.4 Control acquisitions (`Control1_PA`, `Control2_AP`/`_PA`, `Control3_AP`/`_PA`)

- **Runs:** Typically Control1 (PA), Control2 (AP in most subjects; PA variant rare), Control3 (PA in most; AP variant rare); 20 volumes each.
- **BIDS task name (planned):** `task-control`.
- **Associated files:** SBRef + PhysioLog when present.
- **Stimulus content:** **Not documented** in sampled MATLAB folders (no dedicated control paradigm script found). Acquisition parameters match other functional EPI.

## 3.5 Reverse phase-encode / spin-echo field maps

- `SpinEchoFieldMap_AP` and `SpinEchoFieldMap_PA` present in **all 135 sessions**.
- Used for susceptibility distortion correction (AP/PA pair).
- BIDS: `*_dir-AP_*_epi` / `*_dir-PA_*_epi` under `fmap/` (planned).

## 3.6 Calibration / localizer (non-paradigm, but in session)

- `Localizer` at session start.
- FOV / eye-dominance checks and isoluminance scripts in MATLAB (`0-Islominance_*`, `1-Check_FOV_and_EyeTracking/`) precede functional paradigms operationally.

---

# 4. Session organization

## 4.1 Sessions per participant

| Sessions per participant | Participants |
|---:|---:|
| 1 | 33 |
| 2 | 51 |
| **Mean** | **1.61** |
| **Total sessions** | **135** |

## 4.2 Standard functional core completeness

Defined core for a “complete” functional protocol within a session:  
`REST1_AP` + `Movie1–4_AP` + `fMRI1–4_AP`.

| Metric | Value |
|---|---:|
| Sessions with complete core | 130 / 135 |
| Sessions incomplete | 5 |

### Incomplete sessions (exceptions)

| Participant | Session | Cohort | Missing from core |
|---|---|---|---|
| sub-010 | ses-01 | Control | Movie2, Movie3, Movie4 |
| sub-049 | ses-02 | Control | REST1, Movie4 |
| sub-055 | ses-01 | Control | REST1, Movie4 (also no T1 anatomical; functional-heavy visit) |
| sub-063 | ses-01 | Data_ON | Movies 1–4, fMRI 1–4 (has REST1 + Control + field maps) |
| sub-078 | ses-02 | Glaucoma | REST1, Movie2–4 |

## 4.3 Control-run naming variants

Most participants use `Control2_AP` + `Control3_PA`. A minority use `Control2_PA` and/or `Control3_AP` (7 participants each in exact-label counts). This is a **protocol labelling / PE convention difference**, not absence of all control runs.

## 4.4 Additional / redo runs

Redo/rerun series exist for a small number of visits (examples: `fMRI1_AP_REDO`, `fMRI*_Rerun`, `Movie4_AP_redo_cuz_gogle_moved`, `Control2_AP_redo`, `SpinEchoFieldMap_AP_rerun`). These are **additional** series beyond the standard labels.

---

# 5. Dataset-wide consistency

| Aspect | Consistent? | Evidence |
|---|---|---|
| Scanner family | Largely yes | SIEMENS Prisma / MAGNETOM Prisma; software syngo MR E11 in sample |
| Functional EPI geometry (sample) | Yes | Shared TR/TE/FA/voxel size/sequence name |
| Number of functional run labels | Mostly | 130/135 sessions have full REST+Movie+fMRI core |
| Control PE labels | No | Mix of Control2/3 AP vs PA conventions |
| Duplicate series rows per label | Common | Median 2 rows per functional label |
| Identical protocol for every participant/session | **No** | 5 incomplete sessions; Control PE variants; redo series |
| BIDS conversion outputs | N/A | `bids/` not present |

**Every highlighted inconsistency**
1. Incomplete functional core in 5 sessions (table above).  
2. Control2/Control3 phase-encode label variants (`_AP` vs `_PA`).  
3. Occasional redo/rerun series.  
4. `sub-055` lacks REST1 and anatomical T1 (functional + fieldmap session).  
5. `sub-063` ses-01 lacks Movies and task fMRI series.  
6. No repository-wide confirmation that every visit used identical multiband factor / echo spacing (tags not in extracts).  
7. Planned BIDS task naming exists in code, but converted BIDS data / JSON sidecars / `events.tsv` are absent.

---

# 6. Acquisition timeline

Exact primary-series order for a **complete exemplar session** (`sub-001` / `ses-01`), ordered by `series_number` after excluding SBRef, PhysioLog, and derived maps:

```
Localizer
↓
fMRI1_AP
↓
fMRI2_AP
↓
Control1_PA
↓
fMRI3_AP
↓
fMRI4_AP
↓
Movie1_AP
↓
Movie2_AP
↓
Movie3_AP
↓
Movie4_AP
↓
REST1_AP
↓
SpinEchoFieldMap_AP
↓
SpinEchoFieldMap_PA
↓
T1w_MPR
↓
Sag Flair 3D-0.8
↓
WMn_MPRAGE_sagittal
↓
gsld_76dir_b2000_1mmiso_AP  (DWI)
↓
tfl_b1map_1mmiso
↓
gsld_75TE_PA_3b0
↓
Control3_AP
↓
Control2_PA
```

**Notes**
- Functional block (task → control → movies → rest → field maps) precedes anatomical/DWI in this Control session.
- Later Control2/Control3 appear after diffusion/B1 in this visit; ordering of Control2/3 relative to anatomicals can vary.
- A Data_TON protocol PDF sampled by exploration listed a similar functional block (fMRI → Control → Movies → fieldmaps → REST → anatomicals); minor order differences across cohorts/visits should be expected.

---

# 7. Participant instructions

No participant-facing instruction sheets (Word/PDF for subjects) were found. Available text is **operator-facing** (MATLAB comments + `README.pdf` in MATLAB folders).

### Rest (`4-resting state/main.m`)
- Fixation spot radius 0.25°.
- `trs = 320`.
- Wait for trigger key `t` from FORP device.
- Stimulated eye: gray background + fixation; non-stimulated eye black.
- **No explicit “eyes open/closed” sentence** beyond fixation presentation to the stimulated eye.

### Movie (`3-Movie_Data/main.m`, `Show_movie.m`; operator README)
- “press t to start --> this comes from the trigger box”
- “press space to finish”
- run_id mapping to Movie1A/2A/1B/2B and left/right eye stimulation.
- Fixation overlay during movie playback.
- README: set `change_eye` from FOV results; choose run 1–4.

### Task / grating (`2-Grating/main.m`, `presentStimParams.m`; operator README)
- Trigger `t` to start; fixation spot on stimulated eye; non-stimulated eye blank.
- Block design with initial baseline (10 TRs) then alternating stimulus/baseline cycles.
- Fixation: inner radius 0.15°, outer 0.25°; red fixation color in params.
- README: run `RandomGenerator` once per subject; set eye from FOV; start scanner when “Experiment will start shortly” appears; expected grating run structure described for operators.

### FOV / eye check (`1-Check_FOV_and_EyeTracking/main.m`)
- Press `t` to start stimulus; press `esc` to end.
- Ask subject what they see with left/right eye (stereo eye-dominance / FOV check).
- Modes for same-color / different-color dots and checkerboard to both eyes.

### Button presses
- Operator/scanner trigger: key `t` (FORP).
- Abort movie: `space`.
- FOV end: `esc`.
- **No participant response-button mapping for task/movie/rest was found in the sampled code.**

### events.tsv / Stimulus onset files
- **Not present** in repository (BIDS not materialized).
- Eye-tracking `*_Events.txt` files exist under some visit EyeTracking folders (fixation/saccade timing), not scanner stimulus onset tables.

---

# 8. Acquisition documentation

| Document type | Location / example | Content recovered |
|---|---|---|
| Protocol sample Methods | `reports/protocol_sample/methods_mri_acquisition.md` | Scanner + per-series parameters (draft; contains a duplicated conflicting field-strength line: 3 T vs Not available) |
| Sequence catalogue | `reports/protocol_sample/sequence_summary.md`, `sequence_parameters.json` | Full extracted parameter list for sample visit |
| Manuscript acquisition table | `reports/mri_acquisition_table/MRI_Acquisition_Table.*` | Condensed publication table |
| Completeness tables | `reports/protocol_completeness/*` | Presence percentages by cohort |
| Siemens session PDF exports | e.g. `raw_original/Data_TON/.../SUBT01_Session02_2024JUN01.pdf` | Protocol table of contents / sequence pages |
| Operator README PDF | `raw_original/Data_ON|Data_TON/**/**_MATLAB/README.pdf` | FOV, Grating, Movie operator steps |
| MATLAB paradigm code | `raw_original/**/**_MATLAB/{2-Grating,3-Movie_Data,4-resting state}` | Timing, fixation, triggers |
| Pipeline BIDS Methods | `neuro_pipeline/docs/METHODS_BIDS.md` | Conversion/metadata policy (not paradigm content) |

**Useful notes recovered**
- Protocol folder names: `DR_SHMUEL_COMPLETE_PROTOCOL`, `DR_SHMUEL_FINAL_PROTOCOL`.
- Functional geometry described as 2 mm isotropic multiband EPI, TR 937 ms, TE 37 ms, FA 52°.
- Field maps: spin-echo EPI AP/PA, TR 9710 ms, TE 66 ms.

---

# 9. Functional MRI summary (publication-ready draft)

Functional MRI data were acquired on a Siemens Prisma 3 T system (software syngo MR E11) using a shared multiband EPI prescription (TR 937 ms; TE 37 ms; flip angle 52°; 2 mm isotropic voxels; sequence name `epfid2d1_104`). Within a typical session, participants completed four grating-task runs (`fMRI1_AP`–`fMRI4_AP`; 226 volumes each), brief control EPI runs (`Control*`; 20 volumes), four movie-viewing runs (`Movie1_AP`–`Movie4_AP`; 210 volumes each), and one resting-state run (`REST1_AP`; 320 volumes), accompanied by single-band references and physiological log series. Spin-echo EPI field maps were acquired in opposing phase-encode directions (`SpinEchoFieldMap_AP`/`PA`) for distortion correction. Task and movie runs were presented with Psychtoolbox scripts synchronized to the scanner trigger; the grating paradigm used a TR-locked block design with fixation, and resting-state runs used monocular fixation without stimulus blocks. Movie runs presented one of four movie segments with monocular stimulation assigned by run. Of 135 sessions, 130 contained the full resting-state, movie, and task series set; exceptions and control phase-encode labelling variants are documented in the repository completeness tables. Detailed numerical parameters are provided in the MRI acquisition table; BIDS conversion of these series (planned task labels `rest`, `movie`, `fmri`, `control`) had not been materialized in the inspected workspace.

---

# 10. Missing information

| Missing item | Why it matters | Where it would normally be obtained |
|---|---|---|
| Converted BIDS dataset (`bids/`), JSON sidecars | Slice timing, EffectiveEchoSpacing, TotalReadoutTime, MultibandAccelerationFactor, CoilName | dcm2niix JSON from DICOM; Siemens CSA headers |
| `events.tsv` / stimulus onset files | Exact event timing for modelling | Stimulus logs exported by Psychtoolbox scripts; eye-tracking synced logs |
| Explicit multiband factor | Methods completeness | DICOM CSA / protocol PDF / IDEA sequence card |
| Effective echo spacing / total readout time | Distortion correction | DICOM / dcm2niix JSON |
| Coil name | Hardware description | DICOM `(0018,1250)` Receive Coil Name / protocol |
| Dummy / discarded volumes | Preprocessing | Protocol card or scanner PDF |
| Parallel imaging factor, partial Fourier, bandwidth, fat sat | Full sequence card | Siemens protocol PDF / DICOM |
| Slice timing vector | Slice-time correction | DICOM / JSON sidecar |
| Participant-facing instruction sheet (eyes open/closed wording) | Methods reproducibility | Consent/instruction PDF (not found) |
| Control-run stimulus definition | Interpret `task-control` | Missing MATLAB/protocol description |
| Dataset-wide per-subject TR/TE audit | Confirm zero parameter drift | Would require reading one DICOM header per series (not done here by design) |
| Confirmed BIDS run indexing vs four fMRI labels vs “16 grating runs” in README | Align operator docs with scanner series | Operator README vs `session_mapping` (discrepancy unresolved) |

---

## Source file index

| Path | Role |
|---|---|
| `metadata/session_mapping.csv` | Acquisition presence & series order |
| `reports/protocol_sample/sequence_parameters.json` | Parameter extraction sample |
| `reports/protocol_sample/scanner_summary.json` | Scanner summary |
| `reports/mri_acquisition_table/MRI_Acquisition_Table.md` | Publication parameter table |
| `reports/protocol_completeness/protocol_completeness_summary.md` | Completeness by cohort |
| `neuro_pipeline/neuro_pipeline/convert_to_bids.py` | Planned BIDS task naming |
| `raw_original/**/**_MATLAB/` | Paradigm timing & operator comments |
| `raw_original/**/**_MATLAB/README.pdf` | Operator instructions (FOV/Grating/Movie) |
