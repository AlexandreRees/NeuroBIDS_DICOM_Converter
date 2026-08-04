# Methods and Technical Validation (QC)

Manuscript-ready text for the quality-control parts of Methods and Technical Validation.  
**Methods** = procedures only. **Technical Validation** = outcomes only.  
File layout and inventory: Data Records. Paradigm design: Methods (acquisition / paradigms).

---

# METHODS

This subsection documents quality-control and conversion procedures applied when preparing the released BIDS MRI resource. Outcome tallies, coverage percentages, and pass/fail counts are reported in Technical Validation.

## Conversion/BIDS validation procedure

Source DICOM series were inventoried without modifying the original archive and assigned pseudonymous BIDS entities (`sub-<ID>`, `ses-01`/`ses-02`, modality folder, run index) from study mapping tables. De-identified working copies were converted to gzip-compressed NIfTI with JSON sidecars using dcm2niix (`v1.0.20230411`; arguments `-b y -ba y -z y`), organised to BIDS 1.9.0 and orchestrated by `neuro_pipeline` version 2.1.0.

After conversion, sidecars were scrubbed of residual personal and institutional identifiers; missing `TaskName` values were injected from filenames when needed; phase images were renamed to BIDS `part-phase`; and field-map `IntendedFor` targets were set where applicable. For Siemens XA30 Enhanced MR sessions in which dcm2niix did not export `SliceTiming`, values were recovered from DICOM frame timing (`FrameAcquisitionDateTime` / `InStackPositionNumber`) when available. Task event tables were generated from experimental records only under a unique protocol→BOLD matching rule (see Functional MRI paradigms).

Structural compliance of the converted tree was checked with bids-validator version 1.15.0. Remediation preceding the validation snapshot included field-map metadata repairs, filename/entity fixes, XA30 `SliceTiming` recovery, and inclusion of verified event tables. Validator warnings were reviewed and disclosed rather than suppressed.

## Anatomical QC procedure

Quantitative image-quality metrics (IQMs) for T1-weighted volumes were computed with MRIQC (Esteban et al., 2017). Processing jobs targeted modality `T1w` (container reference `nipreps/mriqc:24.0.2`; runtime version recorded in derivative metadata). Participant-level HTML reports and JSON IQMs were written under `derivatives/mriqc/`. MRIQC outputs were intended as quantitative summaries to support inspection, not as automatic exclusion labels. Anatomical IQMs were interpreted with protocol awareness (standard MPRAGE versus white-matter-nulled MPRAGE).

As a complementary structural screen, all BIDS files matching `*_T1w.nii.gz` were evaluated with the published Pizarro et al. (2023) classifier using the production ONNX model `model.FINAL.onnx` (model label `Pizarro2023-FINAL`) via ONNX Runtime. Preprocessing followed the authors’ production utilities. For each volume, Monte Carlo dropout inference used 10 stochastic forward passes with fixed seed 1010. Retained continuous scores were artifact probability, majority confidence, and vote uncertainty. These scores were used solely to prioritise visual inspection; no image or participant was excluded solely on the basis of the model. Primary quantitative structural IQMs remained those from MRIQC.

## Functional QC procedure

Magnitude BOLD image-quality metrics were computed with the same MRIQC workflow as anatomical QC (modality `bold`; outputs under `derivatives/mriqc/`). Metrics such as framewise displacement and temporal SNR were retained to characterise motion and temporal stability and to prioritise visual review. Exploratory within-cohort outlier labels, when provided, support transparent reuse and were not applied as automatic exclusions.

Released `task-fmri` event tables were checked automatically for required columns (`onset`, `duration`, `trial_type`), non-negative timing, chronological order, non-overlapping blocks (edge-touching allowed), and documented condition labels. Movie event tables were checked for schema consistency with `task-movie_events.json`. Stimulus dictionaries under `code/` were cross-checked against event `trial_type` vocabularies. Event and dictionary checks document modelling provenance; they do not alter raw BOLD volumes.

## Diffusion QC procedure

Diffusion series were assessed in a read-only QC workflow that did not modify the distributed BIDS tree. Checks included presence of NIfTI, JSON, `.bval`, and `.bvec` companions; consistency of volume counts with gradient-table lengths; inventory of *b*-value schemes; presence of opposing phase-encode spin-echo field-map pairs when expected; and MRtrix3 `dwigradcheck` ranking of gradient-orientation hypotheses. Suggested orientation transforms from `dwigradcheck` were recorded for documentation only and were not applied to released files. No automatic exclusions were based on diffusion QC scores.

