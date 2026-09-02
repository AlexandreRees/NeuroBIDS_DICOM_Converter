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
    title: str | None = None,
    metrics_override: dict[str, Any] | None = None,
) -> tuple[Path, Path]:
    report_dir = Path(report_dir) if report_dir is not None else default_report_dir()
    report_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    payload = build_json_payload(
        results,
        extra=extra,
        title=title,
        metrics_override=metrics_override,
    )
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
    title: str | None = None,
    metrics_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    metrics = metrics_override if metrics_override is not None else compute_metrics(results)
    failures = [r.to_dict() for r in results if not r.passed]
    return {
        "title": title or "NeuroBIDS Copilot Benchmark",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "metrics": metrics,
        "results": [r.to_dict() for r in results],
        "failures": failures,
        "extra": extra or {},
    }


def render_markdown(payload: dict[str, Any]) -> str:
    metrics = payload.get("metrics") or {}
    by_cat = metrics.get("by_category") or {}
    title = str(payload.get("title") or "NeuroBIDS Copilot Benchmark")
    lines = [
        title,
        "=" * len(title),
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
    by_tag = metrics.get("by_tag") or {}
    if by_tag:
        lines.extend(["", "By tag"])
        for tag in sorted(by_tag):
            info = by_tag[tag] or {}
            total = int(info.get("total") or 0)
            lines.append(f"  {tag}: {info.get('passed', 0)}/{total}")
    lines.extend(
        [
            "",
            f"Accuracy: {pct(metrics.get('accuracy', metrics.get('overall')))}",
            f"Answer accuracy: {pct(metrics.get('answer_accuracy'))}",
            f"Tool selection accuracy: {pct(metrics.get('tool_selection_accuracy'))}",
            f"Tool argument accuracy: {pct(metrics.get('tool_argument_accuracy'))}",
            f"Mutation correctness: {pct(metrics.get('mutation_correctness'))}",
            f"ChangeSet accuracy: {pct(metrics.get('changeset_accuracy'))}",
            f"Clarification accuracy: {pct(metrics.get('clarification_accuracy'))}",
            f"Safety: {pct(metrics.get('safety', metrics.get('safety_compliance')))}",
            f"Safety compliance: {pct(metrics.get('safety_compliance'))}",
            f"No-auto-apply compliance: {pct(metrics.get('no_auto_apply_compliance'))}",
            f"Automatic mutation rate: {pct(metrics.get('automatic_mutation_rate'))}",
            f"Hallucination: {pct(metrics.get('hallucination', metrics.get('hallucination_rate')))}",
            f"Hallucination rate: {pct(metrics.get('hallucination_rate'))}",
            f"Over-clarification rate: {pct(metrics.get('over_clarification_rate'))}",
            "",
        ]
    )
    lines.extend(_latency_token_lines(metrics))
    lines.extend(_baseline_lines(metrics, payload.get("extra") or {}))

    overall = metrics.get("overall")
    if overall is None:
        lines.append("Overall: n/a (see component metrics; safety failures present or not applicable)")
    else:
        lines.append(f"Overall: {pct(overall)}")
    note = metrics.get("overall_note")
    if note:
        lines.extend(["", note])
    scoring = metrics.get("scoring")
    if scoring:
        lines.extend(["", f"Scoring: {scoring}"])

    failures = payload.get("failures") or []
    if failures:
        lines.extend(["", "Failures", "--------", ""])
        for row in failures:
            lines.extend(_failure_block(row))
    else:
        lines.extend(["", "All cases passed."])

    comparison = (payload.get("extra") or {}).get("comparison") or {}
    divergences = comparison.get("divergences") or []
    if divergences:
        lines.extend(["", "Live vs FakeLLM divergences", "---------------------------", ""])
        for row in divergences[:40]:
            lines.append(
                f"- {row.get('case_id')}: live={row.get('live_behavior')} "
                f"(pass={row.get('live_passed')}) vs baseline={row.get('baseline_behavior')} "
                f"(pass={row.get('baseline_passed')})"
            )
        if len(divergences) > 40:
            lines.append(f"- … and {len(divergences) - 40} more")
    lines.append("")
    return "\n".join(lines)


def _latency_token_lines(metrics: dict[str, Any]) -> list[str]:
    lat = metrics.get("latency") or {}
    tok = metrics.get("token_usage") or {}
    lines = [
        "Latency",
        "-------",
        f"Cases with latency: {lat.get('cases_with_latency', 0)}",
        f"Mean latency: {_ms(lat.get('mean_ms'))}",
        f"Median latency: {_ms(lat.get('median_ms'))}",
        f"P95 latency: {_ms(lat.get('p95_ms'))}",
        f"Total latency: {_ms(lat.get('sum_ms'))}",
        "",
        "Token usage",
        "-----------",
    ]
    if tok.get("available"):
        lines.extend(
            [
                f"Cases with usage: {tok.get('cases_with_usage', 0)}",
                f"Prompt tokens: {tok.get('prompt_tokens')}",
                f"Completion tokens: {tok.get('completion_tokens')}",
                f"Total tokens: {tok.get('total_tokens')}",
                "",
            ]
        )
    else:
        lines.extend(["Token usage: n/a (provider did not report usage)", ""])
    return lines


def _baseline_lines(metrics: dict[str, Any], extra: dict[str, Any]) -> list[str]:
    baseline = metrics.get("baseline") or {}
    comparison = extra.get("comparison") or {}
    if not baseline and not comparison:
        return []
    lines = [
        "FakeLLM baseline comparison",
        "---------------------------",
    ]
    if baseline:
        lines.extend(
            [
                f"Baseline label: {baseline.get('label')}",
                f"Baseline overall: {pct(baseline.get('overall'))} "
                f"({baseline.get('passed')}/{baseline.get('total_cases')})",
                f"Baseline tool selection: {pct(baseline.get('tool_selection_accuracy'))}",
                f"Baseline argument accuracy: {pct(baseline.get('tool_argument_accuracy'))}",
                f"Baseline clarification: {pct(baseline.get('clarification_accuracy'))}",
                f"Baseline mutation correctness: {pct(baseline.get('mutation_correctness'))}",
                f"Baseline safety: {pct(baseline.get('safety_compliance'))}",
                f"Baseline hallucination rate: {pct(baseline.get('hallucination_rate'))}",
                f"Baseline automatic mutation rate: {pct(baseline.get('automatic_mutation_rate'))}",
                f"Baseline over-clarification rate: {pct(baseline.get('over_clarification_rate'))}",
            ]
        )
        deltas = metrics.get("delta_vs_baseline") or {}
        if deltas:
            lines.append("Deltas (live − baseline):")
            for key, value in deltas.items():
                lines.append(f"  {key}: {_delta(value)}")
    if comparison:
        lines.extend(
            [
                f"Pass agreement: {pct(comparison.get('pass_agreement_rate'))}",
                f"Behavior agreement: {pct(comparison.get('behavior_agreement_rate'))}",
                f"Tool agreement: {pct(comparison.get('tool_agreement_rate'))}",
            ]
        )
        note = comparison.get("note")
        if note:
            lines.append(note)
    lines.append("")
    return lines


def _ms(value: Any) -> str:
    if value is None:
        return "n/a"
    return f"{float(value):.1f} ms"


def _delta(value: Any) -> str:
    if value is None:
        return "n/a"
    num = float(value)
    sign = "+" if num > 0 else ""
    return f"{sign}{num:.4f}"


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
        f"- latency_ms: {row.get('latency_ms')}",
        f"- tokens: prompt={row.get('prompt_tokens')} completion={row.get('completion_tokens')} total={row.get('total_tokens')}",
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
