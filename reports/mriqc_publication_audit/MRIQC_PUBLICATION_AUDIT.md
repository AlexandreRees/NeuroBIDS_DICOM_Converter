# MRIQC audit — publication documentation

**Generated:** 2026-07-24  
**Software:** MRIQC 24.0.2 (fault-tolerant wrapper, `neuro_pipeline`)  
**BIDS:** `/home/alexrees/scratch/bids` (84 subjects, 124 sessions)  
**Derivatives:** `/home/alexrees/scratch/derivatives/mriqc`

---

## 1. Executive verdict

| Criterion | Result | Interpretation |
| --- | --- | --- |
| Strict coverage (100% expected IQMs) | **FAIL** (4/1852) | 4 pathological acquisitions |
| T1w+BOLD scan coverage | **99.8%** (1848/1852) | Acceptable for deposit |
| Complete sessions | **96.8%** (120/124) | 4 sessions missing 1 run each |
| Cohort quality (fd / tSNR / CNR) | **Good** | See §4 |
| Block OpenNeuro / Scientific Data? | **No** | Document the 4 cases |

**Recommendation:** publish with transparent Technical Validation; do not wait for 100%.

---

## 2. Coverage (audit 2026-07-24T12:55Z)

| Level | Complete | Expected | % |
| --- | ---: | ---: | ---: |
| Sessions (all expected IQMs) | 120 | 124 | 96.8 |
| T1w | 354 | 356 | 99.4 |
| Magnitude BOLD | 1494 | 1496 | 99.9 |
| T1w+BOLD scans | 1848 | 1852 | **99.8** |
| HTML reports | 1848 | — | — |
| Subjects with ≥1 IQM | 84 | 84 | 100 |

### Pipeline progression

| Stage | Sessions | T1w | BOLD |
| --- | ---: | ---: | ---: |
| Post-retry without ACF patch (23 Jul) | 78.2% | 99.2% | 91.4% |
| After corrected ACF patch (24 Jul) | **96.8%** | **99.4%** | **99.9%** |

Root cause of mass failures (resolved): AFNI `3dFWHMx -acf` → ACF model too large → missing `3dFWHMx.1D` → no IQM JSON. Fix: `neuro_pipeline/config/mriqc_crash_tolerant_entrypoint.py` (`acf=False`, import `nipype.interfaces.afni.utils.FWHMx`).

Key jobs: `66078951` (array), `66277341` / `66310069` (retries), `66329461` (ACF patch), `66342993` (final ×4 retry).

---

## 3. Four scans without IQM (documented exclusions)

| Session | Acquisition | BIDS evidence | Class | Publication action |
| --- | --- | --- | --- | --- |
| sub-002 / ses-01 | task-fmri_run-07_bold | 4 volumes (expected ~226) | Truncated BOLD | List as incomplete acquisition |
| sub-011 / ses-01 | task-fmri_run-03_bold | 3 volumes (expected ~226) | Truncated BOLD | Same |
| sub-039 / ses-02 | run-03_T1w | FOV 192×224×224, max≈390 (sibling OK: 208×300×320, max≈4095) | Out-of-protocol T1w | List as abnormal anatomical series |
| sub-058 / ses-01 | run-03_T1w | FOV 192×224×224, max≈294 | Out-of-protocol T1w | Same |

Shared MRIQC error: `RuntimeError: Input inhomogeneity-corrected data seem empty` (`measures` node).  
Retry `66342993`: exit 0, **no recovery** — expected.

Complete `BOLD_ONLY` sessions (not failures): sub-049/ses-02, sub-055/ses-01 (0 T1w expected).

---

## 4. Cohort quality (IQMs)

Distributions from `group_qc` dated 2026-07-23 (**n=1707** scored acquisitions then; current coverage 1848). Statistics below remain representative.

### BOLD (n≈1357)

| IQM | Median | Mean | p95 | Quality reading |
| --- | ---: | ---: | ---: | --- |
| fd_mean (mm) | **0.176** | 0.200 | 0.375 | Globally low motion |
| tsnr | **20.9** | 21.5 | 32.4 | Compatible with multiband TR 937 ms |
| dvars | 64.6 | 65.6 | ~93 | High tail = motion subjects |
| snr | 1.40 | 1.46 | 2.08 | — |

- **61%** of runs: fd_mean < 0.2 mm  
- **23** runs: fd_mean ≥ 0.5 mm  
- **4** runs: fd_mean ≥ 1.0 mm  

### T1w (n≈350)

| IQM | Median | Mean | p95 | Reading |
| --- | ---: | ---: | ---: | --- |
| cnr | **1.51** | 1.40 | 1.92 | Good contrast |
| cjv | **0.629** | 0.691 | 0.951 | Lower is better |
| snr_total | **5.53** | 4.65 | ~7.3 | — |
| qi_1 | 0 | 0 | 0 | No wrap-around artifact flagged |

### By BOLD task (medians)

| Task | n | fd_mean | tsnr |
| --- | ---: | ---: | ---: |
| control | 362 | 0.147 | 28.2 |
| fmri | 445 | 0.183 | 20.1 |
| movie | 439 | 0.189 | 19.9 |
| rest | 111 | 0.197 | 18.4 |

*(control = 20 volumes → higher tSNR expected.)*

---

## 5. Warnings — summary

Full catalogue: [MRIQC_WARNINGS_AND_JUSTIFICATIONS.md](MRIQC_WARNINGS_AND_JUSTIFICATIONS.md).

| Class | N | Publication severity | Automatic exclusion? |
| --- | ---: | --- | --- |
| MISSING_IQM (data pathology) | 4 | **High — must document** | No (document) |
| HIGH_MOTION (fd ≥ 0.5 mm) | 23 runs | Medium — flags | Not a priori |
| IQM_OUTLIER (z/IQR) | 736 flags / 394 acq / 80 subjects | Low — exploratory | **No** |
| SMOOTHNESS/ACF historical | ~130 (resolved) | N/A (fixed) | N/A |

Most flagged subjects (outliers): sub-012 (102), sub-080 (34), sub-084 (32), sub-040 (25), sub-031 (24).  
sub-012 also dominates high motion — discuss with PI, **not** a forced deposit exclusion.

---

## 6. Figures for the PI (recommended order)

1. `Fig09_PI_onepager_quality_summary` — open  
2. `Fig01` + `Fig06` — coverage  
3. `Fig03` + `Fig04` — BOLD / T1w quality  
4. `Fig08` — why four are missing  
5. `Fig02` — what the ACF patch unlocked  
6. `Fig07` — motion transparency (if asked)

---

## 7. Manuscript text

English ready to paste: [Technical_Validation_MRIQC_EN.md](Technical_Validation_MRIQC_EN.md).

---

## 8. Reproducibility

```bash
# Coverage
python3 code/audit_mriqc_coverage.py

# Figures + warning tables
python3 code/mriqc_publication_audit/generate_mriqc_pi_figures.py
```

Optional: regenerate `derivatives/mriqc/group_qc/` to align with n=1848 before final deposit.
