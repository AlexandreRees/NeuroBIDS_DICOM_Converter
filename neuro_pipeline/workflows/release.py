"""Public-release pipeline workflow orchestration."""

from __future__ import annotations

import logging

from neuro_pipeline.utils.paths import ProjectPaths
from neuro_pipeline.utils.step_artifacts import release_step_artifacts
from neuro_pipeline.workflows.runner import execute_pipeline
from neuro_pipeline.workflows.steps import RELEASE_PIPELINE_STEPS

LOGGER = logging.getLogger(__name__)


def _release_preflight(paths: ProjectPaths) -> int | None:
    if not paths.raw_bids.is_dir():
        LOGGER.error("raw_bids/ not found. Run neuro-pipeline first.")
        return 1
    return None


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
    """Run all public-release pipeline steps in order."""
    paths.ensure_logs_dir()
    paths.ensure_metadata_dir()

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

    return execute_pipeline(
        paths,
        steps=RELEASE_PIPELINE_STEPS,
        checkpoint_path=paths.metadata / "release_checkpoints.json",
        pipeline_mode="release",
        master_log=paths.logs / "release_pipeline_master.log",
        log_level=log_level,
        stop_after=stop_after,
        resume=resume,
        step_artifacts=release_step_artifacts,
        step_extra=step_extra,
        preflight=_release_preflight,
        completion_message=f"Release pipeline completed — output: {paths.public_dataset}",
        step_label="release step",
    )
