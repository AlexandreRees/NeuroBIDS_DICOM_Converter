<p align="center">
  <img src="assets/logo.png" alt="NeuroPipeline logo" width="96" />
</p>

# NeuroPipeline DICOM Converter — User Guide

**Version 1.0.0** · Practical guide for researchers and technologists

This guide explains how to use every part of the application in everyday work.
Technical details for developers live in other `docs/` files; this page is for **end users**.

---

## What this application does

NeuroPipeline DICOM Converter turns MRI **DICOM** folders into **BIDS-ready NIfTI** datasets using [dcm2niix](https://github.com/rordenlab/dcm2niix).

| You select… | The app… | You get… |
|-------------|----------|----------|
| A DICOM folder (one or many patients) | Scans series, classifies them, plans BIDS names | Preview + optional inventory spreadsheet |
| Convert / Queue | Runs dcm2niix and organizes outputs | `sub-*/ses-*/anat|func|dwi|fmap/` + report |

### Important safety rule

**Source DICOM files are never renamed, moved, deleted, or overwritten.**  
All naming edits happen in an in-memory plan or in files you save **outside** the DICOM folder.

---

## Install & launch (Windows)

1. Run `NeuroPipeline_DICOM_Converter_Setup.exe`.
2. Finish the installer (optional desktop shortcut).
3. Launch **NeuroPipeline DICOM Converter**.
4. If asked for **dcm2niix**, browse to `dcm2niix.exe` (or place it next to the app / on PATH).

No Python install is required for the packaged Windows build.

---

## Main window — navigation

Left sidebar:

| Page | Purpose |
|------|---------|
| **Convert** | Everyday one-folder conversion: analysis, BIDS preview, inventory, Convert |
| **Queue** | Convert many subjects one after another; pause / retry / recover after restart |
| **Settings** | dcm2niix path, defaults, custom **Naming Rules** |
| **Logs** | View conversion logs |

---

## Recommended everyday workflow (Convert)

```
Input folder  →  Output folder  →  Input analysis  →  BIDS Preview
       →  Subject/Session (optional)  →  Convert
```

### 1. Select Input Folder

Click **Browse…** next to **Input Folder**.

Supported layouts:

**A — One subject**
```
MyScan/
  *.dcm  (or nested series folders)
```

**B — Several subjects in one parent folder**
```
Batch/
  Patient_001/   ← DICOM for subject 1
  Patient_002/   ← DICOM for subject 2
  Patient_003/   ← DICOM for subject 3
```

The app scans **recursively to unlimited depth** (see [dicom_discovery.md](dicom_discovery.md)).

**Discovery mode** (Input analysis panel, default **Automatic**):

- **Automatic** — unique PatientIDs when possible; otherwise folder / deep-folder grouping
- **PatientID only** — group only by DICOM PatientID
- **Folder recursive** — always prefer folder-based subjects

Deep trees such as `subject/visit/raw/MR/DICOM` are supported. DICOM on disk is never modified.

Wait until **Input analysis** finishes.

### 2. Select Output Folder

Choose (or create) the **BIDS dataset root** where results will be written.
Prefer an empty folder for a new dataset.

### 3. Read Input analysis

You should see something like:

```
Detected subjects: 3

Detection method: Folder based grouping
Reason: PatientID collision detected

Patient_001
  Source: Patient_001
  Original PatientID: ANON
  DICOM files: 542
  Series: 34
```

or for unique PatientIDs:

```
Detected subjects: 2

Detection method: PatientID
…
Output:
BIDS dataset
```

If you expected several subjects but see only one, try **Folder recursive** discovery mode, or confirm each subject’s files sit under a distinct folder tree. Details: [dicom_discovery.md](dicom_discovery.md).

### 4. BIDS Preview (before any conversion)

The **BIDS Preview** panel shows:

- A **tree** of planned paths (e.g. `sub-001/anat/sub-001_T1w.nii.gz`) — files do **not** exist yet  
- An **editable table**: Include, Subject, Session, Task, Run, Acquisition, Direction, …

Buttons:

| Button | What it does |
|--------|----------------|
| **Refresh Preview** | Rebuild planned filenames from the table |
| **Reset Changes** | Restore automatic classification |
| **Validate Plan** | Check duplicates, labels, missing entities |
| **Save / Load Plan** | Optional `conversion_plan.json` (user choices only) |
| **Continue to Conversion** | Validate, then focus **Convert** |

Edits never touch DICOM. Invalid plans block conversion until fixed.

### 5. Subject / Session (optional)

- **Subject** empty → auto from PatientID (or folder name when folder routing applies).  
- For a **single** subject you may force a BIDS label (e.g. `001` → `sub-001`).  
- For **multi-subject** input, leave Subject empty so each patient keeps its own ID.  
- **Session** optional (e.g. `01` → `ses-01`).

### 6. Advanced options (collapsed)

Typical defaults:

- Validate output  
- Smart filenames  
- JSON metadata  
- Compress NIfTI (`.nii.gz`)

### 7. Convert

Click **Convert**.

Progress shows the current job / series. When finished:

- Open the output with **OPEN OUTPUT**  
- Review `conversion_report.html` and logs if something failed  

---

## Generate Inventory (no conversion)

Use this to inspect a dataset **without** writing NIfTI/BIDS.

1. Set **Input Folder** (and preferably **Output Folder**).  
2. Wait for analysis.  
3. Click **Generate Inventory**.

Creates (under Output, or `<input>/inventory` if Output is empty):

- `dicom_inventory.xlsx` — series metadata + protocol completeness  
- CSV copies of the same tables  

Useful columns include **Detected Acquisition Type**, **Naming Rule Applied**, planned BIDS filename, and a ✓/✗ protocol checklist per subject/session.

---

## Queue — large multi-subject batches

Open **Queue** when you have many subjects to convert over time.

1. Fill **Subject**, optional **Session**, **Input**, **Output**.  
2. **Add to queue** (repeat for each subject).  
3. **Start Queue**.

Controls:

- **Pause Queue** / **Resume Queue**  
- **Cancel Selected** / **Retry Failed** / **Remove Selected**  

Progress shows subject, current step, and %.  
Unfinished jobs are restored after restart from `conversion_queue.json`.

---

## Settings

### General

- Path to **dcm2niix**  
- Default output style / compression  
- Apply for this session  

### Naming Rules

Optional lab rules that run **after** automatic classification:

**Priority:** User rules → classifier → default BIDS naming  

Example idea: if ProtocolName contains `REST_AP` → `task=rest`, `datatype=func`, `suffix=bold`.

Use the table to Add / Edit / Delete / Duplicate / Import / Export / Validate / Save.  
With no rules saved, behaviour matches previous releases.

Rules appear in Preview and Inventory as **Naming Rule** / **Naming Rule Applied**.

---

## What good output looks like

```
MyBIDS/
  dataset_description.json
  participants.tsv
  sub-001/
    ses-01/
      anat/
        sub-001_ses-01_T1w.nii.gz
        sub-001_ses-01_T1w.json
      func/
        sub-001_ses-01_task-rest_bold.nii.gz
        …
  conversion_report.html
  _staging/          ← temporary dcm2niix outputs (internal)
```

ADC maps (when detected) may be kept under `derivatives/non-BIDS/` rather than the raw BIDS tree.

---

## Feature map (quick reference)

| Feature | Where | Writes NIfTI? | Touches DICOM? |
|---------|--------|---------------|----------------|
| Input analysis | Convert | No | No (read-only scan) |
| BIDS Preview | Convert | No | No |
| Generate Inventory | Convert | No | No |
| Convert | Convert | Yes (output folder) | No |
| Conversion Queue | Queue | Yes | No |
| Naming Rules | Settings | No (affects plan/names) | No |
| Logs | Logs | No | No |

---

## Troubleshooting

| Problem | What to try |
|---------|-------------|
| **dcm2niix not found** | Settings → set path, or place `dcm2niix.exe` next to the app |
| **No DICOM detected** | Confirm files are under Input; wait for scan to finish |
| **Only 1 subject but 3 folders** | Use one parent Input with 3 patient subfolders; shared PatientID triggers folder grouping |
| **Convert blocked by plan** | Preview → fix table or **Reset Changes** → **Validate Plan** |
| **Conversion failed** | Open HTML report + Logs page |
| **Disk space** | Free space on the output drive and retry |
| **Output not empty** | Confirm the dialog; existing files are not overwritten blindly |

---

## Data privacy & safety

- DICOM PatientName is not written into public inventory summaries.  
- Conversion logs avoid unnecessary absolute DICOM paths and patient names where possible.  
- Always keep an independent backup of raw DICOM archives.

---

## Need more detail?

| Topic | Document |
|-------|----------|
| Short install checklist | [user_manual.md](user_manual.md) |
| BIDS preview internals | [bids_conversion_preview.md](bids_conversion_preview.md) |
| Inventory columns | [dicom_inventory.md](dicom_inventory.md) |
| Naming rules JSON | [naming_rules.md](naming_rules.md) |
| Queue persistence | [conversion_queue.md](conversion_queue.md) |
| Architecture (developers) | [architecture.md](architecture.md) |

---

<p align="center">
  <img src="assets/logo_small.png" alt="NeuroPipeline" width="40" /><br/>
  <em>NeuroPipeline DICOM Converter</em>
</p>
