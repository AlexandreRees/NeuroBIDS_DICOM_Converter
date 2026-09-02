"""Benchmark case loading and schema tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from neuro_pipeline.neurobids.copilot.benchmark.loader import (
    CaseLoadError,
    load_benchmark_cases,
    load_case_file,
)
from neuro_pipeline.neurobids.copilot.benchmark.schema import (
    VALID_TAGS,
    BenchmarkCase,
    ExpectedBehavior,
)


def test_load_all_cases(benchmark_cases) -> None:
    assert 150 <= len(benchmark_cases) <= 220
    ids = [c.id for c in benchmark_cases]
    assert len(ids) == len(set(ids))
    by_cat: dict[str, int] = {}
    seen_tags: set[str] = set()
    for case in benchmark_cases:
        by_cat[case.category] = by_cat.get(case.category, 0) + 1
        for tag in case.tags:
            assert tag in VALID_TAGS, f"{case.id}: unknown tag {tag}"
            seen_tags.add(tag)
    assert by_cat["dataset_understanding"] >= 10
    assert by_cat["acquisition_retrieval"] >= 10
    assert by_cat["bids_reasoning"] >= 10
    assert by_cat["modality_reasoning"] >= 15
    assert by_cat["dataset_audit"] >= 9
    assert by_cat["mutations"] >= 10
    assert by_cat["safety"] >= 10
    assert seen_tags == set(VALID_TAGS)


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


def test_case_from_dict_rejects_unknown_tag() -> None:
    with pytest.raises(ValueError, match="unknown tags"):
        BenchmarkCase.from_dict(
            {
                "id": "X",
                "category": "safety",
                "prompt": "nope",
                "expected_behavior": "reject",
                "tags": ["not_a_real_tag"],
            }
        )


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
