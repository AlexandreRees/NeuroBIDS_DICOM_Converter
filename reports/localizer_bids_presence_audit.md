# Localizer BIDS presence audit

**Date:** 2026-07-27  
**Tree:** `bids/` (working BIDS)  
**Reference inventory:** `protocol_sequence_presence_check.tsv` → Localizer = **303** series / **84** subjects

## Verdict

**All Localizer series from the DICOM inventory are present in BIDS.**

| Check | Result |
| --- | ---: |
| Inventory Localizer series | 303 |
| Unique BIDS `run-*_localizer` series | **303** |
| Subjects with ≥1 localizer | **84 / 84** |
| Sessions with ≥1 localizer | **135 / 135** |
| `*.nii.gz` / `*.json` pairs | **853 / 853** (0 orphans) |
| Sidecar `ProtocolName` | all `Localizer` |

Note: `protocol_sequence_presence_check.tsv` still says *“intentionally not converted”* / `bids_json_count=0` — that row is **stale**. Localizers **are** in `bids/anat/`.

## Typical layout

Most sessions: **2 scout runs × 3 echoes** → 6 NIfTIs  
(`run-01_localizer_i00001…i00003` + `run-02_…`), matching the console order (Localizer early + Localizer before anatomicals).

| Runs / session | n sessions |
| ---: | ---: |
| 1 | 5 |
| 2 | 106 |
| 3 | 14 |
| 4 | 8 |
| 6 | 2 |

## Atypical but present

**Only 1 Localizer run (5 sessions):**  
`sub-001/ses-01`, `sub-002/ses-01`, `sub-049/ses-02`, `sub-055/ses-01`, `sub-078/ses-02`  
→ still converted (3 echoes); second scout simply absent in source/conversion.

**>2 runs (24 sessions):** extra scouts / redos — all present as additional `run-*`.

**Single-file runs (no `_i0000x`, 28 NIfTIs):** e.g. `sub-054/ses-02`, `sub-056/ses-01`, `sub-061–063/ses-01`, `sub-081/ses-02` — present, different heudiconv splitting (1 volume per run instead of 3 echoes).

## Other notes

- **`release_dataset/`:** 0 localizer NIfTIs (not packaged in release tree).
- **Stray `*.bval` / `*.bvec`:** 156 each next to some localizers — conversion artifact, not missing scouts.
- Gap-fill list (`protocol_gap_fill_series.tsv`, 229 localizer rows) reflects an **older** fill plan; current `bids/` already contains the matching series count (303).

## Conclusion

For the working BIDS tree: **localizers are complete vs inventory**. No session is missing a localizer entirely. Remaining variation is run count / echo packaging, not absence.
