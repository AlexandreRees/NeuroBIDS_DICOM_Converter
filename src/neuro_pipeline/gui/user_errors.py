"""Structured user-facing errors (no stack traces by default)."""

from __future__ import annotations

import errno
import os
from dataclasses import dataclass, field
from typing import Sequence

from neuro_pipeline.utils.exceptions import (
    ConversionFailedError,
    CorruptedDicomError,
    Dcm2niixNotFoundError,
    EmptyFolderError,
    InvalidDicomFolderError,
    MissingDcm2niixError,
    NeuroPipelineError,
    NonDicomFolderError,
    OutputFolderError,
    PermissionDeniedError,
    ValidationError,
)


@dataclass(slots=True)
class UserFacingError:
    """Stable shape for GUI / logs presentation."""

    title: str
    explanation: str
    actions: list[str] = field(default_factory=list)
    details: str = ""
    code: str = ""
    log_hint: str = "See Logs for technical details."


def format_user_error(error: UserFacingError, *, include_details: bool = False) -> str:
    """Plain-text body suitable for labels or simple dialogs."""
    parts = [error.explanation.strip()]
    if error.actions:
        parts.append("")
        parts.append("Possible causes / next steps:")
        for action in error.actions:
            parts.append(f"• {action}")
    if error.log_hint:
        parts.append("")
        parts.append(error.log_hint)
    if include_details and error.details:
        parts.append("")
        parts.append(error.details.strip())
    return "\n".join(parts).strip()


def _os_error_code(exc: BaseException) -> int | None:
    if isinstance(exc, OSError):
        return getattr(exc, "errno", None)
    return None


def user_error_from_exception(exc: BaseException, *, fallback_title: str = "Something went wrong") -> UserFacingError:
    """Map known exceptions to a professional user message."""
    details = str(exc).strip()
    code = getattr(exc, "code", "") or ""

    if isinstance(exc, (MissingDcm2niixError, Dcm2niixNotFoundError)):
        return UserFacingError(
            title="dcm2niix unavailable",
            explanation="NeuroBIDS could not find the dcm2niix converter.",
            actions=[
                "Confirm dcm2niix is bundled with the application, or install it separately",
                "Set the path in Settings → dcm2niix",
                "Restart NeuroBIDS after installing dcm2niix",
            ],
            details=details,
            code=code or "dcm2niix_missing",
        )

    if isinstance(exc, EmptyFolderError):
        return UserFacingError(
            title="Empty folder",
            explanation="The selected folder appears empty.",
            actions=[
                "Choose a folder that contains DICOM files",
                "Check that you selected the correct drive or network share",
            ],
            details=details,
            code=code or "empty_folder",
        )

    if isinstance(exc, (NonDicomFolderError, InvalidDicomFolderError)):
        return UserFacingError(
            title="No DICOM files found",
            explanation="NeuroBIDS did not find readable DICOM series in this folder.",
            actions=[
                "Confirm the folder contains DICOM (.dcm) files",
                "Try the parent folder if series are nested deeply",
                "Check that files are not encrypted or incomplete",
            ],
            details=details,
            code=code or "no_dicom",
        )

    if isinstance(exc, CorruptedDicomError):
        return UserFacingError(
            title="Unreadable DICOM",
            explanation="At least one DICOM file could not be read.",
            actions=[
                "Re-export or re-copy the affected series from the scanner/PACS",
                "Exclude corrupted series from conversion if the rest of the dataset is usable",
            ],
            details=details,
            code=code or "corrupted_dicom",
        )

    if isinstance(exc, PermissionDeniedError) or _os_error_code(exc) in {errno.EACCES, errno.EPERM}:
        return UserFacingError(
            title="Permission denied",
            explanation="NeuroBIDS does not have permission to access this path.",
            actions=[
                "Choose a folder you can read and write",
                "Check network-share or institutional permissions",
                "Avoid writing into protected system directories",
            ],
            details=details,
            code=code or "permission_denied",
        )

    if isinstance(exc, OutputFolderError):
        lower = details.lower()
        if "exist" in lower:
            return UserFacingError(
                title="Output folder unavailable",
                explanation="The chosen output location cannot be used as-is.",
                actions=[
                    "Choose an empty folder for a new BIDS dataset",
                    "Or pick a different output path if the folder already contains data",
                ],
                details=details,
                code=code or "output_exists",
            )
        return UserFacingError(
            title="Output folder unavailable",
            explanation="NeuroBIDS could not prepare the output folder.",
            actions=[
                "Confirm the parent directory exists and is writable",
                "Check available disk space",
            ],
            details=details,
            code=code or "output_unavailable",
        )

    if isinstance(exc, ConversionFailedError):
        return UserFacingError(
            title="Conversion could not be completed",
            explanation="dcm2niix reported a failure while converting this dataset.",
            actions=[
                "Open Logs for the converter output",
                "Confirm the DICOM series is complete",
                "Retry after freeing disk space if the drive is nearly full",
            ],
            details=details,
            code=code or "conversion_failed",
        )

    if isinstance(exc, ValidationError):
        return UserFacingError(
            title="Validation could not finish",
            explanation="Post-conversion checks could not be completed.",
            actions=[
                "Open the conversion report for detailed findings",
                "Remember: BIDS-invalid does not automatically mean conversion-invalid",
            ],
            details=details,
            code=code or "validation_failed",
        )

    if isinstance(exc, FileNotFoundError) or _os_error_code(exc) == errno.ENOENT:
        return UserFacingError(
            title="Path not found",
            explanation="A required folder or file no longer exists.",
            actions=[
                "Confirm the DICOM source folder still exists",
                "Re-select the input and output folders",
                "Check that network drives are still mounted",
            ],
            details=details,
            code=code or "path_not_found",
        )

    if isinstance(exc, TimeoutError) or "timed out" in details.lower():
        return UserFacingError(
            title="Operation timed out",
            explanation="The operation took too long and was stopped.",
            actions=[
                "Retry the operation",
                "For Copilot, check that the LLM provider is reachable",
            ],
            details=details,
            code=code or "timeout",
        )

    if _os_error_code(exc) == errno.ENOSPC or "no space" in details.lower():
        return UserFacingError(
            title="Insufficient disk space",
            explanation="There is not enough free disk space to continue.",
            actions=[
                "Free space on the output drive",
                "Choose an output folder on a larger volume",
            ],
            details=details,
            code=code or "disk_full",
        )

    if isinstance(exc, NeuroPipelineError):
        return UserFacingError(
            title=fallback_title,
            explanation=details or "The operation could not be completed.",
            actions=["Retry the operation", "Open Logs if the problem continues"],
            details=details,
            code=code or "app_error",
        )

    # Unknown / unexpected — keep explanation generic; details hold the technical string.
    safe = details
    if "Traceback" in safe or "File \"" in safe:
        safe = safe.splitlines()[-1].strip() if safe else "Unexpected error"
    return UserFacingError(
        title=fallback_title,
        explanation="The operation could not be completed.",
        actions=[
            "Retry the operation",
            "Open Logs for technical details",
            "If this keeps happening, note the steps that lead to the error",
        ],
        details=safe,
        code=code or "unexpected",
    )


