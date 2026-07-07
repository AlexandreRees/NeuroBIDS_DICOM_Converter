#!/usr/bin/env python3
"""Orchestrate the public-release pipeline (OpenNeuro-ready by default)."""

from __future__ import annotations

import argparse
import logging
import subprocess
import sys
from pathlib import Path

from neuro_pipeline.pipeline_steps import RELEASE_PIPELINE_STEPS
from neuro_pipeline.utils.checkpoint import CheckpointStore
from neuro_pipeline.utils.logging_config import configure_logging
from neuro_pipeline.utils.paths import ProjectPaths, resolve_project_root
from neuro_pipeline.utils.step_artifacts import release_step_artifacts

LOGGER = logging.getLogger(__name__)


def run_step(
    module: str,
    project_root: Path,
    master_log: Path,
    log_level: str,
    extra_args: list[str],
) -> int:
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
    LOGGER.info("Executing release step: %s", module)
    return int(subprocess.run(command, check=False).returncode)


def run_release_pipeline(
    paths: ProjectPaths,
    log_level: str,
    openneuro_mode: bool,
    enable_defacing: bool,
    skip_defacing: bool,
    seed: str | None,
    workers: int,
    stop_after: str | None,
    resume: bool,
    use_npx: bool,
) -> int:
    paths.ensure_logs_dir()
    paths.ensure_metadata_dir()

    if not paths.raw_bids.is_dir():
        LOGGER.error("raw_bids/ not found. Run neuro-pipeline first.")
        return 1

    master_log = paths.logs / "release_pipeline_master.log"
    if not resume:
        master_log.write_text("", encoding="utf-8")

    checkpoint = CheckpointStore.load(
        paths.metadata / "release_checkpoints.json",
        pipeline_mode="release",
    )

    anonymize_args: list[str] = ["--workers", str(workers)]
    if openneuro_mode:
        anonymize_args.append("--openneuro")
    else:
        anonymize_args.append("--no-openneuro")
    if enable_defacing:
        anonymize_args.append("--enable-defacing")
    if skip_defacing:
        anonymize_args.append("--skip-defacing")
    if seed:
        anonymize_args.extend(["--seed", seed])

    step_extra: dict[str, list[str]] = {
        "anonymize": anonymize_args,
        "validate_public_dataset": (["--use-npx"] if use_npx else []),
    }

    for step_name, module in RELEASE_PIPELINE_STEPS:
        required = release_step_artifacts(paths, step_name)
        if resume and checkpoint.is_complete(step_name, required):
            LOGGER.info("Skipping completed release step '%s' (resume)", step_name)
            if stop_after == step_name:
                break
            continue

        exit_code = run_step(
            module,
            paths.root,
            master_log,
            log_level,
            step_extra.get(step_name, []),
        )
        if exit_code != 0:
            checkpoint.mark_failed(step_name, f"exit code {exit_code}")
            return exit_code

        checkpoint.mark_complete(step_name, artifacts=required)
        if stop_after == step_name:
            break

    LOGGER.info("Release pipeline completed — output: %s", paths.public_dataset)
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="OpenNeuro-ready release pipeline: raw_bids → Public_Dataset",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--project-root", type=Path, default=None)
    parser.add_argument("--log-level", choices=["DEBUG", "INFO", "WARNING", "ERROR"], default="INFO")
    parser.add_argument("--stop-after", choices=[name for name, _ in RELEASE_PIPELINE_STEPS], default=None)
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
