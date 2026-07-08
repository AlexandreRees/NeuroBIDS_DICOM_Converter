"""Research pipeline workflow orchestration."""

from __future__ import annotations

from neuro_pipeline.utils.paths import ProjectPaths
from neuro_pipeline.utils.step_artifacts import research_step_artifacts
from neuro_pipeline.workflows.runner import execute_pipeline
from neuro_pipeline.workflows.steps import RESEARCH_PIPELINE_STEPS


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

    return execute_pipeline(
        paths,
        steps=RESEARCH_PIPELINE_STEPS,
        checkpoint_path=paths.metadata / "research_checkpoints.json",
        pipeline_mode="research",
        master_log=paths.master_log,
        log_level=log_level,
        stop_after=stop_after,
        resume=resume,
        step_artifacts=research_step_artifacts,
        step_extra=step_extra,
        completion_message=f"Research pipeline completed — canonical dataset: {paths.raw_bids}",
        step_label="step",
    )
