# 4. Technical Validation

This section reports technical checks applied to the released BIDS MRI resource. Automated metrics were used to characterise acquisitions and to prioritise visual inspection; they were not used as automatic exclusion criteria. Acquisition design and stimulus content are described in Methods; file layout and inventory are described in Data Records. No biological group comparisons are reported here.

## 4.1 BIDS compliance

The dataset was validated with bids-validator version 1.15.0 against BIDS 1.9.0. After remediation of field-map metadata (including `IntendedFor` and phase-encoding / readout fields), filename and entity issues, recovery of missing `SliceTiming` values for Siemens XA30 BOLD sidecars, and inclusion of verified task-event tables, a Scientific Data preparation snapshot reported **0 errors**.

Remaining **warnings** do not invalidate the tree under the validator’s error criteria and are disclosed for reuse. They include incomplete longitudinal session coverage where follow-up visits were not completed; `EVENTS_TSV_MISSING` for resting-state, control, and grating runs without a unique protocol-to-BOLD mapping; cross-subject `INCONSISTENT_PARAMETERS` where protocol variants exist; and a placeholder Authors field in `dataset_description.json` to be completed before deposition. NIfTI readability and JSON syntactic validity were confirmed as part of BIDS validation and modality inventories.

## 4.2 Acquisition completeness

Completeness was assessed relative to planned sessions and expected modality coverage rather than by fabricating missing visits. The live BIDS tree contains **84** participant folders and **135** subject–session folders (`ses-01`: 83; `ses-02`: 52). Follow-up is incomplete by recruitment and retention: **51** participants have both sessions, **32** have `ses-01` only, and **1** has `ses-02` only. Empty placeholder session folders were not created.

Within completed sessions, expected anatomical, functional, diffusion, and field-map series are generally present as summarised in Data Records. Known incompleteness that affects reuse includes: magnitude `task-fmri` runs without `*_events.tsv` when protocol-to-BOLD correspondence was ambiguous; resting-state and control runs without events by design or documentation limits; physiology files for a subset of BOLD runs only (Section 4.7); and acquisitions that could not be scored by MRIQC because they were truncated or out of protocol (short `task-fmri` runs and atypical T1-weighted series). These cases remain in the raw tree for provenance and are documented rather than removed.

## 4.3 Anatomical MRI quality assessment

### MRIQC

Anatomical image-quality metrics (IQMs) for T1-weighted volumes were computed with MRIQC (processing jobs targeted container tag `nipreps/mriqc:24.0.2`; runtime version recorded in derivative metadata). Participant-level HTML reports and JSON IQMs are released under `derivatives/mriqc/`. At the audited packaging snapshot, IQMs were available for **1848 of 1852** expected T1w and magnitude BOLD scans (**99.8%**), covering all **84** participants; session-level completeness (all expected T1w and magnitude BOLD IQMs present) was **120 of 124** sessions (**96.8%**). Remaining gaps correspond to accepted pathological or out-of-protocol acquisitions. A transient AFNI `3dFWHMx` autocorrelation-function failure initially blocked IQM generation for a subset of runs and was addressed by forcing classic FWHM estimation in the fault-tolerant MRIQC entrypoint. Anatomical IQMs should be interpreted with protocol stratification (standard MPRAGE versus white-matter-nulled MPRAGE). Exploratory within-cohort outlier labels, when provided, support transparent reuse and are not automatic exclusions.

### Pizarro

As a complementary structural screen, all BIDS `*_T1w.nii.gz` volumes were evaluated with the published Pizarro et al. (2023) classifier (production ONNX model `model.FINAL.onnx`; Monte Carlo dropout with 10 passes and seed 1010). The regenerated package scored **385 of 385** T1w images with no inference errors. Continuous artifact-probability and uncertainty scores were used only to prioritise visual inspection; no image or participant was excluded solely on the basis of this model. Primary quantitative structural IQMs remain those from MRIQC.

### Defacing

Anatomical facial features intended for public structural sharing were removed with pydeface under `derivatives/defacing/` without overwriting raw BIDS anatomicals. Audited T1w defacing coverage was complete for the packaging inventory (matched original–defaced pairs), with preserved geometry between pairs (**0** geometry mismatches) and scrubbed derivative JSON free of residual institutional identifier fields. Provenance is recorded in `derivatives/defacing/dataset_description.json`.

## 4.4 Functional MRI quality assessment

### MRIQC BOLD metrics

Magnitude BOLD IQMs were computed with the same MRIQC workflow and are included in the coverage figures in Section 4.3. Cohort medians for available BOLD outputs included mean framewise displacement of approximately **0.176 mm** and temporal SNR of approximately **20.6–20.9**. Exploratory outlier labels, when present, flag review priority only and were not used as automatic exclusions.

### Events validation

Released `task-fmri` event tables (**514**) were validated automatically for required columns (`onset`, `duration`, `trial_type`), non-negative timing, chronological order, non-overlapping blocks (edge-touching allowed), and documented condition labels; audited grating events passed these checks without FAIL. Stimulus condition dictionaries under `code/` were cross-checked against event `trial_type` vocabularies. Resting-state and control runs intentionally lack events (by design or documentation limits). Magnitude `task-fmri` runs without a unique protocol-to-BOLD mapping intentionally remain without `*_events.tsv`.

