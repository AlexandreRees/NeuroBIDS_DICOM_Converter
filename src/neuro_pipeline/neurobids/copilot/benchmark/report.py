"""JSON + Markdown reports for the NeuroBIDS Copilot benchmark."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from neuro_pipeline.neurobids.copilot.benchmark.evaluators import CaseResult
from neuro_pipeline.neurobids.copilot.benchmark.metrics import compute_metrics, pct
from neuro_pipeline.neurobids.copilot.benchmark.schema import CaseCategory


def default_report_dir() -> Path:
    here = Path(__file__).resolve()
    repo = here.parents[5]
    reports = repo / "tests" / "benchmarks" / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    return reports


def write_reports(
    results: list[CaseResult],
    *,
    report_dir: Path | None = None,
    extra: dict[str, Any] | None = None,
) -> tuple[Path, Path]:
    report_dir = Path(report_dir) if report_dir is not None else default_report_dir()
    report_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    payload = build_json_payload(results, extra=extra)
    json_path = report_dir / f"neurobids_copilot_benchmark_{stamp}.json"
    md_path = report_dir / f"neurobids_copilot_benchmark_{stamp}.md"
    json_path.write_text(_dumps(payload), encoding="utf-8")
    md_path.write_text(render_markdown(payload), encoding="utf-8")
    latest_json = report_dir / "latest.json"
    latest_md = report_dir / "latest.md"
    latest_json.write_text(json_path.read_text(encoding="utf-8"), encoding="utf-8")
    latest_md.write_text(md_path.read_text(encoding="utf-8"), encoding="utf-8")
    return json_path, md_path


def build_json_payload(
    results: list[CaseResult],
    *,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    metrics = compute_metrics(results)
    failures = [r.to_dict() for r in results if not r.passed]
    return {
        "title": "NeuroBIDS Copilot Benchmark",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "metrics": metrics,
        "results": [r.to_dict() for r in results],
        "failures": failures,
        "extra": extra or {},
    }


def render_markdown(payload: dict[str, Any]) -> str:
    metrics = payload.get("metrics") or {}
    by_cat = metrics.get("by_category") or {}
    lines = [
        "NeuroBIDS Copilot Benchmark",
        "============================",
        "",
        f"Total evaluations: {metrics.get('total_cases', 0)}",
        f"Passed: {metrics.get('passed', 0)}",
        f"Failed: {metrics.get('failed', 0)}",
        "",
    ]
    for cat in [c.value for c in CaseCategory]:
        info = by_cat.get(cat) or {}
        total = int(info.get("total") or 0)
        if total == 0:
            continue
        pretty = cat.replace("_", " ").title()
        lines.append(f"{pretty}: {info.get('passed', 0)}/{total}")
    lines.extend(
        [
            "",
            f"Answer accuracy: {pct(metrics.get('answer_accuracy'))}",
            f"Tool selection accuracy: {pct(metrics.get('tool_selection_accuracy'))}",
            f"Tool argument accuracy: {pct(metrics.get('tool_argument_accuracy'))}",
            f"Mutation correctness: {pct(metrics.get('mutation_correctness'))}",
            f"ChangeSet accuracy: {pct(metrics.get('changeset_accuracy'))}",
            f"Clarification accuracy: {pct(metrics.get('clarification_accuracy'))}",
            f"Safety compliance: {pct(metrics.get('safety_compliance'))}",
            f"No-auto-apply compliance: {pct(metrics.get('no_auto_apply_compliance'))}",
            f"Automatic mutation rate: {pct(metrics.get('automatic_mutation_rate'))}",
            f"Hallucination rate: {pct(metrics.get('hallucination_rate'))}",
            "",
        ]
    )
    overall = metrics.get("overall")
    if overall is None:
        lines.append("Overall: n/a (see component metrics; safety failures present or not applicable)")
    else:
        lines.append(f"Overall: {pct(overall)}")
    note = metrics.get("overall_note")
    if note:
        lines.extend(["", note])

    failures = payload.get("failures") or []
    if failures:
        lines.extend(["", "Failures", "--------", ""])
        for row in failures:
            lines.extend(_failure_block(row))
    else:
        lines.extend(["", "All cases passed."])
    lines.append("")
    return "\n".join(lines)


def _failure_block(row: dict[str, Any]) -> list[str]:
    return [
        f"### {row.get('case_id')} ({row.get('level')})",
        f"- prompt: {row.get('prompt')}",
        f"- expected behavior: {row.get('expected_behavior')}",
        f"- observed behavior: {row.get('observed_behavior')}",
        f"- expected tool: {row.get('expected_tool')}",
        f"- observed tool: {row.get('observed_tool')}",
        f"- expected arguments: {row.get('expected_arguments')}",
        f"- observed arguments: {row.get('observed_arguments')}",
        f"- expected mutation: {row.get('expected_mutation')}",
        f"- observed mutation: {row.get('observed_mutation')}",
        f"- safety preserved: {row.get('safety_preserved')}",
        f"- likely failure category: {', '.join(row.get('failure_categories') or []) or 'unknown'}",
        f"- mismatches: {row.get('mismatches')}",
        "",
    ]


def _dumps(payload: dict[str, Any]) -> str:
    import json

    return json.dumps(payload, indent=2, ensure_ascii=False, default=str) + "\n"


__all__ = [
    "build_json_payload",
    "default_report_dir",
    "render_markdown",
    "write_reports",
]
