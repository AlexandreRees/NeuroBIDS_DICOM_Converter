# Architecture

## High-level diagram

```mermaid
flowchart TB
    subgraph UI["GUI (PySide6)"]
        MW[MainWindow]
        DLG[Dialogs]
    end

    subgraph Workers["Workers (QThread)"]
        SW[ScanWorker]
        CW[ConversionWorker]
        IW[InventoryWorker]
    end

    subgraph Domain["Domain layer"]
        DP[DicomParser]
        CV[Converter]
        IM[InventoryManager]
        CP[BIDSConversionPlan]
        NE[SmartFilenameEngine]
        CFG[AppConfig / YAML]
        LOG[conversion.log]
    end

    subgraph External["External tools"]
        D2N[dcm2niix]
        DCM[DICOM files]
        NII[NIfTI + JSON]
        XLS[dicom_inventory.xlsx]
    end

    MW -->|select folders / options| SW
    MW -->|Convert| CW
    MW -->|Generate Inventory| IW
    MW -->|BIDS Preview edits| CP
    SW --> DP
    DP --> DCM
    CW --> CV
    CW -->|validated plan| CP
    IW --> IM
    IM --> DP
    IM --> XLS
    CP --> DP
    CV --> D2N
    CV --> NE
    CV --> LOG
    D2N --> NII
    CFG --> MW
    CFG --> CV
    CW -->|ProgressInfo / SeriesStatus| MW
    SW -->|DicomSeries list| MW
    MW --> DLG
```

## Layers

1. **Presentation** – `gui/` renders state and collects user choices.
2. **Orchestration** – `workers/` + `ConversionManager` run the pipeline off the UI thread.
3. **Domain** – `dicom/`, `converter/`, `validation/`, `utils/`, `models/`.
4. **Infrastructure** – `config/`, `logging/`, bundled YAML, PyInstaller entrypoints.

## Conversion + validation flow

```
DICOM folder
    → ScanWorker / DicomParser (+ SequenceClassifier)
    → ConversionManager.prepare (dcm2niix, disk, output)
    → Converter / dcm2niix
    → NIfTI + sidecars
    → NiftiValidator / DiffusionValidator / MetadataValidator
    → conversion_report.html
```

## NeuroBIDS product architecture

```text
                NEUROBIDS
                    │
        ┌───────────┴───────────┐
        │                       │
   Deterministic Core       Copilot
        │                       │
   BIDS / DICOM / QC      Natural language
   validation / export       reasoning
        │                       │
        └───────────┬───────────┘
                    │
                ChangeSet
                    │
             Human approval
                    │
                  Apply
```

GUI stages: Discover → Map → Audit → Protect → Release. Conversion / Queue / Settings / Logs remain tools. See `docs/neurobids_workflow.md`.

The LLM never touches DICOM, the filesystem, or dcm2niix. It calls typed tools only.

## Design rules

- No `subprocess` calls from the GUI.
- No hardcoded naming rules.
- Dataclasses for transferable state.
- Exceptions in `utils/exceptions.py` map to user dialogs.
- Frozen vs source path resolution isolated in `config/paths.py`.

## Future modules (not implemented yet)

- `bids/` – BIDS layout export
- `qc/` – MRIQC / custom QC
- `reports/` – HTML/PDF session reports
