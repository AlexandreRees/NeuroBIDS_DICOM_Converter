# MRI acquisition table audit

**Date:** 2026-07-23
**Existing table:** `reports/mri_acquisition_table/MRI_Acquisition_Table.md`
**BIDS root:** `/home/alexrees/scratch/bids` (read-only)
**Sidecars inspected:** 7956 JSON files under `anat/`, `func/`, `dwi/`, `fmap/`
**Revised table:** `reports/mri_acquisition_table_revised.tsv`

## Scanner-level metadata (BIDS consensus)

- Manufacturer: **Siemens**
- Model: **Prisma**
- Field strength: **3 T**
- Software versions present: `syngo MR E11` (n=7763), `syngo MR XA30` (n=193)
- Receive coil: **HeadNeck_64**
- ReceiveCoilActiveElements (top): `HC2,4,6,7;NC2` (n=5338), `HC1-7;NC1,2` (n=1754), `HC1-6` (n=313)

## Sidecar field coverage

| Field | Present | Coverage |
|---|---:|---:|
| `Manufacturer` | 7956 | 100.0% |
| `ManufacturersModelName` | 7956 | 100.0% |
| `MagneticFieldStrength` | 7956 | 100.0% |
| `SoftwareVersions` | 7956 | 100.0% |
| `ReceiveCoilName` | 7763 | 97.6% |
| `ReceiveCoilActiveElements` | 7763 | 97.6% |
| `RepetitionTime` | 7956 | 100.0% |
| `EchoTime` | 7956 | 100.0% |
| `FlipAngle` | 7956 | 100.0% |
| `SliceThickness` | 7956 | 100.0% |
| `PhaseEncodingDirection` | 7455 | 93.7% |
| `MultibandAccelerationFactor` | 3123 | 39.3% |
| `ParallelReductionFactorInPlane` | 842 | 10.6% |
| `TotalReadoutTime` | 7112 | 89.4% |
| `SeriesDescription` | 7956 | 100.0% |
| `SequenceName` | 7763 | 97.6% |
| `ProtocolName` | 7956 | 100.0% |

## A) Missing information (vs Scientific Data MRI acquisition needs)

Parameters expected for a reproducible MRI Methods/acquisition table but **absent or incomplete** in the existing curated table:

1. **MultibandAccelerationFactor** for BOLD (BIDS mode = 8) — not listed in the table body.
2. **ParallelReductionFactorInPlane / iPAT** when present (anat/DWI/RESOLVE).
3. **TotalReadoutTime** and **EffectiveEchoSpacing** for EPI (func/fmap/dwi) — needed for distortion correction reproducibility.
4. **Receive coil name / active elements** — mentioned in Methods prose elsewhere, not in the acquisition table.
5. **SoftwareVersions diversity** — table states only `syngo MR E11`; BIDS also contains `syngo MR XA30`.
6. **BIDS labels** (`T1w`, `FLAIR`, `task-*_bold`, `dir-*_epi`, `dwi`) — table uses free-text only.
7. **Diffusion scheme diversity** — table implies a single `76 dir / b=2000` protocol; BIDS `.bval` schemes include multiple unique-b-value sets (see below).
8. **RESOLVE geometry** — table mentions RESOLVE but omits TR/TE/FA/resolution (BIDS: TR≈4140 ms, TE≈51 ms, FA≈180°, ~1.4 mm).
9. **Reverse-PE b0** — existing table claims PA reverse-PE b0 (3 volumes), but **no such series appears in released BIDS `dwi/`** (only `gsld_76dir_*` and RESOLVE). Treat as protocol history / conversion gap, not a released acquisition.
10. **SBRef** — explicitly omitted by table note; for Scientific Data, a one-line note that SBRef exists and matches BOLD geometry is preferable to silence.
11. **Physiological monitoring** — omitted from table (Methods correctly notes PhysioLog not released as BIDS physio); table should either omit with explicit cross-ref or state “acquired but not distributed”.
12. **PhaseEncodingDirection** coded as BIDS `j`/`j-` (not only “AP/PA” prose) for fmap/func/dwi.
13. **Number of volumes** verified from NIfTI for each functional task (table values appear protocol-derived; confirm against BIDS).

