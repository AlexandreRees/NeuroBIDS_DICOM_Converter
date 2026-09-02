"""Log viewer page."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from neuro_pipeline.logging.setup import get_conversion_log_path
from neuro_pipeline.models.config import AppConfig


class LogWidget(QWidget):
    """Display ``conversion.log`` (and related logger output) in a text view."""

    def __init__(
        self,
        config: AppConfig,
        *,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.config = config
        self._last_size = -1
        self._build_ui()
        self._timer = QTimer(self)
        self._timer.setInterval(1500)
        self._timer.timeout.connect(self.refresh)
        self._timer.start()
        self.refresh()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(8)

        header = QHBoxLayout()
        title = QLabel("Logs")
        title.setObjectName("titleLabel")
        header.addWidget(title)
        header.addStretch(1)
        self.path_label = QLabel("")
        self.path_label.setObjectName("statusLabel")
        header.addWidget(self.path_label)
        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.clicked.connect(self.refresh)
        header.addWidget(self.refresh_btn)
        root.addLayout(header)

        self.view = QPlainTextEdit(self)
        self.view.setReadOnly(True)
        self.view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.view.setObjectName("logView")
        root.addWidget(self.view, stretch=1)

    def log_path(self) -> Path:
        """Same resolution as :func:`configure_logging` / :func:`get_conversion_log_path`."""
        return get_conversion_log_path(self.config.log_dir or None)

    def refresh(self) -> None:
        path = self.log_path()
        self.path_label.setText(str(path))
        if not path.is_file():
            self.view.setPlainText(
                f"No log file yet.\nExpected location:\n{path}\n\n"
                "Run a conversion to create conversion.log."
            )
            self._last_size = -1
            return
        try:
            size = path.stat().st_size
            if size == self._last_size and self.view.toPlainText():
                return
            # Tail large logs for responsiveness
            data = path.read_bytes()
            if len(data) > 400_000:
                data = data[-400_000:]
            text = data.decode("utf-8", errors="replace")
            self.view.setPlainText(text)
            self.view.moveCursor(QTextCursor.MoveOperation.End)
            self._last_size = size
        except OSError as exc:
            self.view.setPlainText(f"Could not read log file:\n{exc}")

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self.refresh()

    def shutdown(self) -> None:
        self._timer.stop()
