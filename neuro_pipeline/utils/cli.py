"""Shared argparse helpers for pipeline scripts."""

from __future__ import annotations

import argparse
from pathlib import Path


def add_project_root_argument(parser: argparse.ArgumentParser) -> None:
    """Add standard ``--project-root`` argument."""
    parser.add_argument(
        "--project-root",
        type=Path,
        default=None,
        help=(
            "Root directory containing raw_original/, metadata/, and raw_bids/. "
            "Defaults to the current working directory."
        ),
    )


def add_master_log_argument(parser: argparse.ArgumentParser) -> None:
    """Add optional shared master log path (used by orchestrator)."""
    parser.add_argument(
        "--master-log",
        type=Path,
        default=None,
        help="Optional shared master log file path for orchestrated runs.",
    )


def add_log_level_argument(parser: argparse.ArgumentParser) -> None:
    """Add ``--log-level`` argument."""
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="Logging verbosity.",
    )


def build_base_parser(description: str) -> argparse.ArgumentParser:
    """Create a parser with common pipeline arguments."""
    parser = argparse.ArgumentParser(
        description=description,
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    add_project_root_argument(parser)
    add_master_log_argument(parser)
    add_log_level_argument(parser)
    return parser
