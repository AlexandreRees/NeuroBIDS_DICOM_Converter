"""Discover page — dataset overview (reuses existing scan / DatasetContext)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from neuro_pipeline.gui.audit_summary import dataset_overview
from neuro_pipeline.gui.status_tokens import apply_status
from neuro_pipeline.logging.privacy import safe_folder_label

if TYPE_CHECKING:
    from neuro_pipeline.gui.convert_widget import ConvertWidget


_SUGGESTED = (
    ("Explain this dataset", "Explain this dataset."),
    ("How many subjects are there?", "How many subjects are there?"),
    ("Show me the acquisition types", "Show me the acquisition types."),
    ("Find potential inconsistencies", "Find potential inconsistencies in this dataset."),
    ("What should I review before conversion?", "What should I review before conversion?"),
)


class DiscoverPage(QWidget):
    """First workflow stage: load a dataset and inspect counts."""

    ask_requested = Signal(str)
    open_map_requested = Signal()
    open_copilot_requested = Signal()

    def __init__(self, convert: ConvertWidget, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._convert = convert
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(12)

        kicker = QLabel("① DISCOVER")
        kicker.setObjectName("pageKicker")
        root.addWidget(kicker)
        title = QLabel("Dataset Discovery")
        title.setObjectName("titleLabel")
        root.addWidget(title)
        sub = QLabel("From raw neuroimaging data to a research-ready dataset.")
        sub.setObjectName("subtitleLabel")
        sub.setWordWrap(True)
        root.addWidget(sub)

        path_box = QGroupBox("Dataset")
        path_layout = QVBoxLayout(path_box)
        self.path_label = QLabel("No dataset selected")
        self.path_label.setObjectName("monoLabel")
        self.path_label.setWordWrap(True)
        path_row = QHBoxLayout()
        path_row.addWidget(self.path_label, 1)
        self.browse_btn = QPushButton("Select dataset…")
        self.browse_btn.setObjectName("primaryButton")
        self.browse_btn.clicked.connect(self._convert._browse_input)
        self.output_btn = QPushButton("Set output…")
        self.output_btn.clicked.connect(self._convert._browse_output)
        path_row.addWidget(self.browse_btn)
        path_row.addWidget(self.output_btn)
        path_layout.addLayout(path_row)
        self.output_label = QLabel("Output: not set")
        self.output_label.setObjectName("statusLabel")
        self.output_label.setWordWrap(True)
        path_layout.addWidget(self.output_label)
        self.scan_status = QLabel("")
        path_layout.addWidget(self.scan_status)
        root.addWidget(path_box)

        checks = QHBoxLayout()
        self.check_subjects = QLabel("")
        self.check_sessions = QLabel("")
        self.check_files = QLabel("")
        self.check_modalities = QLabel("")
        self.check_acq = QLabel("")
        for w in (
            self.check_subjects,
            self.check_sessions,
            self.check_files,
            self.check_modalities,
            self.check_acq,
        ):
            checks.addWidget(w)
        checks.addStretch(1)
        root.addLayout(checks)

        stats_box = QGroupBox("Dataset overview")
        grid = QGridLayout(stats_box)
        self.stat_subjects = _stat_card("Subjects")
        self.stat_sessions = _stat_card("Sessions")
        self.stat_acq = _stat_card("Acquisitions")
        self.stat_files = _stat_card("Files")
        for i, card in enumerate(
            (self.stat_subjects, self.stat_sessions, self.stat_acq, self.stat_files)
        ):
            grid.addWidget(card, 0, i)
        root.addWidget(stats_box)

        mod_box = QGroupBox("Modalities")
        mod_layout = QVBoxLayout(mod_box)
        self.modalities_label = QLabel("—")
        self.modalities_label.setWordWrap(True)
        mod_layout.addWidget(self.modalities_label)
        self.datatypes_label = QLabel("")
        self.datatypes_label.setObjectName("statusLabel")
        self.datatypes_label.setWordWrap(True)
        mod_layout.addWidget(self.datatypes_label)
        root.addWidget(mod_box)

        ask_box = QGroupBox("Ask NeuroBIDS")
        ask_layout = QVBoxLayout(ask_box)
        hint = QLabel("Suggested questions")
        hint.setObjectName("statusLabel")
        ask_layout.addWidget(hint)
        for label, prompt in _SUGGESTED:
            btn = QPushButton(label)
            btn.setObjectName("chipButton")
            btn.clicked.connect(lambda _=False, p=prompt: self._ask(p))
            ask_layout.addWidget(btn)
        open_row = QHBoxLayout()
        map_btn = QPushButton("Open Map")
        map_btn.clicked.connect(self.open_map_requested.emit)
        copilot_btn = QPushButton("Ask NeuroBIDS")
        copilot_btn.setObjectName("primaryButton")
        copilot_btn.clicked.connect(self.open_copilot_requested.emit)
        open_row.addWidget(map_btn)
        open_row.addWidget(copilot_btn)
        open_row.addStretch(1)
        ask_layout.addLayout(open_row)
        root.addWidget(ask_box)
        root.addStretch(1)

    def _ask(self, prompt: str) -> None:
        self.ask_requested.emit(prompt)

    def refresh(self) -> None:
        convert = self._convert
        folder = convert.input_edit.text().strip()
        output = convert.output_edit.text().strip()
        scanning = bool(getattr(convert, "is_scanning", lambda: False)())
        self.path_label.setText(safe_folder_label(folder) if folder else "No dataset selected")
        self.output_label.setText(
            f"Output: {safe_folder_label(output)}" if output else "Output: not set — required before conversion"
        )
        if scanning:
            apply_status(self.scan_status, "INFO", "Scanning…")
            return

        ctx = None
        session = convert.copilot_panel.controller.session
        if session is not None and session.plan.items:
            ctx = session.dataset_context()
        analysis = convert._analysis
        n_files = analysis.number_of_dicom_files if analysis is not None else 0
        overview = dataset_overview(ctx, n_files_fallback=n_files)
        if analysis is not None and not overview["files"]:
            overview["files"] = analysis.number_of_dicom_files
        if analysis is not None and not ctx:
            overview["subjects"] = analysis.number_of_subjects
            overview["acquisitions"] = analysis.number_of_series
            overview["files"] = analysis.number_of_dicom_files

        _set_stat(self.stat_subjects, overview["subjects"])
        _set_stat(self.stat_sessions, overview["sessions"])
        _set_stat(self.stat_acq, overview["acquisitions"])
        _set_stat(self.stat_files, overview["files"])

        has = overview["acquisitions"] > 0 or overview["subjects"] > 0
        apply_status(self.check_subjects, "PASS" if overview["subjects"] else "INFO", "Subjects")
        apply_status(self.check_sessions, "PASS" if overview["sessions"] else "INFO", "Sessions")
        apply_status(self.check_files, "PASS" if overview["files"] else "INFO", "Files")
        apply_status(
            self.check_modalities,
            "PASS" if overview["modalities"] else "INFO",
            "Modalities",
        )
        apply_status(self.check_acq, "PASS" if overview["acquisitions"] else "INFO", "Acquisitions")

        mods = overview["modalities"] or []
        dts = overview.get("datatypes") or {}
        self.modalities_label.setText(", ".join(mods) if mods else "No modalities detected yet.")
        if dts:
            self.datatypes_label.setText(
                "  ·  ".join(f"{k}: {v}" for k, v in dts.items())
            )
        else:
            self.datatypes_label.setText("")

        if not folder:
            apply_status(self.scan_status, "INFO", "Select a DICOM folder to begin.")
        elif not has:
            apply_status(self.scan_status, "REVIEW", "No acquisitions found.")
        else:
            apply_status(self.scan_status, "PASS", "Dataset loaded")


def _stat_card(caption: str) -> QFrame:
    frame = QFrame()
    frame.setObjectName("statCard")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(12, 10, 12, 10)
    value = QLabel("0")
    value.setObjectName("statValue")
    caption_lbl = QLabel(caption)
    caption_lbl.setObjectName("statCaption")
    layout.addWidget(value)
    layout.addWidget(caption_lbl)
    frame._value = value  # type: ignore[attr-defined]
    return frame


def _set_stat(card: QFrame, value: int) -> None:
    card._value.setText(f"{int(value):,}")  # type: ignore[attr-defined]
