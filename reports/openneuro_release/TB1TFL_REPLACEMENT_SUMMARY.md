# TB1TFL defaced replacement into release_dataset

**Updated (UTC):** 2026-07-27T17:13:17Z

| Metric | Value |
|---|---:|
| Release TB1TFL | **270** |
| Replaced with defaced | **270** |
| Still face-intact in release | **0** |

Audit: `TB1TFL_REPLACEMENT_AUDIT.tsv`  
Recovery of the last 3: `TB1TFL_THREE_RECOVERY.json` · `TB1TFL_THREE_FAILURE_AUDIT.md`

## Verification

- All **270** release TB1TFL NIfTI match `derivatives/defacing`.
- **0** still match face-intact `bids/`.

## Recovery of the 3 quota failures (2026-07-27)

Env fix: patched scratch `defacing_env` pydeface `get_data()` → `get_fdata()`; used working `/home/alexrees/defacing_env` (already patched) + FSL.

| File | Runtime | Status |
|---|---:|---|
| `sub-027_ses-02_run-02_TB1TFL` | 328 s | PASS → release |
| `sub-028_ses-02_run-01_TB1TFL` | 257 s | PASS → release |
| `sub-031_ses-01_run-01_TB1TFL` | 214 s | PASS → release |

Also restored missing `sub-027_ses-02_run-01_TB1TFL.json` into derivatives.

## Safety

- `bids/` was not modified.
