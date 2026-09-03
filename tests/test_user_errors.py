"""User-facing error mapping tests."""

from __future__ import annotations

import errno

import pytest

from neuro_pipeline.gui.user_errors import (
    format_user_error,
    user_error_from_exception,
    user_error_from_message,
)
from neuro_pipeline.utils.exceptions import (
    ConversionFailedError,
    EmptyFolderError,
    MissingDcm2niixError,
    NonDicomFolderError,
    OutputFolderError,
    PermissionDeniedError,
)


def test_dcm2niix_missing_maps_cleanly() -> None:
    err = user_error_from_exception(MissingDcm2niixError("dcm2niix not on PATH"))
    assert err.title.lower().startswith("dcm2niix")
    assert "Traceback" not in format_user_error(err)
    assert any("Settings" in a or "path" in a.lower() for a in err.actions)
    assert "dcm2niix not on PATH" in err.details


def test_empty_and_no_dicom() -> None:
    empty = user_error_from_exception(EmptyFolderError("empty"))
    assert "empty" in empty.title.lower() or "empty" in empty.explanation.lower()
    nod = user_error_from_exception(NonDicomFolderError("no dicom here"))
    assert "dicom" in nod.explanation.lower()


def test_permission_and_disk() -> None:
    perm = user_error_from_exception(PermissionDeniedError("denied"))
    assert "permission" in perm.title.lower()
    os_err = OSError(errno.ENOSPC, "No space left on device")
    disk = user_error_from_exception(os_err)
    assert "disk" in disk.title.lower() or "space" in disk.explanation.lower()


def test_output_and_conversion() -> None:
    out = user_error_from_exception(OutputFolderError("output already exists"))
    assert "output" in out.title.lower()
    conv = user_error_from_exception(ConversionFailedError("dcm2niix exit 1"))
    text = format_user_error(conv)
    assert "Conversion could not be completed" in conv.title or "could not" in text.lower()
    assert "Traceback" not in text


def test_message_heuristics() -> None:
    err = user_error_from_message("Permission denied: /data/out")
    assert err.code == "permission_denied" or "permission" in err.title.lower()
    err2 = user_error_from_message("Cancelled by user")
    assert err2.code == "cancelled"
    err3 = user_error_from_message("No DICOM series found")
    assert "dicom" in err3.explanation.lower()


def test_unexpected_strips_traceback_noise() -> None:
    raw = 'Traceback (most recent call last):\n  File "x.py", line 1\nRuntimeError: boom'
    err = user_error_from_exception(RuntimeError(raw))
    body = format_user_error(err, include_details=True)
    assert "Traceback" not in err.explanation
    assert "boom" in body or "boom" in err.details
