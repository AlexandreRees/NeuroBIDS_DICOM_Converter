# Remaining decisions before OpenNeuro deposition

**Date:** 2026-07-24  
**Reviewer stance:** PI / Scientific Data + OpenNeuro reviewer  
**Overall verdict:** **NOT READY TO UPLOAD TODAY**  
Imaging conversion, defacing (freeze-era), MRIQC, DWI QC and Pizarro are largely publication-grade. What remains is mostly **legal/metadata ownership**, one **freeze vs sync** packaging choice, and **explicit disclosure decisions**.

---

## Executive summary (reviewer)

| Gate | Status |
|---|---|
| Research BIDS conversion | Strong |
| Defaced public tree (`release_dataset/`) | Strong for **124** sessions |
| QC layers (MRIQC / DWI / Pizarro) | Strong — document, don’t exclude |
| Authors / Name / License / consent | **BLOCKING** |
| Release tree = current research inventory | **OUT OF SYNC** (11 new `ses-02`) |
| README / Technical Validation currency | Needs refresh before upload |
| Associated data (physio / eye / stimuli) | Withhold (documented) |

**Bottom line for the PI:** Engineering cannot “finish OpenNeuro” without you. Upload is blocked by authorship + license/consent. Separately, you must choose whether v1 deposits the July-23 **124-session** package or waits for defacing + rebuild of **11 newly converted `ses-02`**.

---

## Snapshot of the two trees (must be understood)

| Metric | Research `bids/` | Public `release_dataset/` |
|---|---:|---:|
| Subjects | 84 | 84 |
| Sessions | **135** | **124** |
| NIfTI | **8594** | **7956** |
| Anatomicals | Face-intact | **Defaced** |
| Authors / License | Placeholder / missing | Placeholder / missing |

**11 `ses-02` in `bids/` but not in `release_dataset/`:**  
`sub-057, 064, 066, 067, 068, 069, 072, 073, 074, 078, 081`  
(~638 NIfTI). These sessions need **defacing before** they can enter any OpenNeuro package.

**Do not upload research `bids/` as-is:** non-defaced structurals; OpenNeuro requires affirming defacing.

---

## A. HARD blockers — decide before any upload

### A1. Authors list and order
**Current:** `"Authors": ["Neuro BIDS Pipeline"]` in both  
`bids/dataset_description.json` and `release_dataset/dataset_description.json`.

**Why it blocks:** OpenNeuro + Scientific Data require identifiable authors; validator warns `TOO_FEW_AUTHORS`; placeholder is not publication-grade.

**PI decision:** Provide ordered list of names + affiliations (OpenNeuro field + paper).

- [ ] Decision recorded: _______________________________

---

### A2. Final dataset title (`Name`)
**Current:** `"Neuro BIDS Pipeline Dataset"`.

**PI decision:** Choose the public title (should match Scientific Data article title closely).

- [ ] Final Name: _______________________________

---

### A3. License + consent-to-share
**Current:** no `"License"` field; no `LICENSE` file; README still has citation/DOI placeholders.

**OpenNeuro norm:** **CC0**.  
**Ethics backdrop:** MUHC REB Protocol **2020-5879** (Methods draft). Consent language for **open redistribution** must be confirmed by PI/legal — engineering cannot sign this.

**PI decision (choose one):**
- **A)** CC0 (recommended for OpenNeuro) — consent covers open sharing  
- **B)** Other license — may conflict with OpenNeuro defaults; justify  
- **C)** Hold deposit — consent insufficient for open share

- [ ] Choice: A / B / C  
- [ ] Consent confirmation signed off by: _____________ date: _______

---

### A4. Deposit snapshot (freeze vs sync) — critical packaging fork

| Option | What you deposit | Pros | Cons |
|---|---|---|---|
| **A — Freeze v1** | Current `release_dataset/` (124 sessions, defaced) | Ready sooner; already audited | Must **disclose** 11 post-freeze `ses-02` as pending v2 |
| **B — Sync then deposit** | Deface 11 `ses-02` → rebuild release → re-QC → upload | “Most complete” claim | Days of work; MRIQC/DWI denominators change; re-validate |

**Reviewer recommendation:** Prefer **A** if Scientific Data timeline is near, with explicit README/CHANGES wording that 11 follow-ups were converted after packaging and will appear in a revision. Prefer **B** if you want a single “complete as of deposit date” claim.

- [ ] Choice: A / B

---

### A5. If choosing B: undefaced new anatomicals
New sessions currently lack defaced derivatives for those 11 subjects’ `ses-02` (T1w / FLAIR / TB1TFL as applicable).

**Hard rule:** no face-intact structural MRI on OpenNeuro without documented consent exception.

- [ ] Defacing completed + release rebuild signed off

---

### A6. Ethics / redistribution green light
Beyond REB number: explicit PI statement that this cohort may be shared under the chosen license.

- [ ] PI green-light for OpenNeuro upload: Yes / Hold

---

