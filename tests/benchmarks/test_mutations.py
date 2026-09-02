"""Mutation / ChangeSet evaluation."""

from __future__ import annotations

from neuro_pipeline.neurobids.copilot.benchmark.evaluators import evaluate_level1
from neuro_pipeline.neurobids.copilot.changeset import ChangeSetStatus
from neuro_pipeline.neurobids.copilot.plan_ops import plan_fingerprint


def test_rename_subjects_changeset_then_apply(benchmark_cases, benchmark_session) -> None:
    case = next(c for c in benchmark_cases if c.id == "MU-01")
    before_fp = plan_fingerprint(benchmark_session.plan)
    result = evaluate_level1(case, benchmark_session)
    assert result.passed, result.mismatches
    assert result.observed_behavior == "mutation proposal"
    # Original session must be untouched; evaluation clones internally.
    assert plan_fingerprint(benchmark_session.plan) == before_fp


def test_exclude_localizers_changeset(benchmark_cases, benchmark_session) -> None:
    case = next(c for c in benchmark_cases if c.id == "MU-05")
    result = evaluate_level1(case, benchmark_session)
    assert result.passed, result.mismatches
    preview = result.observed_mutation or {}
    uids = {row["series_uid"] for row in (preview.get("include_changes") or [])}
    assert "uid.001.01.loc" in uids
    assert "uid.003.01.loc" in uids


def test_apply_edit_task_run(benchmark_cases, benchmark_session) -> None:
    case = next(c for c in benchmark_cases if c.id == "MU-07")
    result = evaluate_level1(case, benchmark_session)
    assert result.passed, result.mismatches


def test_mutation_status_not_applied_before_explicit_apply(
    benchmark_cases, benchmark_session
) -> None:
    from neuro_pipeline.neurobids.copilot.benchmark.dataset import clone_benchmark_session
    from neuro_pipeline.neurobids.copilot.tools.registry import default_registry

    work = clone_benchmark_session(benchmark_session)
    registry = default_registry()
    out = registry.execute(
        "rename_subjects",
        work,
        {"mode": "sequential", "start": 10, "width": 3},
    )
    assert out.ok
    cs = out.data["changeset"]
    assert cs.status != ChangeSetStatus.APPLIED
    assert {i.subject for i in work.plan.items} == {"001", "002", "003", "004"}
