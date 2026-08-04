# Burned-in annotation and overlay audit

**Generated (UTC):** 2026-07-22T16:51:43.820571+00:00
**DICOM root scanned:** `/lustre07/scratch/alexrees/raw_original`
**Candidate DICOM files discovered:** 83154
**Files inspected (headers only):** 1133
**Sampling:** one representative instance per series directory (1133 series dirs from 83154 files)

Read-only audit. No DICOM files were modified. Pixel data were not loaded.

## Counts

| Metric | Count |
| --- | ---: |
| DICOM candidates discovered | 83154 |
| Files inspected | 1133 |
| BurnedInAnnotation = YES | 0 |
| BurnedInAnnotation = NO | 0 |
| BurnedInAnnotation tag absent | 1133 |
| BurnedInAnnotation present (other/empty) | 0 |
| Files with overlay groups (6000–601E) | 0 |
| Files with graphic annotation (0070,*) | 0 |
| Files with AnatomicRegionSequence (0008,2218) | 0 |
| Parse errors | 1133 |
| High risk (YES or overlay/graphics) | 0 |

## Interpretation

- **tag absent** — `(0028,0301)` not present. This does **not** prove pixels are free of burned-in text.
- **NO** — tag explicitly states no burned-in annotation (still not a pixel-level guarantee).
- **YES** — burned-in annotation declared; treat as a privacy blocker until reviewed.
- Overlay / graphic annotation presence elevates risk even when BurnedInAnnotation is absent or NO.

## Evidence of burned-in PHI?

**No affirmative tag-level evidence** of burned-in annotations (YES=0). However, 1133 inspected file(s) lack the tag entirely; absence is inconclusive. Spot-check representative anatomical series visually before release.

Detailed TSV: `burned_in_annotation_audit.tsv`