## B. SOFT blockers — strongly recommended before upload

### B1. Refresh README QC text
Release README still frames MRIQC/DWI as incomplete/pilot in places; current audits say:
- MRIQC **1848/1852 (99.8%)**
- DWI technical validation **PASS** (0 FAIL gradients)

**Action:** rewrite QC section to match audits before upload.

---

### B2. Re-validate the *upload* tree
- Research `bids/` historically had `MULTIPLE_README_FILES` when both `README` and `README.md` existed.  
- `release_dataset/` keeps a single `README.md` (good).  
- After Authors/License/sync edits: re-run **bids-validator** on the exact upload directory.  
- Prior release build noted validator `NOT_AVAILABLE` at build time — do not upload without a fresh 0-error run.

---

### B3. Fill post-accession placeholders
After OpenNeuro accession: DOI, How to cite, DatasetDOI in `dataset_description.json`, README citation block. Optional but recommended: `CITATION.cff`.

---

### B4. Free-text sidecar hygiene — **DECIDED / PASS (2026-07-24)**
Full scan of `release_dataset/` (**7956** JSON): **0** hits on Patient*/Institution*/dates/Accession/comments.  
Prior heuristic flags on `Sag Flair 3D-0.8*` = **false positives** (FLAIR protocol).  
Report: `reports/privacy_audit/FREETEXT_PHI_AUDIT_RELEASE_2026-07-24.md`.

**PI decision:** **A) Keep** SeriesDescription / ProtocolName as technical labels. No PHI scrub required.

---

### B5. Age in manuscript vs `participants.tsv` — **DECIDED (2026-07-24)**
Public `participants.tsv` columns: `participant_id`, `cohort`, `sex` only (84 rows; Control 56 / Glaucoma 19 / DataON 7 / DataTON 2; F 46 / M 38).

**PI decision:** **A) Keep age out of public participants**  
- Do **not** add an age column to OpenNeuro `participants.tsv`  
- Do **not** report aggregate age (mean ± SD) in the Data Descriptor  
- Manuscript drafts updated (Background / Methods / TeX); internal age tables stay private

---

### B6. TB1TFL policy
`.bidsignore` contains `*_TB1TFL.*` while files remain on disk (release ~248).

**PI decision:**
- **A)** Include & validate in public package  
- **B)** Keep ignored / exclude from upload (document)

---

### B7. MRIQC group tables refresh
Group aggregation dated with n≈1707 while current scored ≈1848. Optional regenerate `derivatives/mriqc/group_qc/` before shipping IQMs.

---

### B8. Visual spot-check of defacing
Coverage for freeze-era T1w was complete; still recommend PI/trainee visual sample check before affirming `--affirmDefaced`.

---

### B9. Citations housekeeping
Peer-reviewed DOIs in draft: **9/9 PASS**. Add **MRtrix3** to software/references (used in DWI QC).

---

## C. Documentation / disclosure decisions (reviewer expects these)

| Topic | Reviewer expectation |
|---|---|
| De-identification | Frame as **PS3.15-oriented custom subset**, **not** certified full Basic Profile |
| Longitudinal coverage | Incomplete follow-up, not missing placeholders — **align numbers to deposited tree** (124 vs 135) |
| task-fmri events | **456/507 (89.9%)**; **51** intentionally omitted (ambiguous mapping) — disclose |
| movie / control / rest events | None by design → validator `EVENTS_TSV_MISSING` warnings OK if explained |
| Physio | Source PhysioLog exists; **not released** (mapping not verified) — disclose withhold |
| Eye-tracking | Inventoried; **not in public BIDS** — disclose |
| Stimuli / movies | Do **not** redistribute `.mp4` without rights clearance; publish IDs/checksums/instructions instead |
| Associated raw tree | **Do not ship** (PHI-flagged / copyrighted content in audits) |
| Reverse-PE DWI b0 | Absent from `dwi/`; distortion via spin-echo fmap AP/PA (**120/120** sessions) — disclose |
| XA30 / coil metadata | Occasional missing coil fields; SliceTiming recovered where possible — non-blocker if documented |
| Date-shift table / raw↔BIDS ID maps | **Keep private** — never deposit |

---

## D. QC decisions (what a reviewer will accept)

**Recommended policy (already supported by audits): inclusive raw release; no automatic exclusions.**

| Layer | Fact | Decision needed? |
|---|---|---|
| MRIQC coverage | **99.8%** (1848/1852); 4 pathological unscored | **A)** publish with documentation (recommended) **B)** wait (no gain for known bad inputs) |
| MRIQC 4 gaps | Truncated BOLD ×2; out-of-protocol T1w ×2 | Retain in BIDS; list in Technical Validation |
| High motion | 23 runs fd≥0.5 mm; 4 ≥1.0 mm | Flags only — **not** deposit exclusions |
| IQM outliers | Exploratory within-cohort flags | Not a failure rate |
| DWI integrity | 361/361 PASS | No decision |
| dwigradcheck | 250 PASS / **111 REVIEW** / **0 FAIL** | **A)** document only, no bvec edits (recommended) **B)** apply corrections (not supported) |
| Negative mean b0 | n≈26 | Signed recon ± mask — retain; use median metrics |
| Pizarro | 385/385; screening only | Confirm: **no auto exclusion** |
| Eddy / eddy_quad motion | N.A. in audited derivatives | State unavailable |

