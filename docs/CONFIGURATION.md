# NeuroBIDS / Copilot configuration

## Application config

Primary YAML: `configs/default.yaml`

| Key | Meaning |
|-----|---------|
| `compression` | Write `.nii.gz` |
| `one_folder_per_patient` | Group outputs per subject |
| `preserve_json` | Keep dcm2niix JSON sidecars |
| `smart_naming` | Apply naming rules |
| `threads` | Conversion worker threads |
| `output_format` | e.g. `nii.gz` / BIDS |
| `dcm2niix_path` | Optional explicit path to dcm2niix |

Naming rules: `configs/naming_rules.yaml` (or user override under the user config root).

User writable data lives under:

- Windows: `%LOCALAPPDATA%\NeuroPipeline`
- Linux/macOS: `$XDG_STATE_HOME/NeuroPipeline` or `~/.local/state/NeuroPipeline`

## Copilot LLM (optional)

NeuroBIDS works **without** an LLM. When configured, the Copilot uses OpenAI-compatible Chat Completions.

| Variable | Example | Notes |
|----------|---------|-------|
| `NEUROBIDS_LLM_PROVIDER` | `openai` / `compatible` / `azure` / `local` / `none` | `local` needs no API key |
| `NEUROBIDS_LLM_MODEL` | `gpt-4o-mini` or `qwen3:30b` | Required for live use |
| `NEUROBIDS_LLM_API_KEY` | *(secret)* | Required except `local` |
| `NEUROBIDS_LLM_BASE_URL` | `http://localhost:11434/v1` | Ollama default for `local` |
| `NEUROBIDS_LLM_TIMEOUT` | `300` | Seconds (local defaults higher) |
| `NEUROBIDS_LLM_MAX_TOOL_CALLS` | `5` | Agent loop cap |
| `NEUROBIDS_LLM_MAX_RETRIES` | `2` | HTTP retries |
| `NEUROBIDS_LLM_RETRY_BACKOFF` | `0.5` | Seconds |
| `NEUROBIDS_COPILOT_PROVENANCE` | `1` / `0` | Persist audit JSONL |

### Local Ollama example

```bash
export NEUROBIDS_LLM_PROVIDER=local
export NEUROBIDS_LLM_MODEL=qwen3:30b
export NEUROBIDS_LLM_BASE_URL=http://localhost:11434/v1
```

Never commit API keys. The provider redacts secrets from logs/errors.

## Provenance

When enabled, Copilot writes versioned JSONL under:

`…/NeuroPipeline/logs/copilot_provenance/events.jsonl`

Export:

```python
from neuro_pipeline.neurobids.copilot.provenance import CopilotProvenanceStore
CopilotProvenanceStore().export_json("copilot_audit_export.json")
```

Records scrub API keys, absolute paths, PatientName, and binary/pixel payloads.

## Benchmark

```bash
# Deterministic FakeLLM (CI / release gate)
PYTHONPATH=src python -m neuro_pipeline.neurobids.copilot.benchmark --no-level3

# Optional live model (not a release gate)
PYTHONPATH=src python -m neuro_pipeline.neurobids.copilot.benchmark --live
```

See [`tests/benchmarks/README.md`](../tests/benchmarks/README.md).
