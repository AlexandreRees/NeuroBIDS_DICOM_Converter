# Methods (Data Descriptor draft)

**Status:** revised draft for *Scientific Data*  
**Date:** 23 July 2026  
**Provenance:** prior Methods/Data Record LaTeX draft (22 July 2026), BIDS metadata, protocol/acquisition tables, de-identification and QC documentation  
**Policy:** document practical procedures used to create the data; no biological analyses; no validation tallies in this section (see Technical Validation)

---

## Manuscript text (for submission)

### Methods

This section documents the procedures used to create the released imaging resource: experimental design, MRI acquisition, de-identification and BIDS conversion, and quality-control processing applied to the data. General outcome summaries and validation tallies are reported in Technical Validation rather than here.

#### Experimental design

Data were collected in a prospective observational MRI study of adults with optic nerve injury (traumatic optic neuropathy, optic neuritis, or glaucoma) and participants with clinically normal vision (McGill University Health Centre Research Ethics Board Protocol 2020-5879). Imaging was planned at a baseline visit (`ses-01`) and at an approximately six-month follow-up (`ses-02`). The acquisition battery was designed to support characterisation of resting-state and visually driven BOLD activity, structural anatomy, and diffusion-weighted measures of white-matter microstructure; the present Data Descriptor documents the multimodal MRI resource and its technical preparation and does not report biological group comparisons.

#### Participants

The released dataset includes 84 participants in four cohorts recorded in BIDS `participants.tsv`: Control (*n* = 56), optic neuritis (cohort label `DataON`; *n* = 7), traumatic optic neuropathy (cohort label `DataTON`; *n* = 2), and Glaucoma (*n* = 19).

The sample comprised 46 female and 38 male participants. Sex was taken from DICOM `PatientSex` and propagated through inventory and mapping into `participants.tsv`. Individual ages are **not** distributed in the public release: the BIDS root `participants.tsv` contains only `participant_id`, `cohort`, and `sex`. Age-related DICOM fields were cleared from released sidecars during de-identification, and no aggregate age statistic is reported here in order to reduce re-identification risk in this relatively small multimodal clinical cohort.

In the current BIDS tree, 40/84 participants have both sessions, 43/84 have `ses-01` only, and 1/84 has `ses-02` only. Absent sessions reflect incomplete follow-up rather than omitted placeholder folders.

#### Ethics statement

The study was approved by the McGill University Health Centre (MUHC) Research Ethics Board (Protocol 2020-5879), McGill University. Written informed consent was obtained from participants.

#### MRI acquisition

MRI data were acquired on a Siemens Prisma system operating at 3 T using a 64-channel head/neck receive coil (BIDS sidecars: `ReceiveCoilName = HeadNeck_64`; `ReceiveCoilActiveElements = HC1-7;NC1,2`). Scanner software versions present in the converted dataset include `syngo MR E11` and `syngo MR XA30`. Institutional site identifiers are not retained in released sidecars because corresponding DICOM fields were cleared during de-identification.

Representative sequence parameters below are taken from the curated protocol acquisition tables used for conversion; run-specific values for each released file are recorded in the accompanying BIDS JSON sidecars (and, for diffusion, `.bval`/`.bvec` files).

**Anatomical.** T1-weighted MPRAGE (`T1w_MPR`): TR 2500 ms, TE 2.22 ms, flip angle 8°, 0.8 mm isotropic. White-matter-nulled MPRAGE (`WMn_MPRAGE_sagittal`): TR 4000 ms, TE 3.82 ms, flip angle 7°, 1 mm isotropic. 3D FLAIR (`Sag Flair 3D-0.8`): TR 6000 ms, TE 357 ms, flip angle 120°, 0.8 mm isotropic. B1-related mapping series (`tfl_b1map_1mmiso`) were also acquired in the source protocol.

**Functional MRI.** BOLD EPI acquisitions shared TR 937 ms, TE 37 ms, flip angle 52°, 2 mm isotropic resolution (sequence family `epfid2d1_104`). Sampled BOLD sidecars report multiband acceleration factor 8. Matching single-band reference (`SBRef`) series were acquired with the BOLD runs. Functional paradigm design and BIDS task labels are described below.

**Field maps.** Spin-echo EPI field maps were acquired in opposing phase-encode directions (AP/PA): TR 9710 ms, TE 66 ms, flip angle 90°, 2 mm isotropic.

