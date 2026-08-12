# Recursive DICOM discovery

NeuroPipeline discovers DICOM datasets at **any folder depth** and reconstructs BIDS subjects without modifying source files.

Raw DICOM is never renamed, moved, or overwritten. Subject routing is applied only in memory before Input Analysis, Inventory, BIDS Preview, Conversion Plan, and the Conversion Queue.

## Pipeline

```
Input folder
    → Recursive DICOM Discovery
    → DICOM file collection (headers only)
    → Subject candidate detection
    → Subject grouping engine
    → InputAnalysis
    → BIDSConversionPlan / Inventory / Queue
```

The conversion engine (`ConversionManager`, `dcm2niix`, `BIDSExporter`) is unchanged: it receives already-routed `DicomSeries` objects.

## Supported folder structures

Examples that work:

```
Input/
├── subject01/
│   └── data/
│       └── DICOM/
└── subject02/
    └── visit01/
        └── raw/
            └── MR/
                └── DICOM/
```

```
Input/
├── Patient_A/raw/MR/...
└── Patient_B/session01/...
```

```
Input/
├── Study001/Session01/MR/Series001/
└── Study002/Session01/MR/
```

Discovery does **not** require `.dcm` extensions. A file is DICOM if `pydicom.dcmread(..., stop_before_pixels=True)` succeeds and a `SeriesInstanceUID` is present.

## Discovery modes (GUI)

On the Convert page → **Input analysis** → **Discovery mode**:

| Mode | Behaviour |
|------|-----------|
| **Automatic (recommended)** | Prefer unique PatientIDs; fall back to folder grouping / deep inference |
| **PatientID only** | Group only by DICOM PatientID (colliding IDs merge) |
| **Folder recursive** | Always use scored folder candidates |

Default: **Automatic**.

## Subject detection logic

### Priority 1 — Unique PatientID

If every file has a non-empty PatientID and IDs distinguish subjects (or a single ID with a single-subject tree), subjects are `sanitized(PatientID)`.

### Priority 2 — Folder-based grouping

Triggered when PatientIDs are missing, identical across multiple subject trees, or otherwise non-discriminative (common with anonymized exports).

Uses top-level / scored subject candidate folders under the input root.

### Priority 3 — Deep recursive folder inference

When the first folder level is uninformative (`data/`, `DICOM/`, `raw/`, …), candidates are scored deeper in the tree.

### Candidate scoring

| Signal | Score |
|--------|------:|
| Name matches `SUB*`, `subject*`, `patient*`, `participant*` | +5 |
| Folder contains multiple DICOM series | +3 |
| Folder contains one or more StudyInstanceUID | +2 |
| Folder is directly under the input root | +2 |
| Name is `DICOM`, `MR`, `MRI`, `RAW`, `DATA`, … | −5 |

Highest-scoring candidate wins per file tree.

## Preserved metadata

Routing remaps the in-memory `DicomSeries.patient_id` used for BIDS subject labels.

Original values are preserved as:

- `dicom_patient_id` / inventory **Original PatientID**
- `source_subject_folder` / inventory **Source Subject Folder**
- `subject_detection_method` / inventory **Detection Method**

## Input Analysis display

Example (folder collision):

```
Detected subjects: 3

Detection method: Folder based grouping
Reason: PatientID collision detected

Patient_A
  Source: Patient_A
  Original PatientID: ANON
  DICOM files: 542
  Series: 34
…
```

## BIDS Preview

Preview subjects follow the remapped IDs. When a source folder is known, the tree shows:

```
sub-PatientA
  source: Patient_A
  anat/
    …
```

Task, run, datatype, suffix, and naming rules are unchanged.

## Performance notes

- Pixel data is never loaded (`stop_before_pixels=True`).
- Metadata is read once per file during recursive discovery.
- Series classification still uses the existing `DicomParser.scan` (parser core unchanged).
- Suitable for large trees (100k+ files); runtime is dominated by filesystem walk + header reads.

## Fallback behaviour

| Situation | Result |
|-----------|--------|
| No DICOM files | Clear “No DICOM files detected” error |
| Single subject | Detection method `single` |
| PatientID-only mode + shared ID | One merged subject |
| Automatic + shared ID + multiple folders | Multiple folder-based subjects |

See also: [USER_GUIDE.md](USER_GUIDE.md).
