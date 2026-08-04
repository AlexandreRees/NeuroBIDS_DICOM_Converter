# ses-02 retry11 — pre-QC gate

**Generated (UTC):** 2026-07-24T17:25:12Z
**Targets:** 11
**PASS / BLOCK / FAIL:** 11 / 0 / 0
**Overall gate:** PASS

| Subject | n_nii | T1w | BOLD | DWI | marker | conv | bids | phi | gate | notes |
|---|---:|---:|---:|---:|---|:---:|:---:|:---:|---|---|
| sub-057 | 66 | 3 | 12 | 4 | `SUBON01_ses-02.SUCCESS_PARTIAL` | Y | Y | Y | PASS |  |
| sub-064 | 65 | 2 | 12 | 4 | `SUBTON01_ses-02.SUCCESS_PARTIAL` | Y | Y | Y | PASS |  |
| sub-066 | 66 | 3 | 12 | 4 | `SUBG01_ses-02.SUCCESS_PARTIAL` | Y | Y | Y | PASS |  |
| sub-067 | 66 | 3 | 12 | 4 | `SUBG02_ses-02.SUCCESS_PARTIAL` | Y | Y | Y | PASS |  |
| sub-068 | 66 | 3 | 12 | 4 | `SUBG03_ses-02.SUCCESS_PARTIAL` | Y | Y | Y | PASS |  |
| sub-069 | 66 | 3 | 12 | 4 | `SUBG04_ses-02.SUCCESS_PARTIAL` | Y | Y | Y | PASS |  |
| sub-072 | 66 | 3 | 12 | 4 | `SUBG07_ses-02.SUCCESS_PARTIAL` | Y | Y | Y | PASS |  |
| sub-073 | 66 | 3 | 12 | 4 | `SUBG08_ses-02.SUCCESS_PARTIAL` | Y | Y | Y | PASS |  |
| sub-074 | 62 | 3 | 11 | 4 | `SUBG09_ses-02.SUCCESS_PARTIAL` | Y | Y | Y | PASS |  |
| sub-078 | 27 | 0 | 6 | 0 | `SUBG13_ses-02.SUCCESS` | Y | Y | Y | PASS |  |
| sub-081 | 43 | 3 | 12 | 2 | `SUBG16_ses-02.SUCCESS_PARTIAL` | Y | Y | Y | PASS |  |

## Criteria

- Conversion: ≥20 NIfTI + BOLD (or documented sparse sub-078), or SUCCESS marker.
- BIDS: every imaging NIfTI has a JSON sidecar; filenames match `sub-*_ses-*_*.nii.gz`.
- PHI / admin: no InstitutionName / InstitutionalDepartmentName / StationName / DeviceSerialNumber / Patient* keys; JSON must parse.