**Diffusion.** Diffusion-weighted imaging in the source protocol included a multi-direction series (`gsld_76dir_b2000_1mmiso_AP`; representative TR 3500 ms, TE 75 ms), reverse-phase-encode *b* = 0 volumes, and RESOLVE trace acquisitions (`resolve_3scan_trace_*`). Exact *b*-value tables and gradient directions for each converted run are provided as BIDS `.bval`/`.bvec` files.

**Physiology.** Scanner physiological logging series (`*_PhysioLog`) were acquired for ECG, respiration, and pulse channels. These recordings are not distributed as BIDS physiology files in the present release because verified sampling-frequency, start-time, and run-mapping metadata required for BIDS physiology sidecars were not available at conversion.

#### Functional MRI paradigms

The dataset includes four complementary blood-oxygen-level-dependent (BOLD) functional MRI paradigms: (i) resting-state fixation (`task-rest`); (ii) monocular naturalistic movie stimulation (`task-movie`); (iii) block-design visual stimulation with grating and checkerboard stimuli (`task-fmri`); and (iv) short control functional acquisitions (`task-control`). These paradigms were designed to characterise spontaneous functional organisation and stimulus-evoked responses within the visual system under monocular viewing conditions. Sequence parameters cotmon to the BOLD series are given above; run counts, volumes, and approximate durations are summarised in **Table X** (`Table1_Functional_paradigm_summary`; see also overview **Figure Xa** / `Figure2_functional_paradigm_overview`). The subsections below summarise the acquisition paradigms and released stimulus-related metadata.

##### Resting-state fixation paradigm

Resting-state BOLD data were acquired under the BIDS task label `task-rest`. Participants viewed a uniform grey background with a white fixation cross. Stimulation was monocular: the non-stimulated eye remained occluded (dark), and no stimulus blocks were presented. Each resting-state run comprised 320 BOLD volumes (approximately 5 minutes at the shared functional TR). This paradigm provides resting-state BOLD measurements under controlled visual fixation conditions.

##### Naturalistic movie stimulation paradigm

Naturalistic movie stimulation was acquired under the BIDS task label `task-movie` as four functional runs corresponding to movie segments Movie1A, Movie2A, Movie1B, and Movie2B (ProtocolName `Movie1`–`Movie4`). Monocular eye assignment by protocol was: Movie1/Movie1A left; Movie2/Movie2A right; Movie3/Movie1B right; Movie4/Movie2B left (**Table Y** / `Table2_Movie_run_eye_assignment`). A fixation cross was superimposed during movie presentation. Each movie run comprised approximately 210 BOLD volumes (approximately 3.3 minutes). Design-level stimulus timing files are included for all magnitude movie runs (`onset = 0` protocol sync; MP4 duration); videos are not redistributed (copyright).

##### Block-design visual stimulation paradigm

Visually driven task BOLD data were acquired under the BIDS task label `task-fmri` using a block-design grating and checkerboard stimulation paradigm synchronised to MRI scanner triggers (**Figure Xb** / `Figure1_task_fmri_block_design`). After an initial baseline of 10 TRs, the experimental design comprised 12 cycles of 8 TR stimulus presentation alternating with 10 TR baseline periods, for a total of 226 BOLD volumes per run. Twelve stimulus conditions (`stim-01` to `stim-12`) encompassed magnocellular and parvocellular variants and grating and checkerboard conditions. During presentation, a fixation marker consisting of a blue/red oval with a central cross was displayed. Stimulus order was randomised across subjects.

Event timing files (`*_events.tsv`) were generated from the original experimental records by combining scanner trigger recordings (MATLAB `scan_info` / `triggerTimes`), stimulus-order metadata (`Stim_order_selected`), and the protocol block design (`presentStimParams.m`). An events file was created only when a unique correspondence between protocol records and one BIDS BOLD acquisition could be established (`ProtocolName`/`SeriesDescription` match to `fMRI{N}`). When the session `runs_random` workspace belonged to a different fMRI index, the canonical protocol block design was applied to the same measured triggers; no default TR was substituted and no synthetic onsets were introduced. Runs without an unambiguous mapping intentionally remain without `events.tsv`. Automatic consistency checks of the released event tables are reported in Technical Validation. A machine-readable mapping between `stim-01`…`stim-12` and stimulus parameters is provided in `code/task-fmri_condition_dictionary.tsv`, with column definitions in `task-fmri_events.json`.

##### Control functional paradigm

Short control functional runs were acquired under the BIDS task label `task-control`. Each control run comprised 20 BOLD volumes (approximately 19 seconds). The exact stimulus content of these control runs could not be fully reconstructed from the available documentation.

