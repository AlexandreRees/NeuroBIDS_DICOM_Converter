"""Level 1 — deterministic tool benchmark."""

from __future__ import annotations

from neuro_pipeline.neurobids.copilot.benchmark.evaluators import evaluate_level1
from neuro_pipeline.neurobids.copilot.benchmark.runner import run_benchmark


def test_level1_all_cases(benchmark_cases, benchmark_session, tmp_path) -> None:
    run = run_benchmark(
        cases=benchmark_cases,
        levels=["level1"],
        dataset_root=tmp_path / "ds",
        report_dir=tmp_path / "reports",
        include_level3=False,
    )
    failed = [r for r in run.results if not r.passed]
    assert not failed, _format_failures(failed)


def test_level1_inspect_dataset_direct(benchmark_cases, benchmark_session) -> None:
    case = next(c for c in benchmark_cases if c.id == "DU-01")
    result = evaluate_level1(case, benchmark_session)
    assert result.passed
    assert result.observed_tool == ["inspect_dataset"]
    assert result.auto_applied is False


def _format_failures(failed) -> str:
    lines = []
    for row in failed:
        lines.append(f"{row.case_id}: {row.mismatches} ({row.failure_categories})")
    return "\n".join(lines)
