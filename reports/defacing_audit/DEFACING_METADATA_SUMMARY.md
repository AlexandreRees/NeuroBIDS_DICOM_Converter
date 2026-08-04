# Defacing derivative metadata investigation (READ-ONLY)

**Date (UTC):** 2026-07-22  
**Scope:** All JSON sidecars under `/home/alexrees/scratch/derivatives/defacing`  
**Inputs modified:** none  
**Machine-readable detail:** `defacing_metadata_audit.tsv`  
**Counts helper:** `defacing_metadata_audit_counts.json`

## Link to the prior audit warning

The full defacing audit reported:

> PHI-like keys in derivative JSON (**352**)

That count comes from `code/audit_defacing.py`’s internal `PHI_KEYS` list applied to **T1w** derivative sidecars only.  
**Exact field responsible:** `InstitutionalDepartmentName` on **352 / 356** defaced `*_T1w.json` files (4 T1w sidecars lack the key).

No `PatientName`, `PatientID`, `PatientBirthDate`, `AccessionNumber`, `InstitutionName`, calendar `*Date` / `*Time` identifiers, `DeviceSerialNumber`, or physician/operator name fields were found in any defacing sidecar.

---

## STEP 1 — Flagged metadata inventory

Sidecar JSON scanned: **725** (plus `dataset_description.json`).  
Rows written to `defacing_metadata_audit.tsv`: **2168** (one row per watched field occurrence).

### Fields present that were reviewed

| Field | Occurrences (all modalities) | Unique values | Example values |
| --- | ---: | ---: | --- |
| `InstitutionalDepartmentName` | 718 | 2 | `Department` (676); `Centre de Recherche` (42) |
| `ProtocolName` | 725 | 5 | `T1w_MPR`; `tfl_b1map_1mmiso`; `Sag Flair 3D-0.8`; `WMn_MPRAGE_sagittal`; `Sag Flair 3D-0.8_usethisone` |
| `SeriesDescription` | 725 | 8 | Same family as protocols, plus rare `_ND` / `_usethisone` suffixes |

### T1w-only (explains the “352” warning)

| Field | T1w occurrences | Notes |
| --- | ---: | --- |
| `InstitutionalDepartmentName` | **352** | Sole field counted by the defacing PHI heuristic |
| `ProtocolName` | 356 | Not in audit `PHI_KEYS`; reviewed here for OpenNeuro free-text practice |
| `SeriesDescription` | 356 | Same |

### Classification vs BIDS / OpenNeuro practice

| Field | Classification | Rationale (standards-oriented) |
| --- | --- | --- |
| `InstitutionalDepartmentName` | **SHOULD_REMOVE** *(hygiene)* / not patient PHI | Institution-related DICOM attribute; OpenNeuro / sharing practice typically strips `Institution*` from public sidecars. Values here are generic or site-label text, not required by BIDS. |
| `ProtocolName` | **SAFE_TO_KEEP** | Standard acquisition descriptor widely retained in BIDS; values are sequence protocol names only. |
| `SeriesDescription` | **SAFE_TO_KEEP** | Common BIDS/dcm2niix sidecar field; values are sequence labels only (no personal names in this cohort). |
| Other `PHI_KEYS` from the audit list | **Absent** | N/A |

**Note:** `PatientPosition` appears in 725 sidecars (e.g. head-first supine). That is **acquisition geometry**, not a patient identity field, and was not part of the 352 warning.

---

## STEP 2 — Is each field actually PHI? (inspect values, not only names)

### `InstitutionalDepartmentName`

| Question | Answer |
| --- | --- |
| Direct identifier? | **No** — no person name, MRN, accession, or contact info |
| Quasi-identifier? | **Weak / institutional** — `Centre de Recherche` discloses a generic research-center label; `Department` is a placeholder |
| Acquisition metadata? | **No** — not TR/TE/FA/resolution |
| Provenance metadata? | **No** |
| Harmless free text? | **Mostly yes** for `Department`; **mild site wording** for `Centre de Recherche` |

**Why the heuristic fired:** the *field name* is on institutional/PHI scrub lists. **Why it is not residual personal health information:** values do not identify a participant.

### `ProtocolName`

