# Key methodological strengths

These points are drawn from the technical de-identification report and are framed for a Scientific Data audience.

## 1. Immutable raw data preservation

**Why this matters scientifically.**  
Neuroimaging claims depend on the ability to audit the primary acquisition. Keeping scanner exports untouched separates archival truth from any later confidentiality transforms.

**Why it increases dataset value.**  
Reusers, auditors, and future reprocessing pipelines can return to an unaltered DICOM archive if conversion conventions evolve or if a privacy policy needs re-checking.

**How it should be presented in the manuscript.**  
State explicitly that original acquisitions were never overwritten and that de-identification operated on derived copies. Pair with **Figure 1** and **Figure 4**.

---

## 2. Non-destructive de-identification

**Why this matters scientifically.**  
Confidentiality controls that destroy the only copy of the data undermine reproducibility. Non-destructive transforms create a controlled research-facing derivative while preserving the source.

**Why it increases dataset value.**  
The dataset can support both privacy-constrained sharing and long-term stewardship without forcing a one-way irreversible edit of the archive.

**How it should be presented in the manuscript.**  
Describe a two-tier storage model: immutable raw repository versus de-identified DICOM used for conversion. Emphasize that inventory itself was read-only.

---

## 3. Metadata preservation for imaging science

**Why this matters scientifically.**  
fMRI, diffusion, and fieldmap analyses require geometric and sequence parameters (for example repetition time, echo time, flip angle, voxel geometry) and series descriptors that label paradigm and polarity.

**Why it increases dataset value.**  
Users can reconstruct acquisition methods and run standards-compatible conversion without reconstructing missing physics from secondary notes alone.

**How it should be presented in the manuscript.**  
Contrast cleared identifier fields with retained acquisition metadata and unchanged pixel data. Point to **Figure 2** and the supplementary tag table. Note residual uncertainty where private vendor tags were removed ([Information not available in repository] for quantitative sidecar impact).

---

## 4. Reproducibility of the confidentiality process

**Why this matters scientifically.**  
De-identification that cannot be described at the level of actions (clear, pseudonymize, shift, remap) is not scientifically accountable.

**Why it increases dataset value.**  
A fixed tag policy, deterministic UID remapping within a participant, and per-participant date offsets allow the same confidentiality rules to be reapplied and audited.

**How it should be presented in the manuscript.**  
Summarize the transformation categories and validation philosophy without software vernacular. Use **Figure 2** and **Figure 3**. Keep date-offset tables private while stating that offsets preserve relative longitudinal intervals.

---

## 5. Alignment with DICOM confidentiality practice

**Why this matters scientifically.**  
Community trust increases when methods map onto recognized DICOM confidentiality concepts rather than ad hoc deletions.

**Why it increases dataset value.**  
Reviewers and data repositories can evaluate the procedure against a known standard framework (PS3.15 Basic Application Level Confidentiality Profile orientation).

**How it should be presented in the manuscript.**  
Claim orientation toward the Basic Profile, not certified full-profile compliance. Cite DICOM PS3.15 in the reference list. Disclose that the implemented policy is a documented custom subset (cleared PHI list, private-tag removal, date shift, UID remap).

---

## 6. Compatibility with neuroimaging standards (BIDS)

**Why this matters scientifically.**  
BIDS organization depends on retained series descriptors and valid convertible DICOM geometry; privacy transforms that erase those fields reduce reuse.

**Why it increases dataset value.**  
De-identified DICOM can feed reproducible DICOM-to-NIfTI conversion into a BIDS layout used by mainstream analysis tools.

**How it should be presented in the manuscript.**  
State that conversion proceeds from the de-identified DICOM repository after privacy validation, and that series descriptions and core acquisition parameters were retained to support BIDS entity assignment (**Figure 1**).

---

## 7. Longitudinal data integrity

**Why this matters scientifically.**  
Many scientific questions in this cohort depend on within-participant visit structure. Absolute calendar dates create re-identification risk; destroying relative timing destroys science.

**Why it increases dataset value.**  
Participant-specific date shifting removes absolute dates while preserving intervals between sessions for the same individual.

**How it should be presented in the manuscript.**  
Explain date shifting as a confidentiality measure that retains longitudinal intervals. Illustrate with the synthetic before/after example (**Figure 3**). Do not publish the offset table.

---

## 8. Provenance and integrity controls

**Why this matters scientifically.**  
A Methods claim that “raw data were unchanged” is stronger when accompanied by an integrity check linking source snapshots to conversion readiness.

**Why it increases dataset value.**  
Provenance records (mapping tables, de-identification reports, integrity snapshots) support audit, correction, and transparent limitation statements.

**How it should be presented in the manuscript.**  
Describe private provenance artefacts retained by the study team and privacy validation before conversion (**Figure 4**). Avoid listing internal filenames in the main text.
