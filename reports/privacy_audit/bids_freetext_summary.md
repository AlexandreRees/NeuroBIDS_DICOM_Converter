# BIDS free-text metadata PHI audit

**Generated (UTC):** 2026-07-22T16:58:35.501835+00:00
**BIDS root:** `/lustre07/scratch/alexrees/bids`
**JSON sidecars parsed:** 7958
**JSON parse errors:** 0

Read-only audit. No files under `bids/` were modified.

## Field classification

| Field | Classification | Unique values | Suspicious |
| --- | --- | ---: | ---: |
| `SeriesDescription` | **REVIEW_REQUIRED** | 65 | 3 |
| `ProtocolName` | **REVIEW_REQUIRED** | 29 | 2 |
| `SequenceName` | **SAFE_TO_KEEP** | 8 | 0 |
| `PulseSequenceDetails` | **SAFE_TO_KEEP** | 7 | 0 |
| `ScanningSequence` | **SAFE_TO_KEEP** | 5 | 0 |
| `InstitutionalDepartmentName` | **REVIEW_REQUIRED** | 2 | 1 |
| `Manufacturer` | **SAFE_TO_KEEP** | 1 | 0 |
| `ManufacturersModelName` | **SAFE_TO_KEEP** | 2 | 0 |

## Unique value inventory (SeriesDescription / ProtocolName / SequenceName)

### `SeriesDescription`

| Value | Count | Flag | Reason |
| --- | ---: | --- | --- |
| `SpinEchoFieldMap_AP` | 481 | False | — |
| `SpinEchoFieldMap_PA` | 481 | False | — |
| `fMRI1_AP` | 257 | False | — |
| `fMRI1_AP_SBRef` | 256 | False | — |
| `Movie1_AP` | 248 | False | — |
| `fMRI4_AP` | 247 | False | — |
| `fMRI3_AP` | 246 | False | — |
| `REST1_AP` | 245 | False | — |
| `Control1_PA` | 244 | False | — |
| `Movie1_AP_SBRef` | 244 | False | — |
| `fMRI4_AP_SBRef` | 244 | False | — |
| `Movie3_AP` | 243 | False | — |
| `Movie2_AP` | 242 | False | — |
| `fMRI2_AP` | 242 | False | — |
| `fMRI3_AP_SBRef` | 242 | False | — |
| `Control1_PA_SBRef` | 240 | False | — |
| `Movie3_AP_SBRef` | 240 | False | — |
| `REST1_AP_SBRef` | 240 | False | — |
| `T1w_MPR` | 240 | False | — |
| `gsld_76dir_b2000_1mmiso_AP` | 240 | False | — |
| `Movie2_AP_SBRef` | 238 | False | — |
| `Movie4_AP` | 238 | False | — |
| `tfl_b1map_1mmiso` | 238 | False | — |
| `fMRI2_AP_SBRef` | 236 | False | — |
| `Movie4_AP_SBRef` | 234 | False | — |
| `Control2_AP` | 225 | False | — |
| `Control3_PA` | 221 | False | — |
| `Control2_AP_SBRef` | 220 | False | — |
| `Control3_PA_SBRef` | 216 | False | — |
| `resolve_3scan_trace_tra_p3_160_1.4iso_AP` | 121 | False | — |
| `Sag Flair 3D-0.8` | 119 | True | name_like_tokens |
| `WMn_MPRAGE_sagittal` | 111 | False | — |
| `Control3_AP` | 18 | False | — |
| `Control3_AP_SBRef` | 18 | False | — |
| `Control2_PA` | 14 | False | — |
| `Control2_PA_SBRef` | 14 | False | — |
| `tfl_b1map_1mmiso_ND` | 10 | False | — |
| `SpinEchoFieldMap_AP_Pha` | 9 | False | — |
| `SpinEchoFieldMap_PA_Pha` | 9 | False | — |
| `Control2_AP_Pha` | 5 | False | — |
| `Control3_PA_Pha` | 5 | False | — |
| `REST1_AP_Pha` | 5 | False | — |
| `Sag Flair 3D-0.8_ND` | 5 | True | name_like_tokens |
| `T1w_MPR_ND` | 5 | False | — |
| `fMRI1_AP_Pha` | 5 | False | — |
| `Control1_PA_Pha` | 4 | False | — |
| `Movie1_AP_Pha` | 4 | False | — |
| `Movie2_AP_Pha` | 4 | False | — |
| `Movie3_AP_Pha` | 4 | False | — |
| `Movie4_AP_Pha` | 4 | False | — |
| `fMRI2_AP_Pha` | 4 | False | — |
| `fMRI3_AP_Pha` | 4 | False | — |
| `fMRI4_AP_Pha` | 4 | False | — |
| `Control2_AP_redo` | 2 | False | — |
| `Control2_AP_redo_SBRef` | 2 | False | — |
| `Movie4_AP_redo_cuz_gogle_moved` | 2 | False | — |
| `Movie4_AP_redo_cuz_gogle_moved_SBRef` | 2 | False | — |
| `SpinEchoFieldMap_AP_rerun` | 2 | False | — |
| `fMRI1_AP_REDO` | 2 | False | — |
| `fMRI1_AP_REDO_SBRef` | 2 | False | — |
| `fMRI1_AP_Rerun` | 2 | False | — |
| `fMRI1_AP_Rerun_SBRef` | 2 | False | — |
| `fMRI2_AP_Rerun` | 2 | False | — |
| `fMRI2_AP_Rerun_SBRef` | 2 | False | — |
| `Sag Flair 3D-0.8_usethisone` | 1 | True | name_like_tokens |

