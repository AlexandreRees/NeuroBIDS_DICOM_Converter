# SUB-043 DICOM Resolution Report

Generated: `2026-07-28T14:11:07.614589+00:00`

## Problem

BIDS `sub-043/ses-02` has two magnitude `task-fmri` runs for each of `fMRI3_AP` and `fMRI4_AP` (runs 01/02 and 05/06), with identical `SeriesNumber` in JSON and no `SeriesTime`, blocking fail-closed event assignment.

## DICOM finding (critical)

The raw folder mixes **two acquisition dates** under the same series directories:

| Cohort | StudyDate pattern in filenames | fMRI3 SeriesTime | fMRI4 SeriesTime |
|--------|--------------------------------|------------------|------------------|
| **2025FEB19** (true session) | `SUBC044_SESSION02_2025FEB19...` | **14:34:29** (SN15 mag) | **14:38:46** (SN19 mag) |
| **2024JUL25_orphan** | `...2024JUL25...` / COMPLETE_PROTOCOL | 17:29:27 (SN15 mag) | 17:33:41 (SN19 mag) |

For each protocol, Siemens stored **magnitude + phase** as consecutive series:

- fMRI3: SN**15** magnitude + SN**16** phase (`ImageType` …`\M\` vs …`\P\`)
- fMRI4: SN**19** magnitude + SN**20** phase

## MATLAB clock alignment

| MATLAB | Timestamp | Nearest 2025 magnitude SeriesTime | Δ (SeriesTime → MATLAB save) |
|--------|-----------|-----------------------------------|------------------------------|
| fMRI3 | 14:40:19 | 14:34:29 (SN15) | ≈350 s (scan ~211 s + save lag) |
| fMRI4 | 14:44:31 | 14:38:46 (SN19) | ≈345 s |

Orphan 17:xx series are **not** compatible with MATLAB afternoon timestamps.

## Linking BIDS twins via ImagingFrequency

JSON `SeriesInstanceUID` is absent, but `ImagingFrequency` uniquely fingerprints the DICOM cohort:

| BIDS run | Protocol | ImagingFrequency | Matched DICOM cohort | SeriesTime |
|---------:|----------|------------------|----------------------|------------|
| 01 | fMRI3_AP | 123.257831 | 2024JUL25_orphan | 17:29:27.268 |
| 02 | fMRI3_AP | 123.257877 | 2025FEB19 | 14:34:29.422 |
| 05 | fMRI4_AP | 123.257835 | 2024JUL25_orphan | 17:33:41.413 |
| 06 | fMRI4_AP | 123.257881 | 2025FEB19 | 14:38:46.273 |

## Decision

| fmri_number | decision | selected_bids_run | reason |
|------------:|----------|------------------:|--------|
| 3 | **ACCEPT** | 02 | UNIQUE_FREQ_MATCH_TO_2025_MAGNITUDE_SERIES; SeriesTime=14:34:29.422 precedes MATLAB 14:40:19 by 350s; rejected orphan 2024JUL25 twin |
| 4 | **ACCEPT** | 06 | UNIQUE_FREQ_MATCH_TO_2025_MAGNITUDE_SERIES; SeriesTime=14:38:46.273 precedes MATLAB 14:44:31 by 345s; rejected orphan 2024JUL25 twin |

### ACCEPT only if unique

Both cases are **ACCEPT**: each MATLAB file links to exactly one **2025FEB19 magnitude** DICOM series, which fingerprints to exactly one BIDS run via `ImagingFrequency`. The other BIDS twin is the **2024JUL25 orphan** magnitude series and must not receive these events.

## Confirmations

- Read-only on `raw_original/` and `bids/`
- No invented timing
- Events still derive from MATLAB `triggerTimes` only
- `bids/` not modified

## Summary

ACCEPT: **2**  
REVIEW: **0**  
REJECT: **0**

**Integration scientifically justified: YES**

See `INTEGRATE_SUB043_EVENTS_READY.tsv` (copy not performed).
