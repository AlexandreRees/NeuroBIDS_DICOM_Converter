"""User-facing dialog helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import QMessageBox, QWidget

if TYPE_CHECKING:
    from neuro_pipeline.gui.user_errors import UserFacingError


def show_error(parent: QWidget | None, title: str, message: str) -> None:
    QMessageBox.critical(parent, title, message)


def show_warning(parent: QWidget | None, title: str, message: str) -> None:
    QMessageBox.warning(parent, title, message)


def show_info(parent: QWidget | None, title: str, message: str) -> None:
    QMessageBox.information(parent, title, message)


def confirm(parent: QWidget | None, title: str, message: str) -> bool:
    reply = QMessageBox.question(
        parent,
        title,
        message,
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.No,
    )
    return reply == QMessageBox.StandardButton.Yes


def show_user_facing_error(parent: QWidget | None, error: "UserFacingError") -> None:
    """Critical dialog with explanation, actions, and expandable details."""
    from neuro_pipeline.gui.user_errors import show_user_error

    show_user_error(parent, error)
