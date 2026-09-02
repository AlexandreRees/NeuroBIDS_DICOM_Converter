"""Live LLM benchmark harness tests (mocked providers; no real API)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from neuro_pipeline.neurobids.copilot.benchmark.live import (
    TrackingLLMProvider,
    compare_live_to_baseline,
    run_live_benchmark,
    run_live_case,
)
from neuro_pipeline.neurobids.copilot.benchmark.loader import load_benchmark_cases
from neuro_pipeline.neurobids.copilot.benchmark.metrics import (
    compute_live_metrics,
    over_clarification_rate,
)
from neuro_pipeline.neurobids.copilot.benchmark.report import render_markdown, write_reports
from neuro_pipeline.neurobids.copilot.llm.config import LLMConfig
from neuro_pipeline.neurobids.copilot.llm.openai_compatible import OpenAICompatibleProvider
from neuro_pipeline.neurobids.copilot.llm.provider import FakeLLMProvider


class _FakeResponse:
    def __init__(self, body: dict[str, Any]) -> None:
        self._raw = json.dumps(body).encode("utf-8")

    def read(self) -> bytes:
        return self._raw

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None


def test_openai_provider_records_usage() -> None:
    def fake_urlopen(req: Any, timeout: float = 0):  # noqa: ANN401
        return _FakeResponse(
            {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": json.dumps(
                                {"type": "message", "content": "hello"}
                            ),
                        }
                    }
                ],
                "usage": {
                    "prompt_tokens": 11,
                    "completion_tokens": 3,
                    "total_tokens": 14,
                },
            }
        )

    provider = OpenAICompatibleProvider(
        LLMConfig(provider="openai", api_key="sk-test", model="m", max_retries=0),
        urlopen=fake_urlopen,
        sleep=lambda _s: None,
    )
    out = provider.generate(system="s", user_payload="u", tools=[])
    assert out.type.value == "message"
    assert provider.last_usage["prompt_tokens"] == 11
    assert provider.last_usage["completion_tokens"] == 3
    assert provider.last_usage["total_tokens"] == 14


def test_tracking_provider_sums_latency_and_tokens() -> None:
    class _Inner(FakeLLMProvider):
        def generate(self, **kwargs):  # type: ignore[no-untyped-def]
            self.last_usage = {
                "prompt_tokens": 5,
                "completion_tokens": 2,
                "total_tokens": 7,
            }
            return super().generate(**kwargs)

    inner = _Inner([{"type": "message", "content": "a"}, {"type": "message", "content": "b"}])
    tracker = TrackingLLMProvider(inner)
    tracker.generate(system="s", user_payload="u1", tools=[])
    tracker.generate(system="s", user_payload="u2", tools=[])
    totals = tracker.totals()
    assert totals["n_provider_calls"] == 2
    assert totals["prompt_tokens"] == 10
    assert totals["completion_tokens"] == 4
    assert totals["total_tokens"] == 14
    assert totals["latency_ms"] is not None and totals["latency_ms"] >= 0


def test_live_case_matches_level2_with_scripted_provider(benchmark_session) -> None:
    cases = load_benchmark_cases()
    case = next(c for c in cases if c.id.startswith("DU-") and c.scripted_llm_responses)
    provider = FakeLLMProvider(list(case.scripted_llm_responses or []))
    live = run_live_case(case, benchmark_session, provider=provider)
    assert live.level == "live"
    assert live.latency_ms is not None
    assert live.passed is True
    assert "not_over_clarified" in live.checks


def test_live_benchmark_compares_to_fakellm_baseline(benchmark_session, tmp_path: Path) -> None:
    cases = load_benchmark_cases()
    # Use a stable subset that covers multiple categories.
    wanted = {
        "DU-01",
        "AR-01",
        "BR-01",
        "MU-01",
        "SF-01",
    }
    subset = [c for c in cases if c.id in wanted]
    assert len(subset) == len(wanted)

    run = run_live_benchmark(
        cases=subset,
        provider_factory=lambda c: FakeLLMProvider(list(c.scripted_llm_responses or [])),
        report_dir=tmp_path,
        compare_baseline=True,
        write=True,
    )
    assert len(run.live_results) == len(subset)
    assert len(run.baseline_results) == len(subset)
    assert run.comparison["paired_cases"] == len(subset)
    assert run.comparison["pass_agreement_rate"] == 1.0
    assert run.metrics["mode"] == "live"
    assert run.metrics["scoring"].startswith("explicit ground truth")
    assert "tool_selection_accuracy" in run.metrics
    assert "over_clarification_rate" in run.metrics
    assert "latency" in run.metrics
    assert "baseline" in run.metrics
    assert run.markdown_report is not None
    md = run.markdown_report.read_text(encoding="utf-8")
    assert "Tool selection accuracy" in md
    assert "Over-clarification rate" in md
    assert "FakeLLM baseline comparison" in md
    assert "Latency" in md


def test_live_full_suite_with_scripted_factory_agrees_with_baseline(tmp_path: Path) -> None:
    """Same cases + same scripts ⇒ live path agrees with FakeLLM level2."""
    cases = load_benchmark_cases()
    assert len(cases) >= 50
    run = run_live_benchmark(
        cases=cases,
        provider_factory=lambda c: FakeLLMProvider(list(c.scripted_llm_responses or [])),
        report_dir=tmp_path,
        compare_baseline=True,
        write=False,
    )
    assert len(run.live_results) == len(cases)
    assert run.comparison["pass_agreement_rate"] == 1.0
    assert run.comparison["behavior_agreement_rate"] == 1.0
    assert all(r.passed for r in run.live_results)
    assert (run.metrics.get("automatic_mutation_rate") or 0) == 0
    assert (run.metrics.get("hallucination_rate") or 0) == 0


def test_over_clarification_detected(benchmark_session) -> None:
    cases = load_benchmark_cases()
    case = next(
        c
        for c in cases
        if c.expected_behavior == "read-only response" and c.scripted_llm_responses
    )
    provider = FakeLLMProvider(
        [{"type": "clarify", "question": "Which subject do you mean?"}]
    )
    live = run_live_case(case, benchmark_session, provider=provider)
    assert live.checks.get("not_over_clarified") is False
    assert "over_clarification" in live.failure_categories
    assert over_clarification_rate([live]) == 1.0


def test_live_case_records_tokens_from_provider(benchmark_session) -> None:
    cases = load_benchmark_cases()
    case = next(c for c in cases if c.id.startswith("DU-") and c.scripted_llm_responses)

    class _UsageFake(FakeLLMProvider):
        def generate(self, **kwargs):  # type: ignore[no-untyped-def]
            self.last_usage = {
                "prompt_tokens": 40,
                "completion_tokens": 12,
                "total_tokens": 52,
            }
            return super().generate(**kwargs)

    live = run_live_case(
        case,
        benchmark_session,
        provider=_UsageFake(list(case.scripted_llm_responses or [])),
    )
    assert live.passed
    assert live.prompt_tokens == 40 * len(case.scripted_llm_responses or [])
    assert live.completion_tokens == 12 * len(case.scripted_llm_responses or [])
    assert live.total_tokens == 52 * len(case.scripted_llm_responses or [])
    assert live.latency_ms is not None


def test_compare_and_metrics_render(tmp_path: Path) -> None:
    from neuro_pipeline.neurobids.copilot.benchmark.evaluators import CaseResult

    live = [
        CaseResult(
            case_id="X",
            level="live",
            category="dataset_understanding",
            prompt="p",
            passed=True,
            expected_behavior="read-only response",
            observed_behavior="read-only response",
            checks={"tool_selection": True, "not_over_clarified": True, "no_hallucination": True},
            latency_ms=12.5,
            prompt_tokens=10,
            completion_tokens=4,
            total_tokens=14,
        )
    ]
    base = [
        CaseResult(
            case_id="X",
            level="level2",
            category="dataset_understanding",
            prompt="p",
            passed=True,
            expected_behavior="read-only response",
            observed_behavior="read-only response",
            checks={"tool_selection": True},
        )
    ]
    comparison = compare_live_to_baseline(live, base)
    metrics = compute_live_metrics(live, baseline_results=base)
    assert comparison["pass_agreement_rate"] == 1.0
    assert metrics["token_usage"]["total_tokens"] == 14
    json_path, md_path = write_reports(
        live,
        report_dir=tmp_path,
        title="Live Test",
        metrics_override=metrics,
        extra={"comparison": comparison},
    )
    text = md_path.read_text(encoding="utf-8")
    assert "Live Test" in text
    assert "Token usage" in text
    assert "14" in text
    assert json_path.exists()
    assert "Token usage" in render_markdown(
        {
            "title": "Live Test",
            "metrics": metrics,
            "failures": [],
            "extra": {"comparison": comparison},
        }
    )


def test_live_provider_unavailable_raises() -> None:
    with pytest.raises(RuntimeError, match="No usable LLM provider"):
        run_live_benchmark(
            cases=load_benchmark_cases()[:1],
            config=LLMConfig(provider="none"),
            write=False,
        )
