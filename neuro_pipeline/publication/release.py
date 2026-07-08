#!/usr/bin/env python3
"""Public-release anonymization: raw_bids → anonymization_release/Public_Dataset."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone

from mri_anonymization.config import AnonymizationConfig
from mri_anonymization.pipeline import AnonymizationPipeline

from neuro_pipeline.qc.anatomical import dataset_has_anatomical_mri
from neuro_pipeline.reporting.openneuro_documentation import (
    write_openneuro_documentation,
    write_provenance_json,
)
from neuro_pipeline.utils.cli import build_base_parser
from neuro_pipeline.utils.errors import FatalPipelineError
from neuro_pipeline.utils.execution_context import ExecutionContext
from neuro_pipeline.config.extensions import PIPELINE_VERSION, build_manifest, write_manifest
from neuro_pipeline.utils.logging_config import configure_logging
from neuro_pipeline.utils.paths import ProjectPaths, resolve_project_root

LOGGER = logging.getLogger(__name__)


def resolve_defacing_policy(
    paths: ProjectPaths,
    *,
    openneuro_mode: bool,
    enable_defacing: bool,
    skip_defacing: bool,
) -> tuple[bool, str]:
    """Determine whether defacing should run for this release."""
    has_anatomical = dataset_has_anatomical_mri(paths.raw_bids)
    if skip_defacing:
        if openneuro_mode and has_anatomical:
            raise FatalPipelineError(
                "OpenNeuro release requires defacing for anatomical MRI "
                "(--skip-defacing cannot be used when T1w/T2w volumes are present)"
            )
        return False, "skipped by user flag"

    if enable_defacing:
        return True, "explicitly enabled"

    if openneuro_mode and has_anatomical:
        LOGGER.info(
            "OpenNeuro mode: anatomical MRI detected — enabling defacing automatically"
        )
        return True, "auto-enabled (OpenNeuro + anatomical MRI)"

    return False, "not required"


def run_release_anonymization(
    paths: ProjectPaths,
    *,
    openneuro_mode: bool = True,
    enable_defacing: bool = False,
    skip_defacing: bool = False,
    seed: str | None = None,
    num_workers: int = 4,
    dataset_name: str = "Anonymized Neuroimaging Dataset",
) -> None:
    """Anonymize the internal BIDS dataset for public release."""
    if not paths.raw_bids.is_dir():
        raise FatalPipelineError(
            f"Research BIDS dataset not found: {paths.raw_bids}. "
            "Run the research pipeline (neuro-pipeline) first."
        )

    defacing, defacing_reason = resolve_defacing_policy(
        paths,
        openneuro_mode=openneuro_mode,
        enable_defacing=enable_defacing,
        skip_defacing=skip_defacing,
    )

    context = ExecutionContext.capture(
        project_root=paths.root,
        parameters={
            "openneuro_mode": openneuro_mode,
            "defacing": defacing,
            "defacing_reason": defacing_reason,
            "seed_provided": seed is not None,
        },
        deterministic_seed=seed,
    )
    context.write_json(paths.metadata / "release_dataset_context.json")

    paths.anonymization_release.mkdir(parents=True, exist_ok=True)
    config = AnonymizationConfig(
        input_dir=paths.raw_bids,
        output_root=paths.anonymization_release,
        enable_defacing=defacing,
        seed=seed,
        num_workers=num_workers,
        dataset_name=dataset_name,
    )
    pipeline = AnonymizationPipeline(config)
    stats = pipeline.run()

    if stats.n_files_failed > 0:
        raise FatalPipelineError(
            f"Release anonymization failed for {stats.n_files_failed} file(s); "
            f"see {paths.release_failed_files_csv}"
        )

    dataset_version = f"openneuro-{context.execution_id}" if openneuro_mode else f"release-{context.execution_id}"

    if openneuro_mode:
        write_openneuro_documentation(
            paths.public_dataset,
            dataset_name=dataset_name,
            dataset_version=dataset_version,
            defacing_applied=defacing,
            context=context,
        )
        write_provenance_json(
            paths.public_dataset / "PROVENANCE.json",
            context=context,
            dataset_version=dataset_version,
            pipeline_mode="openneuro_release",
            extra={
                "defacing_applied": defacing,
                "defacing_reason": defacing_reason,
                "subjects": stats.n_subjects,
                "files_processed": stats.n_files_processed,
            },
        )

    manifest = build_manifest(
        paths.root,
        steps_completed=["anonymize"],
        extra={
            "pipeline_mode": "openneuro_release" if openneuro_mode else "release",
            "release_input": str(paths.raw_bids.resolve()),
            "release_output": str(paths.public_dataset.resolve()),
            "release_subjects": stats.n_subjects,
            "release_files_processed": stats.n_files_processed,
            "release_defacing_enabled": defacing,
            "release_defacing_reason": defacing_reason,
            "openneuro_mode": openneuro_mode,
            "execution_id": context.execution_id,
        },
    )
    write_manifest(paths.anonymization_release / "release_manifest.json", manifest)

    status_path = paths.anonymization_release / "release_status.json"
    status_path.write_text(
        json.dumps(
            {
                "step": "anonymize",
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "pipeline_version": PIPELINE_VERSION,
                "openneuro_mode": openneuro_mode,
                "defacing_applied": defacing,
                "subjects": stats.n_subjects,
                "files_processed": stats.n_files_processed,
                "files_failed": stats.n_files_failed,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    LOGGER.info("Release anonymization complete: %s", paths.public_dataset)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = build_base_parser(
        description="Anonymize raw_bids/ for public release (OpenNeuro-ready by default)."
    )
    parser.add_argument("--openneuro", dest="openneuro", action="store_true", default=True)
    parser.add_argument("--no-openneuro", dest="openneuro", action="store_false")
    parser.add_argument(
        "--enable-defacing",
        action="store_true",
        help="Force defacing even outside OpenNeuro mode.",
    )
    parser.add_argument(
        "--skip-defacing",
        action="store_true",
        help="Skip defacing (disallowed in OpenNeuro mode when anatomical MRI is present).",
    )
    parser.add_argument("--seed", type=str, default=None)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--dataset-name", type=str, default="Anonymized Neuroimaging Dataset")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    paths = resolve_project_root(args.project_root)
    openneuro_mode = args.openneuro

    global LOGGER
    LOGGER = configure_logging(
        __name__,
        log_file=paths.metadata / "release_dataset.log",
        level=getattr(logging, args.log_level),
        master_log=args.master_log or paths.master_log,
    )

    LOGGER.info(
        "Starting public-release anonymization for %s (openneuro=%s)",
        paths.root,
        openneuro_mode,
    )
    try:
        run_release_anonymization(
            paths,
            openneuro_mode=openneuro_mode,
            enable_defacing=args.enable_defacing,
            skip_defacing=args.skip_defacing,
            seed=args.seed,
            num_workers=args.workers,
            dataset_name=args.dataset_name,
        )
    except FatalPipelineError as exc:
        LOGGER.error("FATAL: %s", exc.message)
        return 1
    except (PermissionError, OSError, ValueError) as exc:
        LOGGER.error("FATAL: %s", exc)
        return 1

    LOGGER.info("Public-release anonymization completed successfully")
    return 0


if __name__ == "__main__":
    sys.exit(main())
