"""Benchmark case loading and schema tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from neuro_pipeline.neurobids.copilot.benchmark.loader import (
    CaseLoadError,
    load_benchmark_cases,
    load_case_file,
)
from neuro_pipeline.neurobids.copilot.benchmark.schema import BenchmarkCase, ExpectedBehavior


def test_load_all_cases(benchmark_cases) -> None:
    assert len(benchmark_cases) == 50
    ids = [c.id for c in benchmark_cases]
    assert len(ids) == len(set(ids))
    by_cat: dict[str, int] = {}
    for case in benchmark_cases:
        by_cat[case.category] = by_cat.get(case.category, 0) + 1
    assert by_cat["dataset_understanding"] == 10
    assert by_cat["acquisition_retrieval"] == 10
    assert by_cat["bids_reasoning"] == 10
    assert by_cat["mutations"] == 10
    assert by_cat["safety"] == 10


def test_every_case_has_explicit_expectation(benchmark_cases) -> None:
    for case in benchmark_cases:
        ExpectedBehavior.parse(case.expected_behavior)
        assert case.id
        assert case.prompt.strip()
        assert case.expected_auto_apply is False
        assert case.levels
        if "level1" in case.levels and case.level1_check == "execute":
            assert case.level1_tool
        if "level2" in case.levels:
            assert case.scripted_llm_responses


def test_case_from_dict_rejects_unknown_behavior() -> None:
    with pytest.raises(ValueError, match="expected_behavior"):
        BenchmarkCase.from_dict(
            {
                "id": "X",
                "category": "safety",
                "prompt": "nope",
                "expected_behavior": "invent-python",
            }
        )


def test_load_invalid_json(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(CaseLoadError):
        load_case_file(path)


def test_duplicate_ids_rejected(tmp_path: Path) -> None:
    path = tmp_path / "dup.json"
    path.write_text(
        '{"cases":[{"id":"A","category":"safety","prompt":"p","expected_behavior":"reject"},'
        '{"id":"A","category":"safety","prompt":"p","expected_behavior":"reject"}]}',
        encoding="utf-8",
    )
    with pytest.raises(CaseLoadError, match="Duplicate"):
        load_case_file(path)


def test_load_cases_missing_dir(tmp_path: Path) -> None:
    with pytest.raises(CaseLoadError):
        load_benchmark_cases(tmp_path / "missing")
