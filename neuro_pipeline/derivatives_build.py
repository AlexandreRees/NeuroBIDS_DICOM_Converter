#!/usr/bin/env python3
"""Build and validate BIDS derivatives separation from raw_bids."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from neuro_pipeline.derivatives_metadata import write_derivatives_dataset_description
from neuro_pipeline.publication_metadata import write_citation_cff, write_default_license
from neuro_pipeline.raw_bids_guard import lock_raw_bids
from neuro_pipeline.utils.cli import build_base_parser
from neuro_pipeline.utils.errors import FatalPipelineError
from neuro_pipeline.utils.extensions import build_manifest, write_manifest
from neuro_pipeline.utils.logging_config import configure_logging
from neuro_pipeline.pipeline_steps import RESEARCH_STEP_NAMES
from neuro_pipeline.utils.paths import ProjectPaths, resolve_project_root
from neuro_pipeline.utils.raw_bids_purity import assert_raw_bids_purity, validate_raw_bids_purity

LOGGER = logging.getLogger(__name__)

DERIVATIVES_SUBDIRS: tuple[str, ...] = (
    "conversion",
    "validation",
    "qc",
)


def ensure_derivatives_layout(paths: ProjectPaths) -> None:
    """Create standard derivatives subdirectories."""
    paths.ensure_derivatives_dir()
    for subdir in DERIVATIVES_SUBDIRS:
        target = paths.derivatives / subdir
        target.mkdir(parents=True, exist_ok=True)
        paths.validate_writable(target)


def write_derivatives_readme(paths: ProjectPaths) -> None:
    """Write a README describing pipeline derivatives."""
    readme = paths.derivatives / "README"
    readme.write_text(
        "Neuro pipeline computed outputs. raw_bids/ contains BIDS raw data only.\n",
        encoding="utf-8",
    )


def run_derivatives_build(paths: ProjectPaths) -> dict[str, object]:
    """Validate raw_bids purity and finalize derivatives layout."""
    paths.ensure_metadata_dir()
    ensure_derivatives_layout(paths)
    write_derivatives_readme(paths)

    blockers = validate_raw_bids_purity(paths.raw_bids)
    if blockers:
        raise FatalPipelineError(
            "Derivatives build failed raw_bids purity check: "
            + "; ".join(blockers[:10])
        )

    assert_raw_bids_purity(paths.raw_bids)
    LOGGER.info("raw_bids purity validated: no forbidden pipeline artifacts")

    context = __import__(
        "neuro_pipeline.utils.execution_context", fromlist=["ExecutionContext"]
    ).ExecutionContext.capture(project_root=paths.root)
    write_derivatives_dataset_description(paths, context=context)
    dataset_version = f"research-{context.execution_id}"
    lock_payload = lock_raw_bids(paths, dataset_version=dataset_version)
    write_citation_cff(paths.raw_bids, title="Neuro BIDS Research Dataset", version=dataset_version)
    write_default_license(paths.raw_bids)

    summary = {
        "derivatives_root": str(paths.derivatives.resolve()),
        "raw_bids_purity": "pass",
        "subdirectories": list(DERIVATIVES_SUBDIRS),
        "raw_bids_locked": True,
        "dataset_version": dataset_version,
        "raw_bids_file_count": lock_payload.get("file_count", 0),
    }
    summary_path = paths.derivatives / "derivatives_build_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    manifest = build_manifest(
        paths.root,
        steps_completed=list(RESEARCH_STEP_NAMES),
        execution_context=context,
        project_paths=paths,
        extra={"derivatives_build": summary},
    )
    write_manifest(paths.pipeline_manifest_json, manifest)

    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = build_base_parser(
        description="Validate derivatives separation and raw_bids purity."
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Entry point for derivatives build."""
    args = parse_args(argv)
    paths = resolve_project_root(args.project_root)

    global LOGGER
    LOGGER = configure_logging(
        __name__,
        log_file=paths.metadata / "derivatives_build.log",
        level=getattr(logging, args.log_level),
        master_log=args.master_log or paths.master_log,
    )

    LOGGER.info("Starting derivatives build for %s", paths.root)
    try:
        run_derivatives_build(paths)
    except FatalPipelineError as exc:
        LOGGER.error("FATAL: %s", exc.message)
        return 1
    except (PermissionError, OSError) as exc:
        LOGGER.error("FATAL: %s", exc)
        return 1

    LOGGER.info("Derivatives build completed successfully")
    return 0


if __name__ == "__main__":
    sys.exit(main())
