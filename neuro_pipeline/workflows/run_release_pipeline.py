#!/usr/bin/env python3
"""CLI entry point for the public-release pipeline."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from neuro_pipeline.utils.logging_config import configure_logging
from neuro_pipeline.utils.paths import resolve_project_root
from neuro_pipeline.workflows.release import run_release_pipeline
from neuro_pipeline.workflows.steps import RELEASE_PIPELINE_STEPS

LOGGER = logging.getLogger(__name__)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="OpenNeuro-ready release pipeline: raw_bids → Public_Dataset",
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
        choices=[name for name, _ in RELEASE_PIPELINE_STEPS],
        default=None,
    )
    parser.add_argument("--openneuro", dest="openneuro", action="store_true", default=True)
    parser.add_argument("--no-openneuro", dest="openneuro", action="store_false")
    parser.add_argument("--enable-defacing", action="store_true")
    parser.add_argument("--skip-defacing", action="store_true")
    parser.add_argument("--seed", type=str, default=None)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--use-npx", action="store_true", help="Run bids-validator via npx.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Entry point for release-pipeline orchestration."""
    args = parse_args(argv)
    paths = resolve_project_root(args.project_root)

    global LOGGER
    LOGGER = configure_logging(
        __name__,
        log_file=paths.logs / "run_release_pipeline.log",
        level=getattr(logging, args.log_level),
        master_log=paths.logs / "release_pipeline_master.log",
    )

    return run_release_pipeline(
        paths,
        args.log_level,
        openneuro_mode=args.openneuro,
        enable_defacing=args.enable_defacing,
        skip_defacing=args.skip_defacing,
        seed=args.seed,
        workers=args.workers,
        stop_after=args.stop_after,
        resume=args.resume,
        use_npx=args.use_npx,
    )


if __name__ == "__main__":
    sys.exit(main())
