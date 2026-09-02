# Examples

Public sample materials for NeuroPipeline / NeuroBIDS (no patient data).

| Path | Description |
|------|-------------|
| [`synthetic_dataset/`](synthetic_dataset/) | Synthetic placeholder “DICOM” tree for demos and docs. See [`synthetic_dataset/README.md`](synthetic_dataset/README.md). |

## Preview mode

Run the GUI preview without a live model or real scans:

```bash
PYTHONPATH=src python -m neuro_pipeline.gui.preview
```

The preview command uses a built-in synthetic demo. For an on-disk example tree, open `examples/synthetic_dataset/dicom` in the convert UI (placeholders only — not real DICOM).