### Diffusion b-value schemes observed in BIDS

| Unique b-values | Sidecar-linked scans (sampled groups) |
|---|---:|
| `0,1000,2000` | 240 |
| `0,1000` | 121 |

### Functional volume counts (NIfTI sample per task group)

| task | sampled volumes |
|---|---:|
| `control` | 20 |
| `fmri` | 226 |
| `movie` | 210 |
| `rest` | 320 |

## B) Incorrect / inconsistent information

**Unit note:** BIDS JSON stores `RepetitionTime` / `EchoTime` in **seconds**. The existing manuscript table correctly uses **milliseconds**. After unit conversion, core TR/TE/FA values match.

| Claim / check | Status | BIDS evidence (converted) |
|---|---|---|
| T1 TR 2500 ms | **match** | sidecar mode 2.5 s → 2500 ms |
| T1 TE 2.22 ms | **match** | sidecar mode 0.0022 s → 2.2 ms |
| T1 FA 8° | **match** | 8 |
| WMn TR/TE/FA | **match** | 4 s / 0.0038 s / 7° |
| FLAIR TR/TE/FA | **match** | 6 s / 0.357 s / 120° |
| BOLD TR/TE/FA | **match** | 0.937 s / 0.037 s / 52° |
| BOLD MB factor | **missing from table** (present in BIDS) | MB=8 |
| FMAP TR/TE/FA | **match** | 9.71 s / 0.066 s / 90° |
| SoftwareVersions = E11 only | **mismatch** | E11 n=7763; **XA30 n=193** also present |
| Model name | **minor** | mostly `Prisma`; XA30 subset uses `MAGNETOM Prisma` |
| Coil on XA30 | **gap** | `ReceiveCoilName` missing on 193 XA30 sidecars |
| DWI “76 directions; b=2000” | **mismatch / oversimplified** | Dominant shell is **b=0,1000,2000** with **~365 diffusion directions** (n=228); also RESOLVE **b=0,1000** (n=121). The historical “76-dir” protocol name does not describe the modal released scheme. |
| DWI 1 mm isotropic | **needs careful wording** | Protocol name implies 1 mm iso; sampled NIfTI zooms can read as `1×1×5 mm` because of SMS/slice-stack encoding — report **protocol resolution** and point readers to NIfTI headers |
| Functional volume counts | **match** | rest 320; movie 210; fmri 226; control 20 |
| Control PE AP/PA | **partially supported** | BIDS `PhaseEncodingDirection` includes both `j` and `j-` across control runs |
| Reverse-PE b0 (PA; 3 volumes) | **not in BIDS** | No `gsld_75TE_PA_3b0` (or other b0-only reverse-PE) sidecars among 361 `dwi/*.json` |

### Notable consistency findings

- After converting BIDS seconds→milliseconds, anatomical, BOLD, and field-map TR/TE/FA in the existing table **match** dominant sidecar modes.
- The table **under-reports** multiband acceleration (MB=8) and scanner software heterogeneity (E11 + XA30).
- The table **over-simplifies** diffusion (76-dir / b=2000 only) relative to released `.bval` schemes and RESOLVE runs.
- Reverse-PE b0 is listed in the curated table but **absent from released BIDS**; do not include as a data row unless conversion is completed. Distortion correction for DWI may rely on SE field maps (`fmap`) instead.

## C) Redundant information

Safe to keep out of the main manuscript table (put in prose or omit):

1. Localizers / scout scans.
2. Derived vendor maps (RESOLVE ADC/FA/ColFA/TENSOR) if not released as primary BIDS imaging.
3. Duplicate magnitude/phase pairs beyond noting `part-phase` exists for fmap when relevant.
4. Per-run identifiers, SeriesInstanceUID, AcquisitionDate.
5. Institutional site address / station names (already de-identified).
6. Full PixelBandwidth / ReconMatrixPE matrices — useful in supplements, not the main table.
7. Listing every SBRef as its own row (one footnote is enough).
8. PhysioLog series names when physiology is not distributed.
9. Per-row `SoftwareVersions` / `SequenceName` — keep once in prose; ExactEchoSpacing matrices belong in supplements.

## D) Recommended final manuscript table structure

