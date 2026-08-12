# DICOM Format Support Audit — NeuroPipeline DICOM Converter

**Date:** 2026-08-10  
**Scope:** Code inspection of `src/neuro_pipeline/{dicom,converter,scanner,discovery,metadata,bids,validation,gui}` + installer  
**Rule applied:** Capabilities are marked only when supported by code paths and/or synthetic tests. Untested claims are *not* marked as fully supported.

**Legend**

| Column | Meaning |
|--------|---------|
| Detected | File/object can be recognized as DICOM candidate |
| Parsed | Header metadata readable (`stop_before_pixels`) |
| Supported | Pipeline intentionally handles this class |
| Converted | Sent to dcm2niix and expected to produce NIfTI |
| Tested | Covered by automated synthetic tests in-repo |

---

## Executive summary

NeuroPipeline is a **thin orchestration layer** around **pydicom** (scan / metadata) and **dcm2niix** (actual pixel conversion). Most “format support” for Transfer Syntax / compression is therefore owned by **dcm2niix**, not re-implemented in Python.

**What works well for neuro MRI today**

- Recursive folder scan; Part-10 with `DICM` preamble; `.dcm` / `.dicom` / `.ima` / extensionless
- Series grouping by `SeriesInstanceUID`
- Coarse sequence classification (T1/T2/FLAIR/DWI/BOLD/fmap) via plugins + regex
- Crash-safe skip of unreadable files during scan
- Bundled dcm2niix search next to exe / `tools/` / PATH

**Critical gaps (before fixes in this pass)**

1. **Extension whitelist in `DicomParser`** could miss real DICOM with proprietary extensions (while discovery was more content-oriented).
2. **No SOP Class gate** — Secondary Capture / SR / Encapsulated PDF / waveforms with a Series UID could be handed to dcm2niix.
3. **Transfer Syntax / NumberOfFrames** not captured for auditing or multi-frame awareness.
4. **PyInstaller spec** did not embed `dcm2niix.exe`; icon path pointed to missing `assets/icon.ico` (actual file: `assets/NeuroPipeline.ico`).
5. Pixel decompressability is **never tested** in-app (`stop_before_pixels=True` everywhere).

---

## Feature matrix

| Feature | Detected | Parsed | Supported | Converted | Tested | Notes |
|---|---|---|---|---|---|---|
| Extension `.dcm` / `.DCM` | Y | Y | Y | Y* | Y | `*via dcm2niix` |
| Extension `.dicom` / `.ima` | Y | Y | Y | Y* | Y | |
| Extensionless DICOM | Y | Y | Y | Y* | Y | Content + parse |
| Proprietary / arbitrary extension + `DICM` preamble | Y† | Y† | Y† | Y* | Y | †After critical fix (magic probe) |
| False `.dcm` (text/PDF named .dcm) | Y skip | N | Y | N | Y | Parse fails → skipped |
| DICOM Part 10 (`DICM` @ 128) | Y | Y | Y | Y* | Y | |
| Non-Part-10 (no meta) | Partial | Partial | Limited | Maybe* | Partial | `force=True` retry |
| Implicit VR LE `1.2.840.10008.1.2` | Y‡ | Y‡ | Y‡ | Likely* | Header only | ‡UID capturable; decompress via dcm2niix |
| Explicit VR LE `1.2.840.10008.1.2.1` | Y‡ | Y‡ | Y‡ | Likely* | Header only | Most common MRI export |
| Deflated Explicit VR LE `.1.99` | Y‡ | Y‡ | Limited | Maybe* | Untested | Depends on dcm2niix build |
| Explicit VR Big Endian `.1.2.2` | Y‡ | Y‡ | Limited | Maybe* | Untested | Rare; retired TS |
| JPEG Baseline `.4.50` | Y‡ | Y‡ | Limited | Maybe* | Untested | dcm2niix usually OK; pydicom needs plugin |
| JPEG Extended `.4.51` | Y‡ | Y‡ | Limited | Maybe* | Untested | |
| JPEG Lossless `.4.57` / `.4.70` | Y‡ | Y‡ | Limited | Maybe* | Untested | Common SC / derived |
| JPEG-LS `.4.80` / `.4.81` | Y‡ | Y‡ | Limited | Maybe* | Untested | |
| JPEG 2000 `.4.90` / `.4.91` | Y‡ | Y‡ | Limited | Maybe* | Untested | Needs dcm2niix codecs / OpenJPEG |
| JPEG 2000 Part 2 `.4.92` / `.4.93` | Y‡ | Y‡ | Limited | Unknown | Untested | |
| RLE Lossless | Y‡ | Y‡ | Limited | Maybe* | Untested | |
| MPEG-2 / MPEG-4 / HEVC | Y‡ | Y‡ | N | N | Untested | Video — not neuroimaging NIfTI path |
| MR Image Storage | Y | Y | Y | Y* | Y | Primary target |
| Enhanced MR Image Storage | Y | Y | Limited | Maybe* | Partial | Multi-frame not specially handled |
| CT / Enhanced CT | Y | Y | Limited | Maybe* | Untested | No modality gate previously |
| PET / Enhanced PET | Y | Y | Limited | Maybe* | Untested | |
| MR Spectroscopy | Y | Y | Limited | Often N | Untested | Often fails / not NIfTI anatomy |
| Secondary Capture | Y | Y | Limited | Maybe* | Untested | Now classified; conversion skipped if non-image SOP family |
| Segmentation / SR / Encapsulated PDF | Y | Y | Marked non-convertible† | N† | Y | †After SOP gate |
| Mixed folder DICOM+JSON/TXT/PDF | Y | Y | Y | Y* | Y | Non-DICOM suffixes skipped |
| Private tags Siemens/GE/Philips | Y | Partial | Y | Pass-through* | Partial | Not interpreted; not crashing |
| Pixel Data absent | N/A | Header OK | Y | Fail at dcm2niix | Partial | Soft fail per series |
| Zero-byte / corrupt | Skip | N | Y | N | Y | Continues scan |

