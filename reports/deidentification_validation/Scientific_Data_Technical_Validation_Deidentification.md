# De-identification and privacy protection

The dataset was processed through a DICOM PS3.15-oriented de-identification workflow implementing removal of direct identifiers, UID remapping, temporal shifting, and controlled handling of technical metadata required for MRI conversion. This section documents the privacy controls applied before Scientific Data release and the validation evidence supporting those controls. It does **not** claim certified conformance to the full DICOM PS3.15 Basic Application Level Confidentiality Profile (Annex E).

## Workflow overview

Source DICOM objects were converted to BIDS using the project `neuro_pipeline` stack. De-identification is implemented as a **custom Attribute Confidentiality workflow oriented to DICOM PS3.15**, with the following elements:

1. **Pseudonymisation.** PatientName and PatientID are replaced with mapped study identifiers (`sub-*` / canonical IDs) rather than retained as scanner-exported names.
2. **Direct identifier removal.** Administrative and identity-bearing DICOM attributes on a curated tag list are cleared (including accession, physician/operator names, institution/station/device-serial fields, and related comment fields) as implemented in `neuro_pipeline/mri_anonymization/`.
3. **UID remapping.** Study, Series, SOP, and Frame of Reference UIDs (and related UI references) are deterministically remapped to the `2.25.*` namespace to reduce linkage risk while preserving intra-subject consistency for conversion.
4. **Longitudinal date shifting.** Calendar dates (DA/DT) are shifted by a reproducible per-participant offset; acquisition clock times (TM) are retained. The shift table is retained privately under `metadata/` and is **not** part of the public package.
5. **Private-tag policy.** Private tags are removed except where the conversion path documents retention of Siemens CSA reconstruction blocks (group `0x0029`) required for accurate BIDS sidecar derivation (e.g., SliceTiming, phase-encode polarity, readout timing).
6. **BIDS sidecar metadata cleaning.** After conversion, JSON sidecars were audited and cleaned to remove residual administrative fields (notably `InstitutionalDepartmentName`) while preserving MRI acquisition parameters required for reuse (e.g., RepetitionTime, EchoTime, FlipAngle, MagneticFieldStrength, Manufacturer, PhaseEncodingDirection, TotalReadoutTime).
7. **Structural MRI defacing.** All T1-weighted volumes intended for sharing were defaced with **pydeface** via `neuro_pipeline.modules.defacing.run_defacing_session`. Defaced NIfTI and associated provenance live under `derivatives/defacing/`; the original BIDS tree is not overwritten.

Public distribution is intended as **BIDS (+ defaced anatomical derivatives)**. Source DICOM under `raw_original/` is **not** distributed.

### Validation of de-identification

Pre-publication validation was performed with read-only audits under `reports/deidentification_validation/` (scripts: `code/audit_dicom_deidentification.py`, `code/audit_bids_sidecar_privacy.py`, `code/audit_defacing_release.py`), reusing prior privacy and PS3.15-oriented documentation where live DICOM was no longer available on disk.

1. **DICOM tag audit.** Pipeline policy and prior audits document removal/pseudonymisation of direct identifiers, UID remapping, date shifting, and private-tag handling. At the time of the final packaging check, the working `raw_original/` tree contained no live DICOM instances; therefore residual-PHI claims for DICOM objects rely on prior READ-ONLY audits and code policy rather than a fresh exhaustive re-scan. No DICOM objects are included in the public release package.

2. **PHI residual audit.** Prior burned-in annotation / overlay header checks on series representatives found no affirmative `BurnedInAnnotation=YES` and no overlay/graphic annotation evidence in the inspected set (tag absence remains inconclusive for pixel-level text; visual spot-checks remain advised for institutional QA).

3. **BIDS metadata audit.** All **7958** BIDS JSON sidecars were scanned. No residual direct-identifier fields (`PatientName`, `PatientID`, `PatientBirthDate`, `PatientAge`, institution/device/operator identifiers, acquisition calendar dates) were detected. Free-text technical fields (`SeriesDescription`, `ProtocolName`, `SequenceName`, `PulseSequenceDetails`) were reviewed and classified as safe technical descriptors for this cohort. **No residual direct identifiers were detected in the validated BIDS release structure.**

4. **Defacing validation.** Coverage, geometry, and metadata checks were performed against `derivatives/defacing/` (see below).

### Structural MRI defacing

Facial features on structural T1-weighted MRI were removed with **pydeface** before public sharing of anatomical images. Validation strategy:

- **Coverage:** **356 / 356** BIDS T1w volumes have matched defaced counterparts with preserved subject/session/run filename entities (0 missing, 0 unexpected).
- **Spatial integrity:** Pairwise checks confirmed matching shape, voxel sizes, orientation, and affine (0 geometry failures).
- **Voxel modification:** Material intensity differences (`|Δ| > 0.5`) were quantified across the full cohort (median ≈ **24.1%** changed voxels; mean ≈ **24.0%**; range ≈ 9.6–37.9%). No fixed pass/fail threshold is applied; values are reported as evidence that defacing altered face-region intensities while preserving brain FOV geometry.
- **Acquisition metadata:** Derivative sidecars remain valid JSON. Provenance is recorded in `derivatives/defacing/dataset_description.json` (`GeneratedBy`: `neuro_pipeline.modules.defacing.run_defacing_session`). Per-sidecar `GeneratedBy` may be absent. A follow-up scan confirmed **`InstitutionalDepartmentName` is absent** from all derivative JSON under `derivatives/defacing/` (0 / 726), consistent with BIDS sidecar sanitization.

### Recommended publication wording

> Imaging data were de-identified using a DICOM PS3.15-oriented workflow, with additional BIDS metadata cleaning and anatomical defacing validation.

Avoid claiming that DICOM data were “fully anonymized according to DICOM PS3.15 Basic Profile” unless every Annex E action is independently certified. The supported formulation is a **PS3.15-oriented custom de-identification workflow with documented privacy audits.**
