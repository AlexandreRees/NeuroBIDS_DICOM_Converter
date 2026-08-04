# MRIQC audit — 11 previously missing ses-02 sessions

**Date:** 2026-07-24  
**Scope:** the 11 AUTO_CONFIRMED `ses-02` visits that were absent from BIDS (DataON 1, DataTON 1, Glaucoma 9).

## Verdict (updated 2026-07-27)

| Stage | Status |
|---|---|
| BIDS conversion | **11/11 present** |
| MRIQC job `66379863` | **10/11 COMPLETED**, **1 FAILED** (task 9 = sub-074) |
| Sessions with full T1w+BOLD IQMs | **9/11** |
| Gaps | **sub-066** `run-03_T1w` (pathological — accepted); **sub-074** entire session (segfault — **requeued**) |

See also: `MRIQC_PATHOLOGICAL_ACQUISITIONS.md` · retry script `run_mriqc_retry_partial_and_074.slurm`.

## Conversion status

| BIDS | Canonical | Marker | n_nii (BIDS) | T1w | mag BOLD |
|---|---|---|---:|---:|---:|
| sub-057/ses-02 | SUBON01 | SUCCESS_PARTIAL | 66 | 3 | 12 |
| sub-064/ses-02 | SUBTON01 | SUCCESS_PARTIAL | 65 | 2 | 12 |
| sub-066/ses-02 | SUBG01 | SUCCESS_PARTIAL | 66 | 3 | 12 |
| sub-067/ses-02 | SUBG02 | SUCCESS_PARTIAL | 66 | 3 | 12 |
| sub-068/ses-02 | SUBG03 | SUCCESS_PARTIAL | 66 | 3 | 12 |
| sub-069/ses-02 | SUBG04 | SUCCESS_PARTIAL | 66 | 3 | 12 |
| sub-072/ses-02 | SUBG07 | SUCCESS_PARTIAL | 66 | 3 | 12 |
| sub-073/ses-02 | SUBG08 | SUCCESS_PARTIAL | 66 | 3 | 12 |
| sub-074/ses-02 | SUBG09 | SUCCESS_PARTIAL | 62 | 3 | 11 |
| sub-078/ses-02 | SUBG13 | SUCCESS | 27 | 0 | 6 |
| sub-081/ses-02 | SUBG16 | *(no marker file; data on disk)* | 33 | 3 | 9–10 |

Notes:
- `SUCCESS_PARTIAL` = usable NIfTI count ≥20 despite non-zero conversion exit (typical DWI `.bval` failures), same pattern as Control ses-02.
- sub-078 is BOLD-heavy / incomplete anat (0 T1w expected in this visit).
- Markers under `logs/ses02_retry11/`.

## MRIQC coverage (these 11 only)

| Metric | Expected | Have | Coverage |
|---|---:|---:|---:|
| Sessions with any IQM | 11 | **0** | **0%** |
| T1w IQMs | ~29 | **0** | **0%** |
| Magnitude BOLD IQMs | ~123 | **0** | **0%** |
| Combined T1w+BOLD IQMs | ~152 | **0** | **0%** |

Per session: all `MRIQC_NONE` (0 JSON / 0 HTML under `derivatives/mriqc/` for `*_ses-02_*`).

## Why MRIQC is at 0%

1. These sessions were **not in BIDS** when the main MRIQC arrays were built.
2. `metadata/mriqc_array_tasks.tsv` still only lists **`session_id=01`** for these participants.
3. No new MRIQC Slurm array was submitted for the retry-11 sessions after conversion.

This is a **scheduling gap**, not an MRIQC software failure.

## Impact on global MRIQC headline (context)

Previous deposit narrative (pre-retry): **1848/1852 (99.8%)** on the then-124-session tree.  
After adding ~152 expected T1w+BOLD scans with 0 IQMs, global coverage will drop until these sessions are processed (order-of-magnitude: ~1848 / (1852+152) ≈ **92%** if nothing else changes — exact denominator depends on how “expected” is redefined for incomplete visits like sub-078).

## Recommended next step

1. Append the 11 sessions to an MRIQC task list (same schema as `mriqc_array_tasks.tsv`: `participant_label`, `session_id=02`, `n_t1w`, `n_bold_mag`).
2. Submit a dedicated array (reuse existing MRIQC Slurm wrapper / crash-tolerant entrypoint).
3. Re-run `code/audit_mriqc_coverage.py` and refresh PI figures.

## Deliverable

- `reports/mriqc_coverage_audit/mriqc_ses02_retry11_audit.tsv`