---

## Transfer Syntax — detailed status

Distinctions required by this audit:

| Transfer Syntax | pydicom recognizes UID | Header readable (`stop_before_pixels`) | Pixel decompress in NeuroPipeline | dcm2niix typically accepts | NeuroPipeline converts* | Notes |
|---|---|---|---|---|---|---|
| Implicit VR LE | Y | Y | Not tested (pixels skipped) | Y | Delegated | Default many scanners |
| Explicit VR LE | Y | Y | Not tested | Y | Delegated | Most common |
| Deflated Explicit VR LE | Y | Often Y | Not tested | Build-dependent | Untested | |
| Explicit VR Big Endian | Y | Often Y | Not tested | Limited | Untested | Retired |
| JPEG Baseline/Extended | Y | Y | Needs pylibjpeg/gdcm — **not guaranteed in bundle** | Usually Y | Untested | |
| JPEG Lossless | Y | Y | Plugin-dependent | Usually Y | Untested | |
| JPEG-LS | Y | Y | Plugin-dependent | Usually Y | Untested | |
| JPEG 2000 | Y | Y | OpenJPEG/plugin | Build-dependent | Untested | Do **not** claim supported without sample |
| RLE | Y | Y | Often Y in pydicom | Usually Y | Untested | |
| MPEG / H.264 / HEVC | Y | Y | N (video) | N for NIfTI | **Unsupported** | |

\*Conversion = “will invoke dcm2niix on the series folder”; success not guaranteed without real fixtures.

---

## SOP Class / modality policy

| Category | Pipeline class | Action |
|----------|----------------|--------|
| MR / CT / PT image storage (classic + many Enhanced) | `DICOM_IMAGE` / `DICOM_ENHANCED_MULTI_FRAME` | Eligible for dcm2niix |
| Secondary Capture (image-like) | `DICOM_SECONDARY_CAPTURE` | Convert only if looks like image (Rows/Columns) |
| MR Spectroscopy | `DICOM_SPECTROSCOPY` | **Not converted** (flagged) |
| Segmentation | `DICOM_SEGMENTATION` | **Not converted** |
| Structured Report | `DICOM_STRUCTURED_REPORT` | **Not converted** |
| Waveform / ECG / EEG | `DICOM_WAVEFORM` | **Not converted** |
| Encapsulated PDF / STL / OBJ | `DICOM_OTHER` | **Not converted** |
| Unreadable | `CORRUPTED_DICOM` | Skipped |
| Non-DICOM | `NON_DICOM` | Skipped |

| Modality | Status |
|----------|--------|
| MR | **SUPPORTED** (primary) |
| CT, PT | **SUPPORTED_WITH_LIMITATIONS** (convertible if image SOP; not neuro-specialized) |
| NM, US, XA, DX, CR, MG, RF | **SUPPORTED_WITH_LIMITATIONS** / often poor NIfTI usefulness |
| SC | **SUPPORTED_WITH_LIMITATIONS** |
| SR, SEG, PR, ECG, EEG | **NOT_APPLICABLE** to NIfTI anatomy export |
| OT / unknown | **UNKNOWN** — convert only if image SOP + pixel geometry |

---

## MRI sequence classification (existing)

Handled at textual / plugin level (SeriesDescription / ProtocolName / ImageType), not Transfer Syntax:

