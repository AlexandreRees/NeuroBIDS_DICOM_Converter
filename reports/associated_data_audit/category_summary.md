# Associated data publication audit — category summary

Generated: `2026-07-21T15:28:20.479403+00:00`

This was a read-only audit of files listed in `reports/associated_data_inventory.tsv`.
Source files were opened only for reading and source size/mtime were checked before and after inspection.

## Summary statistics

- Total files inspected: **5756**
- Files with PHI: **2911**
- Files requiring de-identification: **2911**
- Files already BIDS-compatible: **0**
- Files convertible to BIDS (including custom converters): **3563**
- Files suitable for direct public release: **2832**
- Files requiring manual review: **242**
- Files containing scanner metadata: **1136**

## By category

| Category | Files | PHI | Direct release | De-identify | Convertible/custom | Manual review |
|---|---:|---:|---:|---:|---:|---:|
| eye_tracking | 448 | 412 | 36 | 412 | 448 | 0 |
| physiology | 339 | 336 | 3 | 336 | 339 | 0 |
| stimulus | 3716 | 1055 | 2648 | 826 | 1668 | 242 |
| task_timing | 1108 | 1108 | 0 | 1108 | 1108 | 0 |
| unknown | 145 | 0 | 145 | 0 | 0 | 0 |

## Recommended workflow

1. Review `phi_report.md`; treat every positive as a potential disclosure until verified.
2. Build de-identified derivatives in a separate staging tree; never edit source files.
3. Convert run-linked timing/behavior to `*_events.tsv` and physiology to `*_physio.tsv.gz` plus JSON.
4. Convert eye tracking with a validated custom converter and preserve sampling/calibration metadata.
5. Resolve audiovisual licenses before copying any movie/audio into `stimuli/`.
6. Rerun PHI scanning and BIDS validation on the release candidate.
7. Manually adjudicate unreadable, unsupported, ambiguous, and copyright-flagged files.
