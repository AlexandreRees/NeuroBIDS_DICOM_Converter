# NeuroPipeline DICOM Converter — User Manual

Version 1.0.0

> **Full walkthrough (all features):** see **[USER_GUIDE.md](USER_GUIDE.md)**  
> (Convert, BIDS Preview, Inventory, Queue, Naming Rules, multi-subject folders)

<p align="center">
  <img src="assets/logo_small.png" alt="NeuroPipeline" width="48" />
</p>

## 1. Install the software

1. Download `NeuroPipeline_DICOM_Converter_Setup.exe`.
2. Double-click the installer.
3. Follow the install wizard (default location: Program Files).
4. Leave **Create a desktop icon** checked if you want a Desktop shortcut.
5. Finish the wizard and launch the application.

No Python installation is required.

## 2. Select a DICOM folder

1. Click **Select DICOM folder**.
2. Choose the folder that contains your MRI DICOM files (or patient folders).
3. Wait for the series table to fill.

The application lists detected series, modalities, and estimated types (`anat`, `func`, `dwi`, `fmap`).

## 3. Choose an output folder

1. Click **Select output folder**.
2. Choose an empty folder (recommended) where NIfTI files will be written.

## 4. Start conversion

1. Review OPTIONS:
   - **Create JSON metadata** — keep dcm2niix JSON sidecars
   - **Compress NIfTI** — write `.nii.gz`
   - **Validate output** — run post-conversion checks + HTML report
2. Click **START CONVERSION**.
3. Watch overall progress, current series, and estimated time.

If `dcm2niix` is missing, you will be prompted to locate `dcm2niix.exe`.

## 5. Understand the report

After a successful run with validation enabled:

- Click **Open HTML report** to open `conversion_report.html`.
- The report summarizes conversions, warnings, and errors.
- Click **Open NIfTI folder** to browse outputs.
- Click **Open logs** for `conversion.log` (no patient names / no absolute DICOM paths).

## 6. Generate a DICOM inventory (no conversion)

Use this when you want a spreadsheet of discovered series and protocol completeness **without** writing NIfTI/BIDS files.

1. Select an **Input Folder** and wait for analysis to finish.
2. Optionally set Subject / Session and an Output Folder.
3. Click **Generate Inventory**.
4. Open `dicom_inventory.xlsx` (plus CSV copies) in the output folder (or `<input>/inventory` if Output is empty).

See [dicom_inventory.md](dicom_inventory.md) for column definitions and architecture.

## 7. Preview and edit the BIDS conversion plan

After Input analysis finishes, the **BIDS Preview** panel shows the planned subject/datatype tree and an editable table.

1. Review planned filenames (no files exist yet).
2. Edit Include, Subject, Session, Task, Run, Acquisition, or Direction as needed.
3. Click **Refresh Preview**, then **Validate Plan**.
4. Optionally **Save Plan…** to `conversion_plan.json` (never inside the DICOM folder).
5. Click **Continue to Conversion** or **Convert**.

DICOM files are never modified by preview edits. See [bids_conversion_preview.md](bids_conversion_preview.md).

## 8. Custom BIDS naming

Laboratories can define optional naming rules under **Settings → Naming Rules**.

Rules refine BIDS entities (task, datatype, suffix, …) after automatic classification.
They appear in BIDS Preview and Inventory as **Naming Rule Applied**.

With no rules configured, naming is unchanged. See [naming_rules.md](naming_rules.md).

## 9. Managing large conversions

Use the **Queue** page to convert many subjects sequentially:

1. Add jobs (Subject, Session, Input, Output).
2. Click **Start Queue**.
3. Pause / Resume / Cancel / Retry Failed as needed.

The queue survives application restart via `conversion_queue.json`. See [conversion_queue.md](conversion_queue.md).

## Troubleshooting

| Problem | What to do |
|---------|------------|
| dcm2niix not found | Place `dcm2niix.exe` next to the app, add it to PATH, or browse when prompted |
| No series detected | Confirm the folder contains DICOM files |
| Conversion failed | Open the HTML report and logs |
| Disk space error | Free space on the output drive and retry |

## Data safety

- Source DICOM files are never modified.
- Existing NIfTI files are not overwritten silently (unique folder names are used).
