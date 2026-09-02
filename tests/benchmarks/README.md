# NeuroBIDS Copilot Benchmark

This suite evaluates the **complete Copilot behavior** — deterministic tools, the
agent loop, ChangeSets, and Apply/Reject — not merely generated text.

It does **not** add RAG, embeddings, fine-tuning, or new Copilot capabilities.
It does **not** use a real research dataset. Ground truth is a small synthetic
plan that can be checked by hand.

## Why it exists

NeuroBIDS Copilot can look correct in conversation while still:

- calling the wrong tool
- passing the wrong arguments
- inventing mappings
- proposing an incorrect diff
- skipping clarification
- auto-applying a mutation

The benchmark makes those failures explicit and repeatable.

## Dataset structure

Synthetic dataset: **4 subjects**, **5 sessions**, **24 acquisitions**.

| Subject | Sessions | Contents |
| --- | --- | --- |
| `001` | `01`, `02` (longitudinal) | T1w, func, DWI + localizer in `01`; T1w + func in `02` (**no DWI** in `02`) |
| `002` | `01` | T1w, func, DWI, ambiguous `ep2d_mixed`, excluded Phoenix report |
| `003` | `01` | T1w, localizer, unmapped `unknown_protocol` |
| `004` | `01` | T2w, FLAIR, task BOLD, SBRef, fmap AP/PA, multi-echo, run-02, conflicting `mprage`/`tse` |

Placeholder DICOM files contain the bytes `SYNTHETIC_DICOM_BYTES_NOT_PIXELS`.
Every case asserts they are never modified.

## Case categories

~184 JSON cases under `src/neuro_pipeline/neurobids/copilot/benchmark/cases/`
(target 150–200). The original 74 skill cases remain; tagged expansions
cover prompt robustness and edge conditions without changing the 24-acquisition
synthetic dataset.

Skill categories (original + expansions):

1. Dataset understanding
2. Acquisition retrieval
3. BIDS reasoning
4. Modality reasoning — T1w/T2w/FLAIR, BOLD rest/task, DWI, fieldmap AP/PA, SBRef, multi-echo, run/echo/acquisition entities, ambiguous/unclassified
5. Dataset audit — unmapped, ambiguous, missing modalities, structure, missing metadata, suspicious entities, fieldmap association, excluded
6. Mutations
7. Safety / ambiguity

Stress tags (a case keeps its skill `category` and may add `tags`):

- `nl_variation` — paraphrases of the same grounded request
- `typo` — misspellings with the same expected tools/facts
- `ambiguous` — underspecified prompts that must clarify
- `missing_metadata` — unclassified / unknown protocol / empty datatype
- `contradictory` — mutually exclusive instructions that must clarify
- `multi_step` — inspect then list or mutate
- `adversarial` — jailbreaks, PHI requests, auto-apply
- `unsafe_mutation` — unregistered apply/exec/convert/overwrite tools
- `large_dataset` — complete enumeration of all 24 acquisitions / 4 subjects / 5 sessions
- `longitudinal` — subject 001 ses-01 vs ses-02 (DWI missing in ses-02)
- `modality_edge` — SBRef vs BOLD, fmap AP/PA, multi-echo, run-02, mixed mprage/tse

Each case has an explicit `expected_behavior` (`reject`, `clarify`,
`read-only response`, `mutation proposal`) plus expected tools, arguments,
facts, and ChangeSet diffs where they apply. Scoring uses that deterministic
ground truth only — **never LLM-as-judge**.

## Evaluation methodology

Three layers, all runnable without an LLM API key:

| Level | What it tests | LLM |
| --- | --- | --- |
| **1** | Registered tools directly (`ToolRegistry.execute`) | none |
| **2** | `User prompt → CopilotAgent → FakeLLMProvider → ToolRegistry → ChangeSet` | scripted `FakeLLMProvider` |
| **3** | `CopilotController` Ask → pending ChangeSet → Apply / Reject | same FakeLLM scripts |

Level 3 uses the controller (Apply/Reject + preview refresh signal), not
fragile GUI timing.

## Metrics

The runner reports component rates, not a single vanity score:

- **accuracy** (alias of overall pass rate; omitted if safety is not 100%)
- answer accuracy
- tool selection accuracy
- tool argument accuracy
- mutation / ChangeSet correctness
- clarification accuracy
- over-clarification rate (clarify when a decisive answer was expected)
- safety / safety compliance
- automatic mutation rate (must stay 0)
- hallucination rate (numeric claims that contradict expected facts)
- latency (mean / median / p95)
- per-tag and per-category breakdowns

If safety is not 100%, **overall is omitted** so a high average cannot hide a
dangerous failure. Per-case results are always preserved in the JSON report.

## Deterministic vs live-LLM

| Mode | Command | API key |
| --- | --- | --- |
| **Regression (default)** | `pytest tests/benchmarks/` or `python -m neuro_pipeline.neurobids.copilot.benchmark` | not required |
| **Optional live** | `python -m neuro_pipeline.neurobids.copilot.benchmark --live` | `NEUROBIDS_LLM_PROVIDER` + credentials |

Live-LLM results are **not** a regression gate. They run the same ground-truth cases,
score against the same explicit `expected_*` ground truth (never LLM-as-judge),
and compare component metrics to the deterministic FakeLLM level2 baseline.

Reported live metrics include accuracy, tool/argument/clarification accuracy,
mutation correctness, safety, hallucination rate, automatic mutation rate,
over-clarification rate, latency, and token usage when the provider reports it.
Filter with `--tag` or `--category`.

Reports are written under `tests/benchmarks/reports/` with a UTC timestamp
(`latest.json` / `latest.md` are overwritten each run).

On some Linux cluster images, `pytest-qt` / PySide6 crash during plugin
import (Qt ABI mismatch). The deterministic suite does not need Qt:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest tests/benchmarks/
python -m neuro_pipeline.neurobids.copilot.benchmark --no-level3
```

Level 3 is skipped automatically when Qt cannot be imported.

## Known limitations

- Level 2 **tool selection** is only as good as the scripted FakeLLM turns.
  It verifies the agent loop (validation, ChangeSet, no auto-apply, refusals),
  not a production model's judgment. Use `--live` for that.
- Longitudinal inconsistency is detected from `inspect_subject` session
  datatypes; there is no dedicated “diff sessions” tool.
- `apply_changeset` is not a registered tool, so a model that requests it is
  rejected as `invalid_tool_name` (still a safe refusal).
- Fallback NIfTI naming assigns datatype `unknown` to included unclassified
  series; excluded series keep an empty datatype.
- The suite never claims BIDS compliance of a real study.
