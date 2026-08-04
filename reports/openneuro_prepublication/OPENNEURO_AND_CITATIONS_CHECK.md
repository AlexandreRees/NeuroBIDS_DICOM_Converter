# OpenNeuro validator & citation pre-publication check

**Date (UTC):** 2026-07-22  
**Dataset:** `/home/alexrees/scratch/bids`  
**Defaced anatomicals:** `/home/alexrees/scratch/derivatives/defacing`  
**References draft:** `reports/scientific_data_manuscript_draft/Scientific_Data_References_Draft_2026-07-22.tex`

---

## 1. OpenNeuro / BIDS validator

OpenNeuro rejects uploads with **BIDS validator errors** (warnings may be ignored with `--ignoreWarnings`). The same engine used in prior Scientific Data checks is **bids-validator 1.15.0**.

### Fresh re-run (this check)

| Item | Value | Source |
| --- | --- | --- |
| Validator | bids-validator **1.15.0** (`npx`) | `bids_validator_openneuro_check.json` |
| **Errors** | **1** — `MULTIPLE_README_FILES` | both `README` and `README.md` at dataset root |
| Warning groups | EVENTS_TSV_MISSING, INCONSISTENT_SUBJECTS, INCONSISTENT_PARAMETERS, MISSING_SESSION, TOO_FEW_AUTHORS | same JSON |
| Subjects / sessions / files | 84 / 01+02 / 16195 | same |

Prior Scientific Data pass (`VALIDATION_AFTER_EVENTS_ST.md`, 2026-07-21) reported **0 errors** before `README.md` was added alongside `README`. The new README duplication is the **only new validator error**.

Remaining **warnings** (OpenNeuro can ignore with `--ignoreWarnings`, but disclose them):

- `EVENTS_TSV_MISSING`
- `INCONSISTENT_SUBJECTS`
- `INCONSISTENT_PARAMETERS`
- `MISSING_SESSION`
- `TOO_FEW_AUTHORS`

### OpenNeuro packaging checklist (beyond validator)

| Requirement | Status | Notes |
| --- | --- | --- |
| BIDS format | **PASS** (0 errors) | After priority + events/SliceTiming fixes |
| Structural scans **defaced in the uploaded tree** | **NOT READY for OpenNeuro upload as-is** | Raw `bids/` still contains **non-defaced** T1w (sample `sub-001` differs from derivative; ~19% voxels changed). Defaced copies exist only under `derivatives/defacing/` (356/356). OpenNeuro requires affirming that structural scans in the shared dataset are defaced (or consent exception). |
| Defacing tool | pydeface (documented) | Matches OpenNeuro recommendation |
| License **CC0** (OpenNeuro default) | **MISSING** | `dataset_description.json` has no `License`; no `LICENSE` file |
| Real **Authors** list | **PLACEHOLDER** | `Authors: ["Neuro BIDS Pipeline"]` → triggers `TOO_FEW_AUTHORS` |
| `CITATION.cff` | **MISSING** | Optional but recommended |
| README | Present | `README` + `README.md` |
| `CHANGES` | Present | Initial conversion note |
| No identifiable DICOM in package | Policy OK | Do not ship `raw_original/` |
| Derivative JSON institution scrub | **PASS** | `InstitutionalDepartmentName` count = 0 after cleaning |

### OpenNeuro verdict

**BIDS validator errors: FAIL (1)** — resolve `MULTIPLE_README_FILES` (keep a single `README` or `README.md`).  
**OpenNeuro upload readiness of current `bids/` tree: NOT READY** — also must publish **defaced** structural images in the upload package, set **CC0** license, and replace placeholder **Authors**.

---

## 2. Citation verification

DOIs from `Scientific_Data_References_Draft_2026-07-22.tex` were checked against the **Crossref** API (`reports/openneuro_prepublication/citation_doi_check.json`).

| Draft label | DOI | Crossref | Match |
| --- | --- | --- | --- |
| BIDS | 10.1038/sdata.2016.44 | Gorgolewski 2016, *Scientific Data* | **OK** |
| BIDS apps | 10.1371/journal.pcbi.1005209 | Gorgolewski 2017, *PLOS Comp Biol* | **OK** |
| dcm2niix | 10.1016/j.jneumeth.2016.03.001 | Li 2016, *J Neurosci Methods* | **OK** |
| MRIQC | 10.1371/journal.pone.0184661 | Esteban 2017, *PLOS ONE* | **OK** |
| Pizarro | 10.1016/j.media.2023.102942 | Pizarro 2023, *Med Image Anal* | **OK** |
| FSL | 10.1016/j.neuroimage.2004.07.051 | Smith 2004, *NeuroImage* | **OK** |
| OpenNeuro | 10.7554/eLife.71774 | Markiewicz 2021, *eLife* | **OK** |
| NumPy | 10.1038/s41586-020-2649-2 | Harris 2020, *Nature* | **OK** |
| Matplotlib | 10.1109/MCSE.2007.55 | Hunter 2007, *CiSE* | **OK** |
| DICOM PS3.15 | NEMA Part 15 URL | Standards document (not a journal DOI) | **OK as standards cite** |

### Citation gaps / notes (not DOI failures)

1. **MRtrix3** (`dwigradcheck`, `dwi2mask`) is used in DWI QC but **not** listed in the References draft — add a software/standards entry (and optional Tournier et al. MRtrix3 paper if you cite methods literature).  
2. **nibabel** is listed as software-only — fine.  
3. **neuro_pipeline** has no peer-reviewed paper — correctly listed as software only.  
4. **pydeface** correctly listed as GitHub software (no separate journal DOI claimed).  
5. In-manuscript wording must keep DICOM de-id as **PS3.15-oriented subset**, not full Basic Profile certification (already noted in the draft).

### Citations verdict

**PASS** for all peer-reviewed DOIs in the draft (9/9 resolve and match author/year/journal).  
**OPTIONAL FIX:** add MRtrix3 to the software inventory / references for completeness.

---

## 3. Combined pre-publication status

| Gate | Verdict |
| --- | --- |
| BIDS validator errors | **FAIL (1)** — `MULTIPLE_README_FILES` |
| Citation DOIs | **PASS** |
| OpenNeuro packaging (defaced upload + CC0 + Authors) | **FAIL / incomplete** |
| Scientific Data privacy/defacing narrative | **READY** (with justified PS3.15 wording; defacing derivatives complete) |

### Recommended next actions for OpenNeuro

1. Keep **one** root readme (`README` *or* `README.md`, not both).  
2. Build a **public release tree** where `anat/*_T1w.nii.gz` (and FLAIR if shared) are the **defaced** volumes (from `derivatives/defacing`), not the face-intact research BIDS copies.  
3. Set `"License": "CC0"` (or OpenNeuro-required equivalent) and add a LICENSE file.  
4. Replace placeholder Authors with the real author list (and ideally `CITATION.cff`).  
5. Re-run bids-validator on that public tree before `openneuro upload --affirmDefaced`.

### Recommended next actions for Scientific Data citations

1. Keep the verified DOI list as-is.  
2. Add MRtrix3 to Methods/References software list.  
3. Ensure Methods cite Pizarro + MRIQC with the draft wording (screening ≠ exclusion).
