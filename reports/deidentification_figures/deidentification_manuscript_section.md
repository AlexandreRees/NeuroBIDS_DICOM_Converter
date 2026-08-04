# Anonymization / de-identification — manuscript section

Text is written for a Scientific Data Methods subsection. Figure callouts refer to figures generated in this folder.

---

## 1. Full Methods version

Confidentiality protection was implemented as a dedicated stage of research-data preparation, after non-destructive inventory of the DICOM archive and after construction of approved participant–session mapping tables, and before conversion to the Brain Imaging Data Structure (BIDS) (Fig. 1). The purpose of this stage was to reduce re-identification risk carried by DICOM headers and identifiers while retaining the acquisition metadata and image content required for scientifically valid neuroimaging analysis. Original scanner exports were treated as an immutable archive and were never overwritten. De-identification was applied only to derived copies; subsequent conversion and quality control used those copies by default (Fig. 4).

Header confidentiality measures were oriented toward the DICOM PS3.15 Basic Application Level Confidentiality Profile. Direct identifiers, including patient name and patient ID, were replaced with a mapped study-specific canonical participant code (Fig. 3). Institutional, physician, accession, device-serial, free-text comment, and related identifier fields on a fixed policy list were cleared; all private DICOM tags were removed; and study, series, instance, and related unique identifiers were deterministically remapped so that original UIDs could not be used for external linkage (Fig. 2; Supplementary Table). Calendar dates were shifted by a participant-specific day offset, preserving relative intervals across longitudinal visits of the same individual, whereas acquisition clock times were left unchanged. De-identified objects were labelled to indicate that patient identity had been removed and to record the de-identification method.

Acquisition parameters required for analysis and standards-compatible conversion—including series descriptions used for modality and task labelling, repetition time, echo time, flip angle, and geometric fields—were retained, as was patient sex by default for demographic summary tables. Image pixel values were not modified during DICOM de-identification, and facial defacing was not performed at this stage. Because private vendor tags were removed, some scanner-specific fields that may otherwise support advanced reconstruction descriptors [Information not available in repository: quantitative impact on converted sidecar parameters such as slice timing, multiband factor, or effective echo spacing] may not be recoverable from the de-identified DICOM alone.

Pseudonymization therefore operated with a mapped canonical study code written into the de-identified DICOM identity fields, while sequential BIDS participant labels assigned during mapping organized the converted dataset. Mapping tables, date-shift offsets, and de-identification reports were retained privately for provenance and audit and were not intended for public redistribution with the imaging data. Prior to conversion, privacy validation confirmed that de-identified outputs satisfied predefined header checks and that integrity snapshots of the raw archive remained consistent with the unmodified source (Fig. 4).

---

## 2. Short Scientific Data version

After read-only inventory of the DICOM archive and construction of approved participant–session mappings, series were de-identified on derived copies while original acquisitions remained an immutable archive (Fig. 1). Header processing followed a DICOM PS3.15 Basic Application Level Confidentiality–oriented policy: protected identity and free-text fields were cleared; patient name and patient ID were replaced with mapped study codes; private tags were removed; unique identifiers were remapped; and calendar dates were shifted by a participant-specific offset that preserves longitudinal intervals within individuals (Figs. 2–3; Supplementary Table). Acquisition parameters required for analysis, including series descriptions used for modality labelling, were retained, as was patient sex by default. Image pixel values were not modified, and facial defacing was not performed during DICOM de-identification. Conversion to NIfTI and organization according to BIDS proceeded from the de-identified repository only after privacy validation and checks that source integrity snapshots remained consistent with the untouched raw archive (Fig. 4).

---

## 3. Figure placement notes (for authors)

| Figure | Recommended location |
|---|---|
| Fig. 1 Workflow | Opening of the de-identification Methods subsection |
| Fig. 2 Tag-action summary | Immediately after describing transformation classes |
| Fig. 3 Before/after example | When introducing pseudonymization, date shifting, and UID remapping |
| Fig. 4 Provenance | When stating that raw data remain immutable and conversion uses derivatives |
| Supplementary Table | Online supplementary material; cite at first mention of the tag policy |