**Publication assets (this section).** Source files under `reports/functional_mri_paradigm_figures/`:

| Asset | File stem | Role |
| --- | --- | --- |
| Table X | `Table1_Functional_paradigm_summary` | Paradigm summary (runs, volumes, duration) |
| Table Y | `Table2_Movie_run_eye_assignment` | Movie segment × stimulated eye |
| Figure Xa | `Figure2_functional_paradigm_overview` | Four-panel paradigm overview |
| Figure Xb | `Figure1_task_fmri_block_design` | `task-fmri` block-design timeline |

Formats: tables as `.png`/`.pdf`/`.tex`/`.docx`/`.md`; figures as `.png`/`.pdf`/`.svg`. Captions in `captions.md`. Rebuild with `build_functional_paradigm_assets.py`.

#### Computational processing

##### Inventory and BIDS mapping

Source DICOM series were inventoried without modifying the original archive. Series were catalogued by DICOM `SeriesInstanceUID` and assigned pseudonymous BIDS entities (`sub-XXX`, `ses-01`/`ses-02`, modality folder, and run index) using study mapping tables. Modality folders (`anat`, `func`, `dwi`, `fmap`) and filename entities (including functional `task-` labels and field-map `dir-` labels) were assigned from DICOM modality and series-description heuristics. Mapping outputs used for conversion included `metadata/participant_mapping.csv` and `metadata/session_mapping.csv`.

##### De-identification

DICOM de-identification was applied to copies of mapped acquisitions before conversion; original scanner exports were retained as an unmodified archive and were not overwritten. Header processing followed a custom attribute-confidentiality policy oriented toward the DICOM PS3.15 Basic Application Level Confidentiality Profile; the implemented tag actions are a curated policy subset and are not claimed as certified full-profile compliance.

Direct identifiers (including patient name and patient ID) were replaced with study-specific codes. Institutional, physician, accession, device-serial, and related free-text identifier fields were cleared according to a fixed tag policy; private DICOM tags were removed. Study, series, SOP, and related unique identifiers were deterministically remapped (to the `2.25.*` root) while preserving SOP Class UIDs required for DICOM validity. Calendar dates were shifted by a participant-specific day offset, preserving relative intervals across longitudinal visits; acquisition clock times were left unchanged. Patient sex and acquisition parameters required for analysis and labelling (including series descriptions) were retained by default. Image pixel values were not altered during DICOM header de-identification.

Anatomical facial defacing was performed as a separate stage after conversion using pydeface version `2.0.0+computecanada` with FSL version `6.0.7.20`, writing outputs under `derivatives/defacing/`.

##### DICOM-to-BIDS conversion

De-identified series were converted to gzip-compressed NIfTI with JSON sidecars using dcm2niix version `v1.0.20230411` (version string recorded in BIDS sidecars), with arguments `-b y -ba y -z y` (Li et al., 2016). Organisation followed BIDS specification version 1.9.0 (Gorgolewski et al., 2016), orchestrated by the study conversion workflow `neuro_pipeline` version 2.1.0. Conversion operated on per-acquisition working copies so that the original DICOM archive remained untouched.

After dcm2niix, JSON sidecars were scrubbed of residual personal and institutional identifiers; `TaskName` was injected from filenames when missing; phase images were renamed to BIDS `part-phase`; and field-map `IntendedFor` fields were set to session functional targets where applicable. For Siemens XA30 Enhanced MR sessions in which dcm2niix did not export `SliceTiming`, values were recovered from DICOM `FrameAcquisitionDateTime` and `InStackPositionNumber` when available. Task-fMRI `*_events.tsv` files were generated from original experimental logs (scanner triggers, MATLAB stimulus-order files, and protocol metadata) only when sufficient metadata allowed an unambiguous protocol→BIDS correspondence; movie and control runs without such timing sources remain without event tables (see Functional MRI paradigms and Technical Validation).

#### Quality-control procedures

Quality-control steps below describe processing applied to the data. Coverage statistics, metric distributions, and pass/fail tallies are reported in Technical Validation.

**BIDS structural validation.** The converted tree was checked with bids-validator version 1.15.0 prior to descriptor preparation. Remediation steps preceding the validation snapshot included recovery of missing XA30 `SliceTiming` values and inclusion of `task-fmri` event files generated from original experimental records under a unique protocol→BOLD matching rule.