def user_error_from_message(
    message: str,
    *,
    title: str = "Something went wrong",
    actions: Sequence[str] | None = None,
    code: str = "",
) -> UserFacingError:
    """Best-effort mapping when only a worker string is available."""
    text = (message or "").strip()
    lower = text.lower()
    if "dcm2niix" in lower and ("not found" in lower or "missing" in lower or "cannot" in lower):
        return user_error_from_exception(MissingDcm2niixError(text), fallback_title=title)
    if "permission" in lower or "access is denied" in lower:
        return user_error_from_exception(PermissionDeniedError(text), fallback_title=title)
    if "no space" in lower or "errno 28" in lower:
        return UserFacingError(
            title="Insufficient disk space",
            explanation="There is not enough free disk space to continue.",
            actions=["Free space on the output drive", "Choose another output location"],
            details=text,
            code=code or "disk_full",
        )
    if "cancel" in lower:
        return UserFacingError(
            title="Cancelled",
            explanation="The operation was cancelled.",
            actions=["Start again when ready"],
            details=text,
            code=code or "cancelled",
        )
    if "no dicom" in lower or "non-dicom" in lower or "no readable" in lower:
        return user_error_from_exception(NonDicomFolderError(text), fallback_title=title)
    if "timed out" in lower or "timeout" in lower:
        return UserFacingError(
            title="Operation timed out",
            explanation="The operation took too long and was stopped.",
            actions=["Retry the operation"],
            details=text,
            code=code or "timeout",
        )
    return UserFacingError(
        title=title,
        explanation="The operation could not be completed.",
        actions=list(actions or ["Open Logs for technical details", "Retry the operation"]),
        details=text,
        code=code or "message",
    )


def show_user_error(parent, error: UserFacingError) -> None:  # noqa: ANN001
    """Show a critical dialog with optional expandable technical details."""
    from PySide6.QtWidgets import QMessageBox

    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Critical)
    box.setWindowTitle(error.title)
    box.setText(error.explanation)
    informative = []
    if error.actions:
        informative.append("Possible causes / next steps:\n" + "\n".join(f"• {a}" for a in error.actions))
    if error.log_hint:
        informative.append(error.log_hint)
    if informative:
        box.setInformativeText("\n\n".join(informative))
    if error.details:
        box.setDetailedText(error.details)
    box.exec()
