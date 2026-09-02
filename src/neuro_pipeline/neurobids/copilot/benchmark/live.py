"""Optional live-LLM benchmark scored against explicit ground truth.

This is separate from the deterministic FakeLLM regression suite.
Scoring never uses LLM-as-judge — only the existing expected_* fields.

    python -m neuro_pipeline.neurobids.copilot.benchmark --live
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from neuro_pipeline.neurobids.copilot.benchmark.compare import (
    contains_all,
    detect_numeric_hallucination,
)
from neuro_pipeline.neurobids.copilot.benchmark.dataset import (
    build_benchmark_session,
    clone_benchmark_session,
    compute_ground_truth,
    dicom_mtime_map,
    dicom_payload_map,
)
from neuro_pipeline.neurobids.copilot.benchmark.evaluators import (
    CaseResult,
    RecordingToolRegistry,
    _apply_and_check_final,
    _attempted_tool,
    _check_arguments,
    _check_auto_apply,
    _check_changeset,
    _check_dicom,
    _check_facts,
    _check_tool_selection,
    _classify_turn,
    _enrich_tool_data,
    _finalize_behavior,
    _preview_dict,
    _seal,
    evaluate_level2,
)
from neuro_pipeline.neurobids.copilot.benchmark.loader import load_benchmark_cases
from neuro_pipeline.neurobids.copilot.benchmark.metrics import compute_live_metrics, compute_metrics
from neuro_pipeline.neurobids.copilot.benchmark.report import write_reports
from neuro_pipeline.neurobids.copilot.benchmark.schema import (
    BenchmarkCase,
    ExpectedBehavior,
    FailureCategory,
)
from neuro_pipeline.neurobids.copilot.changeset import ChangeSet
from neuro_pipeline.neurobids.copilot.llm.agent import CopilotAgent
from neuro_pipeline.neurobids.copilot.llm.config import LLMConfig
from neuro_pipeline.neurobids.copilot.llm.provider import (
    LLMProvider,
    UnavailableLLMProvider,
    build_provider_from_config,
)
from neuro_pipeline.neurobids.copilot.plan_ops import plan_fingerprint
from neuro_pipeline.neurobids.copilot.session import CopilotSession


class TrackingLLMProvider(LLMProvider):
    """Wraps a provider to record per-call latency and token usage."""

    name = "tracking"

    def __init__(self, inner: LLMProvider) -> None:
        self.inner = inner
        self.name = getattr(inner, "name", "tracking")
        self.calls: list[dict[str, Any]] = []

    @property
    def model(self) -> str:
        return getattr(self.inner, "model", "") or ""

    def generate(
        self,
        *,
        system: str,
        user_payload: str,
        tools: Any,
        transcript: Any = None,
    ):
        t0 = time.perf_counter()
        out = self.inner.generate(
            system=system,
            user_payload=user_payload,
            tools=tools,
            transcript=transcript,
        )
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        usage = dict(getattr(self.inner, "last_usage", None) or {})
        self.calls.append(
            {
                "latency_ms": elapsed_ms,
                "prompt_tokens": usage.get("prompt_tokens"),
                "completion_tokens": usage.get("completion_tokens"),
                "total_tokens": usage.get("total_tokens"),
            }
        )
        return out

    def totals(self) -> dict[str, Any]:
        lat = [float(c["latency_ms"]) for c in self.calls]
        prompt = [int(c["prompt_tokens"]) for c in self.calls if c.get("prompt_tokens") is not None]
        completion = [
            int(c["completion_tokens"]) for c in self.calls if c.get("completion_tokens") is not None
        ]
        total = [int(c["total_tokens"]) for c in self.calls if c.get("total_tokens") is not None]
        return {
            "latency_ms": sum(lat) if lat else None,
            "prompt_tokens": sum(prompt) if prompt else None,
            "completion_tokens": sum(completion) if completion else None,
            "total_tokens": sum(total) if total else None,
            "n_provider_calls": len(self.calls),
        }


def live_provider_available(config: LLMConfig | None = None) -> bool:
    cfg = config or LLMConfig.from_env()
    if cfg.provider in {"", "none", "off", "disabled", "fake", "mock"}:
        return False
    try:
        provider = build_provider_from_config(cfg)
    except Exception:
        return False
    if isinstance(provider, UnavailableLLMProvider):
        return False
    if (cfg.provider or "").lower() == "local":
        # Fail fast when Ollama/local server is not listening.
        base = (cfg.base_url or "http://localhost:11434/v1").rstrip("/")
        probe = base[: -len("/v1")] + "/api/tags" if base.endswith("/v1") else base + "/models"
        try:
            import urllib.request

            with urllib.request.urlopen(probe, timeout=2.0) as resp:
                resp.read(64)
        except Exception:
            return False
    return True


def run_live_case(
    case: BenchmarkCase,
    session: CopilotSession,
    *,
    config: LLMConfig | None = None,
    provider: LLMProvider | None = None,
) -> CaseResult:
    """Execute one case against a real (or injected) provider.

    Scoring uses the same explicit expected_* ground truth as FakeLLM level2.
    """
    work = clone_benchmark_session(session)
    cfg = config or LLMConfig.from_env()
    raw_provider = provider or build_provider_from_config(cfg)
    tracker = TrackingLLMProvider(raw_provider)
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
        notes="live-LLM evaluation scored against explicit ground truth (not LLM-as-judge)",
        tags=list(case.tags),
        provider_name=getattr(raw_provider, "name", ""),
        model_name=getattr(raw_provider, "model", "") or cfg.model,
    )

    t0 = time.perf_counter()
    agent = CopilotAgent(session=work, registry=registry, provider=tracker, config=cfg)
    turn = agent.handle(case.prompt)
    result.latency_ms = round((time.perf_counter() - t0) * 1000.0, 2)
    totals = tracker.totals()
    result.prompt_tokens = totals.get("prompt_tokens")
    result.completion_tokens = totals.get("completion_tokens")
    result.total_tokens = totals.get("total_tokens")
    if totals.get("latency_ms") is not None:
        result.latency_ms = round(float(totals["latency_ms"]), 2)

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
    data = _enrich_tool_data(dict((last_ok or {}).get("data") or {}))
    if data:
        _check_facts(result, case, data)

    if case.expected_answer_contains:
        missing = contains_all(result.message, case.expected_answer_contains)
        result.checks["answer_contains"] = not missing
        result.mismatches.extend(missing)
        if missing:
            result.failure_categories.append(FailureCategory.INCOMPLETE_ANSWER.value)

    hallu = detect_numeric_hallucination(
        result.message,
        case.expected_answer if isinstance(case.expected_answer, dict) else None,
    )
    result.checks["no_hallucination"] = not hallu
    if hallu:
        result.mismatches.extend(hallu)
        result.failure_categories.append(FailureCategory.HALLUCINATION.value)

    if case.expected_stopped_reason and turn.stopped_reason != case.expected_stopped_reason:
        result.mismatches.append(
            f"stopped_reason: expected {case.expected_stopped_reason!r}, "
            f"observed {turn.stopped_reason!r}"
        )

    attempted = _attempted_tool(turn, traces, [])
    if result.observed_behavior == ExpectedBehavior.REJECT.value and not result.observed_tool:
        result.observed_tool = [attempted] if attempted else []

    _check_tool_selection(result, case, result.observed_tool, attempted=attempted)
    if result.observed_arguments:
        _check_arguments(result, case, result.observed_arguments)
    elif case.expected_behavior != ExpectedBehavior.REJECT.value:
        _check_arguments(result, case, result.observed_arguments)

    _check_changeset(result, case, changeset)
    if case.apply_changeset and changeset is not None:
        _apply_and_check_final(result, case, work, changeset)
    _check_dicom(result, work, before_mtime, before_bytes)
    _check_auto_apply(result, case, work, before_fp, applied_explicitly=case.apply_changeset)

    _finalize_behavior(result, case)
    _seal(result)
    return result


@dataclass
class LiveBenchmarkRun:
    live_results: list[CaseResult] = field(default_factory=list)
    baseline_results: list[CaseResult] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    comparison: dict[str, Any] = field(default_factory=dict)
    json_report: Path | None = None
    markdown_report: Path | None = None
    ground_truth: dict[str, Any] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return bool(self.live_results) and all(r.passed for r in self.live_results)


def run_live_benchmark(
    *,
    cases: Iterable[BenchmarkCase] | None = None,
    config: LLMConfig | None = None,
    provider: LLMProvider | None = None,
    provider_factory: Callable[[BenchmarkCase], LLMProvider] | None = None,
    dataset_root: Path | None = None,
    report_dir: Path | None = None,
    write: bool = True,
    compare_baseline: bool = True,
) -> LiveBenchmarkRun:
    """Run all cases with a real LLM and compare to FakeLLM level2 baseline."""
    cfg = config or LLMConfig.from_env()
    if provider is None and provider_factory is None and not live_provider_available(cfg):
        raise RuntimeError(
            "No usable LLM provider configured. Set NEUROBIDS_LLM_PROVIDER "
            "(and credentials if required)."
        )

    session = build_benchmark_session(dataset_root)
    gt = compute_ground_truth(session)
    loaded = list(cases) if cases is not None else load_benchmark_cases()

    shared = provider
    if shared is None and provider_factory is None:
        shared = build_provider_from_config(cfg)

    live_results: list[CaseResult] = []
    baseline_results: list[CaseResult] = []
    for case in loaded:
        case_provider = provider_factory(case) if provider_factory is not None else shared
        assert case_provider is not None
        live_results.append(run_live_case(case, session, config=cfg, provider=case_provider))
        if compare_baseline and case.scripted_llm_responses:
            baseline_results.append(evaluate_level2(case, session))

    comparison = compare_live_to_baseline(live_results, baseline_results) if compare_baseline else {}
    metrics = compute_live_metrics(live_results, baseline_results=baseline_results)

    run = LiveBenchmarkRun(
        live_results=live_results,
        baseline_results=baseline_results,
        metrics=metrics,
        comparison=comparison,
        ground_truth=gt,
    )
    if write:
        json_path, md_path = write_reports(
            live_results,
            report_dir=report_dir,
            title="NeuroBIDS Copilot Live LLM Benchmark",
            metrics_override=metrics,
            extra={
                "mode": "live",
                "ground_truth": gt,
                "baseline_metrics": compute_metrics(baseline_results) if baseline_results else {},
                "comparison": comparison,
                "live_metrics": metrics,
                "provider": cfg.provider,
                "model": cfg.model or getattr(shared, "model", ""),
            },
        )
        run.json_report = json_path
        run.markdown_report = md_path
    return run


def compare_live_to_baseline(
    live_results: list[CaseResult],
    baseline_results: list[CaseResult],
) -> dict[str, Any]:
    """Case-level agreement between live LLM and FakeLLM level2 (same ground truth)."""
    by_id = {r.case_id: r for r in baseline_results}
    paired = 0
    agree_pass = 0
    agree_behavior = 0
    agree_tools = 0
    divergences: list[dict[str, Any]] = []
    for live in live_results:
        base = by_id.get(live.case_id)
        if base is None:
            continue
        paired += 1
        if live.passed == base.passed:
            agree_pass += 1
        if live.observed_behavior == base.observed_behavior:
            agree_behavior += 1
        if list(live.observed_tool) == list(base.observed_tool):
            agree_tools += 1
        if live.passed != base.passed or live.observed_behavior != base.observed_behavior:
            divergences.append(
                {
                    "case_id": live.case_id,
                    "live_passed": live.passed,
                    "baseline_passed": base.passed,
                    "live_behavior": live.observed_behavior,
                    "baseline_behavior": base.observed_behavior,
                    "live_tools": list(live.observed_tool),
                    "baseline_tools": list(base.observed_tool),
                    "live_mismatches": list(live.mismatches),
                }
            )

    def _rate(n: int, d: int) -> float | None:
        return round(n / d, 4) if d else None

    return {
        "paired_cases": paired,
        "pass_agreement_rate": _rate(agree_pass, paired),
        "behavior_agreement_rate": _rate(agree_behavior, paired),
        "tool_agreement_rate": _rate(agree_tools, paired),
        "divergences": divergences,
        "note": (
            "Agreement compares live LLM outcomes to FakeLLM level2 on the same cases. "
            "Both are scored against explicit ground truth — not against each other as judge."
        ),
    }


__all__ = [
    "LiveBenchmarkRun",
    "TrackingLLMProvider",
    "compare_live_to_baseline",
    "live_provider_available",
    "run_live_benchmark",
    "run_live_case",
]
