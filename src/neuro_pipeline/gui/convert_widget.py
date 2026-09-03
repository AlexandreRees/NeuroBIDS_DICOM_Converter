"""Convert page — professional one-click DICOM → BIDS workflow."""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from neuro_pipeline.batch.input_analysis import InputAnalysis
from neuro_pipeline.gui import dialogs
from neuro_pipeline.gui.bids_preview_panel import BIDSPreviewPanel
from neuro_pipeline.gui.neurobids_copilot_panel import NeuroBIDSCopilotPanel
from neuro_pipeline.gui.widgets import CollapsibleSection
from neuro_pipeline.logging.privacy import safe_folder_label
from neuro_pipeline.models import ConversionOptions, ProgressInfo
from neuro_pipeline.models.config import AppConfig
from neuro_pipeline.utils.exceptions import (
    Dcm2niixNotFoundError,
    MissingDcm2niixError,
    NeuroPipelineError,
)
from neuro_pipeline.utils.filesystem import folder_has_content
from neuro_pipeline.utils.naming import SmartFilenameEngine
from neuro_pipeline.workers import FolderConvertWorker, InventoryWorker, ScanWorker, start_worker

LOGGER = logging.getLogger(__name__)


class ConvertWidget(QWidget):
    """Conversion + inventory workflow (scan / dcm2niix / reports)."""

    dataset_changed = Signal()
    busy_changed = Signal(bool)
    open_map_requested = Signal()

    def __init__(
        self,
        config: AppConfig,
        naming_engine: SmartFilenameEngine,
        *,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.config = config
        self._naming_engine = naming_engine
        self.series = []
        self._analysis: InputAnalysis | None = None
        self._scan_thread = None
        self._scan_worker: ScanWorker | None = None
        self._convert_thread = None
        self._convert_worker: FolderConvertWorker | None = None
        self._inventory_thread = None
        self._inventory_worker: InventoryWorker | None = None
        self._last_report: Path | None = None
        self._last_bids_validation_report: Path | None = None
        self._last_output: Path | None = None
        self._dcm2niix_override: str = ""
        self._converting: bool = False
        self._last_input_folder: str = ""
        self._discovery_result = None

        self._build_ui()
        self.apply_config_defaults()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        outer.addWidget(scroll, stretch=1)

        content = QWidget()
        scroll.setWidget(content)
        root = QVBoxLayout(content)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(10)

        kicker = QLabel("TOOLS · DICOM → NIfTI / BIDS")
        kicker.setObjectName("pageKicker")
        root.addWidget(kicker)
        title = QLabel("Conversion")
        title.setObjectName("titleLabel")
        root.addWidget(title)
        intro = QLabel(
            "Run conversion and inventory here. BIDS mapping lives on the Map page. "
            "Original DICOM files are never modified."
        )
        intro.setObjectName("subtitleLabel")
        intro.setWordWrap(True)
        root.addWidget(intro)

        # --- Input Folder ---
        in_box = QGroupBox("Input Folder")
        in_layout = QHBoxLayout(in_box)
        self.input_edit = QLineEdit()
        self.input_edit.setPlaceholderText("DICOM folder…")
        self.input_browse = QPushButton("Browse…")
        self.input_browse.clicked.connect(self._browse_input)
        in_layout.addWidget(self.input_edit, 1)
        in_layout.addWidget(self.input_browse)
        root.addWidget(in_box)

        # --- Output Folder ---
        out_box = QGroupBox("Output Folder")
        out_layout = QHBoxLayout(out_box)
        self.output_edit = QLineEdit()
        self.output_edit.setPlaceholderText("BIDS dataset root…")
        self.output_browse = QPushButton("Browse…")
        self.output_browse.clicked.connect(self._browse_output)
        out_layout.addWidget(self.output_edit, 1)
        out_layout.addWidget(self.output_browse)
        root.addWidget(out_box)

        # --- Input analysis ---
        analysis_box = QGroupBox("Input analysis")
        analysis_layout = QVBoxLayout(analysis_box)
        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("Discovery mode:"))
        self.discovery_mode_combo = QComboBox()
        self.discovery_mode_combo.addItem("Automatic (recommended)", "automatic")
        self.discovery_mode_combo.addItem("PatientID only", "patient_id")
        self.discovery_mode_combo.addItem("Folder recursive", "folder_recursive")
        self.discovery_mode_combo.setCurrentIndex(0)
        self.discovery_mode_combo.currentIndexChanged.connect(self._on_discovery_mode_changed)
        mode_row.addWidget(self.discovery_mode_combo, 1)
        analysis_layout.addLayout(mode_row)
        self.analysis_view = QTextEdit()
        self.analysis_view.setReadOnly(True)
        self.analysis_view.setMinimumHeight(140)
        self.analysis_view.setMaximumHeight(240)
        self.analysis_view.setPlainText("No folder selected.")
        analysis_layout.addWidget(self.analysis_view)
        root.addWidget(analysis_box)

        # Preview + Copilot are owned here (data/session binding) but laid out
        # on the Map page / main shell so Map remains the central workspace.
        self.preview_panel = BIDSPreviewPanel()
        self.preview_panel.status_message.connect(self._on_preview_status)
        self.preview_panel.continue_requested.connect(self._on_preview_continue)
        self.preview_panel.plan_changed.connect(self.dataset_changed.emit)
        self.copilot_panel = NeuroBIDSCopilotPanel()
        self.copilot_panel.status_message.connect(self._on_preview_status)
        self.copilot_panel.bind_preview(self.preview_panel)

        map_note = QGroupBox("BIDS mapping")
        map_note_layout = QHBoxLayout(map_note)
        map_hint = QLabel(
            "Subjects, sessions, and acquisitions are curated on Map. "
            "Continue to Conversion when the plan is ready."
        )
        map_hint.setObjectName("statusLabel")
        map_hint.setWordWrap(True)
        open_map = QPushButton("Open Map")
        open_map.clicked.connect(self.open_map_requested.emit)
        map_note_layout.addWidget(map_hint, 1)
        map_note_layout.addWidget(open_map)
        root.addWidget(map_note)

        # --- Subject / Session (optional) ---
        id_box = QGroupBox("Subject / session")
        id_layout = QGridLayout(id_box)
        id_layout.setHorizontalSpacing(8)
        id_layout.setVerticalSpacing(4)
        self.subject_edit = QLineEdit()
        self.subject_edit.setPlaceholderText("optional — auto from PatientID when empty")
        self.session_edit = QLineEdit()
        self.session_edit.setPlaceholderText("optional, e.g. 01 or ses-01")
        id_layout.addWidget(QLabel("Subject:"), 0, 0)
        id_layout.addWidget(self.subject_edit, 0, 1)
        id_layout.addWidget(QLabel("Session:"), 1, 0)
        id_layout.addWidget(self.session_edit, 1, 1)
        hint = QLabel(
            "Leave Subject empty to use automatic discovery "
            "(unique PatientID, or subject folders when IDs collide/are missing). "
            "For multi-subject trees, each reconstructed subject becomes one BIDS subject."
        )
        hint.setObjectName("statusLabel")
        hint.setWordWrap(True)
        id_layout.addWidget(hint, 2, 0, 1, 2)
        root.addWidget(id_box)

        # --- Progress ---
        progress_box = QGroupBox("Progress")
        progress_layout = QVBoxLayout(progress_box)
        progress_layout.setSpacing(3)
        self.status_label = QLabel("Ready.")
        self.status_label.setObjectName("statusLabel")
        self.detail_label = QLabel("")
        self.current_series_label = QLabel("Current: —")
        self.series_progress_label = QLabel("Jobs completed: 0 / 0")
        self.eta_label = QLabel("")
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        for w in (
            self.status_label,
            self.current_series_label,
            self.series_progress_label,
            self.eta_label,
            self.detail_label,
            self.progress_bar,
        ):
            progress_layout.addWidget(w)
        root.addWidget(progress_box)

        # --- Advanced (collapsed) ---
        self.advanced_section = CollapsibleSection("Advanced options", expanded=False)
        self.chk_validate = QCheckBox("Validate output")
        self.chk_per_patient = QCheckBox("Create one folder per patient")
        self.chk_smart = QCheckBox("Smart filenames")
        self.chk_json = QCheckBox("Create JSON metadata")
        self.chk_compress = QCheckBox("Compress NIfTI (.nii.gz)")
        for w in (
            self.chk_validate,
            self.chk_per_patient,
            self.chk_smart,
            self.chk_json,
            self.chk_compress,
        ):
            self.advanced_section.add_widget(w)
        root.addWidget(self.advanced_section)

        # Compatibility aliases used by leftover summary references
        self.summary_subject = QLabel("Subject: —")
        self.summary_session = QLabel("Session: —")
        self.summary_bids = QLabel("BIDS: —")
        self.summary_provenance = QLabel("Provenance: —")
        for w in (
            self.summary_subject,
            self.summary_session,
            self.summary_bids,
            self.summary_provenance,
        ):
            w.setVisible(False)

        root.addStretch(1)

        actions = QHBoxLayout()
        self.open_output_btn = QPushButton("OPEN OUTPUT")
        self.open_output_btn.setEnabled(False)
        self.open_output_btn.clicked.connect(self.open_output_folder)
        self.inventory_btn = QPushButton("Generate Inventory")
        self.inventory_btn.clicked.connect(self._on_generate_inventory)
        self.convert_btn = QPushButton("Convert")
        self.convert_btn.setObjectName("primaryButton")
        self.convert_btn.clicked.connect(self._on_convert)
        actions.addWidget(self.open_output_btn)
        actions.addStretch(1)
        actions.addWidget(self.inventory_btn)
        actions.addWidget(self.convert_btn)
        root.addLayout(actions)

        self.input_edit.editingFinished.connect(self._maybe_autoscan)
        self.input_edit.textChanged.connect(lambda _=None: self.dataset_changed.emit())
        self.output_edit.textChanged.connect(lambda _=None: self.dataset_changed.emit())

    def is_scanning(self) -> bool:
        return self._scan_thread is not None and self._scan_thread.isRunning()

    def is_converting(self) -> bool:
        return bool(self._converting)

    def apply_config_defaults(self) -> None:
        self.chk_compress.setChecked(bool(self.config.compression))
        self.chk_per_patient.setChecked(bool(self.config.one_folder_per_patient))
        self.chk_json.setChecked(bool(self.config.preserve_json))
        self.chk_smart.setChecked(bool(self.config.smart_naming))
        self.chk_validate.setChecked(bool(self.config.validate_output))

    def set_dcm2niix_override(self, path: str) -> None:
        self._dcm2niix_override = (path or "").strip()

    def dcm2niix_override(self) -> str:
        return self._dcm2niix_override

    def _browse_input(self) -> None:
        from PySide6.QtWidgets import QFileDialog

        path = QFileDialog.getExistingDirectory(self, "Select DICOM folder")
        if path:
            self.input_edit.setText(path)
            self._start_scan(Path(path))

    def _browse_output(self) -> None:
        from PySide6.QtWidgets import QFileDialog

        path = QFileDialog.getExistingDirectory(self, "Select output folder")
        if path:
            self.output_edit.setText(path)

    def _maybe_autoscan(self) -> None:
        if self._converting or (
            self._convert_thread is not None and self._convert_thread.isRunning()
        ):
            return
        if self._scan_thread is not None and self._scan_thread.isRunning():
            return
        text = self.input_edit.text().strip()
        if not text or not Path(text).is_dir():
            return
        if text == self._last_input_folder and self._analysis is not None:
            return
        self._start_scan(Path(text))

    def _set_busy(self, busy: bool) -> None:
        self.input_browse.setEnabled(not busy)
        self.output_browse.setEnabled(not busy)
        self.convert_btn.setEnabled(not busy)
        self.inventory_btn.setEnabled(not busy)
        self.preview_panel.setEnabled(not busy)
        self.input_edit.setEnabled(not busy)
        self.output_edit.setEnabled(not busy)
        # Block Copilot mutations while scan/convert/inventory runs; keep panel visible.
        if hasattr(self, "copilot_panel"):
            self.copilot_panel.set_conversion_busy(busy or self._converting)
        self.busy_changed.emit(bool(busy or self._converting))

    def _discovery_mode(self) -> str:
        return str(self.discovery_mode_combo.currentData() or "automatic")

    def _on_discovery_mode_changed(self, _index: int = 0) -> None:
        text = self.input_edit.text().strip()
        if text and Path(text).is_dir() and not self._converting:
            self._start_scan(Path(text))

    def _start_scan(self, folder: Path) -> None:
        self._cleanup_scan()
        self._last_input_folder = str(folder)
        self._analysis = None
        self._discovery_result = None
        self.series = []
        self.analysis_view.setPlainText("Scanning…")
        self.status_label.setText("Analysing DICOM folder…")
        self.detail_label.setText(f"Folder: {safe_folder_label(folder)}")
        self.preview_panel.set_context(series=[], dataset_root=str(folder))
        self.preview_panel.rebuild_plan()
        self.progress_bar.setRange(0, 0)
        self._set_busy(True)

        self._scan_worker = ScanWorker(folder, discovery_mode=self._discovery_mode())
        self._scan_thread = start_worker(self._scan_worker)
        self._scan_worker.progress.connect(self._on_scan_progress)
        self._scan_worker.discovery_finished.connect(self._on_discovery_finished)
        self._scan_worker.finished.connect(self._on_scan_finished)
        self._scan_worker.failed.connect(self._on_scan_failed)
        self._scan_thread.finished.connect(self._scan_thread.deleteLater)
        self._scan_thread.start()

    def _on_scan_progress(self, message: str) -> None:
        self.status_label.setText(message)

    def _on_discovery_finished(self, result: object) -> None:
        self._discovery_result = result

    def _on_scan_finished(self, series: list) -> None:
        self.series = list(series)
        for item in self.series:
            item.smart_name = self._naming_engine.resolve(
                item.series_description,
                item.protocol_name,
            )
        if self._discovery_result is not None:
            self._analysis = InputAnalysis.from_discovery(
                self.series,
                self._discovery_result,
                folder=self._last_input_folder,
            )
        else:
            self._analysis = InputAnalysis.from_series(
                self.series,
                folder=self._last_input_folder,
                discovery_mode=self._discovery_mode(),
            )
        self.analysis_view.setPlainText(self._analysis.summary_text())
        self._update_preview_plan()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        n_jobs = max(self._analysis.number_of_subjects, 0)
        self.series_progress_label.setText(f"Jobs completed: 0 / {n_jobs}")
        if self._analysis.has_dicom:
            self.status_label.setText(
                f"Detected {self._analysis.number_of_subjects} subject(s), "
                f"{self._analysis.number_of_series} series."
            )
            self.detail_label.setText("Review the analysis, then click Convert.")
        else:
            self.status_label.setText("No DICOM files detected.")
            self.detail_label.setText("")
        self._set_busy(False)
        self._cleanup_scan()
        self.dataset_changed.emit()

    def _on_scan_failed(self, message: str) -> None:
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self._analysis = InputAnalysis.empty(
            self._last_input_folder or "",
            message="No DICOM files detected.",
        )
        self.analysis_view.setPlainText(self._analysis.summary_text())
        self.status_label.setText("Scan failed.")
        self.detail_label.setText(message)
        self._set_busy(False)
        # Soft-fail: empty folders are expected user feedback, not a hard crash dialog
        if "no dicom" not in message.lower():
            from neuro_pipeline.gui.dialogs import show_user_facing_error
            from neuro_pipeline.gui.user_errors import user_error_from_message

            show_user_facing_error(
                self,
                user_error_from_message(
                    message,
                    title="DICOM scan could not be completed",
                    actions=[
                        "Confirm the folder still exists and is readable",
                        "Confirm it contains DICOM files",
                        "Open Logs for technical details",
                    ],
                    code="scan_failed",
                ),
            )
        self._cleanup_scan()
        self.dataset_changed.emit()

    def _cleanup_scan(self) -> None:
        if self._scan_worker is not None:
            self._scan_worker.stop()
        if self._scan_thread is not None and self._scan_thread.isRunning():
            self._scan_thread.quit()
            self._scan_thread.wait(2000)
        self._scan_worker = None
        self._scan_thread = None

    def load_demo_dataset(
        self,
        *,
        series: list,
        plan,
        dataset_root: str,
        output_root: str = "",
        analysis: InputAnalysis | None = None,
    ) -> None:
        """Inject an in-memory dataset for UI Preview/Demo Mode (no DICOM scan).

        Uses the live Preview + Copilot widgets. Does not read real DICOM files.
        """
        self._cleanup_scan()
        self.series = list(series)
        self._last_input_folder = dataset_root
        self.input_edit.setText(dataset_root)
        if output_root:
            self.output_edit.setText(output_root)
        self._analysis = analysis
        if self._analysis is not None:
            self.analysis_view.setPlainText(self._analysis.summary_text())
        else:
            self.analysis_view.setPlainText(
                f"Preview demo: {len(self.series)} synthetic series (no real DICOM)."
            )
        self.preview_panel.set_context(
            series=self.series,
            dataset_root=dataset_root,
            output_root=output_root or self.output_edit.text().strip(),
        )
        # Use the provided plan object so demo scenarios stay deterministic.
        self.preview_panel._plan = plan
        self.preview_panel._populate()
        self.preview_panel.status.setText(
            f"Preview demo plan: {sum(1 for i in plan.items if i.include_in_conversion)} "
            f"of {len(plan.items)} series included."
        )
        self.copilot_panel.rebind_session_from_preview()
        session = self.copilot_panel.controller.session
        if session is not None:
            if analysis is not None:
                session.n_dicom_files = int(analysis.number_of_dicom_files or 0)
                session.detection_method = analysis.detection_method or "preview_demo"
                session.detection_reason = analysis.detection_reason or "UI Preview/Demo Mode"
            else:
                session.detection_method = "preview_demo"
                session.detection_reason = "UI Preview/Demo Mode"
        self.status_label.setText("Preview/Demo Mode — synthetic dataset loaded.")
        self.detail_label.setText("No real DICOM. Copilot uses FakeLLMProvider.")
        self.preview_panel.plan_changed.emit()
        self.dataset_changed.emit()

    def _update_preview_plan(self) -> None:
        self.preview_panel.set_context(
            series=self.series,
            dataset_root=self._last_input_folder,
            output_root=self.output_edit.text().strip(),
            subject_override=self.subject_edit.text().strip(),
            session_override=self.session_edit.text().strip(),
        )
        self.preview_panel.rebuild_plan()
        if hasattr(self, "copilot_panel"):
            self.copilot_panel.rebind_session_from_preview()
            session = self.copilot_panel.controller.session
            if session is not None and self._analysis is not None:
                session.n_dicom_files = int(self._analysis.number_of_dicom_files or 0)
                session.detection_method = self._analysis.detection_method or ""
                session.detection_reason = self._analysis.detection_reason or ""
        self.dataset_changed.emit()

    def _on_preview_status(self, message: str) -> None:
        self.detail_label.setText(message)

    def _on_preview_continue(self) -> None:
        self.status_label.setText("BIDS plan validated — ready to convert.")
        self.detail_label.setText("Review Subject/Session if needed, then click Convert.")
        self.convert_btn.setFocus()

    def _active_conversion_plan(self):
        """Return the preview plan when present (validated by ConversionManager)."""
        panel = getattr(self, "preview_panel", None)
        if panel is None:
            return None
        plan = panel.plan
        if plan is None:
            return None
        # Sync latest table edits before handoff
        panel._sync_table_into_plan()
        plan.refresh_filenames(seed_existing_from_output=True)
        return plan

    def current_options(self) -> ConversionOptions:
        return ConversionOptions(
            compress=self.chk_compress.isChecked(),
            one_folder_per_patient=self.chk_per_patient.isChecked(),
            preserve_json=self.chk_json.isChecked(),
            smart_naming=self.chk_smart.isChecked(),
            validate_output=self.chk_validate.isChecked(),
            output_layout="bids",
            subject_id=self.subject_edit.text().strip(),
            session_id=self.session_edit.text().strip(),
            study_mode="single",
            session_queue=[],
            export_profile="",
            threads=int(self.config.threads or 4),
            dcm2niix_path=self.resolve_dcm2niix_path(),
        )

    def resolve_dcm2niix_path(self) -> str:
        if self._dcm2niix_override:
            return self._dcm2niix_override
        return self.config.dcm2niix_path or "auto"

    def _inventory_output_dir(self, input_path: Path) -> Path:
        out_text = self.output_edit.text().strip()
        if out_text:
            return Path(out_text)
        return input_path / "inventory"

    def _on_generate_inventory(self) -> None:
        try:
            input_path = Path(self.input_edit.text().strip())
            if not input_path.exists():
                raise NeuroPipelineError("Please select a valid DICOM input folder.")
            if self._analysis is None or str(input_path) != self._last_input_folder:
                self._start_scan(input_path)
                raise NeuroPipelineError(
                    "Input analysis is running.\nWait for it to finish, then click Generate Inventory."
                )
            if not self._analysis.has_dicom or not self.series:
                raise NeuroPipelineError("No DICOM files detected.")

            subject = self.subject_edit.text().strip()
            session = self.session_edit.text().strip()
            if subject or session:
                from neuro_pipeline.bids.subject_manager import SubjectManager

                mgr = SubjectManager()
                try:
                    if subject:
                        mgr.validate_subject_id(subject)
                    if session:
                        mgr.validate_session_id(session)
                except ValueError as exc:
                    raise NeuroPipelineError(str(exc)) from exc
        except NeuroPipelineError as exc:
            dialogs.show_warning(self, "Cannot generate inventory", str(exc))
            return

        output_path = self._inventory_output_dir(input_path)
        self._cleanup_inventory()
        self.status_label.setText("Generating DICOM inventory…")
        self.detail_label.setText(f"Output: {safe_folder_label(output_path)}")
        self.current_series_label.setText("Current: inventory")
        self.series_progress_label.setText(f"Series: 0 / {len(self.series)}")
        self.progress_bar.setRange(0, 0)
        self._set_busy(True)

        self._inventory_worker = InventoryWorker(
            folder=input_path,
            output_dir=output_path,
            series_list=self.series,
            subject_id=self.subject_edit.text().strip(),
            session_id=self.session_edit.text().strip(),
            naming_engine=self._naming_engine,
            write_csv=True,
        )
        self._inventory_thread = start_worker(self._inventory_worker)
        self._inventory_worker.progress.connect(self._on_inventory_progress)
        self._inventory_worker.finished.connect(self._on_inventory_finished)
        self._inventory_worker.failed.connect(self._on_inventory_failed)
        self._inventory_thread.finished.connect(self._inventory_thread.deleteLater)
        self._inventory_thread.start()

    def _on_inventory_progress(self, message: str) -> None:
        self.status_label.setText(message)
        self.current_series_label.setText(f"Current: {message}")

    def _on_inventory_finished(self, result: object) -> None:
        self._set_busy(False)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(100)
        xlsx = getattr(result, "xlsx_path", "") or ""
        csv_path = getattr(result, "csv_path", "") or ""
        n_series = getattr(result, "n_series", 0)
        n_subjects = getattr(result, "n_subjects", 0)
        self.series_progress_label.setText(f"Series: {n_series} / {n_series}")
        self.current_series_label.setText("Current: —")
        self.status_label.setText("Inventory complete")
        out_dir = Path(xlsx).parent if xlsx else Path(self.output_edit.text().strip() or ".")
        self._last_output = out_dir
        self.open_output_btn.setEnabled(out_dir.exists())
        self.detail_label.setText(
            f"{n_series} series, {n_subjects} subject(s).\n{xlsx}"
            + (f"\n{csv_path}" if csv_path else "")
        )
        dialogs.show_info(
            self,
            "Inventory complete",
            (
                f"Wrote inventory for {n_series} series "
                f"({n_subjects} subject(s)).\n\n{xlsx}"
                + (f"\n{csv_path}" if csv_path else "")
            ),
        )
        self._cleanup_inventory()

    def _on_inventory_failed(self, message: str) -> None:
        self._set_busy(False)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.status_label.setText("Inventory failed.")
        self.detail_label.setText(message)
        dialogs.show_error(self, "Inventory failed", message)
        self._cleanup_inventory()

    def _cleanup_inventory(self) -> None:
        if self._inventory_worker is not None:
            self._inventory_worker.stop()
        if self._inventory_thread is not None and self._inventory_thread.isRunning():
            self._inventory_thread.quit()
            self._inventory_thread.wait(2000)
        self._inventory_worker = None
        self._inventory_thread = None

    def _prompt_for_dcm2niix(self) -> str | None:
        from PySide6.QtWidgets import QFileDialog

        path, _ = QFileDialog.getOpenFileName(
            self,
            "Locate dcm2niix",
            "",
            "Executable (dcm2niix.exe dcm2niix);;All files (*)",
        )
        return path or None

    def _on_convert(self) -> None:
        try:
            input_path = Path(self.input_edit.text().strip())
            output_path = Path(self.output_edit.text().strip())
            if not input_path.exists():
                raise NeuroPipelineError("Please select a valid DICOM input folder.")
            if not self.output_edit.text().strip():
                raise NeuroPipelineError("Please select an output folder.")

            # Ensure analysis is available; re-scan synchronously via worker path if needed
            if self._analysis is None or str(input_path) != self._last_input_folder:
                self._start_scan(input_path)
                raise NeuroPipelineError(
                    "Input analysis is running.\nWait for it to finish, then click Convert."
                )
            if not self._analysis.has_dicom:
                raise NeuroPipelineError("No DICOM files detected.")

            subject = self.subject_edit.text().strip()
            session = self.session_edit.text().strip()
            if subject or session:
                from neuro_pipeline.bids.subject_manager import SubjectManager

                mgr = SubjectManager()
                try:
                    if subject:
                        mgr.validate_subject_id(subject)
                    if session:
                        mgr.validate_session_id(session)
                except ValueError as exc:
                    raise NeuroPipelineError(str(exc)) from exc
                if subject and self._analysis.number_of_subjects > 1:
                    dialogs.show_warning(
                        self,
                        "Subject override ignored for multi-subject folder",
                        (
                            "Multiple subjects were detected. The Subject field is only "
                            "applied when a single subject is present.\n"
                            "Each DICOM PatientID will be converted to its own BIDS subject."
                        ),
                    )

            if folder_has_content(output_path):
                proceed = dialogs.confirm(
                    self,
                    "Output folder not empty",
                    (
                        "The output folder already contains files.\n\n"
                        "Continue anyway? Existing series folders will not be overwritten; "
                        "new unique folder names will be created when needed."
                    ),
                )
                if not proceed:
                    return

            plan = self._active_conversion_plan()
            if plan is not None:
                validation = plan.validate()
                n_err = len(validation.errors)
                n_warn = len(validation.warnings)
                self.detail_label.setText(
                    f"NIfTI conversion: READY | BIDS validation: "
                    f"{n_warn} warning(s) / {n_err} error(s)"
                )
                if not validation.ok:
                    # BIDS-invalid ≠ conversion-invalid — warn but continue.
                    dialogs.show_warning(
                        self,
                        "BIDS plan has issues",
                        (
                            "BIDS validation reported problems.\n"
                            "NIfTI conversion will still continue.\n\n"
                            + validation.summary()
                        ),
                    )
        except NeuroPipelineError as exc:
            from neuro_pipeline.gui.dialogs import show_user_facing_error
            from neuro_pipeline.gui.user_errors import user_error_from_exception

            show_user_facing_error(
                self,
                user_error_from_exception(exc, fallback_title="Cannot start conversion"),
            )
            return

        from neuro_pipeline.converter import Converter

        probe = Converter(dcm2niix_path=self.resolve_dcm2niix_path())
        try:
            probe.verify()
        except (MissingDcm2niixError, Dcm2niixNotFoundError) as exc:
            from neuro_pipeline.gui.dialogs import show_user_facing_error
            from neuro_pipeline.gui.user_errors import user_error_from_exception

            show_user_facing_error(
                self,
                user_error_from_exception(exc, fallback_title="dcm2niix unavailable"),
            )
            chosen = self._prompt_for_dcm2niix()
            if not chosen:
                return
            self._dcm2niix_override = chosen
        except Exception as exc:  # noqa: BLE001
            from neuro_pipeline.gui.dialogs import show_user_facing_error
            from neuro_pipeline.gui.user_errors import user_error_from_exception

            show_user_facing_error(
                self,
                user_error_from_exception(exc, fallback_title="Cannot start conversion"),
            )
            return

        LOGGER.info(
            "Convert handoff: subjects=%s series=%s plan=%s",
            self._analysis.number_of_subjects if self._analysis else 0,
            len(self.series),
            bool(plan),
        )

        self._cleanup_convert()
        self._converting = True
        self._last_report = None
        self._last_bids_validation_report = None
        self._last_output = output_path
        self.open_output_btn.setEnabled(False)
        self.status_label.setText("Starting conversion…")
        self.current_series_label.setText("Current: —")
        self.series_progress_label.setText(
            f"Jobs completed: 0 / {self._analysis.number_of_subjects}"
        )
        self.progress_bar.setValue(0)
        self._set_busy(True)

        options = self.current_options()
        self._convert_worker = FolderConvertWorker(
            folder=input_path,
            output_dir=output_path,
            options=options,
            subject_id=self.subject_edit.text().strip(),
            session_id=self.session_edit.text().strip(),
            analysis=self._analysis,
            conversion_plan=plan,
        )
        self._convert_thread = start_worker(self._convert_worker)
        self._convert_worker.progress.connect(self._on_folder_progress)
        self._convert_worker.job_updated.connect(self._on_job_updated)
        self._convert_worker.finished.connect(self._on_folder_finished)
        self._convert_worker.failed.connect(self._on_convert_failed)
        self._convert_thread.finished.connect(self._convert_thread.deleteLater)
        self._convert_thread.start()

    def _on_folder_progress(self, message: str) -> None:
        self.status_label.setText(message)
        self.current_series_label.setText(f"Current: {message}")

    def _on_job_updated(self, job: object) -> None:
        jobs = []
        if self._convert_worker is not None and self._convert_worker._manager is not None:
            jobs = self._convert_worker._manager.queue.all_jobs()
        if not jobs:
            return
        done = sum(1 for j in jobs if getattr(j, "status", None) and j.status.value in {"COMPLETED", "FAILED"})
        total = len(jobs)
        self.series_progress_label.setText(f"Jobs completed: {done} / {total}")
        self.progress_bar.setValue(int(100 * done / total) if total else 0)
        label = getattr(job, "label", "") or getattr(job, "subject_id", "") or "—"
        status = getattr(getattr(job, "status", None), "value", "")
        self.detail_label.setText(f"{label}: {status}")

    def _on_folder_finished(self, jobs: object) -> None:
        self._converting = False
        self._set_busy(False)
        job_list = list(jobs) if isinstance(jobs, list) else []
        failed = [j for j in job_list if getattr(j, "status", None) and j.status.value == "FAILED"]
        completed = [j for j in job_list if getattr(j, "status", None) and j.status.value == "COMPLETED"]
        self.progress_bar.setValue(100)
        self.series_progress_label.setText(
            f"Jobs completed: {len(completed)} / {len(job_list)}"
        )
        self.current_series_label.setText("Current: —")
        self._last_output = Path(self.output_edit.text().strip())
        self.open_output_btn.setEnabled(self._last_output.exists())
        self.status_label.setText("Conversion completed")
        self.detail_label.setText(
            f"{len(completed)} succeeded, {len(failed)} failed."
        )
        if failed:
            errors = "\n".join(
                f"- {j.label}: {j.error or 'failed'}" for j in failed[:8]
            )
            dialogs.show_warning(
                self,
                "Conversion completed with errors",
                f"{len(failed)} job(s) failed.\n\n{errors}",
            )
        else:
            dialogs.show_info(
                self,
                "Conversion completed",
                "Conversion completed successfully.",
            )
        self._cleanup_convert()

    def _on_convert_progress(self, info: object) -> None:
        # Kept for API compatibility with older hooks / tests.
        if not isinstance(info, ProgressInfo):
            return
        self.progress_bar.setValue(int(info.percent))
        self.status_label.setText(info.message or info.current_series or "Working…")

    def _on_convert_failed(self, message: str) -> None:
        self._converting = False
        self._set_busy(False)
        self.status_label.setText("Conversion aborted.")
        from neuro_pipeline.gui.dialogs import show_user_facing_error
        from neuro_pipeline.gui.user_errors import user_error_from_message

        error = user_error_from_message(
            message,
            title="Conversion could not be completed",
            actions=[
                "Open Logs for technical details",
                "Confirm the DICOM source is still accessible",
                "Confirm the output folder is writable and has free space",
            ],
            code="conversion_failed",
        )
        show_user_facing_error(self, error)
        if "dcm2niix" in (message or "").lower():
            chosen = self._prompt_for_dcm2niix()
            if chosen:
                self._dcm2niix_override = chosen
        self._cleanup_convert()

    def _cleanup_convert(self) -> None:
        if self._convert_worker is not None:
            self._convert_worker.stop()
        if self._convert_thread is not None and self._convert_thread.isRunning():
            self._convert_thread.quit()
            self._convert_thread.wait(2000)
        self._convert_worker = None
        self._convert_thread = None

    def open_output_folder(self) -> None:
        path = self._last_output or Path(self.output_edit.text().strip())
        if not path or not Path(path).exists():
            dialogs.show_warning(self, "Output folder", "Output folder is not available yet.")
            return
        _open_path(Path(path))

    def shutdown(self) -> None:
        self._cleanup_scan()
        self._cleanup_convert()
        self._cleanup_inventory()


def _open_path(path: Path) -> None:
    target = str(path)
    try:
        if sys.platform.startswith("win"):
            os.startfile(target)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", target])  # noqa: S603
        else:
            subprocess.Popen(["xdg-open", target])  # noqa: S603
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("Could not open path: %s", exc)
