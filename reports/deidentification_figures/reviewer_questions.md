# Reviewer perspective — anticipated questions

For each item: potential concern, answer supported by the current pipeline evidence, and missing information if any.

---

## 1. Was protected health information completely removed from DICOM headers?

**Potential concern.** Residual PHI in free-text fields, private tags, or burned-in overlays could undermine sharing.

**Answer supported by current evidence.** A fixed list of identifier and free-text fields is cleared or pseudonymized; all private tags are removed; per-file validation requires cleared PHI fields and presence of identity-removed provenance tags; a privacy gate rechecks selected forbidden fields before conversion.

**Missing information.** Full-cohort completion statistics for the final release; prevalence of burned-in annotations across all series; whether pathnames/filenames that still contain date or scanner-style tokens are acceptable under the sharing model.

---

## 2. Were images (pixel data) altered?

**Potential concern.** Reviewers may assume de-identification includes defacing or intensity alteration.

**Answer supported by current evidence.** DICOM de-identification is header-oriented; pixel data are copied without modification. Facial defacing is not part of this stage.

**Missing information.** Whether any separate public-release derivative applied facial defacing to anatomical volumes.

---

## 3. Were dates preserved or destroyed?

**Potential concern.** Either absolute dates leak identity, or aggressive date removal breaks longitudinal science.

**Answer supported by current evidence.** Calendar dates are shifted by a participant-specific day offset; acquisition times are preserved; relative intervals between visits of the same participant are therefore retained while absolute calendar dates are obscured.

**Missing information.** Public documentation of the production offset seed is not required for readers, but the study team should archive the private offset table used for the final dataset.

---

## 4. Can longitudinal relationships be reconstructed?

**Potential concern.** Remapped identifiers and shifted dates might scramble visit structure.

**Answer supported by current evidence.** Mapping tables link sessions to participants before de-identification; the same participant-specific date offset is applied across that participant’s sessions; BIDS session labels organize visits in the converted dataset.

**Missing information.** None for the methodological claim; public users rely on BIDS session entities rather than raw calendar dates.

---

## 5. Are raw data immutable?

**Potential concern.** In-place anonymization could irreversibly alter the only archive.

**Answer supported by current evidence.** De-identification writes to a separate de-identified DICOM repository; the workflow is designed so original exports are not overwritten; privacy validation can check source integrity snapshots before conversion.

**Missing information.** Confirmation that the final full-cohort run completed with a clean privacy-gate result for all sessions intended for publication.

---

## 6. Is BIDS conversion reproducible from the shared materials?

**Potential concern.** If conversion used raw (non-de-identified) inputs, or if critical metadata were stripped, reproducibility suffers.

**Answer supported by current evidence.** Conversion is configured to use the de-identified DICOM repository by default after privacy validation; series descriptions and core acquisition parameters are retained to support modality labelling and NIfTI/JSON generation.

**Missing information.** Quantitative comparison of JSON sidecars from raw versus de-identified DICOM to document any loss of private-tag–dependent fields (for example slice timing or multiband factor).

---

## 7. Does the procedure comply with DICOM PS3.15?

**Potential concern.** Overclaiming “full PS3.15 compliance” without profile-option detail.

**Answer supported by current evidence.** The method is oriented toward the Basic Application Level Confidentiality Profile (clear/pseudonymize listed fields, remove private tags, shift dates, remap UIDs, set identity-removed provenance).

**Missing information.** Formal mapping to every PS3.15 option (for example Clean Pixel Data Option); this should be described as a documented custom subset, not a certified toolkit implementation.

---

## 8. How are participant identifiers assigned?

**Potential concern.** Hashing versus sequential codes versus retained scanner IDs affects privacy and linkage.

**Answer supported by current evidence.** DICOM patient name/ID are replaced with a mapped canonical study code; sequential BIDS participant labels are assigned during mapping for the converted dataset; identifiers are not left as original scanner patient names.

**Missing information.** Whether a second public-release remapping to new sequential codes was applied to the deposited dataset.

---

## 9. Were private tags removed, and does that harm analysis?

**Potential concern.** Private-tag removal may drop vendor fields used by converters.

**Answer supported by current evidence.** All private tags are removed as a confidentiality measure; standard acquisition tags used for core methods reporting are retained by policy.

**Missing information.** Empirical assessment of which analysis-critical sidecar fields, if any, are missing after conversion from de-identified DICOM.

---

## 10. How was successful de-identification validated?

**Potential concern.** Absence of validation weakens trust.

**Answer supported by current evidence.** Per-file validation precedes writing outputs; failed files are not accepted; a privacy gate and optional subject-level privacy audit compare expected identity and PHI clearance; integrity checks can verify that raw sources remain unchanged.

**Missing information.** Summary pass/fail statistics for the final full dataset suitable for the manuscript or supplement.
