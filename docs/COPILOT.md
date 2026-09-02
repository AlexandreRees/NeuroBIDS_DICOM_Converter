# NeuroBIDS Copilot V1

Natural-language layer over **typed tools** and **ChangeSets**. The deterministic NeuroBIDS core remains the source of truth.

## What Copilot does

- Answers dataset / acquisition / BIDS questions via registered tools
- Proposes plan mutations as a **ChangeSet** awaiting Apply/Reject
- Never modifies original DICOM
- Never auto-applies mutations
- Blocks Apply when the plan is stale or conversion is busy
- Optionally logs privacy-safe provenance (schema v1)

## What Copilot does not do

- No RAG / embeddings / autonomous agents
- No filesystem or shell tools
- No apply/rollback tools exposed to the LLM
- No LLM-as-judge scoring in benchmarks

## Demo without data or API keys

```bash
PYTHONPATH=src python -m neuro_pipeline.gui.preview
```

Synthetic dataset: [`examples/synthetic_dataset/`](../examples/synthetic_dataset/).

## Release verification snapshot

See [`release/COPILOT_V1_RELEASE_CHECKLIST.md`](../release/COPILOT_V1_RELEASE_CHECKLIST.md).
