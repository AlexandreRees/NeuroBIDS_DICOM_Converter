"""Protect page — original DICOM immutability and privacy posture."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import (
    QGroupBox,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from neuro_pipeline.gui.status_tokens import apply_status
from neuro_pipeline.logging.privacy import safe_folder_label

if TYPE_CHECKING:
    from neuro_pipeline.gui.convert_widget import ConvertWidget


class ProtectPage(QWidget):
    """Explain the privacy boundary. Reuses existing privacy behaviour."""

    def __init__(self, convert: ConvertWidget, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._convert = convert
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(12)

        kicker = QLabel("④ PROTECT")
        kicker.setObjectName("pageKicker")
        root.addWidget(kicker)
        title = QLabel("Protect original data")
        title.setObjectName("titleLabel")
        root.addWidget(title)
        sub = QLabel(
            "NeuroBIDS never modifies original DICOM files. Curation happens on the "
            "in-memory BIDS plan, then a de-identified BIDS export."
        )
        sub.setObjectName("subtitleLabel")
        sub.setWordWrap(True)
        root.addWidget(sub)

        flow = QGroupBox("Data flow")
        flow_layout = QVBoxLayout(flow)
        self.flow_label = QLabel(
            "Original data\n"
            "     │\n"
            "     │  READ ONLY\n"
            "     ▼\n"
            "NeuroBIDS processing\n"
            "     │\n"
            "     ▼\n"
            "De-identified BIDS release"
        )
        self.flow_label.setObjectName("monoLabel")
        flow_layout.addWidget(self.flow_label)
        root.addWidget(flow)

        guarantees = QGroupBox("Guarantees")
        g = QVBoxLayout(guarantees)
        self.g_dicom = QLabel("")
        self.g_plan = QLabel("")
        self.g_name = QLabel("")
        self.g_llm = QLabel("")
        for w in (self.g_dicom, self.g_plan, self.g_name, self.g_llm):
            w.setWordWrap(True)
            g.addWidget(w)
        apply_status(self.g_dicom, "PASS", "Original DICOM data is never modified by the curation interface")
        apply_status(self.g_plan, "PASS", "BIDS mapping edits affect the conversion plan only")
        apply_status(self.g_name, "PASS", "PatientName is never sent to Copilot or written to public JSON")
        apply_status(
            self.g_llm,
            "INFO",
            "Copilot cannot access the filesystem, DICOM pixels, or dcm2niix",
        )
        root.addWidget(guarantees)

        review = QGroupBox("Manual review")
        r = QVBoxLayout(review)
        self.review_label = QLabel(
            "De-identification of free-text fields (series descriptions, protocol names) "
            "still requires human review. NeuroBIDS does not claim that a dataset is "
            "fully anonymized."
        )
        self.review_label.setObjectName("statusLabel")
        self.review_label.setWordWrap(True)
        r.addWidget(self.review_label)
        self.dataset_label = QLabel("")
        self.dataset_label.setObjectName("monoLabel")
        self.dataset_label.setWordWrap(True)
        r.addWidget(self.dataset_label)
        root.addWidget(review)
        root.addStretch(1)

    def refresh(self) -> None:
        folder = self._convert.input_edit.text().strip()
        if folder:
            self.dataset_label.setText(f"Original data: {safe_folder_label(folder)}")
        else:
            self.dataset_label.setText("No dataset loaded.")
