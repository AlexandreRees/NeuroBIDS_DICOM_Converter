"""Level 2 — CopilotAgent + FakeLLMProvider (no API key)."""

from __future__ import annotations

from neuro_pipeline.neurobids.copilot.benchmark.evaluators import evaluate_level2
from neuro_pipeline.neurobids.copilot.benchmark.runner import run_benchmark
from neuro_pipeline.neurobids.copilot.llm.provider import FakeLLMProvider


def test_level2_all_cases(benchmark_cases, tmp_path) -> None:
    run = run_benchmark(
        cases=benchmark_cases,
        levels=["level2"],
        dataset_root=tmp_path / "ds",
        report_dir=tmp_path / "reports",
        include_level3=False,
    )
    failed = [r for r in run.results if not r.passed]
    assert not failed, _format_failures(failed)
    assert all(r.level == "level2" for r in run.results)


def test_level2_uses_fake_provider(benchmark_cases, benchmark_session) -> None:
    case = next(c for c in benchmark_cases if c.id == "DU-01")
    result = evaluate_level2(case, benchmark_session)
    assert result.passed
    assert result.stopped_reason == "message"


def test_level2_mutation_not_applied(benchmark_cases, benchmark_session) -> None:
    case = next(c for c in benchmark_cases if c.id == "SF-10")
    before = {i.include_in_conversion for i in benchmark_session.plan.items}
    result = evaluate_level2(case, benchmark_session)
    assert result.passed
    after = {i.include_in_conversion for i in benchmark_session.plan.items}
    assert after == before
    assert result.auto_applied is False


def test_fake_llm_provider_is_the_regression_backend() -> None:
    provider = FakeLLMProvider([{"type": "message", "content": "ok"}])
    assert provider.name == "fake"


def _format_failures(failed) -> str:
    lines = []
    for row in failed:
        lines.append(f"{row.case_id}: {row.mismatches} ({row.failure_categories})")
    return "\n".join(lines)