### Movie timing

Design-level `task-movie` event tables accompany all **536** magnitude movie BOLD runs and were checked for schema consistency with `task-movie_events.json`. Timing uses protocol synchronisation (`onset = 0`; duration equal to measured MP4 length or capped to scan length for truncated runs) rather than millisecond TTL-locked onsets. These events support run-level continuous-movie models; users should not treat them as hardware-trigger-locked timing. Movie video files are not redistributed because of copyright restrictions.

## 4.5 Diffusion MRI quality assessment

### bval/bvec

A total of **361** DWI acquisitions from **82** participants (**120** sessions) were inventoried in a read-only QC workflow. NIfTI, `.bval`, `.bvec`, and JSON sidecars were present for **361/361** scans with matching volume and gradient-table lengths (**0** missing companions). No modifications were applied to distributed gradient tables on the basis of QC findings.

### dwigradcheck

MRtrix3 `dwigradcheck` yielded **250 PASS**, **111 REVIEW**, and **0 FAIL**. REVIEW indicates a non-identity top-ranked gradient-orientation hypothesis; suggested transforms were recorded for documentation and were **not** applied to the distributed dataset. No automatic exclusions were based on diffusion QC.

### Fieldmaps

Opposite phase-encoding spin-echo field-map pairs (`dir-AP` / `dir-PA`) were present for all **120/120** sessions assessed in the diffusion QC inventory. Distortion-correction workflows can use these session field maps; reverse-phase-encode *b* = 0 volumes are not separately distributed under `dwi/` in this release.

## 4.6 Conversion integrity

### dcm2niix

DICOM-to-BIDS conversion used dcm2niix (`v1.0.20230411`) with gzip NIfTI output and JSON sidecars (`-b y -ba y -z y`), orchestrated by `neuro_pipeline` version 2.1.0 on de-identified working copies so that the original archive remained unmodified. Conversion software and version strings are recorded in BIDS sidecars.

### Audit

Post-conversion integrity checks confirmed pairing of imaging volumes with required sidecars (and `.bval`/`.bvec` for diffusion), BIDS entity naming, field-map linkage fields, and JSON syntactic validity. Physiology conversion wrote BIDS products only for gate-passing PhysioLogs (**0** conversion FAIL and **0** PHI_FAIL in the audited conversion run).

### Metadata repair

Documented repairs after dcm2niix included scrubbing residual personal and institutional fields from JSON sidecars; injecting missing `TaskName` from filenames; renaming phase images to BIDS `part-phase`; setting field-map `IntendedFor` targets where applicable; and recovering `SliceTiming` for Siemens XA30 Enhanced MR sessions from DICOM frame timing when dcm2niix did not export the array. No gradient-orientation corrections suggested by `dwigradcheck` were written back to released `.bvec` files.

## 4.7 Physiological data validation

### Coverage

The current tree contains **3620** physiology TSV.GZ files spanning **77** participants (channels include `pulse`, `respiratory`, `trigger`, and rarely `ecg`). Approximately **78%** of magnitude BOLD runs have at least one physiology file. Absence of physiology for a given run indicates failed conversion gates or no archived PhysioLog for that acquisition, not an invalid BOLD series. Session-wide peripheral PMU logs without unique run linkage, and eye-tracking time series, are not included in this BIDS package.

### StartTime

Physiology JSON sidecars report `StartTime` (seconds relative to the start of the linked BOLD series), `StartTimeMethod`, and `StartTimeConfidence`. Confidence is commonly `MEDIUM`. Users should consult these fields before assuming high-precision synchronisation between physiology and BOLD.

### Sampling

Sidecars also report `SamplingFrequency`, `SampleTime_ms`, and `SiemensChannel`. Released physiology files were written only when sampling metadata and start-time derivation passed release gates; post-write checks confirmed allowlisted metadata and absence of forbidden identifier keys.

## 4.8 Privacy and anonymization validation

A privacy-oriented audit of release BIDS JSON sidecars reported **0** invalid JSON and **0** hits for forbidden identifier keys under the audited policy (including patient name, ID, age, and birth date; institutional and physician fields; device serial and station names; accession numbers; and calendar date fields in sidecars). Free-text technical labels such as `SeriesDescription` and `ProtocolName` are retained for reuse and were reviewed as protocol or operator redo labels rather than personal identifiers. Scientific acquisition fields required for analysis (for example TR, TE, and flip angle) remained present after scrubbing.

The public `participants.tsv` contains only `participant_id`, `cohort`, and `sex`. Source DICOM is not redistributed with the public BIDS package. De-identification followed a PS3.15-inspired custom tag policy and is not claimed as certified full-profile compliance. Anatomical defacing for public structural sharing is reported in Section 4.3; raw BIDS anatomicals are not overwritten by defaced derivatives.
