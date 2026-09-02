"""NeuroBIDS Copilot benchmark — evaluate the existing Copilot, not a new model.

This package does not add RAG, embeddings, fine-tuning, or Copilot capabilities.
It measures deterministic tools, the agent loop (FakeLLMProvider), and
controller Apply/Reject behaviour against an explicit synthetic dataset.
"""

from neuro_pipeline.neurobids.copilot.benchmark.dataset import (
    build_benchmark_session,
    clone_benchmark_session,
    compute_ground_truth,
)
from neuro_pipeline.neurobids.copilot.benchmark.loader import load_benchmark_cases
from neuro_pipeline.neurobids.copilot.benchmark.live import live_provider_available, run_live_benchmark
from neuro_pipeline.neurobids.copilot.benchmark.runner import BenchmarkRun, run_benchmark
from neuro_pipeline.neurobids.copilot.benchmark.schema import BenchmarkCase

__all__ = [
    "BenchmarkCase",
    "BenchmarkRun",
    "build_benchmark_session",
    "clone_benchmark_session",
    "compute_ground_truth",
    "live_provider_available",
    "load_benchmark_cases",
    "run_benchmark",
    "run_live_benchmark",
]
