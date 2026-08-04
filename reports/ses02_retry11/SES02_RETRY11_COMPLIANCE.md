# ses-02 retry11 — BIDS compliance

**Generated (UTC):** 2026-07-24T17:25:11Z
**Targets:** 11
**PASS / PARTIAL / FAIL:** 11 / 0 / 0
**BIDS sessions on disk (all subjects):** 135

## Per-session

| Subject | Session | n_nii | anat | func | fmap | dwi | missing JSON | scrubbed | status |
|---|---|---:|:---:|:---:|:---:|:---:|---:|---:|---|
| sub-057 | ses-02 | 66 | Y | Y | Y | Y | 0 | 0 | PASS |
| sub-064 | ses-02 | 65 | Y | Y | Y | Y | 0 | 0 | PASS |
| sub-066 | ses-02 | 66 | Y | Y | Y | Y | 0 | 0 | PASS |
| sub-067 | ses-02 | 66 | Y | Y | Y | Y | 0 | 0 | PASS |
| sub-068 | ses-02 | 66 | Y | Y | Y | Y | 0 | 0 | PASS |
| sub-069 | ses-02 | 66 | Y | Y | Y | Y | 0 | 0 | PASS |
| sub-072 | ses-02 | 66 | Y | Y | Y | Y | 0 | 0 | PASS |
| sub-073 | ses-02 | 66 | Y | Y | Y | Y | 0 | 0 | PASS |
| sub-074 | ses-02 | 62 | Y | Y | Y | Y | 0 | 0 | PASS |
| sub-078 | ses-02 | 27 | N | Y | Y | N | 0 | 0 | PASS |
| sub-081 | ses-02 | 43 | Y | Y | Y | Y | 0 | 0 | PASS |

## Conversion markers

- `SUBG01_ses-02.SUCCESS_PARTIAL`
- `SUBG02_ses-02.SUCCESS_PARTIAL`
- `SUBG03_ses-02.SUCCESS_PARTIAL`
- `SUBG04_ses-02.SUCCESS_PARTIAL`
- `SUBG07_ses-02.SUCCESS_PARTIAL`
- `SUBG08_ses-02.SUCCESS_PARTIAL`
- `SUBG09_ses-02.SUCCESS_PARTIAL`
- `SUBG13_ses-02.SUCCESS`
- `SUBG16_ses-02.SUCCESS_PARTIAL`
- `SUBON01_ses-02.SUCCESS_PARTIAL`
- `SUBTON01_ses-02.SUCCESS_PARTIAL`

## Notes

- Metadata scrub applies the same REMOVE_FIELDS policy as `code/clean_bids_metadata.py`.
- Defacing of new anatomicals and MRIQC are **not** included here; run separately before release rebuild.
- Events recovery for new `task-fmri` runs can be re-run via phase-2 events script after conversion.

