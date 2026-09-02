"""Shared PASS / REVIEW / FAIL / INFO presentation helpers."""

from __future__ import annotations

from PySide6.QtWidgets import QLabel

STATUS_OBJECT_NAMES = {
    "PASS": "statusPass",
    "REVIEW": "statusReview",
    "FAIL": "statusFail",
    "INFO": "statusInfo",
}

_PREFIX = {
    "PASS": "✓",
    "REVIEW": "⚠",
    "FAIL": "✕",
    "INFO": "●",
}


def status_object_name(level: str) -> str:
    return STATUS_OBJECT_NAMES.get((level or "").upper(), "statusInfo")


def format_status(level: str, text: str = "") -> str:
    key = (level or "INFO").upper()
    mark = _PREFIX.get(key, "●")
    body = text.strip() if text else key
    if body.upper() == key:
        return f"{mark} {key}"
    return f"{mark} {body}"


def apply_status(label: QLabel, level: str, text: str = "") -> None:
    key = (level or "INFO").upper()
    label.setObjectName(status_object_name(key))
    label.setText(format_status(key, text))
    label.style().unpolish(label)
    label.style().polish(label)
