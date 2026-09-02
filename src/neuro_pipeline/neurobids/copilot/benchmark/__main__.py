"""python -m neuro_pipeline.neurobids.copilot.benchmark"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from neuro_pipeline.neurobids.copilot.benchmark.loader import load_benchmark_cases
from neuro_pipeline.neurobids.copilot.benchmark.report import render_markdown
from neuro_pipeline.neurobids.copilot.benchmark.runner import run_benchmark


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "NeuroBIDS Copilot benchmark. The default run is deterministic "
            "(FakeLLMProvider, no API key)."
        )
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Optional live-LLM evaluation (requires NEUROBIDS_LLM_PROVIDER). Not a regression gate.",
    )
    parser.add_argument(
        "--level",
        choices=["1", "2", "3", "all"],
        default="all",
        help="Restrict to one evaluation layer (default: all).",
    )
    parser.add_argument(
        "--report-dir",
        type=Path,
        default=None,
        help="Directory for timestamped JSON/Markdown reports.",
    )
    parser.add_argument(
        "--no-level3",
        action="store_true",
        help="Skip GUI/controller evaluation.",
    )
    parser.add_argument(
        "--category",
        action="append",
        default=None,
        help="Only run cases in this category (repeatable).",
    )
    args = parser.parse_args(argv)

    if args.live:
        from neuro_pipeline.neurobids.copilot.benchmark.dataset import build_benchmark_session
        from neuro_pipeline.neurobids.copilot.benchmark.live import live_provider_available, run_live_case
        from neuro_pipeline.neurobids.copilot.benchmark.metrics import compute_metrics
        from neuro_pipeline.neurobids.copilot.benchmark.report import write_reports
        from neuro_pipeline.neurobids.copilot.llm.config import LLMConfig

        cfg = LLMConfig.from_env()
        if not live_provider_available(cfg):
            print(
                "Live LLM benchmark requested, but no usable provider is configured. "
                "Set NEUROBIDS_LLM_PROVIDER (and credentials). "
                "The deterministic suite does not need this.",
                file=sys.stderr,
            )
            return 2
        cases = load_benchmark_cases()
        if args.category:
            cases = [c for c in cases if c.category in set(args.category)]
        session = build_benchmark_session()
        results = [run_live_case(case, session, config=cfg) for case in cases]
        json_path, md_path = write_reports(
            results,
            report_dir=args.report_dir,
            extra={"mode": "live"},
        )
        payload = {"metrics": compute_metrics(results), "failures": [r.to_dict() for r in results if not r.passed]}
        print(render_markdown(payload))
        print(f"JSON report: {json_path}")
        print(f"Markdown report: {md_path}")
        print("NOTE: live-LLM results are NOT the regression baseline.")
        return 0 if all(r.passed for r in results) else 1

    level_map = {"1": ["level1"], "2": ["level2"], "3": ["level3"], "all": None}
    cases = load_benchmark_cases()
    if args.category:
        wanted = set(args.category)
        cases = [c for c in cases if c.category in wanted]
    run = run_benchmark(
        cases=cases,
        levels=level_map[args.level],
        report_dir=args.report_dir,
        include_level3=not args.no_level3,
    )
    from neuro_pipeline.neurobids.copilot.benchmark.report import build_json_payload

    print(render_markdown(build_json_payload(run.results, extra={"skipped_levels": run.skipped_levels})))
    if run.json_report:
        print(f"JSON report: {run.json_report}")
    if run.markdown_report:
        print(f"Markdown report: {run.markdown_report}")
    if run.skipped_levels:
        print("Skipped:", "; ".join(run.skipped_levels))
    return 0 if run.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
