# NeuroBIDS Copilot

The Copilot is an **optional** natural-language layer over typed tools and ChangeSets. The deterministic NeuroBIDS core (scan, plan, audit, convert) remains the source of truth.

NeuroBIDS works fully when the Copilot is disabled.

## What it does

- Answers dataset / acquisition / BIDS questions via registered tools
- Proposes plan mutations as a **ChangeSet** (Apply / Reject)
- Never modifies original DICOM
- Never auto-applies mutations
- Blocks Apply when the plan is stale or conversion is busy
- Optionally logs privacy-safe provenance

## What it does not do

- No RAG / embeddings / autonomous agents
- No filesystem, shell, or Python execution tools
- No direct dcm2niix / ConversionManager access for the LLM
- No fake health or confidence scores

## Configure in the app

**Settings → NeuroBIDS Copilot**

| Choice | Meaning |
|--------|---------|
| **Disabled** | Default. No LLM calls. |
| **Local AI (Ollama)** | Run a model on your machine. Inference stays local. |
| **OpenAI-compatible API** | Remote provider (OpenAI, Azure, or compatible servers). |

Use **Test connection** to see: Connected · Provider unavailable · Model unavailable · Invalid configuration · Timeout.

API keys are never displayed. NeuroBIDS does not write API keys to disk.

### Privacy

- **Local AI** — prompts stay on your computer (via Ollama).
- **Remote API** — prompts and dataset *context summaries* may leave your machine. Follow your institution’s policy for identifiable data.

Ollama is **not** required and is **not** bundled with NeuroBIDS.

## Environment variables

See [CONFIGURATION.md](CONFIGURATION.md). Default:

```text
NEUROBIDS_LLM_PROVIDER=none
```

## Demo without data or API keys

```bash
PYTHONPATH=src python -m neuro_pipeline.gui.preview
```

## Safety reminders

- Original DICOM is read-only
- Mutations require explicit Apply
- Stale ChangeSets and conversion-busy states block Apply
