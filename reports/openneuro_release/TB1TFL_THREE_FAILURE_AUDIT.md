# Audit: 3 TB1TFL missing from defacing derivatives

**Date:** 2026-07-27  
**Files:**
- `sub-027/ses-02/anat/sub-027_ses-02_run-02_TB1TFL.nii.gz`
- `sub-028/ses-02/anat/sub-028_ses-02_run-01_TB1TFL.nii.gz`
- `sub-031/ses-01/anat/sub-031_ses-01_run-01_TB1TFL.nii.gz`

## Verdict

**These volumes are not “undefaceable”.**  
pydeface selected them (head FOV OK), ran for ~3–4 minutes, and **failed only when writing the output** because the scratch **disk quota was exceeded** (`OSError: [Errno 122]`). Sibling TB1TFL in the same sessions succeeded.

Cohort-wide TB1TFL in execution metas: **PASS=264, FAIL=2, SKIP=2** (the only logged FAILs are sub-028 and sub-031; sub-027 ses-02 crashed before writing its report).

---

## Per-file root cause

### 1. `sub-028_ses-02_run-01_TB1TFL` — Disk quota on write

- Report: `reports/defacing/sub-028_ses-02/defacing_execution_meta.json` (2026-07-22)
- Status: **FAIL** after **234.1 s**
- Include reason: `head FOV visible shape=(64,64,15) fov_mm=[220,220,150]`
- Error (abbreviated):

```text
File ".../pydeface/utils.py", line 126, in deface_image
    masked_brain.to_filename(outfile)
OSError: [Errno 122] Disk quota exceeded:
  .../derivatives/defacing/sub-028/ses-02/anat/sub-028_ses-02_run-01_TB1TFL.nii.gz
```

- Sibling `run-02` (FLIP ANGLE MAP): **PASS** in 266 s → algorithm OK on this session.

### 2. `sub-031_ses-01_run-01_TB1TFL` — Same quota error

- Report: `reports/defacing/sub-031_ses-01/defacing_execution_meta.json` (2026-07-22)
- Status: **FAIL** after **202.5 s**
- Same traceback: quota exceeded on `to_filename` of the defaced NIfTI
- Sibling `run-02`: **PASS** in 424 s

### 3. `sub-027_ses-02_run-02_TB1TFL` — Job aborted mid-session (quota)

- Slurm: `logs/defacing_array_66208682_49.err` (task 49, 2026-07-22)
- Progress before crash:
  - T1w run-01/02/03: PASS
  - FLAIR: PASS
  - TB1TFL run-01: started → then

```text
ERROR defacing.session: [Errno 122] Disk quota exceeded:
  .../derivatives/defacing/sub-027/ses-02/anat/sub-027_ses-02_run-01_TB1TFL.json
```

- Job died **before** reaching `run-02` and **before** writing `defacing_execution.tsv` / meta → empty `reports/defacing/sub-027_ses-02/`
- Note: `run-01` NIfTI later exists in derivatives (sidecar copy failed); `run-02` never produced

---

## Not the cause (ruled out)

| Hypothesis | Evidence |
|---|---|
| Bad FOV / not face-visible | All three selected with same head FOV heuristic as successful TB1TFL |
| Image type (M vs FLIP ANGLE MAP) | Both types PASS elsewhere; FAILs include both types |
| Geometry / empty / NaN | Normal 64×64×15 int16 volumes; siblings nearly identical shape/zooms |
| pydeface registration hard-fail | Runtime 200–234 s then fail at **write**, not at FLIRT |

Contrast note (not causal for FAIL): TB1TFL pairs are typically **run-01 = magnitude (`ImageType` M, FA≈8°)** and **run-02 = flip-angle map (`FLIP ANGLE MAP`, FA≈80°)**. Failures hit one of each; siblings of the other type succeeded.

---

## Why retry on 2026-07-27 also failed

Current `defacing_env` on the login path hits a **separate** software break:

```text
nibabel.deprecator.ExpiredDeprecationError: get_data() is deprecated...
```

pydeface still calls `get_data()`; nibabel ≥5 raises. That blocked re-defacing today even though quota may no longer be the issue.

---

## What this means for the release

- **267/270** TB1TFL in `release_dataset` are defaced replacements.
- These **3** were removed from release rather than left face-intact.
- They **can** be recovered by re-running pydeface in a fixed env (nibabel&lt;5 or patched pydeface) once scratch quota is OK, then copying into `release_dataset`.
