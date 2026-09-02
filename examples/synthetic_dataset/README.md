# Synthetic example dataset

**Synthetic only — not real imaging data.**

This folder contains placeholder DICOM-like files (`*.dcm`) whose payload is a short `SYNTHETIC` marker byte string. There are **no patient identifiers (PHI)**, **no pixel data**, and **no clinical content**. Files exist only so the GUI and Copilot tooling can demonstrate folder layout, subject/session navigation, and preview workflows without shipping real DICOM.

## Layout

```
synthetic_dataset/
  dicom/
    sub-<id>/
      ses-<id>/
        <series_description>/
          IM0001.dcm   # placeholder bytes, not a real DICOM
```

Generated with `neuro_pipeline.neurobids.copilot.benchmark.dataset.build_benchmark_session` (benchmark synthetic builder). Do not treat these files as convertible medical images.

## Open in the app / preview mode

From the repository root (with dependencies installed):

```bash
# Lightweight GUI preview (built-in demo provider; no real LLM or DICOM decode)
PYTHONPATH=src python -m neuro_pipeline.gui.preview

# Or point the main convert UI at this folder's dicom/ tree as an input dataset
# (placeholders will not convert to NIfTI — use for layout / UX exploration only)
PYTHONPATH=src python -m neuro_pipeline.gui
```

Preview mode loads an in-memory demo dataset by default. To explore **this** on-disk package, select `examples/synthetic_dataset/dicom` as the DICOM input directory in the convert UI.

## Regenerating placeholders

```bash
PYTHONPATH=src python -c "
from pathlib import Path
from neuro_pipeline.neurobids.copilot.benchmark.dataset import build_benchmark_session
build_benchmark_session(Path('examples/synthetic_dataset'))
"
```

Then remove any generated `bids_out/` directory if present; this package only ships `dicom/` placeholders plus this README.
