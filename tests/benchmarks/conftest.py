"""Shared fixtures for NeuroBIDS Copilot benchmark tests."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from neuro_pipeline.neurobids.copilot.benchmark.dataset import (
    build_benchmark_session,
    compute_ground_truth,
)
from neuro_pipeline.neurobids.copilot.benchmark.loader import load_benchmark_cases
from neuro_pipeline.neurobids.copilot.benchmark.schema import BenchmarkCase


@pytest.fixture
def benchmark_root(tmp_path: Path) -> Path:
    return tmp_path / "benchmark_dataset"


@pytest.fixture
def benchmark_session(benchmark_root: Path):
    return build_benchmark_session(benchmark_root)


@pytest.fixture
def benchmark_ground_truth(benchmark_session):
    return compute_ground_truth(benchmark_session)


@pytest.fixture
def benchmark_cases() -> list[BenchmarkCase]:
    return load_benchmark_cases()
