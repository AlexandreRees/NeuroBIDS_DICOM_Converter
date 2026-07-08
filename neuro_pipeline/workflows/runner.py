"""Shared subprocess orchestration utilities for pipeline workflows."""

from __future__ import annotations

import logging
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from neuro_pipeline.utils.checkpoint import CheckpointStore
from neuro_pipeline.utils.paths import ProjectPaths

LOGGER = logging.getLogger(__name__)

StepArtifactsFn = Callable[[ProjectPaths, str], list[Path]]
PreflightFn = Callable[[ProjectPaths], int | None]


def run_step(
    module: str,
    project_root: Path,
    master_log: Path,
    log_level: str,
    extra_args: list[str],
    *,
    step_label: str = "step",
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
    LOGGER.info("Executing %s: %s", step_label, module)
    result = subprocess.run(command, check=False)
    return int(result.returncode)


def execute_pipeline(
    paths: ProjectPaths,
    *,
    steps: tuple[tuple[str, str], ...],
    checkpoint_path: Path,
    pipeline_mode: str,
    master_log: Path,
    log_level: str,
    stop_after: str | None,
    resume: bool,
    step_artifacts: StepArtifactsFn,
    step_extra: dict[str, list[str]],
    preflight: PreflightFn | None = None,
    completion_message: str,
    step_label: str = "step",
) -> int:
    """Run an ordered list of pipeline steps with checkpoint/resume support."""
    if preflight is not None:
        preflight_code = preflight(paths)
        if preflight_code is not None:
            return preflight_code

    if not resume:
        master_log.write_text("", encoding="utf-8")

    checkpoint = CheckpointStore.load(checkpoint_path, pipeline_mode=pipeline_mode)

    for step_name, module in steps:
        required = step_artifacts(paths, step_name)
        if resume and checkpoint.is_complete(step_name, required):
            LOGGER.info("Skipping completed %s '%s' (resume)", step_label, step_name)
            if stop_after == step_name:
                break
            continue

        exit_code = run_step(
            module,
            paths.root,
            master_log,
            log_level,
            step_extra.get(step_name, []),
            step_label=step_label,
        )
        if exit_code != 0:
            checkpoint.mark_failed(step_name, f"exit code {exit_code}")
            LOGGER.error(
                "Pipeline halted at %s '%s' (exit %d)",
                step_label,
                step_name,
                exit_code,
            )
            return exit_code

        checkpoint.mark_complete(
            step_name,
            artifacts=required,
            message="completed via orchestrator",
        )
        LOGGER.info("%s '%s' completed successfully", step_label.capitalize(), step_name)
        if stop_after == step_name:
            LOGGER.info("Stopping early after %s '%s'", step_label, step_name)
            break

    LOGGER.info(completion_message)
    return 0