## Physiological QC procedure

Siemens PhysioLog DICOM were converted to BIDS physiology files (`*_recording-<channel>_physio.tsv.gz` with matching `*_physio.json`) only when release gates were met: usable sampling metadata, a derivable start time relative to the linked BOLD series, and unique BOLD association. Channels written under this policy include `pulse`, `respiratory`, `trigger`, and rarely `ecg`. Sidecars were restricted to an allowlisted metadata set (`SamplingFrequency`, `SampleTime_ms`, `SiemensChannel`, `StartTime`, `StartTimeMethod`, `StartTimeConfidence`, and related non-identifying conversion fields). Failed-gate PhysioLogs and session-wide peripheral PMU logs without unique run linkage were not written into the BIDS tree. Post-write checks verified sidecar fields required for reuse interpretation and absence of forbidden identifier keys.

## Privacy QC procedure

DICOM de-identification was applied to mapped working copies before conversion; original scanner exports remained an unmodified archive. Header processing followed a custom attribute-confidentiality policy oriented toward the DICOM PS3.15 Basic Application Level Confidentiality Profile (curated tag actions; not claimed as certified full-profile compliance). Direct identifiers were replaced with study codes; institutional, physician, accession, device-serial, and related free-text identifier fields were cleared; private tags were removed; UIDs were deterministically remapped; and calendar dates were shifted by a participant-specific offset while preserving longitudinal intervals. Acquisition parameters required for analysis (including series descriptions) and patient sex were retained by default. Image pixel values were not altered during DICOM header de-identification.

After conversion, BIDS JSON sidecars were re-scrubbed and audited for residual forbidden personal or institutional fields. The public `participants.tsv` was limited to `participant_id`, `cohort`, and `sex`. Source DICOM was not redistributed with the public package.

Anatomical facial features for public structural sharing were removed after conversion with pydeface (`2.0.0+computecanada`) and FSL (`6.0.7.20`), writing outputs under `derivatives/defacing/` without overwriting raw BIDS anatomicals. Defacing validation checked coverage of expected T1w pairs, spatial geometry preservation, and scrubbing of derivative JSON.

---

# TECHNICAL VALIDATION

This section reports outcomes of the procedures above. Automated metrics characterise acquisitions and prioritise visual inspection; they were not used as automatic exclusion criteria. No biological group comparisons are reported here.

## BIDS compliance results

Validation with bids-validator 1.15.0 against BIDS 1.9.0 reported **0 errors** after remediation of field-map metadata (`IntendedFor`, phase-encoding / readout fields), filename and entity issues, XA30 `SliceTiming` recovery, and inclusion of verified task-event tables.

Disclosed **warnings** (not errors) include: incomplete longitudinal session coverage where follow-up visits were not completed; `EVENTS_TSV_MISSING` for resting-state, control, and grating runs without a unique protocol→BOLD mapping; cross-subject `INCONSISTENT_PARAMETERS` where protocol variants exist; and a placeholder Authors field in `dataset_description.json` to be completed before deposition. NIfTI readability and JSON syntactic validity were confirmed within BIDS validation and modality inventories.

## Acquisition completeness

The live BIDS tree contains **84** participant folders and **135** subject–session folders (`ses-01`: 83; `ses-02`: 52). Longitudinal follow-up is incomplete by recruitment and retention: **51** participants have both sessions, **32** have `ses-01` only, and **1** has `ses-02` only. Empty placeholder session folders were not created.

Within completed sessions, expected anatomical, functional, diffusion, and field-map series are generally present (inventory in Data Records). Known incompleteness affecting reuse includes: magnitude `task-fmri` runs without `*_events.tsv` when protocol→BOLD correspondence was ambiguous; resting-state and control runs without events by design or documentation limits; physiology for a subset of BOLD runs only (see Physiological coverage); and acquisitions that could not be scored by MRIQC because they were truncated or out of protocol (accepted pathological gaps: short `task-fmri` runs and atypical T1-weighted series). These cases remain in the raw tree for provenance.

