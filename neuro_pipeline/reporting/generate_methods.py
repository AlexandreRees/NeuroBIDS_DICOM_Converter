#!/usr/bin/env python3
"""Generate manuscript-ready METHODS.md from pipeline provenance."""

from __future__ import annotations

import argparse
import logging
import sys

from neuro_pipeline.reporting.methods_generator import generate_methods_md
from neuro_pipeline.utils.cli import build_base_parser
from neuro_pipeline.utils.errors import FatalPipelineError
from neuro_pipeline.utils.logging_config import configure_logging
from neuro_pipeline.utils.paths import resolve_project_root

LOGGER = logging.getLogger(__name__)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = build_base_parser(
        description="Generate docs/METHODS.md from pipeline provenance artifacts."
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Entry point for neuro-generate-methods."""
    args = parse_args(argv)
    paths = resolve_project_root(args.project_root)

    global LOGGER
    LOGGER = configure_logging(
        __name__,
        log_file=paths.metadata / "generate_methods.log",
        level=getattr(logging, args.log_level),
        master_log=args.master_log or paths.master_log,
    )

    LOGGER.info("Generating Methods document for %s", paths.root)
    try:
        output = generate_methods_md(paths)
    except FatalPipelineError as exc:
        LOGGER.error("FATAL: %s", exc.message)
        return 1
    except (PermissionError, OSError) as exc:
        LOGGER.error("FATAL: %s", exc)
        return 1

    LOGGER.info("Methods document written to %s", output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