Use one concise table with BIDS-aligned columns (TR/TE in milliseconds). Put scanner software (`E11`/`XA30`), coil, and SBRef/physio notes in accompanying prose rather than repeating them in every Additional cell.

| Modality | Sequence | BIDS label | TR (ms) | TE (ms) | Flip angle (°) | Resolution | Additional parameters |
|---|---|---|---:|---:|---:|---|---|
| Anatomical | 3D FLAIR | `FLAIR` | 6000 | 357 | 120 | 0.8×0.8×0.8 mm | in-plane accel=2; PE=i |
| Anatomical | B1 mapping (turbo flash) | `TB1TFL` | 4000 | 1.8 | 8 | 3.438×3.438×10 mm | PE=j-; B1-related series present as TB1TFL; FA variants common in paired maps |
| Anatomical | T1-weighted MPRAGE | `T1w` | 2500 | 2.2 | 8 | 0.8×0.8×0.8 mm | in-plane accel=2 |
| Anatomical | White-matter-nulled MPRAGE | `T1w (WMn series)` | 4000 | 3.8 | 7 | 1×1×1 mm | in-plane accel=2 |
| Field map | Spin-echo EPI (AP) | `dir-AP_epi` | 9710 | 66 | 90 | 2×2×2 mm | PE=j-; TotalReadoutTime=0.0597s |
| Field map | Spin-echo EPI (PA) | `dir-PA_epi` | 9710 | 66 | 90 | 2×2×2 mm | PE=j; TotalReadoutTime=0.0597s |
| Functional | Control BOLD | `task-control_bold` | 937 | 37 | 52 | 2×2×2 mm | MB=8; PE=j; TotalReadoutTime=0.0597s; volumes=20; short runs; AP and/or PA; SBRef paired series n≈710 |
| Functional | Movie BOLD | `task-movie_bold` | 937 | 37 | 52 | 2×2×2 mm | MB=8; PE=j-; TotalReadoutTime=0.0597s; volumes=210; typically 4 runs/session; SBRef paired series n≈958 |
| Functional | Resting-state BOLD | `task-rest_bold` | 937 | 37 | 52 | 2×2×2 mm | MB=8; PE=j-; TotalReadoutTime=0.0597s; volumes=320; typically 1 run/session; SBRef paired series n≈240 |
| Functional | Task BOLD | `task-fmri_bold` | 937 | 37 | 52 | 2×2×2 mm | MB=8; PE=j-; TotalReadoutTime=0.0597s; volumes=226; typically 4 runs/session; SBRef paired series n≈984 |
| Diffusion | Multidirection DWI | `dwi` | 3500 | 75 | 90 | 1 mm isotropic (protocol) | SeriesDescription=gsld_76dir_b2000_1mmiso_AP (historical name); MB=2; in-plane accel=3; PE=j-; TotalReadoutTime=0.0679s; volumes=385; b-values=0,1000,2000 (n=240); n_diff_dirs=365 (n=228); 270 (n=2); 239 (n=2); n_b0=20 (n=240); TR_variants=3.5\|3.9; note: released .bval is multi-shell (0/1000/2000), not single-shell 76-dir |
| Diffusion | RESOLVE trace DWI | `dwi (RESOLVE)` | 4140 | 51 | 180 | ≈1.4 mm (1.375×1.375×1.82 mm) | in-plane accel=3; PE=j-; TotalReadoutTime=0.0161s; volumes=15; b-values=0,1000 (n=121); n_diff_dirs=11 (n=121); n_b0=4 (n=121); TE_variants=0.051\|0.0512; Derived TRACE/ADC/FA maps may exist in source protocol; released BIDS primarily stores convertible DWI runs |

### Recommended accompanying prose (1 short paragraph)

MRI was acquired at 3 T on a Siemens Prisma system using a HeadNeck_64 receive coil. Scanner software versions in the released sidecars include `syngo MR E11` (majority) and `syngo MR XA30` (subset). Exact run-level parameters are stored in BIDS JSON sidecars; diffusion gradient tables are provided as `.bval`/`.bvec`. Single-band reference images accompany BOLD runs. Physiological monitoring (ECG/respiration/pulse) was logged on the scanner but is not distributed as BIDS physiology files. A reverse-PE b0 series referenced in older protocol notes is not present in the released BIDS DWI folder; susceptibility correction for EPI uses spin-echo field maps (`fmap`).

