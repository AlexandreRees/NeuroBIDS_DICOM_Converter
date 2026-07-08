#!/usr/bin/env python3
"""Validate expected MRI acquisitions after DICOM-to-BIDS conversion."""

from __future__ import annotations

import argparse
import logging
import sys

from neuro_pipeline.acquisition.consistency import run_acquisition_validation
from neuro_pipeline.utils.cli import build_base_parser
from neuro_pipeline.utils.errors import FatalPipelineError
from neuro_pipeline.utils.logging_config import configure_logging
from neuro_pipeline.utils.paths import resolve_project_root

LOGGER = logging.getLogger(__name__)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = build_base_parser(
        description=(
            "Validate that every expected acquisition is uniquely identifiable "
            "in raw_bids/ after conversion."
        )
    )
    parser.add_argument(
        "--fail-on-error",
        action="store_true",
        help="Exit with error if any acquisition validation fails.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    paths = resolve_project_root(args.project_root)

    global LOGGER
    LOGGER = configure_logging(
        __name__,
        log_file=paths.metadata / "validate_acquisitions.log",
        level=getattr(logging, args.log_level),
        master_log=args.master_log or paths.master_log,
    )

    LOGGER.info("Starting acquisition validation for %s", paths.root)
    try:
        report = run_acquisition_validation(paths, fail_on_error=args.fail_on_error)
    except FatalPipelineError as exc:
        LOGGER.error("FATAL: %s", exc.message)
        return 1

    error_count = sum(1 for row in report.rows if row.status == "error")
    missing_count = sum(1 for row in report.rows if row.status == "missing")
    warn_count = sum(1 for row in report.rows if row.status == "warning")
    LOGGER.info(
        "Acquisition validation complete: passed=%s, errors=%d, missing=%d, warnings=%d",
        report.passed,
        error_count,
        missing_count,
        warn_count,
    )
    LOGGER.info("Report: %s", paths.acquisition_validation_csv)
    LOGGER.info("Blocklist: %s", paths.acquisition_blocklist_json)

    if report.t1_blocked_sessions:
        LOGGER.warning(
            "T1-dependent processing blocked for sessions: %s",
            ", ".join(sorted(report.t1_blocked_sessions)),
        )

    return 0 if report.passed or not args.fail_on_error else 1


if __name__ == "__main__":
    sys.exit(main())
