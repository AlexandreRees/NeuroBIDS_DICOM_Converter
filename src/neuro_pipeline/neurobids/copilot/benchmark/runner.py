"""Deterministic NeuroBIDS Copilot benchmark runner."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

from neuro_pipeline.neurobids.copilot.benchmark.dataset import (
    build_benchmark_session,
    compute_ground_truth,
)
from neuro_pipeline.neurobids.copilot.benchmark.evaluators import (
    CaseResult,
    evaluate_level1,
    evaluate_level2,
    evaluate_level3,
)
from neuro_pipeline.neurobids.copilot.benchmark.loader import load_benchmark_cases
from neuro_pipeline.neurobids.copilot.benchmark.metrics import compute_metrics
from neuro_pipeline.neurobids.copilot.benchmark.report import write_reports
from neuro_pipeline.neurobids.copilot.benchmark.schema import BenchmarkCase, BenchmarkLevel
from neuro_pipeline.neurobids.copilot.session import CopilotSession

Evaluator = Callable[[BenchmarkCase, CopilotSession], CaseResult]


def _evaluators() -> dict[str, Evaluator]:
    return {
        BenchmarkLevel.LEVEL1.value: evaluate_level1,
        BenchmarkLevel.LEVEL2.value: evaluate_level2,
        BenchmarkLevel.LEVEL3.value: evaluate_level3,
    }


@dataclass
class BenchmarkRun:
    results: list[CaseResult] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    json_report: Path | None = None
    markdown_report: Path | None = None
    ground_truth: dict[str, Any] = field(default_factory=dict)
    skipped_levels: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return bool(self.results) and all(r.passed for r in self.results)


def run_benchmark(
    *,
    cases: Iterable[BenchmarkCase] | None = None,
    levels: Iterable[str] | None = None,
    dataset_root: Path | None = None,
    report_dir: Path | None = None,
    write: bool = True,
    include_level3: bool = True,
) -> BenchmarkRun:
    """Run the deterministic Copilot benchmark (FakeLLMProvider, no API key)."""
    session = build_benchmark_session(dataset_root)
    gt = compute_ground_truth(session)
    loaded = list(cases) if cases is not None else load_benchmark_cases()
    wanted = {str(lv) for lv in (levels or [lv.value for lv in BenchmarkLevel])}
    if not include_level3:
        wanted.discard(BenchmarkLevel.LEVEL3.value)

    evals = _evaluators()
    results: list[CaseResult] = []
    skipped: list[str] = []
    if BenchmarkLevel.LEVEL3.value in wanted:
        try:
            import os

            os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
            from PySide6.QtWidgets import QApplication

            if QApplication.instance() is None:
                QApplication([])
        except Exception as exc:  # noqa: BLE001
            skipped.append(f"level3 unavailable: {exc}")
            wanted.discard(BenchmarkLevel.LEVEL3.value)

    for case in loaded:
        for level in case.levels:
            if level not in wanted:
                continue
            fn = evals.get(level)
            if fn is None:
                continue
            results.append(fn(case, session))

    run = BenchmarkRun(results=results, ground_truth=gt, skipped_levels=skipped)
    run.metrics = compute_metrics(results)
    if write:
        json_path, md_path = write_reports(
            results,
            report_dir=report_dir,
            extra={"ground_truth": gt, "skipped_levels": skipped},
        )
        run.json_report = json_path
        run.markdown_report = md_path
    return run


__all__ = ["BenchmarkRun", "run_benchmark"]
