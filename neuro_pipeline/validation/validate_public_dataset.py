#!/usr/bin/env python3
"""Validate Public_Dataset/ with the official bids-validator (OpenNeuro requirement)."""

from __future__ import annotations

import argparse
import logging
import sys

from neuro_pipeline.validation.bids_validation import validate_bids_dataset
from neuro_pipeline.utils.cli import build_base_parser
from neuro_pipeline.utils.errors import FatalPipelineError
from neuro_pipeline.utils.execution_context import ExecutionContext
from neuro_pipeline.utils.logging_config import configure_logging
from neuro_pipeline.utils.paths import ProjectPaths, resolve_project_root

LOGGER = logging.getLogger(__name__)


def run_public_validation(
    paths: ProjectPaths,
    *,
    validator_path: str | None,
    use_npx: bool,
    fail_on_error: bool,
) -> None:
    """Run bids-validator on anonymization_release/Public_Dataset/."""
    if not paths.public_dataset.is_dir():
        raise FatalPipelineError(
            f"Public dataset not found: {paths.public_dataset}. Run release anonymization first."
        )

    validation_dir = paths.anonymization_release / "validation"
    result = validate_bids_dataset(
        paths.public_dataset,
        report_json=validation_dir / "bids_validation_report.json",
        summary_csv=validation_dir / "bids_validation_summary.csv",
        validator_path=validator_path,
        use_npx=use_npx,
        fail_on_error=fail_on_error,
    )

    context = ExecutionContext.capture(
        project_root=paths.root,
        parameters={"fail_on_error": fail_on_error, "target": "Public_Dataset"},
        software_versions={"bids-validator": result.validator_version},
    )
    context.write_json(paths.metadata / "validate_public_dataset_context.json")
    LOGGER.info(
        "Public BIDS validation passed (%d warnings)",
        result.warning_count,
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = build_base_parser(
        description="Validate Public_Dataset/ using the official bids-validator."
    )
    parser.add_argument("--validator-path", type=str, default=None)
    parser.add_argument("--use-npx", action="store_true")
    parser.add_argument(
        "--skip-validation-errors",
        action="store_true",
        help="Do not fail when bids-validator reports errors (not recommended for OpenNeuro).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    paths = resolve_project_root(args.project_root)

    global LOGGER
    LOGGER = configure_logging(
        __name__,
        log_file=paths.metadata / "validate_public_dataset.log",
        level=getattr(logging, args.log_level),
        master_log=args.master_log or paths.master_log,
    )

    try:
        run_public_validation(
            paths,
            validator_path=args.validator_path,
            use_npx=args.use_npx,
            fail_on_error=not args.skip_validation_errors,
        )
    except FatalPipelineError as exc:
        LOGGER.error("FATAL: %s", exc.message)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
