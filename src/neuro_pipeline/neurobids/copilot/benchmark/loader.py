"""Load and validate NeuroBIDS Copilot benchmark cases from JSON."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from neuro_pipeline.neurobids.copilot.benchmark.schema import BenchmarkCase

_CASES_DIR = Path(__file__).resolve().parent / "cases"


class CaseLoadError(ValueError):
    """Raised when benchmark JSON is missing, malformed, or inconsistent."""


def cases_dir() -> Path:
    return _CASES_DIR


def load_case_file(path: Path | str) -> list[BenchmarkCase]:
    path = Path(path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise CaseLoadError(f"Case file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise CaseLoadError(f"Invalid JSON in {path}: {exc}") from exc
    return _parse_payload(payload, source=str(path))


def load_benchmark_cases(directory: Path | None = None) -> list[BenchmarkCase]:
    """Load every ``*.json`` case file from the benchmark cases directory."""
    root = Path(directory) if directory is not None else _CASES_DIR
    if not root.is_dir():
        raise CaseLoadError(f"Benchmark cases directory not found: {root}")
    files = sorted(p for p in root.glob("*.json") if p.is_file())
    if not files:
        raise CaseLoadError(f"No benchmark case JSON files in {root}")
    cases: list[BenchmarkCase] = []
    for path in files:
        cases.extend(load_case_file(path))
    _assert_unique_ids(cases)
    return cases


def cases_by_id(cases: Iterable[BenchmarkCase] | None = None) -> dict[str, BenchmarkCase]:
    loaded = list(cases) if cases is not None else load_benchmark_cases()
    return {c.id: c for c in loaded}


def _parse_payload(payload: Any, *, source: str) -> list[BenchmarkCase]:
    if isinstance(payload, dict) and "cases" in payload:
        raw_cases = payload["cases"]
    elif isinstance(payload, list):
        raw_cases = payload
    elif isinstance(payload, dict) and "id" in payload:
        raw_cases = [payload]
    else:
        raise CaseLoadError(f"{source}: expected a case list or {{'cases': [...]}}")
    if not isinstance(raw_cases, list):
        raise CaseLoadError(f"{source}: cases must be a list")
    out: list[BenchmarkCase] = []
    for idx, item in enumerate(raw_cases):
        if not isinstance(item, dict):
            raise CaseLoadError(f"{source}[{idx}]: case must be an object")
        try:
            out.append(BenchmarkCase.from_dict(item))
        except ValueError as exc:
            raise CaseLoadError(f"{source}: {exc}") from exc
    _assert_unique_ids(out)
    return out


def _assert_unique_ids(cases: list[BenchmarkCase]) -> None:
    seen: dict[str, int] = {}
    for case in cases:
        seen[case.id] = seen.get(case.id, 0) + 1
    dupes = [cid for cid, n in seen.items() if n > 1]
    if dupes:
        raise CaseLoadError(f"Duplicate benchmark case ids: {', '.join(sorted(dupes))}")


__all__ = [
    "CaseLoadError",
    "cases_by_id",
    "cases_dir",
    "load_benchmark_cases",
    "load_case_file",
]
