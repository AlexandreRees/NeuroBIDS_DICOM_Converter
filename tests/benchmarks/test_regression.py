"""Full deterministic regression gate for NeuroBIDS Copilot."""

from __future__ import annotations

from pathlib import Path

from neuro_pipeline.neurobids.copilot.benchmark.compare import detect_numeric_hallucination
from neuro_pipeline.neurobids.copilot.benchmark.runner import run_benchmark


def test_full_deterministic_benchmark(tmp_path: Path) -> None:
    run = run_benchmark(
        dataset_root=tmp_path / "ds",
        report_dir=tmp_path / "reports",
        include_level3=True,
    )
    failed = [r for r in run.results if not r.passed]
    assert run.json_report is not None and run.json_report.exists()
    assert run.markdown_report is not None and run.markdown_report.exists()
    assert run.metrics["safety_failures"] == 0
    assert run.metrics["automatic_mutation_rate"] in {0, 0.0}
    assert not failed, "\n".join(
        f"{r.case_id}/{r.level}: {r.mismatches} [{r.failure_categories}]" for r in failed
    )


def test_hallucination_detector_flags_wrong_counts() -> None:
    flags = detect_numeric_hallucination(
        "There are 9 subjects in the dataset.",
        {"summary.n_subjects": 3},
    )
    assert flags
    clean = detect_numeric_hallucination(
        "There are 3 subjects in the dataset.",
        {"summary.n_subjects": 3},
    )
    assert not clean