| Question | Answer |
| --- | --- |
| Direct identifier? | **No** |
| Quasi-identifier? | **No** (sequence names shared across subjects) |
| Acquisition metadata? | **Yes** — protocol label used by scanners/pipelines |
| Harmless free text? | **Yes** in this dataset (all values are known sequence protocols) |

### `SeriesDescription`

| Question | Answer |
| --- | --- |
| Direct identifier? | **No** |
| Quasi-identifier? | **No** for observed values |
| Acquisition metadata? | **Yes** — series label |
| Harmless free text? | **Yes** here (matches protocol family; suffixes `_ND` / `_usethisone` are technical, not personal) |

**Free-text caveat (general):** SeriesDescription/ProtocolName *can* contain PHI in other studies. In **this** defacing tree, unique-value audit shows only sequence nomenclature.

---

## STEP 3 — Removal justified?

| Field | Improve privacy? | Reduce usability? | Violate BIDS? | Remove useful acquisition info? | Decision |
| --- | --- | --- | --- | --- | --- |
| `InstitutionalDepartmentName` | Mild hygiene gain (esp. `Centre de Recherche`) | Negligible | No — field not required | No | **OPTIONAL** |
| `ProtocolName` | No meaningful gain | **Yes** — users/tools often rely on it | No — keeping is normal | **Yes** if removed | **KEEP** |
| `SeriesDescription` | No meaningful gain given values | Mild | No — keeping is normal | Mild | **KEEP** |

No field is classified **REMOVE** as *required* removal of actual participant PHI.

---

## STEP 4 — Safety statement

The defacing audit warning (**352**) is driven exclusively by the presence of the key `InstitutionalDepartmentName` on T1w derivative JSON files.

Observed values are only `Department` or `Centre de Recherche`. No patient names, IDs, dates of birth, accession numbers, or other direct identifiers appear in defacing sidecars under the audited key lists.

**Statement:**

> The remaining warning is a heuristic false positive with respect to residual **personal** health information. It does not indicate participant-identifying PHI in defacing derivative JSON. Optional removal of `InstitutionalDepartmentName` remains a sharing-hygiene choice (OpenNeuro-style institution scrub), not a blocker for residual patient PHI.

No fields were identified that **must** still be removed to eliminate participant PHI from these derivatives.

---

## STEP 5 — Cleaning script

**Not generated.**  
Criterion was: create `code/clean_defacing_metadata.py` only if actual PHI remains and fields are classified **REMOVE**.  
Here: **no REMOVE** classifications for participant PHI; `InstitutionalDepartmentName` is **OPTIONAL** hygiene only.

If you later decide to scrub Institution* for packaging consistency, a derivative-only cleaner can be added at that time.

---

## Final publication verdict

### **PASS WITH JUSTIFIED WARNING**

**Justification:**

| Framework | Assessment |
| --- | --- |
| **Scientific Data** | Defacing coverage complete (356/356 T1w), geometry OK, provenance present, acquisition parameters preserved. Residual metadata warning is institutional free-text, not participant PHI. Disclose optional Institution* hygiene if desired. |
| **BIDS** | Keeping `ProtocolName` / `SeriesDescription` is consistent with typical BIDS sidecars. Removing `InstitutionalDepartmentName` would not violate BIDS. |
| **OpenNeuro** | Structural defacing complete. Common practice strips institution fields; current values are low-risk. Not a patient-PHI failure. |
| **DICOM PS3.15 publication practice** | Release is BIDS derivatives, not a claim of full Basic Profile certification. Absence of direct identifiers in these sidecars aligns with a PS3.15-oriented subset narrative. |

**Not FAIL:** no missing defaced T1w, no geometry failure, no direct identifiers in derivative JSON.  
**Not unqualified PASS:** the audit still surfaces an Institution*-key heuristic; document it as justified / non-PHI.

---

## Outputs

| File | Description |
| --- | --- |
| `reports/defacing_audit/defacing_metadata_audit.tsv` | Per-file field/value/reason rows |
| `reports/defacing_audit/DEFACING_METADATA_SUMMARY.md` | This report |
| `reports/defacing_audit/defacing_metadata_audit_counts.json` | Aggregate counts (helper) |
