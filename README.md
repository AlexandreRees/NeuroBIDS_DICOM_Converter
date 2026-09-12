# NeuroPipeline DICOM Converter

<p align="center"> <img src="docs/assets/logo.png" alt="NeuroPipeline logo" width="88" /> </p>

<p align="center"> <a href="https://github.com/AlexandreRees/NeuroBIDS_DICOM_Converter/releases/download/v1.0.0/NeuroPipeline_DICOM_Converter_Setup.exe"><img src="https://img.shields.io/badge/Download-Windows-0078D4?style=for-the-badge&logo=windows&logoColor=white" alt="Download for Windows" /></a> <a href="https://github.com/AlexandreRees/NeuroBIDS_DICOM_Converter/releases/latest"><img src="https://img.shields.io/github/v/release/AlexandreRees/NeuroBIDS_DICOM_Converter?style=for-the-badge&label=Latest%20release" alt="Latest release" /></a> </p>

Windows desktop application for converting MRI DICOM datasets to NIfTI / BIDS with [dcm2niix](https://github.com/rordenlab/dcm2niix).

Designed for researchers with no programming experience. Built as a modular foundation for a future neuroimaging platform (BIDS, QC, MRIQC, reports).

**Version:** 1.0.0

## Download

**[Download for Windows](https://github.com/AlexandreRees/NeuroBIDS_DICOM_Converter/releases/download/v1.0.0/NeuroPipeline_DICOM_Converter_Setup.exe)** — latest Classic/Main installer (`NeuroPipeline_DICOM_Converter_Setup.exe`).

- No Python install required for end users
- `dcm2niix` is bundled
- Copilot / Ollama are **not** required

All releases: [Releases](https://github.com/AlexandreRees/NeuroBIDS_DICOM_Converter/releases)

## For end users

Start here — how to use Convert, Preview, Inventory, Queue, and Naming Rules in practice:

**[User Guide (English)](docs/USER_GUIDE.md)**

Also: [User Manual (short)](docs/user_manual.md)

## Features

- Modern PySide6 interface (Convert · Queue · Settings · Logs)
- Automatic DICOM scan (recursive; multi-subject folders supported)
- BIDS Preview with editable conversion plan (DICOM stays read-only)
- DICOM Inventory Excel/CSV (no conversion)
- Smart naming rules (optional lab JSON rules)
- Conversion queue for large batches (pause / retry / recover)
- Compressed `.nii.gz` output and BIDS layout
- HTML conversion report + provenance + logs

## Requirements

- Windows 10/11 (primary target) or Linux/macOS for development
- Python 3.11+ (developers only)
- [dcm2niix](https://github.com/rordenlab/dcm2niix/releases) on `PATH`, or path set in Settings / `configs/default.yaml`

## Quick start (developers)

```bash
cd NeuroPipeline_DICOM_Converter
python -m venv .venv

# Windows
.venv\Scripts\activate

# Linux / macOS
source .venv/bin/activate

pip install -r requirements.txt
pip install -e .

python -m neuro_pipeline
```

## Example user workflow

1. Open **Convert** → select DICOM **Input** folder and BIDS **Output** folder  
2. Review **Input analysis** and **BIDS Preview**  
3. Click **Convert** (or use **Queue** for many subjects)  
4. Open the output folder / `conversion_report.html`

Full walkthrough: **[docs/USER_GUIDE.md](docs/USER_GUIDE.md)**

## Post conversion validation

After each conversion the application runs an automatic checks pipeline:

```
DICOM
  ↓
dcm2niix
  ↓
NIfTI validation
  ↓
Report
```

Checks include:

- Readable NIfTI headers / data (via nibabel)
- Sensible dimensions, voxel sizes, and affine matrices
- DWI companion files (`.bval` / `.bvec` / `.json`) and gradient/volume counts
- Recommended JSON metadata fields (warnings only if missing)

Nothing writes back to the DICOM input tree. Validation is read-only on produced NIfTI/sidecars.

## Metadata extraction

During scan and conversion, `DicomMetadataExtractor` reads DICOM tags (stop-before-pixels) into a validated `DicomSeriesMetadata` model:

- Patient (ID / age / sex — never exports `PatientName` in public JSON)
- Study / Series / acquisition parameters (TR, TE, field strength, geometry)
- Diffusion tags when present (b-values, gradient directions)

Summaries are written under `series_metadata/*_metadata.json` next to the conversion output. Source DICOM files are never modified.

## Sequence recognition

`SequenceClassifier` remains **informational** (it does not replace BIDS planning):

- Coarse labels: `anat` / `func` / `dwi` / `fmap` / `unknown` (existing behavior)
- Fine labels: `ANAT_T1`, `DWI`, `FMRI_REST`, … with `confidence` (0–1) and human-readable `reason`s
- Rules live in `configs/sequence_rules.yaml` (study-agnostic patterns)

## QC dashboard

After each conversion the pipeline writes `qc_report.html` with:

1. Summary KPIs (total / converted / failed / warnings)
2. Modality bars
3. Scanner information
4. Conversion table (DICOM → NIfTI → type → validation)
5. Warning panel (missing bvec/json, unusual voxels, …)
6. Optional central-slice previews when `nilearn` is installed

GUI tab **QC Dashboard** opens the report and the output folder.

## Export profiles

Package an existing conversion tree without touching source DICOM:

| Profile | Use | Contents |
|---------|-----|----------|
| `bids` | Research / OpenNeuro | NIfTI tree + `dataset_description.json` + `participants.tsv` + `README` |
| `clinical` | Hospital | Organized NIfTI + minimal metadata (no PHI fields) |
| `archive` | Long-term storage | NIfTI + JSON + logs + `checksums.sha256` |

CLI:

```bash
python -m neuro_pipeline export-profile \
  --input conversion_output \
  --profile bids \
  --output dataset
```

GUI: **Export type** dropdown (Research BIDS / Clinical / Archive).

## BIDS validation

When **Output format → BIDS dataset** is selected, NeuroPipeline runs BIDS validation after export:

1. Prefer the official `bids-validator` executable on `PATH` (or a future bundled binary).
2. If the CLI is missing, a structural fallback checks `dataset_description.json`, subjects, and JSON sidecars and records a clear warning.
3. Results are written to `bids_validation_report.html` next to the dataset.
4. The GUI shows **✓ PASS** or **⚠ PASS WITH WARNINGS** and offers **Open validation report**.

Install the official validator for full schema checks:

```bash
npm install -g bids-validator
```

## Metadata preservation

dcm2niix JSON sidecars are treated as first-class outputs:

- Every exported NIfTI keeps its matching `.json` (plus `.bval` / `.bvec` for DWI).
- Sidecars are validated for recommended fields (`Manufacturer`, `MagneticFieldStrength`, `SequenceName`, `ProtocolName`, `RepetitionTime`, `EchoTime`) without failing when optional fields are absent.
- The HTML conversion report includes a scanner / field-strength / sequence summary.

Rules live in `src/neuro_pipeline/metadata/` (`MetadataManager`).

## Sequence plugins

Configurable sequence detection lives under `src/neuro_pipeline/plugins/` with rules in `configs/sequence_plugins.yaml`.

Priority:

1. User YAML patterns
2. Built-in generic plugins (`anat` / `dwi` / `func` / `fmap`)
3. Unknown fallback (manual mapping)

No study names or scanner-vendor cohort protocols are hardcoded. The GUI **Sequence detection** panel shows the label and confidence (or “Unknown sequence — Manual mapping required”).

## Metadata validation

Advanced datatype-specific BIDS JSON checks (`src/neuro_pipeline/bids/metadata_validator.py`) run after conversion:

| Datatype | Required / checked |
|----------|--------------------|
| anat | MagneticFieldStrength, Manufacturer, SequenceName |
| dwi | DiffusionGradientOrientation + `.bvec` / `.bval` companions |
| func | RepetitionTime, TaskName |
| fmap | EchoTime, PhaseEncodingDirection |

Results are written to `metadata_validation_report.html` (advisory; conversion is never blocked).

## QC error detection

Silent post-conversion checks (`src/neuro_pipeline/qc/errors/`, rules in `configs/qc_rules.yaml`) detect:

- Missing JSON / bvec / bval companions
- Dimension mismatches (e.g. 3D DWI when 4D expected)
- Duplicate output filenames
- Empty or corrupt NIfTI files

Pipeline order: **Conversion → metadata validation → error detector → final status**. Overall QC (`PASS` / `WARNING` / `FAIL`) and warning/failure counts appear in the GUI and `qc_error_report.html`.

## Longitudinal studies

`LongitudinalManager` (`src/neuro_pipeline/bids/longitudinal.py`) parses visit-style tokens and validates multi-session layouts:

```
Subject001_visit1  →  sub-Subject001 / ses-01
Subject001_visit2  →  sub-Subject001 / ses-02
```

Supported layouts: `sub-001` alone, or `sub-001/ses-01`, `sub-001/ses-02`, …

In the GUI, set **Study mode → Longitudinal study**, enter Subject / Session IDs, and use the **Session queue** to add multiple session labels. In BIDS mode, conversion exports once into each queued session folder (copy-based; sources remain untouched).

## Subject and session handling

BIDS export accepts optional GUI fields:

- **Subject ID** — `001` or `sub-001` (alphanumeric only)
- **Session ID** — optional `01` or `ses-01`

Layout without session:

```
sub-<id>/
  anat|dwi|func|fmap/…
```

With session:

```
sub-<id>/
  ses-<id>/
    anat|dwi|func|fmap/…
```

If session is empty, no `ses-*` folder is created. Entity patterns are config-driven via `configs/bids_entities.yaml` (no study-specific hardcoding).

## Provenance tracking

Every conversion writes read-only provenance under:

```
derivatives/neuro_pipeline/
  conversion_provenance.json
  conversion_manifest.json
```

Contents include software version, conversion parameters, SHA-256 of the input DICOM folder, and hashes of output files. Source DICOM data is never modified.

## Batch conversion

Use the GUI tab **Batch Conversion**, or the CLI:

```bash
python -m neuro_pipeline convert --input /data/dicoms --output /data/out --batch
```

Expected input layout:

```
dicoms/
  subject001/
  subject002/
```

Features:

- Job queue with statuses `QUEUED` / `RUNNING` / `COMPLETED` / `FAILED` / `PAUSED`
- Resume via `state.json` in each subject output folder
- Per-series checkpoints under `checkpoints/` (skip completed series when source hash matches)
- Exportable Markdown batch report

## Multi scanner support

Scanner manufacturer / model / field strength are auto-detected from DICOM tags
(`Manufacturer`, `ManufacturerModelName`, `SoftwareVersions`, `MagneticFieldStrength`).

Configurable sequence-pattern profiles live in:

```
configs/scanners/
  siemens.yaml
  ge.yaml
  philips.yaml
  generic.yaml
```

Classification still works without profiles (legacy regex fallback). Profiles only refine matching.

## HPC deployment

Templates (no hardcoded account / partition / personal paths):

```
deployment/hpc/slurm_convert_array.sh
deployment/hpc/neuro_pipeline.def
```

```bash
export INPUT_DIR=/path/to/dicoms
export OUTPUT_DIR=/path/to/niftis
sbatch --array=0-99 deployment/hpc/slurm_convert_array.sh
```

Apptainer:

```bash
apptainer build neuropipeline.sif deployment/hpc/neuro_pipeline.def
```

## Docker

See [`README_DOCKER.md`](README_DOCKER.md).

```bash
docker build -t neuropipeline .
docker run --rm -v /data:/data neuropipeline convert --input /data/in --output /data/out --batch
```

Linux quick install:

```bash
./deployment/linux/install.sh
./deployment/linux/run_neuropipeline.sh
```

Windows packaging helpers: `deployment/windows/build.ps1` and `deployment/windows/WINDOWS_INSTALL.md`.

## Configuration

Edit `configs/default.yaml`:

```yaml
compression: true
one_folder_per_patient: true
preserve_json: true
smart_naming: true
threads: 4
output_format: nii.gz
dcm2niix_path: ""   # e.g. C:\Tools\dcm2niix.exe
```

Smart naming rules live in `configs/naming_rules.yaml` (not hardcoded).

## Packaging (Windows EXE)

End users: see [`README_WINDOWS.md`](README_WINDOWS.md).

Developers (build machine):

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_windows.ps1
```

Produces:

- `dist\NeuroPipeline_DICOM_Converter.exe`
- `release\NeuroPipeline_DICOM_Converter_Setup.exe`

Details: [`installer/BUILD_WINDOWS.md`](installer/BUILD_WINDOWS.md).

## Tests

```bash
pytest
```

## Documentation

- [Developer guide](docs/developer.md)
- [Architecture](docs/architecture.md)
- [Changelog](CHANGELOG.md)
- [Docker](README_DOCKER.md)

## Project layout

```
src/neuro_pipeline/
  batch/       # batch jobs, resume, checkpoints
  scanner/     # multi-vendor detection + profiles
  converter/   # dcm2niix wrapper + ConversionManager
  dicom/       # scanner + sequence classifier
  bids/        # exporter, entities, subject/session, validator
  metadata/    # JSON sidecar preservation
  provenance/  # SHA-256 conversion provenance
  reports/     # BIDS validation HTML
  validation/  # NIfTI / DWI / metadata checks + HTML report
  gui/         # PySide6 interface (Single + Batch tabs)
  config/      # YAML loading / path resolution
  utils/       # naming, filesystem, exceptions
  logging/     # conversion.log setup
  workers/     # QThread workers
  models/      # dataclasses
configs/
  scanners/    # Siemens / GE / Philips / generic YAML profiles
  bids_entities.yaml
deployment/
  windows/ linux/ hpc/ docker/
tests/
docs/
installer/
```

## License

MIT

Third-party tools bundled or used by this application (for example **dcm2niix**)
retain their own licenses and are **not** covered by this MIT license.
See `third_party/licenses/`.
