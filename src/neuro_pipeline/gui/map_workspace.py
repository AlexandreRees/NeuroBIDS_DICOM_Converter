"""Map workspace — BIDS Preview as the central NeuroBIDS workspace."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from neuro_pipeline.gui.acquisition_inspector import AcquisitionInspector

if TYPE_CHECKING:
    from neuro_pipeline.gui.bids_preview_panel import BIDSPreviewPanel
    from neuro_pipeline.gui.neurobids_copilot_panel import NeuroBIDSCopilotPanel


class MapWorkspace(QWidget):
    """Subjects | BIDS Preview | Inspector. Copilot lives in the main shell."""

    selection_changed = Signal(dict)
    ask_requested = Signal(str)
    open_copilot_requested = Signal()

    def __init__(
        self,
        preview: BIDSPreviewPanel,
        copilot: NeuroBIDSCopilotPanel,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.preview_panel = preview
        self.copilot_panel = copilot
        self._build_ui()
        self.preview_panel.plan_changed.connect(self.refresh_subjects)
        self.preview_panel.acquisition_selected.connect(self._on_acquisition_selected)
        self.inspector.ask_requested.connect(self._on_inspector_ask)
        self.inspector.explain_requested.connect(self._on_inspector_explain)
        self.inspector.edit_requested.connect(self.preview_panel.select_uid)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(8)

        header = QHBoxLayout()
        col = QVBoxLayout()
        kicker = QLabel("② MAP")
        kicker.setObjectName("pageKicker")
        col.addWidget(kicker)
        title = QLabel("BIDS mapping")
        title.setObjectName("titleLabel")
        col.addWidget(title)
        header.addLayout(col, 1)
        hint = QLabel("Edits change the conversion plan only. Original DICOM files stay untouched.")
        hint.setObjectName("statusLabel")
        hint.setWordWrap(True)
        header.addWidget(hint, 2)
        root.addLayout(header)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(4)
        left_layout.addWidget(QLabel("Subjects"))
        self.subject_list = QListWidget()
        self.subject_list.setMinimumWidth(120)
        self.subject_list.currentItemChanged.connect(self._on_subject_clicked)
        left_layout.addWidget(self.subject_list, 1)
        splitter.addWidget(left)

        splitter.addWidget(self.preview_panel)

        self.inspector = AcquisitionInspector()
        self.inspector.setMinimumWidth(220)
        splitter.addWidget(self.inspector)

        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 5)
        splitter.setStretchFactor(2, 2)
        splitter.setSizes([160, 720, 280])
        root.addWidget(splitter, 1)

    def refresh_subjects(self) -> None:
        current = ""
        item = self.subject_list.currentItem()
        if item is not None:
            current = str(item.data(Qt.ItemDataRole.UserRole) or "")
        self.subject_list.blockSignals(True)
        self.subject_list.clear()
        all_item = QListWidgetItem("All subjects")
        all_item.setData(Qt.ItemDataRole.UserRole, "")
        self.subject_list.addItem(all_item)
        plan = self.preview_panel.plan
        seen: list[str] = []
        if plan is not None:
            for planned in plan.items:
                sub = (planned.subject or "").strip()
                if sub and sub not in seen:
                    seen.append(sub)
                    row = QListWidgetItem(_sub_label(sub))
                    row.setData(Qt.ItemDataRole.UserRole, sub)
                    self.subject_list.addItem(row)
        self.subject_list.blockSignals(False)
        if current:
            for i in range(self.subject_list.count()):
                row = self.subject_list.item(i)
                if row and str(row.data(Qt.ItemDataRole.UserRole) or "") == current:
                    self.subject_list.setCurrentRow(i)
                    return
        self.subject_list.setCurrentRow(0)

    def _on_subject_clicked(self, current: QListWidgetItem | None, _prev=None) -> None:  # noqa: ANN001
        if current is None:
            return
        subject = str(current.data(Qt.ItemDataRole.UserRole) or "")
        self.preview_panel.focus_subject(subject)
        if subject:
            self.selection_changed.emit({"subject": subject})

    def _on_acquisition_selected(self, uid: str) -> None:
        plan = self.preview_panel.plan
        item = plan.get(uid) if plan is not None else None
        series = None
        if uid:
            series = next(
                (
                    s
                    for s in getattr(self.preview_panel, "_series", [])
                    if (s.series_instance_uid or s.display_name) == uid
                ),
                None,
            )
        self.inspector.set_acquisition(item, series, plan)
        payload: dict[str, str] = {}
        if item is not None:
            payload = {
                "subject": item.subject,
                "session": item.session,
                "series_uid": item.source_series_uid,
                "description": item.source_series_description,
                "datatype": item.datatype,
                "suffix": item.suffix,
                "task": item.task,
            }
            self.copilot_panel.set_selection(**payload)
        self.selection_changed.emit(payload)

    def _on_inspector_ask(self, prompt: str) -> None:
        self.open_copilot_requested.emit()
        self.ask_requested.emit(prompt)

    def _on_inspector_explain(self, uid: str) -> None:
        self.open_copilot_requested.emit()
        self.copilot_panel.explain_mapping(uid)


def _sub_label(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return "(unknown)"
    return value if value.startswith("sub-") else f"sub-{value}"
