"""Optional live-LLM benchmark (NOT part of the deterministic regression suite).

This module is deliberately separate. The core Copilot regression benchmark
uses FakeLLMProvider and never requires an API key.

Run only when explicitly requested:

    python -m neuro_pipeline.neurobids.copilot.benchmark --live
"""

from __future__ import annotations

from neuro_pipeline.neurobids.copilot.benchmark.dataset import clone_benchmark_session
from neuro_pipeline.neurobids.copilot.benchmark.evaluators import CaseResult
from neuro_pipeline.neurobids.copilot.benchmark.schema import BenchmarkCase
from neuro_pipeline.neurobids.copilot.llm.agent import CopilotAgent
from neuro_pipeline.neurobids.copilot.llm.config import LLMConfig
from neuro_pipeline.neurobids.copilot.llm.provider import (
    UnavailableLLMProvider,
    build_provider_from_config,
)
from neuro_pipeline.neurobids.copilot.session import CopilotSession


def live_provider_available(config: LLMConfig | None = None) -> bool:
    cfg = config or LLMConfig.from_env()
    if cfg.provider in {"", "none", "off", "disabled", "fake", "mock"}:
        return False
    try:
        provider = build_provider_from_config(cfg)
    except Exception:
        return False
    return not isinstance(provider, UnavailableLLMProvider)


def run_live_case(case: BenchmarkCase, session: CopilotSession, *, config: LLMConfig | None = None) -> CaseResult:
    """Execute one case against a real provider.

    Scoring still uses explicit expected_* fields. This is an optional
    experiment, not a regression gate.
    """
    from neuro_pipeline.neurobids.copilot.benchmark.evaluators import (
        RecordingToolRegistry,
        _apply_and_check_final,
        _check_arguments,
        _check_auto_apply,
        _check_changeset,
        _check_dicom,
        _check_facts,
        _check_tool_selection,
        _classify_turn,
        _finalize_behavior,
        _preview_dict,
        _seal,
    )
    from neuro_pipeline.neurobids.copilot.benchmark.dataset import dicom_mtime_map, dicom_payload_map
    from neuro_pipeline.neurobids.copilot.changeset import ChangeSet
    from neuro_pipeline.neurobids.copilot.plan_ops import plan_fingerprint

    work = clone_benchmark_session(session)
    cfg = config or LLMConfig.from_env()
    provider = build_provider_from_config(cfg)
    registry = RecordingToolRegistry()
    before_fp = plan_fingerprint(work.plan)
    before_mtime = dicom_mtime_map(work)
    before_bytes = dicom_payload_map(work)

    result = CaseResult(
        case_id=case.id,
        level="live",
        category=case.category,
        prompt=case.prompt,
        passed=False,
        expected_behavior=case.expected_behavior,
        observed_behavior="",
        expected_tool=list(case.expected_tools),
        expected_arguments=case.expected_tool_arguments,
        expected_mutation=case.expected_changes or case.expected_change_set,
        notes="live-LLM evaluation (optional; not a regression gate)",
    )
    agent = CopilotAgent(session=work, registry=registry, provider=provider, config=cfg)
    turn = agent.handle(case.prompt)
    traces = list(turn.tool_traces or [])
    result.observed_tool = [t.tool_name for t in traces]
    result.observed_arguments = [dict(t.arguments) for t in traces]
    result.message = turn.message or (turn.error.message if turn.error else "")
    result.stopped_reason = turn.stopped_reason
    changeset = turn.changeset if isinstance(turn.changeset, ChangeSet) else None
    if changeset is not None:
        result.observed_mutation = _preview_dict(changeset)
    result.observed_behavior = _classify_turn(turn, changeset, registry)
    last_ok = next((c for c in reversed(registry.recorded) if c.get("ok")), None)
    from neuro_pipeline.neurobids.copilot.benchmark.evaluators import _enrich_tool_data

    data = _enrich_tool_data(dict((last_ok or {}).get("data") or {}))
    if data:
        _check_facts(result, case, data)
    _check_tool_selection(result, case, result.observed_tool)
    _check_arguments(result, case, result.observed_arguments)
    _check_changeset(result, case, changeset)
    if case.apply_changeset and changeset is not None:
        _apply_and_check_final(result, case, work, changeset)
    _check_dicom(result, work, before_mtime, before_bytes)
    _check_auto_apply(result, case, work, before_fp, applied_explicitly=False)
    _finalize_behavior(result, case)
    _seal(result)
    return result


__all__ = ["live_provider_available", "run_live_case"]
