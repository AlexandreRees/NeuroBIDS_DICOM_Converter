# De-identification audit — DICOM PS3.15 & BIDS/OpenNeuro

**Date:** 2026-07-22  
**Scope:** Pre-publication readiness of the Narval `neuro_pipeline` de-identification stack  
**Standards consulted:**
- [DICOM PS3.15](https://dicom.nema.org/medical/dicom/current/output/html/part15.html) — Security and System Management Profiles (Attribute Confidentiality Profiles / Annex E; user link targets Part 15, including Ch. 5 Conventions)
- OpenNeuro FAQ / User Guide (BIDS + mandatory structural defacing)
- BIDS sidecar hygiene practices for shared datasets

**Engine audited:** `mri_anonymization` (`constants.py`, `dicom_anonymizer.py`) + streaming conversion (`streaming_convert.py`) + BIDS sidecar scrub (`sidecar_postprocess.py`) + associated-data de-id + optional defacing / release path.

---

## Executive verdict

| Dimension | Verdict | Notes |
| --- | --- | --- |
| **DICOM header de-id (research conversion path)** | **PASS with caveats** | Strong custom subset oriented to PS3.15 Basic; **not** a certified full Basic Profile implementation |
| **BIDS JSON PHI scrub (sampled)** | **PASS** | Core Patient*/Institution*/dates/DeviceSerial keys absent in 250 sampled sidecars |
| **OpenNeuro structural defacing** | **NOT READY** | Only **12 / 83** T1w subjects have defaced derivatives |
| **Publication claim wording** | **Must qualify** | Do **not** claim “full PS3.15 Basic Profile compliance”; document as Basic-oriented custom profile |

**Overall for final Scientific Data / OpenNeuro-style release:**  
**Conditional — header de-id is publication-grade if documented as a subset; defacing cohort completion and a few metadata gaps remain blockers.**

---

## 1. What PS3.15 actually requires (relevant parts)

Part 15 defines **Attribute Confidentiality Profiles** (Annex E), not only Ch. 5 Conventions. The profile your code cites is the:

**Basic Application Level Confidentiality Profile**

plus optional profiles such as:
- Clean Descriptors Option  
- Clean Pixel Data Option  
- Retain UIDs Option  
- Retain Patient Characteristics Option  
- Retain Device Identity Option  
- Retain Safe Private Option  
- Retain Longitudinal Temporal Information Options  

A conformant claim of “Basic Profile” implies applying the **full Action table** (Attribute Confidentiality Profile Attribute Action Codes) to every listed attribute. Your pipeline implements a **fixed curated tag list** (~35 cleared/pseudonymized identifiers + UID remap + date shift + private-tag purge), with provenance tags `PatientIdentityRemoved` / `DeidentificationMethod`.

### Mapping of your behavior to named options

| PS3.15 concept | Pipeline behavior | Status |
| --- | --- | --- |
| Basic Profile (identifiers, org, accession, …) | Clears/pseudonymizes `PHI_DICOM_TAGS`; remaps instance UIDs; strips private tags | **Partial / subset** |
| Retain UIDs | Study/Series/SOP/FoR UIDs **remapped** to `2.25.*` | Opposite of Retain UIDs (good for privacy) |
| Retain Longitudinal Temporal Info | Per-subject **date shift**; TM times kept | **Aligned with modified dates option intent** |
| Retain Patient Characteristics | Keeps **PatientSex** (default), **PatientAge** in DICOM | Partial retain |
| Retain Device Identity | Clears DeviceSerialNumber / StationName; keeps Manufacturer/Model | Partial |
| Clean Descriptors | Clears StudyDescription; **keeps SeriesDescription** | Partial gap |
| Clean Pixel Data | Pixels untouched; burned-in/overlays **warned only** | **Not implemented** |
| Retain Safe Private | Streaming path **keeps Siemens CSA (0029)** only | Documented exception |

`DeidentificationMethod` string:  
`PS3.15 Basic Profile; pseudonym; date shift; UID remap`  
(or CSA variant). This string **overclaims** relative to a full Basic Profile table.

---

## 2. Pipeline architecture (as implemented)

```
raw DICOM
  → streaming temp de-id (process_dicom_file, CSA keep ON)
  → dcm2niix → BIDS
  → scrub_sidecar_phi (BIDS_SIDECAR_PHI_KEYS)
  → [optional] associated_data de-id → sourcedata/
  → [optional] anatomical defacing → derivatives/defacing/
  → [optional] release anonymization / OpenNeuro packaging
```

Authoritative tag policy: `mri_anonymization/constants.py`.  
Legacy permanent upstream (`deidentify_dicom_upstream`) strips **all** private tags (CSA off) — not the default Slurm conversion path today.

---

## 3. DICOM controls — strengths

1. **Core direct identifiers** cleared or replaced (PatientName/ID → study pseudonym; birth date; other patient IDs/names; institution; physicians; operators; accession; study ID; device serial; station; many comments).  
2. **UID remapping** prevents linkage via Study/Series/SOP/FoR UIDs while preserving SOP Class / Transfer Syntax.  
3. **Date shift** with per-subject offsets preserves longitudinal intervals without publishing absolute calendar dates.  
4. **Private tags removed** by default; Siemens CSA restored only when needed for conversion physics (SliceTiming, PE, bvals).  
5. **Provenance tags** written (`PatientIdentityRemoved=YES`, method string).  
6. **Validation / privacy gate / audit CLIs** exist (`validate_anonymized_dicom`, `audit_deidentification`, associated-data validators).  
7. **Associated non-DICOM data** has a dedicated scrub path.

---

## 4. DICOM / PS3.15 gaps (pre-publication)

| ID | Gap | Risk | Recommendation |
| --- | --- | --- | --- |
| D1 | Not full Basic Profile Action table | Overclaim if advertised as “PS3.15 compliant” | Reword methods to “Basic-oriented custom subset”; cite Annex E; list Actions you do/don’t apply |
| D2 | `SeriesDescription` retained | Free-text PHI rare but possible | Audit unique values cohort-wide; clear or sanitize outliers |
| D3 | `PatientAge` retained in DICOM | Indirect identifier (esp. rare ages) | Clear on release DICOM mirrors; already scrubbed from BIDS sidecars |
| D4 | `PatientSex` retained in DICOM; present in `participants.tsv` | Acceptable if intentional scientific covariate | Document IRB/consent; ensure no other quasi-identifiers cluster |
| D5 | No Clean Pixel Data | Burned-in PHI / overlays | Cohort scan for `BurnedInAnnotation` / overlays; quarantine positives |
| D6 | Streaming CSA retain | Private-tag residual | Keep documented; ensure release mirror without CSA if OpenNeuro receives only BIDS |
| D7 | Duplicate legacy `dicom_helpers.PHI_TAGS` | Drift if reused | Deprecate / gate tests so only `mri_anonymization` is authoritative |
| D8 | Method LO string says “Basic Profile” | Standards pedantry / reviewer challenge | Change to e.g. `PS3.15-oriented Basic subset; …` |

---

## 5. BIDS / OpenNeuro controls

### Sidecar PHI scrub — empirical spot check

Sampled **250** JSON sidecars across 15 subjects for common PHI keys.

| Finding | Result |
| --- | --- |
| PatientName / PatientID / dates / InstitutionName / DeviceSerialNumber / Operator / Physician keys | **Not present** |
| `InstitutionalDepartmentName` | Present in **250/250** (= `"Department"`) — low risk; consider scrubbing for consistency |
| `participants.tsv` | `participant_id`, `cohort`, `sex` only — appropriate |

Defaced derivative sidecar example (`derivatives/defacing/sub-001/...`) likewise lacks Patient* keys; retains acquisition physics + `SeriesDescription` / `ProtocolName`.

### OpenNeuro / BIDS publication expectations

| Requirement | Status |
| --- | --- |
| Data in BIDS | Research BIDS tree present |
| Structural MRI **defaced** before OpenNeuro upload | **12 / 83** subjects with T1w have defacing derivatives — **blocker** |
| No residual direct identifiers in metadata | Strong on sampled sidecars |
| Document de-id / defacing in README / methods | Partial (internal reports exist; finalize public README) |
| CC0 / consent / ethics statements | Out of scope of this code audit — confirm separately |

---

## 6. Publication readiness checklist

### Ready now (with wording fixes)
- [x] Streaming DICOM header de-id for conversion  
- [x] UID remap + date shift + private-tag policy  
- [x] BIDS sidecar PHI scrub on conversion path  
- [x] Associated-data de-id tooling  
- [ ] Update `DeidentificationMethod` / manuscript claims to **subset** language  

### Required before OpenNeuro / final shared release
- [ ] Complete anatomical **defacing** for all structural volumes intended for share  
- [ ] Cohort burned-in / overlay audit  
- [ ] Cohort `SeriesDescription` / `ProtocolName` uniqueness audit for free-text PHI  
- [ ] Confirm release package does **not** redistribute identifiable raw DICOM  
- [ ] Public README section: de-id profile, date-shift policy, defacing tool (pydeface), CSA note  

### Nice-to-have
- [ ] Extend `BIDS_SIDECAR_PHI_KEYS` with `InstitutionalDepartmentName`, optional UID fields if dcm2niix emits them  
- [ ] Apply sidecar scrub on defacing JSON copies (defense in depth)  
- [ ] Single authoritative tag-policy test vs Annex E Action codes spreadsheet  

---

## 7. Suggested Scientific Data wording

> DICOM headers were de-identified using a custom Attribute Confidentiality workflow oriented to the DICOM PS3.15 Basic Application Level Confidentiality Profile (Annex E). Direct identifiers were removed or replaced with study pseudonyms; instance UIDs were remapped; calendar dates were shifted by a participant-specific offset; and private tags were removed except for a documented Siemens CSA block required for BIDS conversion. This implementation is a curated subset of the full Basic Profile Action table and is not claimed as a certified PS3.15 product. Facial features on structural MRI were removed with pydeface prior to public release. MRIQC / automated QC tools were not used as identity-removal mechanisms.

---

## 8. Key file references

| Path | Role |
| --- | --- |
| `mri_anonymization/constants.py` | Tag policy |
| `mri_anonymization/dicom_anonymizer.py` | De-id engine |
| `neuro_pipeline/streaming_convert.py` | Production path + CSA keep |
| `neuro_pipeline/conversion/sidecar_postprocess.py` | BIDS PHI scrub |
| `docs/STREAMING_DEIDENTIFICATION.md` | Architecture |
| `reports/deidentification_*.md` | Prior methods notes |
| This report | `reports/deidentification_ps315_openneuro_audit.md` |

---

## 9. Bottom line

The de-identification **header pipeline is mature and appropriate for a Scientific Data methods description** if you stop short of claiming full PS3.15 Basic Profile certification and finish documenting exceptions (CSA, SeriesDescription, sex/age).  

For **OpenNeuro-style final publication**, the outstanding hard blocker is **cohort-wide structural defacing** (currently ~14% coverage), plus burned-in / free-text descriptor audits.
