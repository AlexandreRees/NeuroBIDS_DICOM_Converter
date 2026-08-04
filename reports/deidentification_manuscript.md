# Anonymization / de-identification — manuscript text

Derived solely from `reports/deidentification_report.md`. No repository files were modified except this deliverable.

---

## 1. Full manuscript version

DICOM de-identification was performed as a dedicated stage of the research data workflow, after session inventory and participant–session mapping and before conversion to the Brain Imaging Data Structure (BIDS). The purpose of this stage was to reduce the risk of participant re-identification in headers and identifiers while retaining the acquisition metadata required for scientifically valid neuroimaging analysis. De-identification was applied to copies of mapped session DICOM series; the original scanner exports were left unmodified and treated as an immutable archive. Subsequent conversion and analysis were configured to use the de-identified DICOM copies by default, with a privacy validation step confirming that de-identified outputs met predefined checks and that the archived raw files remained unchanged before conversion proceeded.

Participant confidentiality was protected through header-level de-identification oriented toward the DICOM PS3.15 Basic Application Level Confidentiality Profile. Direct identifiers, including patient name and patient ID, were replaced with a mapped study-specific canonical participant code rather than retained in their original form. Additional fields containing demographic free text, institutional and physician information, accession numbers, device serial numbers, study identifiers, and related comment fields were cleared according to a fixed tag policy. All private DICOM tags were removed. Study, series, SOP, frame-of-reference, and related unique identifiers were deterministically remapped so that original UIDs could not be used for linkage, while SOP Class UIDs required for DICOM validity were preserved. Calendar dates were shifted by a participant-specific day offset, preserving relative intervals across longitudinal visits; acquisition times were left unchanged. Each de-identified object was labelled to indicate that patient identity had been removed and to record the de-identification method.

Metadata essential for reconstruction and analysis—including series descriptions used for modality labelling, standard geometric and sequence parameters such as repetition time, echo time, flip angle, and voxel geometry, and pixel data—were retained. Patient sex was retained by default to support demographic tables. Because private vendor tags were removed, some scanner-specific fields that may otherwise support advanced reconstruction parameters [Information not available in repository: quantitative impact on converted sidecar fields such as slice timing, multiband factor, or effective echo spacing] may not be recoverable from the de-identified DICOM alone.

Pseudonymization therefore operated at two related levels: a canonical study identifier written into the de-identified DICOM patient name and patient ID fields, and sequential BIDS participant labels (`sub-XXX`) assigned during mapping for organization of the converted dataset. Mapping tables, date-shift offsets, and de-identification reports were retained privately for provenance and audit and were not intended for public redistribution with the imaging data. Image pixel values were not altered during DICOM de-identification, and facial defacing was not performed at this stage. Image-based facial anonymization is available as an optional procedure for anatomical volumes if a separate public-release preparation is undertaken; whether defacing was applied to any publicly shared derivative of the present dataset is [Information not available in repository].

---

## 2. Condensed version

After inventory and participant–session mapping, and before BIDS conversion, DICOM series were de-identified on copies of the mapped session data while the original scanner exports were kept unchanged. Header processing followed a DICOM PS3.15 Basic Application Level Confidentiality–oriented policy: direct identifiers were replaced with mapped study codes; institutional, physician, accession, device-serial, and free-text identifier fields were cleared; private tags were removed; UIDs were remapped; and dates were shifted by a participant-specific offset, with acquisition times preserved. Acquisition parameters needed for analysis and series descriptions used for labelling were retained, as was patient sex by default. Pixel data were not modified, and facial defacing was not part of DICOM de-identification. Conversion used the de-identified DICOM after privacy checks confirming successful header de-identification and integrity of the raw archive.

---

## 3. Ultra-short version

DICOM de-identification was applied to copies of mapped sessions before BIDS conversion, leaving original exports untouched. Headers were cleaned under a PS3.15 Basic Profile–oriented policy (pseudonymized identifiers, cleared PHI fields, removed private tags, remapped UIDs, and shifted dates), while acquisition parameters and image pixels were preserved. Facial defacing was not performed at this stage.

---

## Reviewer checklist

Statements that would benefit from an external citation and/or additional verification before publication:

1. **Claim of alignment with DICOM PS3.15 Basic Application Level Confidentiality Profile** — Cite the DICOM standard (NEMA PS3.15) and verify which profile options (for example Clean Pixel Data Option) are and are not implemented; the internal report describes a custom subset rather than certified full-profile compliance.

2. **Assertion that original raw DICOM exports remain immutable for the completed dataset** — Verify that full-cohort de-identification finished successfully and that privacy-gate / manifest checks passed for all sessions intended for release.

3. **Statement that conversion always proceeds from de-identified DICOM** — Confirm that the released BIDS dataset was generated exclusively from de-identified inputs and not from any developer override that reads raw archives.

4. **Retention of acquisition metadata sufficient for fMRI, diffusion, and fieldmap processing** — Empirically compare converted JSON sidecars from raw versus de-identified DICOM to document any loss of private-tag–dependent fields (slice timing, multiband acceleration, effective echo spacing).

5. **Date shifting preserves longitudinal intervals** — Cite or briefly justify the statistical privacy rationale for date shifting; verify that the production seed and per-participant offsets used for the final dataset are documented in a controlled provenance record (offsets themselves need not be published).

6. **Deterministic UID remapping prevents linkage** — Optionally cite DICOM UID conventions; confirm that remapped UIDs remain unique and that no original UIDs remain in nested sequences across a sample of series.

7. **Patient sex retention is ethically/regulatory appropriate** — Align with local REB/IRB and data-sharing agreements; some jurisdictions treat sex as sensitive demographic information.

8. **Absence of facial defacing in the de-identification stage** — If anatomical volumes will be shared publicly, reviewers may expect defacing or an explicit justification; confirm the actual status of any public derivative [Information not available in repository].

9. **Filenames and directory names may still contain date or scanner-style subject tokens after header de-identification** — Assess whether this residual path-level information is acceptable under the intended sharing model; remediate or disclose if required.

10. **Burned-in annotation / overlay risk is controlled** — The workflow flags burned-in annotation tags but does not OCR pixel text; report audit results for the cohort or cite residual risk.

11. **“Privacy validation before conversion”** — Describe validation criteria at a level sufficient for reproducibility without software names, and provide summary pass/fail statistics for the final dataset.

12. **Optional public-release remapping to new sequential identifiers** — If the publicly deposited dataset uses a second remapping distinct from research BIDS IDs, state that clearly and cite the mapping custody policy.