**If Option A4-B (sync 11 sessions):** re-audit MRIQC/DWI denominators before locking Technical Validation numbers.

---

## E. Packaging / OpenNeuro-specific checklist

| Requirement | Status / action |
|---|---|
| Upload **defaced** structurals | `release_dataset/` OK for 124-session freeze |
| `openneuro upload --affirmDefaced` | Only after Authors + License + chosen snapshot validated |
| Validator **0 errors** | Re-run on final tree |
| Warnings acceptable with disclosure | Events missing (by design / 51), inconsistent parameters, missing sessions |
| `participants.tsv` | PASS (84; allowed columns) |
| No `desc-defaced` filenames | PASS (standard `*_T1w` names) |
| No DICOM / `raw_original/` in package | Policy PASS |
| Approx. size | ~**1000 GB** — plan transfer + time |
| Derivatives on OpenNeuro? | **Decide:** ship MRIQC (± Pizarro / DWI QC tables) vs paper-only |

**PI decision — derivatives:**
- **A)** Deposit MRIQC (and optionally Pizarro/DWI QC summaries) under OpenNeuro derivatives  
- **B)** Paper / supplement only

---

## F. What is already PASS (do not re-litigate)

- Mapping freeze PASS (84 subjects; frozen 2026-07-20)  
- Release build APPLY: anatomical replacements completed for freeze-era set  
- Release audit 2026-07-24: **0 FAIL**, 4 WARN (authors/name/license/raw_original path)  
- Defacing freeze-era T1w complete; release anat identity checks PASS in prior runs  
- DWI technical validation PASS (0 FAIL; AP/PA complete)  
- MRIQC deposit-ready with disclosure of 4 gaps  
- Pizarro complete as screening layer  
- Citation DOIs 9/9 PASS  
- Privacy narrative ready if framed as PS3.15-oriented subset  
- Event dictionary for released task-fmri events present  

---

## G. PI decision sheet (sign-off)

Print / paste answers; engineering executes from this sheet.

| # | Decision | Options | PI answer |
|---|---|---|---|
| 1 | Authors + order + affiliations | Provide list | |
| 2 | Dataset `Name` | Final title | |
| 3 | License | A CC0 / B other / C hold | |
| 4 | Consent covers open share | Yes / No | |
| 5 | Deposit snapshot | A freeze 124 / B sync 11 then deposit | |
| 6 | TB1TFL public? | A include / B ignore-exclude | |
| 7 | MRIQC 4 gaps | A document & deposit / B delay | |
| 8 | DWI REVIEW n=111 | A document only / B edit bvecs | |
| 9 | Subject/run exclusions for deposit | A none / B list | |
| 10 | Physio | A withhold / B fund recovery for v2 | |
| 11 | Eye-tracking / stimuli | A withhold / B clear rights then add | |
| 12 | Public age column | A omit / B add | **A — omit; no aggregate age in paper** |
| 13 | OpenNeuro derivatives (MRIQC…) | A yes / B paper only | |
| 14 | Free-text SeriesDescription | A keep after review / B scrub | **A — keep (PASS audit)** |
| 15 | Upload green-light after engineering closes path | Yes / Hold | |

**Recommended default answers (reviewer):**  
1–2 provide; **3A**; **4 Yes** (if true); **5A** (or 5B if completeness claims matter more than speed); **6B or A** with explicit README; **7A**; **8A**; **9A**; **10A**; **11A**; **12A**; **13A** for MRIQC at least; **14A**; **15** after validator 0-error on final tree.

---

## H. Minimal path to upload (if PI picks freeze v1 + defaults)

1. PI returns decision sheet (Authors, Name, CC0+consent, freeze A, no exclusions).  
2. Engineering updates `release_dataset/dataset_description.json` + LICENSE + README QC section + CHANGES note on 11 pending `ses-02`.  
3. Fresh bids-validator on `release_dataset/` → **0 errors**.  
4. Visual deface spot-check sample.  
5. `openneuro upload --affirmDefaced` (ignore warnings only with documented justification).  
6. After accession: fill DOI / HowToAcknowledge; sync Scientific Data Methods numbers to **124-session** deposit.  
7. Optional v2: deface + sync 11 `ses-02`, re-QC, revision.

---

## I. Reviewer closing statement

This dataset is **technically close** to OpenNeuro readiness. The remaining risk is not “is MRIQC good enough?” — it is **governance**: who owns authorship, whether consent supports CC0, and whether the public claim of completeness matches the **124-session defaced tree** or the **135-session research tree**. Resolve those decisions first; the rest is packaging and disclosure.
