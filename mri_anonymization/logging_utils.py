"""Logging helpers for anonymization pipeline."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import pandas as pd

from mri_anonymization.models import FileResult


def configure_logger(log_file: Path, level: int = logging.INFO) -> logging.Logger:
    """Configure the pipeline logger with console and file handlers."""
    logger = logging.getLogger("mri_anonymization")
    logger.setLevel(level)
    logger.handlers.clear()
    logger.propagate = False

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    logger.addHandler(console)

    log_file.parent.mkdir(parents=True, exist_ok=True)
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger


def write_file_results(
    results: list[FileResult],
    summary_csv: Path,
    skipped_csv: Path,
    failed_csv: Path,
) -> None:
    """Persist file processing audit tables."""
    if not results:
        return

    rows = [
        {
            "source_path": result.source_path,
            "output_path": result.output_path,
            "subject_id": result.subject_id,
            "file_type": result.file_type,
            "status": result.status,
            "message": result.message,
        }
        for result in results
    ]
    pd.DataFrame(rows).to_csv(summary_csv, index=False)

    skipped = [row for row in rows if row["status"] == "skipped"]
    if skipped:
        pd.DataFrame(skipped).to_csv(skipped_csv, index=False)

    failed = [row for row in rows if row["status"] == "failed"]
    if failed:
        pd.DataFrame(failed).to_csv(failed_csv, index=False)