**MRIQC.** Automated image-quality metrics (IQMs) for T1-weighted and BOLD data were computed with MRIQC (Esteban et al., 2017). The runtime version recorded in derivative metadata is `24.1.0.dev0+gd5b13cb5.d20240826`; processing jobs targeted modalities `T1w` and `bold` (container reference used in job scripts: `nipreps/mriqc:24.0.2`). MRIQC outputs are stored under `derivatives/mriqc/` and are intended as quantitative QC summaries to support inspection, not as automatic exclusion labels.

**Complementary T1-weighted artifact screening.** An additional automated screening step used the published Pizarro et al. (2023) classifier. Inference used the production ONNX model file `model.FINAL.onnx` (model label `Pizarro2023-FINAL`) from the authors' public repository [https://github.com/AS-Lab/Pizarro-et-al-2023-DL-detects-MRI-artifacts](https://github.com/AS-Lab/Pizarro-et-al-2023-DL-detects-MRI-artifacts), executed with ONNX Runtime version 1.23.2 on BIDS files matching `*_T1w.nii.gz` only. For each volume, Monte Carlo dropout inference comprised 10 stochastic forward passes with fixed seed 1010. Retained continuous scores were model-estimated artifact probability, majority confidence, and vote uncertainty; these scores were used solely to prioritise targeted visual inspection. No image or participant was excluded based solely on the model output. Primary quantitative structural IQMs remained those from MRIQC.

#### Software and tools

Software versions used to create and screen the released data are summarised below for reproducibility. Peer-reviewed citations for standards and tools are listed in the companion References draft; tools without a verified journal citation are identified by version and URL.

- BIDS specification 1.9.0 ([https://bids.neuroimaging.io/](https://bids.neuroimaging.io/); Gorgolewski et al., 2016)
- `neuro_pipeline` 2.1.0 (study DICOM inventory, mapping, de-identification orchestration, and BIDS conversion workflow)
- dcm2niix `v1.0.20230411` ([https://github.com/rordenlab/dcm2niix](https://github.com/rordenlab/dcm2niix); Li et al., 2016)
- bids-validator 1.15.0
- MRIQC `24.1.0.dev0+gd5b13cb5.d20240826` (Esteban et al., 2017; job scripts also reference container tag `nipreps/mriqc:24.0.2`)
- Pizarro production model `model.FINAL.onnx` (`Pizarro2023-FINAL`; [https://github.com/AS-Lab/Pizarro-et-al-2023-DL-detects-MRI-artifacts](https://github.com/AS-Lab/Pizarro-et-al-2023-DL-detects-MRI-artifacts); Pizarro et al., 2023), ONNX Runtime 1.23.2
- pydeface `2.0.0+computecanada` with FSL `6.0.7.20` (Smith et al., 2004)

---

## Author notes (not for submission)

1. **Clinical criteria.** Insert inclusion/exclusion criteria from Protocol 2020-5879 before submission (not found in repo materials).
2. **Consent for sharing.** Confirm exact consent language covers open deposition before finalising repository/DOI wording.
3. **MRIQC coverage.** Incomplete as of latest array audit — put coverage % and IQM distributions in Technical Validation only, once finished.
4. **Defacing coverage.** Confirm final `derivatives/defacing/` inventory before deposition; do not leave incomplete-coverage caveats in manuscript prose.
5. **Physiology.** Not currently BIDS-distributed; keep Methods wording factual about what is released.
6. **Data citation.** When OpenNeuro (or other) accession/DOI is assigned, cite it via Scientific Data data-citation format in Data Records (not as a vague homepage link).
7. **Revision vs prior draft.** Removed validation outcomes from Methods (bids-validator error counts, Pizarro 356/83 tallies, MRIQC incompleteness narrative); shortened ops/architecture wording; added Experimental design and Software and tools; embedded specific URLs/versions for reusable inputs.
8. **Functional paradigm assets.** Replace Table X / Table Y / Figure Xa / Figure Xb placeholders with final manuscript numbers; assets live in `reports/functional_mri_paradigm_figures/` (PNG copies also under `figures/`).

## Consistency with other drafts

| Fact | Align with |
| --- | --- |
| 84 participants; cohort *n*; age/sex; session coverage 40/43/1 | Background & Summary draft |
| Prisma 3 T; BIDS 1.9.0; `neuro_pipeline` 2.1.0; dcm2niix `v1.0.20230411` | prior Methods draft / sidecars |
| PS3.15-oriented policy, not full-profile certification | de-identification manuscript notes |
| Pizarro model file + GitHub URL | References draft |
| No biological results | Scientific Data Data Descriptor format |
