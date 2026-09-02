"""Level 3 — controller Apply/Reject (no fragile widget timing)."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from neuro_pipeline.neurobids.copilot.benchmark.evaluators import evaluate_level3
from neuro_pipeline.neurobids.copilot.benchmark.runner import run_benchmark
from neuro_pipeline.neurobids.copilot.plan_ops import plan_fingerprint


def _require_working_qt() -> None:
    try:
        from PySide6.QtWidgets import QApplication

        if QApplication.instance() is None:
            QApplication([])
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"PySide6/Qt unavailable: {exc}")


def test_level3_controller_cases(benchmark_cases, tmp_path) -> None:
    _require_working_qt()
    level3_cases = [c for c in benchmark_cases if "level3" in c.levels]
    run = run_benchmark(
        cases=level3_cases,
        levels=["level3"],
        dataset_root=tmp_path / "ds",
        report_dir=tmp_path / "reports",
        include_level3=True,
    )
    if run.skipped_levels:
        pytest.skip("; ".join(run.skipped_levels))
    failed = [r for r in run.results if not r.passed]
    assert not failed, "\n".join(f"{r.case_id}: {r.mismatches}" for r in failed)


def test_reject_leaves_plan_unchanged(benchmark_cases, benchmark_session) -> None:
    _require_working_qt()
    case = next(c for c in benchmark_cases if c.id == "MU-06")
    before = plan_fingerprint(benchmark_session.plan)
    result = evaluate_level3(case, benchmark_session)
    if any("unavailable" in m.lower() for m in result.mismatches):
        pytest.skip("; ".join(result.mismatches))
    assert result.passed, result.mismatches
    assert plan_fingerprint(benchmark_session.plan) == before


def test_apply_updates_plan_only_after_apply(benchmark_cases, benchmark_session) -> None:
    _require_working_qt()
    case = next(c for c in benchmark_cases if c.id == "MU-01")
    before = plan_fingerprint(benchmark_session.plan)
    result = evaluate_level3(case, benchmark_session)
    if any("unavailable" in m.lower() for m in result.mismatches):
        pytest.skip("; ".join(result.mismatches))
    assert result.passed, result.mismatches
    assert result.auto_applied is False
    assert plan_fingerprint(benchmark_session.plan) == before
