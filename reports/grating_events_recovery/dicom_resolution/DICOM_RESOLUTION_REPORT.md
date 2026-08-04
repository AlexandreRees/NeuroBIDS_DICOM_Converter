# DICOM Resolution Report — Grating events ambiguities

Generated: `2026-07-28T14:39:35.818053+00:00`

## Summary

| Metric | n |
|--------|--:|
| Ambiguous mappings analyzed | 2 |
| **ACCEPT** | 2 |
| **REVIEW** | 0 |
| **REJECT** | 0 |

## Decision table

| subject | session | fMRI# | MATLAB time | selected run | decision | reason |
|---------|---------|------:|-------------|-------------:|----------|--------|
| sub-043 | ses-02 | 3 | 14:40:19 | 02 | **ACCEPT** | Matched MATLAB timing; magnitude series; same acquisition date; twin run excluded as orphan; twin excluded: run-01 belongs to orphan acquisition 2024-07-25; score=28 |
| sub-043 | ses-02 | 4 | 14:44:31 | 06 | **ACCEPT** | Matched MATLAB timing; magnitude series; same acquisition date; twin run excluded as orphan; twin excluded: run-05 belongs to orphan acquisition 2024-07-25; score=28 |

## Before → After

### sub-043 / ses-02 / fMRI3

Before:
```
MATLAB fMRI3
|
|-- run-01  [REJECT] score=-30 date=2024-07-25
|-- run-02  [ACCEPT] score=28 date=2025-02-19
```

After:
```
MATLAB fMRI3
|-- selected run-02
```

### sub-043 / ses-02 / fMRI4

Before:
```
MATLAB fMRI4
|
|-- run-05  [REJECT] score=-30 date=2024-07-25
|-- run-06  [ACCEPT] score=28 date=2025-02-19
```

After:
```
MATLAB fMRI4
|-- selected run-06
```

## Evidence used

- DICOM StudyDate (orphan detection)
- AcquisitionTime / SeriesTime vs MATLAB file timestamp
- SeriesNumber
- ImageType → magnitude / phase
- ImagingFrequency fingerprint (BIDS ↔ DICOM) when SeriesInstanceUID absent from BIDS JSON
- Volume count / TR sanity

## Safety statement

No events.tsv files were generated or modified.
All decisions were made using read-only DICOM metadata.
SeriesInstanceUID values are stored only as SHA256-16 hashes.
Patient identifiers and absolute filesystem paths are excluded from outputs.
