"""python -m neuro_pipeline.neurobids.copilot.benchmark"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from neuro_pipeline.neurobids.copilot.benchmark.loader import load_benchmark_cases
from neuro_pipeline.neurobids.copilot.benchmark.report import build_json_payload, render_markdown
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
        help=(
            "Optional live-LLM evaluation against the same explicit ground-truth cases "
            "(requires NEUROBIDS_LLM_PROVIDER). Compares to FakeLLM level2 baseline. "
            "Not a regression gate. Never uses LLM-as-judge."
        ),
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
    parser.add_argument(
        "--tag",
        action="append",
        default=None,
        help="Only run cases with this tag (repeatable; match any).",
    )
    parser.add_argument(
        "--no-baseline",
        action="store_true",
        help="With --live, skip FakeLLM level2 baseline comparison.",
    )
    args = parser.parse_args(argv)

    if args.live:
        from neuro_pipeline.neurobids.copilot.benchmark.live import (
            live_provider_available,
            run_live_benchmark,
        )
        from neuro_pipeline.neurobids.copilot.benchmark.metrics import compute_metrics
        from neuro_pipeline.neurobids.copilot.llm.config import LLMConfig

        cfg = LLMConfig.from_env()
        if not live_provider_available(cfg):
            if (cfg.provider or "").lower() == "local":
                base = cfg.base_url or "http://localhost:11434/v1"
                print(
                    "Live LLM benchmark requested with NEUROBIDS_LLM_PROVIDER=local, "
                    f"but no OpenAI-compatible server responded at {base}. "
                    "Install/start Ollama, pull the model, then re-run. "
                    "Example:\n"
                    "  curl -fsSL https://ollama.com/install.sh | sh\n"
                    "  ollama serve\n"
                    f"  ollama pull {cfg.model or 'qwen3:30b'}\n"
                    "  export NEUROBIDS_LLM_PROVIDER=local\n"
                    f"  export NEUROBIDS_LLM_MODEL={cfg.model or 'qwen3:30b'}\n"
                    "  export NEUROBIDS_LLM_BASE_URL=http://localhost:11434/v1\n"
                    "  PYTHONPATH=src python -m neuro_pipeline.neurobids.copilot.benchmark --live",
                    file=sys.stderr,
                )
            else:
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
        if args.tag:
            wanted_tags = set(args.tag)
            cases = [c for c in cases if wanted_tags.intersection(c.tags)]
        run = run_live_benchmark(
            cases=cases,
            config=cfg,
            report_dir=args.report_dir,
            compare_baseline=not args.no_baseline,
        )
        payload = build_json_payload(
            run.live_results,
            title="NeuroBIDS Copilot Live LLM Benchmark",
            metrics_override=run.metrics,
            extra={
                "mode": "live",
                "comparison": run.comparison,
                "baseline_metrics": (
                    compute_metrics(run.baseline_results) if run.baseline_results else {}
                ),
            },
        )
        print(render_markdown(payload))
        if run.json_report:
            print(f"JSON report: {run.json_report}")
        if run.markdown_report:
            print(f"Markdown report: {run.markdown_report}")
        print("NOTE: live-LLM results are NOT the regression baseline.")
        return 0 if run.passed else 1

    level_map = {"1": ["level1"], "2": ["level2"], "3": ["level3"], "all": None}
    cases = load_benchmark_cases()
    if args.category:
        wanted = set(args.category)
        cases = [c for c in cases if c.category in wanted]
    if args.tag:
        wanted_tags = set(args.tag)
        cases = [c for c in cases if wanted_tags.intersection(c.tags)]
    run = run_benchmark(
        cases=cases,
        levels=level_map[args.level],
        report_dir=args.report_dir,
        include_level3=not args.no_level3,
    )
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
