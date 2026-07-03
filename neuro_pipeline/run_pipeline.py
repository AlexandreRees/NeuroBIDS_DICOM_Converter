#!/usr/bin/env python3
"""Orchestrate the full DICOM-to-BIDS pipeline sequentially."""

from __future__ import annotations

import argparse
import logging
import subprocess
import sys
from pathlib import Path

from neuro_pipeline.utils.logging_config import configure_logging
from neuro_pipeline.utils.paths import ProjectPaths, resolve_project_root

LOGGER = logging.getLogger(__name__)

PIPELINE_STEPS: tuple[tuple[str, str], ...] = (
    ("inventory", "neuro_pipeline.inventory"),
    ("generate_mapping", "neuro_pipeline.generate_mapping"),
    ("deidentify_dicom", "neuro_pipeline.deidentify_dicom"),
    ("convert_to_bids", "neuro_pipeline.convert_to_bids"),
    ("defacing", "neuro_pipeline.defacing"),
    ("derivatives_build", "neuro_pipeline.derivatives_build"),
    ("validate_dataset", "neuro_pipeline.validate_dataset"),
    ("quality_control", "neuro_pipeline.quality_control"),
    ("publication_gate", "neuro_pipeline.publication_gate"),
)


def run_step(
    module: str,
    project_root: Path,
    master_log: Path,
    log_level: str,
    extra_args: list[str],
) -> int:
    """Run a single pipeline module as a subprocess."""
    command = [
        sys.executable,
        "-m",
        module,
        "--project-root",
        str(project_root),
        "--master-log",
        str(master_log),
        "--log-level",
        log_level,
        *extra_args,
    ]
    LOGGER.info("Executing step: %s", module)
    LOGGER.debug("Command: %s", " ".join(command))
    result = subprocess.run(command, check=False)
    return int(result.returncode)


def run_pipeline(
    paths: ProjectPaths,
    log_level: str,
    stop_after: str | None,
    skip_validation_errors: bool,
    skip_defacing: bool,
    dcm2niix_path: str | None,
    validator_path: str | None,
    use_npx: bool,
) -> int:
    """Run all pipeline steps in order."""
    paths.ensure_logs_dir()
    paths.ensure_metadata_dir()
    paths.ensure_derivatives_dir()
    paths.validate_writable(paths.logs)

    master_log = paths.master_log
    if master_log.is_file():
        master_log.write_text("", encoding="utf-8")

    step_extra: dict[str, list[str]] = {
        "convert_to_bids": (
            ["--dcm2niix-path", dcm2niix_path] if dcm2niix_path else []
        ),
        "defacing": (["--skip-defacing"] if skip_defacing else []),
        "validate_dataset": (
            (["--validator-path", validator_path] if validator_path else [])
            + (["--use-npx"] if use_npx else [])
            + ([] if skip_validation_errors else ["--fail-on-error"])
        ),
    }

    for step_name, module in PIPELINE_STEPS:
        extra = step_extra.get(step_name, [])
        exit_code = run_step(
            module,
            paths.root,
            master_log,
            log_level,
            extra,
        )
        if exit_code != 0:
            LOGGER.error("Pipeline halted at step '%s' (exit %d)", step_name, exit_code)
            return exit_code
        LOGGER.info("Step '%s' completed successfully", step_name)
        if stop_after == step_name:
            LOGGER.info("Stopping early after step '%s'", step_name)
            break

    LOGGER.info("Pipeline completed successfully")
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Run the full neuroimaging BIDS pipeline sequentially.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        default=None,
        help="Project root containing raw_original/, metadata/, staging/, raw_bids/.",
    )
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="Logging verbosity for all steps.",
    )
    parser.add_argument(
        "--stop-after",
        choices=[name for name, _ in PIPELINE_STEPS],
        default=None,
        help="Stop pipeline after the named step completes successfully.",
    )
    parser.add_argument(
        "--dcm2niix-path",
        type=str,
        default=None,
        help="Path to dcm2niix executable forwarded to convert_to_bids.",
    )
    parser.add_argument(
        "--validator-path",
        type=str,
        default=None,
        help="Path to bids-validator executable forwarded to validate_dataset.",
    )
    parser.add_argument(
        "--use-npx",
        action="store_true",
        help="Run bids-validator via npx.",
    )
    parser.add_argument(
        "--skip-validation-errors",
        action="store_true",
        help="Do not treat BIDS validator errors as fatal.",
    )
    parser.add_argument(
        "--skip-defacing",
        action="store_true",
        help="Skip defacing step (debug only; publication gate will fail).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Entry point for pipeline orchestration."""
    args = parse_args(argv)
    paths = resolve_project_root(args.project_root)

    global LOGGER
    LOGGER = configure_logging(
        __name__,
        log_file=paths.logs / "run_pipeline.log",
        level=getattr(logging, args.log_level),
        master_log=paths.master_log,
    )

    LOGGER.info("Starting full pipeline for %s", paths.root)
    return run_pipeline(
        paths,
        args.log_level,
        args.stop_after,
        args.skip_validation_errors,
        args.skip_defacing,
        args.dcm2niix_path,
        args.validator_path,
        args.use_npx,
    )


if __name__ == "__main__":
    sys.exit(main())
