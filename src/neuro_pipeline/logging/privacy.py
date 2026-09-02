"""Privacy-safe logging helpers (no PHI / no absolute DICOM paths)."""

from __future__ import annotations

from pathlib import Path


def safe_folder_label(path: Path | str | None) -> str:
    """Return a non-identifying folder label suitable for logs.

    Uses only the final path component (basename), never the full absolute path.
    """
    if path is None:
        return "<unset>"
    name = Path(path).name.strip()
    return name or "<unnamed>"


def session_log_message(
    *,
    input_folder: Path | str | None,
    output_folder: Path | str | None,
    n_series: int,
    status: str,
) -> str:
    """Format a conversion-session log line without PHI."""
    return (
        f"status={status} "
        f"input={safe_folder_label(input_folder)} "
        f"output={safe_folder_label(output_folder)} "
        f"series={n_series}"
    )
