"""Contextual inspector for a selected planned acquisition."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from neuro_pipeline.bids.conversion_plan import BIDSConversionPlan, PlannedAcquisition
from neuro_pipeline.gui.status_tokens import apply_status
from neuro_pipeline.models import DicomSeries


class AcquisitionInspector(QFrame):
    """Shows DICOM + BIDS fields for the selected series (plan metadata only)."""

    ask_requested = Signal(str)
    edit_requested = Signal(str)
    explain_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("inspectorPanel")
        self._uid = ""
        self._build_ui()
        self.clear()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        kicker = QLabel("SELECTED ACQUISITION")
        kicker.setObjectName("pageKicker")
        layout.addWidget(kicker)

        self.title = QLabel("No acquisition selected")
        self.title.setObjectName("titleLabel")
        self.title.setWordWrap(True)
        layout.addWidget(self.title)

        self.empty = QLabel("Select a subject, session, or acquisition in the BIDS Preview.")
        self.empty.setObjectName("statusLabel")
        self.empty.setWordWrap(True)
        layout.addWidget(self.empty)

        dicom_box = QLabel("DICOM")
        dicom_box.setObjectName("pageKicker")
        layout.addWidget(dicom_box)
        self.dicom_form = QFormLayout()
        self.series_desc = _mono()
        self.protocol = _mono()
        self.series_number = _mono()
        self.modality = QLabel("—")
        self.dicom_form.addRow("Series Description", self.series_desc)
        self.dicom_form.addRow("Protocol Name", self.protocol)
        self.dicom_form.addRow("Series Number", self.series_number)
        self.dicom_form.addRow("Modality", self.modality)
        layout.addLayout(self.dicom_form)

        bids_box = QLabel("BIDS")
        bids_box.setObjectName("pageKicker")
        layout.addWidget(bids_box)
        self.bids_form = QFormLayout()
        self.subject = _mono()
        self.session = _mono()
        self.datatype = _mono()
        self.task = _mono()
        self.suffix = _mono()
        self.filename = _mono()
        self.confidence = QLabel("—")
        self.bids_form.addRow("Subject", self.subject)
        self.bids_form.addRow("Session", self.session)
        self.bids_form.addRow("Datatype", self.datatype)
        self.bids_form.addRow("Task", self.task)
        self.bids_form.addRow("Suffix", self.suffix)
        self.bids_form.addRow("Filename", self.filename)
        self.bids_form.addRow("Confidence", self.confidence)
        layout.addLayout(self.bids_form)

        self.mapping_status = QLabel("")
        layout.addWidget(self.mapping_status)

        row = QHBoxLayout()
        self.edit_btn = QPushButton("Edit mapping")
        self.explain_btn = QPushButton("Explain")
        self.explain_btn.setToolTip(
            "Show why this acquisition is mapped this way (evidence, not chain-of-thought)."
        )
        self.ask_btn = QPushButton("Ask NeuroBIDS")
        self.ask_btn.setObjectName("primaryButton")
        self.edit_btn.clicked.connect(self._on_edit)
        self.explain_btn.clicked.connect(self._on_explain)
        self.ask_btn.clicked.connect(self._on_ask)
        row.addWidget(self.edit_btn)
        row.addWidget(self.explain_btn)
        row.addWidget(self.ask_btn)
        layout.addLayout(row)
        layout.addStretch(1)

    def clear(self) -> None:
        self._uid = ""
        self.title.setText("No acquisition selected")
        self.empty.setVisible(True)
        self._set_fields_visible(False)
        self.edit_btn.setEnabled(False)
        self.explain_btn.setEnabled(False)
        self.ask_btn.setEnabled(False)

    def set_acquisition(
        self,
        item: PlannedAcquisition | None,
        series: DicomSeries | None = None,
        plan: BIDSConversionPlan | None = None,  # noqa: ARG002
    ) -> None:
        if item is None:
            self.clear()
            return
        self._uid = item.source_series_uid
        self.empty.setVisible(False)
        self._set_fields_visible(True)
        desc = (series.series_description if series else "") or item.source_series_description
        self.title.setText(desc or item.intended_filename or "Acquisition")
        self.series_desc.setText(desc or "—")
        self.protocol.setText(
            (series.protocol_name if series else "") or item.source_protocol_name or "—"
        )
        number = (
            series.series_number
            if series is not None and series.series_number is not None
            else item.source_series_number
        )
        self.series_number.setText("—" if number is None else str(number))
        self.modality.setText((series.modality if series else "") or "—")
        self.subject.setText(_sub(item.subject))
        self.session.setText(_ses(item.session))
        self.datatype.setText(item.datatype or "—")
        self.task.setText(item.task or "—")
        self.suffix.setText(item.suffix or "—")
        self.filename.setText(item.intended_filename or "—")
        conf = float(item.confidence_score or 0.0)
        self.confidence.setText(f"{int(round(conf * 100))}%" if conf else "—")
        if series is not None and series.requires_manual_mapping:
            apply_status(self.mapping_status, "REVIEW", "Manual mapping required")
        elif not item.include_in_conversion:
            apply_status(self.mapping_status, "INFO", "Excluded from conversion")
        elif not item.datatype:
            apply_status(self.mapping_status, "REVIEW", "Missing datatype")
        else:
            apply_status(self.mapping_status, "PASS", "Mapped")
        self.edit_btn.setEnabled(True)
        self.explain_btn.setEnabled(True)
        self.ask_btn.setEnabled(True)

    def current_uid(self) -> str:
        return self._uid

    def _set_fields_visible(self, visible: bool) -> None:
        for i in range(self.dicom_form.rowCount()):
            label = self.dicom_form.itemAt(i, QFormLayout.ItemRole.LabelRole)
            field = self.dicom_form.itemAt(i, QFormLayout.ItemRole.FieldRole)
            if label and label.widget():
                label.widget().setVisible(visible)
            if field and field.widget():
                field.widget().setVisible(visible)
        for i in range(self.bids_form.rowCount()):
            label = self.bids_form.itemAt(i, QFormLayout.ItemRole.LabelRole)
            field = self.bids_form.itemAt(i, QFormLayout.ItemRole.FieldRole)
            if label and label.widget():
                label.widget().setVisible(visible)
            if field and field.widget():
                field.widget().setVisible(visible)
        self.mapping_status.setVisible(visible)

    def _on_edit(self) -> None:
        if self._uid:
            self.edit_requested.emit(self._uid)

    def _on_explain(self) -> None:
        if self._uid:
            self.explain_requested.emit(self._uid)

    def _on_ask(self) -> None:
        if not self._uid:
            return
        desc = self.title.text()
        dt = self.datatype.text()
        self.ask_requested.emit(
            f"Why was this classified as {dt}? Selected acquisition: {desc}."
        )


def _mono() -> QLabel:
    label = QLabel("—")
    label.setObjectName("monoLabel")
    label.setWordWrap(True)
    label.setTextInteractionFlags(label.textInteractionFlags())
    return label


def _sub(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return "—"
    return value if value.startswith("sub-") else f"sub-{value}"


def _ses(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return "—"
    return value if value.startswith("ses-") else f"ses-{value}"
