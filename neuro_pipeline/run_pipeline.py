#!/usr/bin/env python3
"""Orchestrate the internal research pipeline (DICOM → BIDS for analysis)."""

from __future__ import annotations

import argparse
import logging
import subprocess
import sys
from pathlib import Path

from neuro_pipeline.pipeline_steps import RESEARCH_PIPELINE_STEPS
from neuro_pipeline.utils.checkpoint import CheckpointStore
from neuro_pipeline.utils.logging_config import configure_logging
from neuro_pipeline.utils.paths import ProjectPaths, resolve_project_root
from neuro_pipeline.utils.step_artifacts import research_step_artifacts

LOGGER = logging.getLogger(__name__)


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
    result = subprocess.run(command, check=False)
    return int(result.returncode)


def run_pipeline(
    paths: ProjectPaths,
    log_level: str,
    stop_after: str | None,
    skip_validation_errors: bool,
    dcm2niix_path: str | None,
    validator_path: str | None,
    use_npx: bool,
    resume: bool,
) -> int:
    """Run all research pipeline steps in order."""
    paths.ensure_logs_dir()
    paths.ensure_metadata_dir()
    paths.ensure_derivatives_dir()
    paths.validate_writable(paths.logs)

    master_log = paths.master_log
    if not resume:
        master_log.write_text("", encoding="utf-8")

    checkpoint = CheckpointStore.load(
        paths.metadata / "research_checkpoints.json",
        pipeline_mode="research",
    )

    step_extra: dict[str, list[str]] = {
        "convert_to_bids": (
            ["--dcm2niix-path", dcm2niix_path] if dcm2niix_path else []
        ),
        "validate_dataset": (
            (["--validator-path", validator_path] if validator_path else [])
            + (["--use-npx"] if use_npx else [])
            + ([] if skip_validation_errors else ["--fail-on-error"])
        ),
    }

    for step_name, module in RESEARCH_PIPELINE_STEPS:
        required = research_step_artifacts(paths, step_name)
        if resume and checkpoint.is_complete(step_name, required):
            LOGGER.info("Skipping completed step '%s' (resume)", step_name)
            if stop_after == step_name:
                break
            continue

        extra = step_extra.get(step_name, [])
        exit_code = run_step(
            module,
            paths.root,
            master_log,
            log_level,
            extra,
        )
        if exit_code != 0:
            checkpoint.mark_failed(step_name, f"exit code {exit_code}")
            LOGGER.error("Pipeline halted at step '%s' (exit %d)", step_name, exit_code)
            return exit_code

        checkpoint.mark_complete(
            step_name,
            artifacts=required,
            message="completed via orchestrator",
        )
        LOGGER.info("Step '%s' completed successfully", step_name)
        if stop_after == step_name:
            LOGGER.info("Stopping early after step '%s'", step_name)
            break

    LOGGER.info("Research pipeline completed — canonical dataset: %s", paths.raw_bids)
    return 0


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
