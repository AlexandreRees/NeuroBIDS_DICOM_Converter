#!/usr/bin/env python3
"""CLI entry point for the internal research pipeline."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from neuro_pipeline.utils.logging_config import configure_logging
from neuro_pipeline.utils.paths import resolve_project_root
from neuro_pipeline.workflows.research import run_pipeline
from neuro_pipeline.workflows.steps import RESEARCH_PIPELINE_STEPS

LOGGER = logging.getLogger(__name__)

__all__ = ["RESEARCH_PIPELINE_STEPS", "main", "parse_args", "run_pipeline"]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description=(
            "Run the internal research pipeline: raw_original → raw_bids "
            "(no public-release anonymization)."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--project-root", type=Path, default=None)
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
    )
    parser.add_argument(
        "--stop-after",
        choices=[name for name, _ in RESEARCH_PIPELINE_STEPS],
        default=None,
    )
    parser.add_argument("--dcm2niix-path", type=str, default=None)
    parser.add_argument("--validator-path", type=str, default=None)
    parser.add_argument("--use-npx", action="store_true")
    parser.add_argument("--skip-validation-errors", action="store_true")
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Skip steps already recorded in metadata/research_checkpoints.json.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Entry point for research-pipeline orchestration."""
    args = parse_args(argv)
    paths = resolve_project_root(args.project_root)

    global LOGGER
    LOGGER = configure_logging(
        __name__,
        log_file=paths.logs / "run_pipeline.log",
        level=getattr(logging, args.log_level),
        master_log=paths.master_log,
    )

    LOGGER.info("Starting research pipeline for %s (resume=%s)", paths.root, args.resume)
    return run_pipeline(
        paths,
        args.log_level,
        args.stop_after,
        args.skip_validation_errors,
        args.dcm2niix_path,
        args.validator_path,
        args.use_npx,
        args.resume,
    )


if __name__ == "__main__":
    sys.exit(main())
