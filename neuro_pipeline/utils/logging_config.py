"""Centralized logging configuration for pipeline scripts."""

from __future__ import annotations

import logging
import sys
from pathlib import Path


def configure_logging(
    name: str,
    log_file: Path | None = None,
    level: int = logging.INFO,
    master_log: Path | None = None,
) -> logging.Logger:
    """Configure a named logger with console and optional file handlers.

    Parameters
    ----------
    name:
        Logger name, typically ``__name__`` of the calling module.
    log_file:
        Step-specific log file path.
    level:
        Logging level for all handlers.
    master_log:
        Shared orchestrator log file appended by each pipeline step.

    Returns
    -------
    logging.Logger
        Configured logger instance.
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.handlers.clear()
    logger.propagate = False

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    if master_log is not None:
        master_log.parent.mkdir(parents=True, exist_ok=True)
        master_handler = logging.FileHandler(master_log, encoding="utf-8")
        master_handler.setLevel(level)
        master_handler.setFormatter(formatter)
        logger.addHandler(master_handler)

    return logger
