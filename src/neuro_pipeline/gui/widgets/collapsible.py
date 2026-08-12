"""Reusable collapsible section widget."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)


class CollapsibleSection(QWidget):
    """Title bar that expands/collapses an inner content widget."""

    def __init__(
        self,
        title: str,
        *,
        parent: QWidget | None = None,
        expanded: bool = False,
    ) -> None:
        super().__init__(parent)
        self._title = title
        self._expanded = bool(expanded)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._toggle = QToolButton(self)
        self._toggle.setObjectName("collapsibleToggle")
        self._toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._toggle.setArrowType(
            Qt.ArrowType.DownArrow if self._expanded else Qt.ArrowType.RightArrow
        )
        self._toggle.setText(title)
        self._toggle.setCheckable(True)
        self._toggle.setChecked(self._expanded)
        self._toggle.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self._toggle.clicked.connect(self._on_toggled)
        root.addWidget(self._toggle)

        self._body = QFrame(self)
        self._body.setObjectName("collapsibleBody")
        self._body.setFrameShape(QFrame.Shape.NoFrame)
        self._body_layout = QVBoxLayout(self._body)
        self._body_layout.setContentsMargins(8, 6, 4, 8)
        self._body_layout.setSpacing(6)
        root.addWidget(self._body)

        self._body.setVisible(self._expanded)
        self._refresh_title()

    @property
    def content_layout(self) -> QVBoxLayout:
        return self._body_layout

    def add_widget(self, widget: QWidget) -> None:
        self._body_layout.addWidget(widget)

    def add_layout(self, layout) -> None:  # noqa: ANN001
        self._body_layout.addLayout(layout)

    def set_expanded(self, expanded: bool) -> None:
        self._expanded = bool(expanded)
        self._toggle.setChecked(self._expanded)
        self._body.setVisible(self._expanded)
        self._toggle.setArrowType(
            Qt.ArrowType.DownArrow if self._expanded else Qt.ArrowType.RightArrow
        )
        self._refresh_title()

    def _on_toggled(self, checked: bool) -> None:
        self.set_expanded(checked)

    def _refresh_title(self) -> None:
        marker = "▼" if self._expanded else "▶"
        self._toggle.setText(f"{marker} {self._title}")