| Label | Support |
|-------|---------|
| T1 / MPRAGE / SPGR / FLASH / MP2RAGE | SUPPORTED (classification) |
| T2 / FLAIR / SPACE / CUBE | SUPPORTED (classification) |
| DWI / DTI / ADC* | SUPPORTED; ADC diverted to derivatives |
| BOLD / task / rest fMRI | SUPPORTED (classification) |
| Fieldmap / phase / magnitude | SUPPORTED (fmap heuristics) |
| SWI / ASL / perfusion | PARTIAL (fine labels exist; BIDS mapping limited) |
| Spectroscopy / qMRI / DIXON / MTsat | LIMITED / UNKNOWN |
| Multi-band / SMS / accelerated EPI | Not separately classified |

Multi-frame Enhanced MR: files are ingested as a series with `num_images = file count` (often 1), **not** `NumberOfFrames` — limitation.

---

## Detection → Conversion chain

```
DETECTION  → content/extension candidacy + dcmread(force=False|True)
LECTURE    → headers only (stop_before_pixels=True)
DÉCOMPRESSION → NOT performed by NeuroPipeline; delegated to dcm2niix
CLASSIFICATION → sequence plugins + SOP object class
CONVERSION → dcm2niix CLI per series folder
VALIDATION → NIfTI/JSON/bval/bvec QC (post hoc)
```

---

## CRITICAL GAPS

1. ~~Proprietary extensions ignored by parser whitelist~~ → **fixed** via DICM magic probe.
2. ~~Non-image SOP classes eligible for dcm2niix~~ → **fixed** with soft skip + message.
3. ~~`dcm2niix.exe` not in PyInstaller datas~~ → **fixed** when file present under repo/`tools/`.
4. ~~Wrong icon path in `.spec`~~ → **fixed** (`assets/NeuroPipeline.ico`).
5. No automated coverage of compressed transfer syntaxes with real pixels (needs opt-in fixtures).
6. Enhanced multi-frame frame count not used in UI/series cardinality.
7. No explicit modality policy UI for CT/PT/NM mixed folders.

## SUPPORTED

- DICOM Part 10 MR series (classic multi-file)
- Extensions `.dcm` / `.dicom` / `.ima` / none / proprietary with preamble
- Recursive trees; mixed with JSON/TXT/PDF/NIfTI noise
- Classification anat/func/dwi/fmap heuristics
- Crash isolation per unreadable file / per conversion series

## SUPPORTED WITH LIMITATIONS

- Enhanced / multi-frame MR (passed through; not specially modeled)
- Compressed Transfer Syntax (success depends on dcm2niix build, not tested here)
- CT/PET and other image modalities (convertible, not neuro-optimized)
- Non-Part-10 via `force=True`

## UNSUPPORTED

- DICOM video (MPEG/H.264/HEVC) → NIfTI
- Guaranteed pydicom pixel decompress for JPEG2000 without plugins in the Windows freeze
- Full private-tag interpretation (by design)

## NOT APPLICABLE

- Structured Reports, Segmentation objects, Encapsulated documents, Waveforms as volumetric NIfTI outputs

---

## dcm2niix packaging notes

Search order (`Converter.verify`): requested path → app dir / `bin` / `tools` → `_MEIPASS` resources → PATH.

**Required for freeze:** place `dcm2niix.exe` at:

- `tools/dcm2niix.exe` **or**
- repository root `dcm2niix.exe`

before `pyinstaller installer/neuro_pipeline.spec`.

User referenced a known-good local `dcm2niix.exe` — copy into this repo’s `tools\` before building.

---

## Files touched by remediation (this pass)

| Path | Action |
|------|--------|
| `reports/DICOM_FORMAT_SUPPORT_AUDIT.md` | Created — audit report |
| `src/neuro_pipeline/dicom/format_support.py` | Created — probe + SOP/TS policy |
| `src/neuro_pipeline/dicom/parser.py` | Updated — content-first candidacy + convertibility meta |
| `src/neuro_pipeline/dicom/__init__.py` | Updated — exports |
| `src/neuro_pipeline/models/__init__.py` | Updated — series format fields |
| `src/neuro_pipeline/converter/dcm2niix.py` | Updated — soft-skip non-convertible SOP; clearer missing-binary message |
| `installer/neuro_pipeline.spec` | Updated — icon, bundle dcm2niix, configs, `console=False` |
| `installer/build.bat` | Updated — preflight dcm2niix check; correct `dist\` path |
| `tests/test_dicom_format_support.py` | Created — synthetic fixtures |
| `tools/README.txt` | Created — where to place `dcm2niix.exe` |

**Not verified on this Linux host:** Windows freeze (`dist\NeuroPipeline\NeuroPipeline.exe`) and presence of packaged `dcm2niix.exe` — run the PowerShell commands below on the Windows machine after copying the binary into `tools\`.