### `ProtocolName`

| Value | Count | Flag | Reason |
| --- | ---: | --- | --- |
| `fMRI1_AP` | 518 | False | — |
| `Movie1_AP` | 496 | False | — |
| `fMRI4_AP` | 495 | False | — |
| `fMRI3_AP` | 492 | False | — |
| `REST1_AP` | 490 | False | — |
| `SpinEchoFieldMap_AP` | 490 | False | — |
| `SpinEchoFieldMap_PA` | 490 | False | — |
| `Control1_PA` | 488 | False | — |
| `Movie3_AP` | 487 | False | — |
| `Movie2_AP` | 484 | False | — |
| `fMRI2_AP` | 482 | False | — |
| `Movie4_AP` | 476 | False | — |
| `Control2_AP` | 450 | False | — |
| `Control3_PA` | 442 | False | — |
| `tfl_b1map_1mmiso` | 248 | False | — |
| `T1w_MPR` | 245 | False | — |
| `gsld_76dir_b2000_1mmiso_AP` | 240 | False | — |
| `Sag Flair 3D-0.8` | 124 | True | name_like_tokens |
| `resolve_3scan_trace_tra_p3_160_1.4iso_AP` | 121 | False | — |
| `WMn_MPRAGE_sagittal` | 111 | False | — |
| `Control3_AP` | 36 | False | — |
| `Control2_PA` | 28 | False | — |
| `Control2_AP_redo` | 4 | False | — |
| `Movie4_AP_redo_cuz_gogle_moved` | 4 | False | — |
| `fMRI1_AP_REDO` | 4 | False | — |
| `fMRI1_AP_Rerun` | 4 | False | — |
| `fMRI2_AP_Rerun` | 4 | False | — |
| `SpinEchoFieldMap_AP_rerun` | 2 | False | — |
| `Sag Flair 3D-0.8_usethisone` | 1 | True | name_like_tokens |

### `SequenceName`

| Value | Count | Flag | Reason |
| --- | ---: | --- | --- |
| `epfid2d1_104` | 5780 | False | — |
| `epse2d1_104` | 946 | False | — |
| `*tfl3d1_16ns` | 235 | False | — |
| `gs_b0` | 235 | False | — |
| `tfl2d1_512` | 228 | False | — |
| `*re_b0` | 115 | False | — |
| `*spcir_288ns` | 115 | False | — |
| `*tfl3d1_200` | 109 | False | — |

## Interpretation

- **SAFE_TO_KEEP** — protocol/vendor-like strings; no automated PHI cues.
- **REVIEW_REQUIRED** — ≥1 value matched conservative heuristics.
- **REMOVE_BEFORE_RELEASE** — large fraction of unique values look identifying.

Heuristics can false-positive on technical strings. Absence of flags does **not** prove absence of PHI.