Opposite phase-encoding spin-echo field-map pairs were present for all sessions assessed in the diffusion QC inventory. Diffusion series in that inventory each had accompanying NIfTI, `.bval`, `.bvec`, and JSON files; volume / gradient-table length mismatches were flagged in QC reports and left unmodified in the distributed tree. MRtrix3 `dwigradcheck` on the audited DWI set yielded **0 FAIL** (PASS and REVIEW tallies recorded; REVIEW transforms not applied).

## Anatomical QC results

At the audited MRIQC packaging snapshot, IQMs were available for **1848 of 1852** expected T1w and magnitude BOLD scans (**99.8%**), covering all **84** participants; session-level completeness (all expected T1w and magnitude BOLD IQMs present) was **120 of 124** sessions (**96.8%**). Remaining gaps correspond to accepted pathological or out-of-protocol acquisitions rather than unqueued healthy series. A transient AFNI `3dFWHMx` autocorrelation-function failure initially blocked IQM generation for a subset of runs and was addressed by forcing classic FWHM estimation in the fault-tolerant MRIQC entrypoint. Anatomical IQMs should be interpreted with protocol stratification (standard MPRAGE versus white-matter-nulled MPRAGE).

The regenerated Pizarro screening package scored **385 of 385** `*_T1w.nii.gz` volumes with no inference errors. Continuous artifact-probability and uncertainty scores were used only to prioritise visual inspection; no image or participant was excluded solely on this model. Primary quantitative structural IQMs remain those from MRIQC.

## Functional QC results

Magnitude BOLD IQMs are included in the MRIQC coverage figures above. Cohort medians for available BOLD outputs included mean framewise displacement of approximately **0.176 mm** and temporal SNR of approximately **20.6–20.9**. Exploratory outlier labels, when present, flag review priority only.

Released `task-fmri` event tables (**514**) passed automated schema and timing checks without FAIL in the audited set. Design-level `task-movie` events accompany all **536** magnitude movie BOLD runs; timing uses protocol synchronisation (`onset = 0`) rather than measured TTL onsets, as stated in Data Records. Resting-state and control runs intentionally lack events.

## Conversion integrity

Post-conversion checks confirmed pairing of imaging volumes with required sidecars (and `.bval`/`.bvec` for diffusion), BIDS entity naming, and field-map linkage fields after documented repairs. XA30 `SliceTiming` recovery restored timing arrays where DICOM frame metadata permitted. Physiology conversion wrote BIDS products only for gate-passing PhysioLogs (**0** conversion FAIL and **0** PHI_FAIL in the audited conversion run). Defacing derivatives record provenance in `derivatives/defacing/dataset_description.json`. No gradient-orientation corrections suggested by `dwigradcheck` were applied to distributed DWI files.

## Physiological coverage

The current tree contains **3620** physiology TSV.GZ files spanning **77** participants (channels include pulse, respiratory, trigger, and rarely ECG). Approximately **78%** of magnitude BOLD runs have at least one physiology file. Absence of physiology for a given run indicates failed conversion gates or no archived PhysioLog for that acquisition, not an invalid BOLD series. Sidecars commonly report `StartTimeConfidence` of `MEDIUM`; users should read `SamplingFrequency`, `StartTime`, and confidence fields before assuming high-precision synchronisation. Session-wide peripheral PMU logs without unique run linkage, and eye-tracking time series, are not included in this BIDS package.

## Privacy validation results

A privacy-oriented audit of release BIDS JSON sidecars reported **0** invalid JSON and **0** hits for forbidden identifier keys under the audited policy (including patient name/ID/age/birth date, institutional and physician fields, device serial / station names, accession numbers, and calendar date fields in sidecars). Free-text technical labels such as `SeriesDescription` and `ProtocolName` are retained for reuse and were manually reviewed as protocol or operator redo labels rather than personal identifiers. Scientific acquisition fields required for analysis (e.g. TR, TE, flip angle) remained present after scrubbing. The participant table contains only `participant_id`, `cohort`, and `sex`. Source DICOM is not redistributed.

Audited T1w defacing coverage was complete for the packaging inventory (matched original–defaced pairs; **0** geometry mismatches). Derivative JSON under `derivatives/defacing/` was confirmed free of residual institutional identifier fields after scrub. Defacing does not overwrite raw BIDS anatomicals.
