#!/usr/bin/env python3
"""Production MRI anonymization for public neuroimaging dataset release.

This module integrates the mri_anonymization framework with the legacy
neuro_pipeline staging workflow.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from mri_anonymization.config import AnonymizationConfig
from mri_anonymization.pipeline import AnonymizationPipeline

from neuro_pipeline.utils.cli import build_base_parser
from neuro_pipeline.utils.errors import FatalPipelineError
from neuro_pipeline.utils.logging_config import configure_logging
from neuro_pipeline.utils.paths import ProjectPaths, resolve_project_root

LOGGER = logging.getLogger(__name__)


def run_deidentify(
    paths: ProjectPaths,
    *,
    enable_defacing: bool = False,
    skip_defacing: bool = False,
    seed: str | None = None,
    num_workers: int = 4,
) -> None:
    """Run the publication-grade anonymization framework on raw_bids."""
    if not paths.raw_bids.is_dir():
        raise FatalPipelineError(f"BIDS dataset not found: {paths.raw_bids}")

    output_root = paths.root / "anonymization_release"
    config = AnonymizationConfig(
        input_dir=paths.raw_bids,
        output_root=output_root,
        enable_defacing=enable_defacing and not skip_defacing,
        seed=seed,
        num_workers=num_workers,
        dataset_name="Neuro BIDS Anonymized Dataset",
    )
    pipeline = AnonymizationPipeline(config)
    stats = pipeline.run()

    if stats.n_files_failed > 0:
        raise FatalPipelineError(
            f"Anonymization failed for {stats.n_files_failed} file(s); "
            f"see {output_root / 'Private/logs'}"
        )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = build_base_parser(
        description="Anonymize BIDS dataset for public release (mri_anonymization)."
    )
    parser.add_argument(
        "--enable-defacing",
        action="store_true",
        help="Apply facial defacing during anonymization.",
    )
    parser.add_argument(
        "--skip-defacing",
        action="store_true",
        help="Disable defacing even if --enable-defacing is set.",
    )
    parser.add_argument(
        "--seed",
        type=str,
        default=None,
        help="Deterministic anonymization seed.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=4,
        help="Parallel worker processes.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Entry point for BIDS anonymization."""
    args = parse_args(argv)
    paths = resolve_project_root(args.project_root)

    global LOGGER
    LOGGER = configure_logging(
        __name__,
        log_file=paths.metadata / "deidentify_dicom.log",
        level=getattr(logging, args.log_level),
        master_log=args.master_log or paths.master_log,
    )

    LOGGER.info("Starting publication-grade anonymization for %s", paths.root)
    try:
        run_deidentify(
            paths,
            enable_defacing=args.enable_defacing,
            skip_defacing=args.skip_defacing,
            seed=args.seed,
            num_workers=args.workers,
        )
    except FatalPipelineError as exc:
        LOGGER.error("FATAL: %s", exc.message)
        return 1
    except (PermissionError, OSError) as exc:
        LOGGER.error("FATAL: %s", exc)
        return 1

    LOGGER.info("Anonymization completed successfully")
    return 0


if __name__ == "__main__":
    sys.exit(main())