## Group inventory (all aggregated protocol groups)

| Modality | Kind | n JSON | TR | TE | FA | Resolution | SeriesDescription |
|---|---|---:|---:|---:|---:|---|---|
| Anatomical | B1map | 248 | 4 | 0.0018 | 8 | 3.438×3.438×10 mm | tfl_b1map_1mmiso |
| Anatomical | T1w_MPRAGE | 245 | 2.5 | 0.0022 | 8 | 0.8×0.8×0.8 mm | T1w_MPR |
| Anatomical | FLAIR | 125 | 6 | 0.357 | 120 | 0.8×0.8×0.8 mm | Sag Flair 3D-0.8 |
| Anatomical | WMn_MPRAGE | 111 | 4 | 0.0038 | 7 | 1×1×1 mm | WMn_MPRAGE_sagittal |
| Diffusion | multi-shell_or_multidir | 240 | 3.5 | 0.075 | 90 | 1×1×5 mm | gsld_76dir_b2000_1mmiso_AP |
| Diffusion | RESOLVE | 121 | 4.14 | 0.051 | 180 | 1.375×1.375×1.82 mm | resolve_3scan_trace_tra_p3_160_1.4iso_AP |
| Field map | epi | 246 | 9.71 | 0.066 | 90 | 2×2×2 mm | SpinEchoFieldMap_AP |
| Field map | epi | 246 | 9.71 | 0.066 | 90 | 2×2×2 mm | SpinEchoFieldMap_AP |
| Field map | epi | 245 | 9.71 | 0.066 | 90 | 2×2×2 mm | SpinEchoFieldMap_PA |
| Field map | epi | 245 | 9.71 | 0.066 | 90 | 2×2×2 mm | SpinEchoFieldMap_PA |
| Functional | bold | 508 | 0.937 | 0.037 | 52 | 2×2×2 mm | fMRI1_AP |
| Functional | bold | 507 | 0.937 | 0.037 | 52 | 2×2×2 mm | fMRI1_AP |
| Functional | bold | 495 | 0.937 | 0.037 | 52 | 2×2×2 mm | Movie1_AP |
| Functional | bold | 494 | 0.937 | 0.037 | 52 | 2×2×2 mm | Movie1_AP |
| Functional | sbref | 492 | 0.937 | 0.037 | 52 | 2×2×2 mm | fMRI1_AP_SBRef |
| Functional | sbref | 492 | 0.937 | 0.037 | 52 | 2×2×2 mm | fMRI1_AP_SBRef |
| Functional | sbref | 479 | 0.937 | 0.037 | 52 | 2×2×2 mm | Movie1_AP_SBRef |
| Functional | sbref | 479 | 0.937 | 0.037 | 52 | 2×2×2 mm | Movie1_AP_SBRef |
| Functional | bold | 369 | 0.937 | 0.037 | 52 | 2×2×2 mm | Control1_PA |
| Functional | bold | 369 | 0.937 | 0.037 | 52 | 2×2×2 mm | Control1_PA |
| Functional | sbref | 355 | 0.937 | 0.037 | 52 | 2×2×2 mm | Control1_PA_SBRef |
| Functional | sbref | 355 | 0.937 | 0.037 | 52 | 2×2×2 mm | Control1_PA_SBRef |
| Functional | bold | 125 | 0.937 | 0.037 | 52 | 2×2×2 mm | REST1_AP |
| Functional | bold | 125 | 0.937 | 0.037 | 52 | 2×2×2 mm | REST1_AP |
| Functional | sbref | 120 | 0.937 | 0.037 | 52 | 2×2×2 mm | REST1_AP_SBRef |
| Functional | sbref | 120 | 0.937 | 0.037 | 52 | 2×2×2 mm | REST1_AP_SBRef |

## Methods

- Read-only inspection of BIDS JSON sidecars (and linked `.bval` / NIfTI headers for resolution and volume counts).
- No modifications to `bids/`.
- Existing curated table treated as the manuscript candidate under audit.

