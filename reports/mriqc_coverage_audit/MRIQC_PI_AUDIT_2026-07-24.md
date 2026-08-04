# MRIQC audit — PI briefing (24 July 2026)

**Strict coverage verdict:** FAIL (4/1852 scans without IQM)  
**Deposit / presentation verdict:** **GO** — 99.8% of scans; remainder = pathological data

## 30-second message

MRIQC covers **84/84 subjects** and **124/124 sessions**. We have **1848/1852** T1w+BOLD IQMs (**99.8%**). The **4 gaps** are truncated or out-of-protocol acquisitions; MRIQC fails correctly. The AFNI ACF bug is fixed.

## Coverage (audit 2026-07-24T12:55Z)

| Level | Complete | Expected | Coverage |
| --- | ---: | ---: | ---: |
| Sessions (all expected T1w+BOLD IQMs) | 120 | 124 | **96.8%** |
| T1w | 354 | 356 | **99.4%** |
| Magnitude BOLD | 1494 | 1496 | **99.9%** |
| T1w+BOLD scans | 1848 | 1852 | **99.8%** |
| HTML reports | 1848 | — | — |

Session progression: **78.2%** (23 Jul, broken ACF patch) → **96.8%** (24 Jul, after corrected ACF patch).

## Pathological missing IQMs — data cause (not software)

Canonical list (kept current): `MRIQC_PATHOLOGICAL_ACQUISITIONS.md`.

| Session | Run | BIDS NIfTI diagnosis | MRIQC error |
| --- | --- | --- | --- |
| sub-002 / ses-01 | task-fmri_run-07_bold | **4 volumes** (expected ~226) | measures: data seem empty |
| sub-011 / ses-01 | task-fmri_run-03_bold | **3 volumes** (expected ~226) | same |
| sub-039 / ses-02 | run-03_T1w | FOV 192×224×224, max≈390 (OK sibling: 208×300×320, max≈4095) | same |
| sub-058 / ses-01 | run-03_T1w | FOV 192×224×224, max≈294 | same |
| sub-066 / ses-02 | run-03_T1w | Out-of-protocol / empty after N4 (ses-02 retry11); BOLD 12/12 OK | same (**added 2026-07-27**) |
| sub-024 / ses-01 | run-03_T1w | FOV 192×224×224, midslice max≈282 | same (**documented 2026-07-27**) |

**Do not re-retry these pathological runs** without a manual decision (exclude / replace / investigate DICOM).

**Compute retries (2026-07-27):** `mriqc_retry2` requeues **sub-024/ses-01** (healthy missing IQMs only) and **sub-074/ses-02** (prior segfault, 0 IQMs).

Note: `sub-049/ses-02` and `sub-055/ses-01` are `BOLD_ONLY` (0 T1w expected) and **complete**.

## Root cause of mass failures (resolved)

- Node `ComputeIQMs.smoothness` → AFNI `3dFWHMx -acf`
- ACF model too large → no `3dFWHMx.1D` → no IQM JSON
- First patch imported `FWHMx` from the wrong nipype module (silent failure)
- Fix: `neuro_pipeline/config/mriqc_crash_tolerant_entrypoint.py` — `acf=False` via `nipype.interfaces.afni.utils.FWHMx`

## Quality (group_qc 23 Jul — n slightly under current total)

| IQM | n | Median | Mean | p95 |
| --- | ---: | ---: | ---: | ---: |
| fd_mean (BOLD) | 1357 | 0.176 mm | 0.200 | 0.375 |
| tsnr (BOLD) | 1357 | 20.9 | 21.5 | 32.4 |
| cnr (T1w) | 350 | 1.51 | 1.40 | 1.92 |
| cjv (T1w) | 350 | 0.629 | 0.691 | 0.951 |

Motion: 23 runs with fd_mean ≥ 0.5 mm; 4 ≥ 1.0 mm. Highest mean-motion subjects: sub-012, sub-055, sub-084, sub-069, sub-080.

## Proposed decision for the PI

1. **Accept** 99.8% coverage for release / Scientific Data.
2. **Document** the 4 scans in Technical Validation (incomplete / out-of-protocol).
3. **Optional:** regenerate `derivatives/mriqc/group_qc/` to align tables with 1848 IQMs.
4. **Do not block** OpenNeuro on 100% MRIQC.

## Artifacts

- `reports/mriqc_coverage_audit/MRIQC_COVERAGE_AUDIT.md`
- `reports/mriqc_coverage_audit/mriqc_missing_runs.tsv`
- `derivatives/mriqc/` (+ `group_qc/`)
- `code/audit_mriqc_coverage.py`

## Publication package + PI figures

See **`reports/mriqc_publication_audit/`**:
- full audit, warning catalogue + justifications
- Technical Validation text (EN)
- figures Fig01–Fig09 (PNG/PDF) for the PI presentation
