"""Logging configuration for conversion sessions."""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path


CONVERSION_LOGGER_NAME = "neuro_pipeline.conversion"


def configure_logging(log_dir: Path | str | None = None) -> Path:
    """Configure root + conversion loggers and return the log file path.

    Default location (empty ``log_dir``)::

        %LOCALAPPDATA%\\NeuroPipeline\\logs\\conversion.log

    Never writes into the install / Program Files tree. Safe to call multiple times.
    """
    from neuro_pipeline.config.paths import resolve_writable_log_dir

    preferred = None if log_dir is None or str(log_dir).strip() == "" else log_dir
    directory = resolve_writable_log_dir(preferred)
    log_file = directory / "conversion.log"

    root = logging.getLogger()
    if getattr(root, "_neuro_pipeline_configured", False):
        return Path(getattr(root, "_neuro_pipeline_log_file", log_file))

    root.setLevel(logging.DEBUG)
    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    root.handlers.clear()

    file_ok = False
    try:
        directory.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=5_000_000,
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
        file_ok = True
    except OSError:
        # Console-only fallback — never abort startup for log I/O.
        log_file = Path("")

    console = logging.StreamHandler(sys.stderr)
    console.setLevel(logging.INFO)
    console.setFormatter(formatter)
    root.addHandler(console)

    setattr(root, "_neuro_pipeline_configured", True)
    setattr(root, "_neuro_pipeline_log_file", log_file if file_ok else None)

    logging.getLogger(CONVERSION_LOGGER_NAME).setLevel(logging.DEBUG)
    if file_ok:
        logging.getLogger(__name__).info("Logging to %s", log_file)
    else:
        logging.getLogger(__name__).warning(
            "Could not open a log file; console logging only."
        )
    return log_file if file_ok else directory / "conversion.log"


def get_conversion_log_path(log_dir: Path | str | None = None) -> Path:
    """Return the conversion.log path using the same resolution as configure_logging."""
    from neuro_pipeline.config.paths import resolve_writable_log_dir

    root = logging.getLogger()
    cached = getattr(root, "_neuro_pipeline_log_file", None)
    if cached:
        return Path(cached)
    preferred = None if log_dir is None or str(log_dir).strip() == "" else log_dir
    return resolve_writable_log_dir(preferred) / "conversion.log"


def get_conversion_logger() -> logging.Logger:
    """Return the dedicated conversion logger."""
    return logging.getLogger(CONVERSION_LOGGER_NAME)
