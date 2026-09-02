"""Conversion Queue page — large multi-subject conversion monitoring."""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from neuro_pipeline.gui import dialogs
from neuro_pipeline.models import ConversionOptions
from neuro_pipeline.models.config import AppConfig
from neuro_pipeline.workers import start_worker
from neuro_pipeline.workers.conversion_queue import (
    ConversionJob,
    ConversionQueueManager,
    QueueJobStatus,
)

LOGGER = logging.getLogger(__name__)


class _QueueRunner(QObject):
    progress = Signal(object)
    finished = Signal(list)
    failed = Signal(str)

    def __init__(self, manager: ConversionQueueManager) -> None:
        super().__init__()
        self.manager = manager
        self._stop = False

    def stop(self) -> None:
        self._stop = True
        self.manager.pause_queue()

    def run(self) -> None:
        try:
            jobs = self.manager.run(
                job_updated=lambda job: self.progress.emit(job),
                stop_check=lambda: self._stop,
            )
            self.finished.emit(jobs)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))


class ConversionQueueWidget(QWidget):
    """Advanced conversion queue UI."""

    def __init__(
        self,
        config: AppConfig,
        *,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.config = config
        self.manager = ConversionQueueManager(
            options=ConversionOptions(
                output_layout="bids",
                compress=bool(config.compression),
                dcm2niix_path=config.dcm2niix_path or "auto",
                validate_output=bool(config.validate_output),
            )
        )
        self.manager.load()
        self._thread: QThread | None = None
        self._worker: _QueueRunner | None = None
        self._build_ui()
        self._refresh_table()
        unfinished = sum(
            1
            for j in self.manager.jobs
            if j.status in {QueueJobStatus.QUEUED, QueueJobStatus.PAUSED, QueueJobStatus.FAILED}
        )
        if unfinished:
            self.status_label.setText(
                f"Recovered {len(self.manager.jobs)} job(s); {unfinished} unfinished."
            )

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        title = QLabel("Conversion Queue")
        title.setObjectName("titleLabel")
        root.addWidget(title)

        hint = QLabel(
            "Queue many subjects for sequential conversion. Uses the existing conversion "
            "engine without modifying DICOM files. State is restored from conversion_queue.json."
        )
        hint.setWordWrap(True)
        hint.setObjectName("statusLabel")
        root.addWidget(hint)

        add_box = QGroupBox("Add job")
        grid = QGridLayout(add_box)
        self.subject_edit = QLineEdit()
        self.subject_edit.setPlaceholderText("001 or sub-001")
        self.session_edit = QLineEdit()
        self.session_edit.setPlaceholderText("optional, e.g. 01")
        self.input_edit = QLineEdit()
        self.output_edit = QLineEdit()
        in_browse = QPushButton("Browse…")
        out_browse = QPushButton("Browse…")
        in_browse.clicked.connect(self._browse_input)
        out_browse.clicked.connect(self._browse_output)
        add_btn = QPushButton("Add to queue")
        add_btn.clicked.connect(self._add_job)
        grid.addWidget(QLabel("Subject"), 0, 0)
        grid.addWidget(self.subject_edit, 0, 1)
        grid.addWidget(QLabel("Session"), 0, 2)
        grid.addWidget(self.session_edit, 0, 3)
        grid.addWidget(QLabel("Input"), 1, 0)
        grid.addWidget(self.input_edit, 1, 1, 1, 2)
        grid.addWidget(in_browse, 1, 3)
        grid.addWidget(QLabel("Output"), 2, 0)
        grid.addWidget(self.output_edit, 2, 1, 1, 2)
        grid.addWidget(out_browse, 2, 3)
        grid.addWidget(add_btn, 3, 3)
        root.addWidget(add_box)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["Subject", "Session", "Status", "Progress", "Time", "Action"]
        )
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        root.addWidget(self.table, 1)

        self.detail = QLabel("Current: —")
        self.detail.setObjectName("statusLabel")
        root.addWidget(self.detail)

        controls = QHBoxLayout()
        self.start_btn = QPushButton("Start Queue")
        self.start_btn.setObjectName("primaryButton")
        self.pause_btn = QPushButton("Pause Queue")
        self.resume_btn = QPushButton("Resume Queue")
        self.cancel_btn = QPushButton("Cancel Selected")
        self.retry_btn = QPushButton("Retry Failed")
        self.remove_btn = QPushButton("Remove Selected")
        for b in (
            self.start_btn,
            self.pause_btn,
            self.resume_btn,
            self.cancel_btn,
            self.retry_btn,
            self.remove_btn,
        ):
            controls.addWidget(b)
        controls.addStretch(1)
        root.addLayout(controls)

        self.status_label = QLabel("Ready.")
        self.status_label.setObjectName("statusLabel")
        root.addWidget(self.status_label)

        self.start_btn.clicked.connect(self._start)
        self.pause_btn.clicked.connect(self._pause)
        self.resume_btn.clicked.connect(self._resume)
        self.cancel_btn.clicked.connect(self._cancel_selected)
        self.retry_btn.clicked.connect(self._retry_failed)
        self.remove_btn.clicked.connect(self._remove_selected)

    def _browse_input(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Select DICOM folder")
        if path:
            self.input_edit.setText(path)

    def _browse_output(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Select BIDS output folder")
        if path:
            self.output_edit.setText(path)

    def _add_job(self) -> None:
        subject = self.subject_edit.text().strip()
        session = self.session_edit.text().strip()
        inp = self.input_edit.text().strip()
        out = self.output_edit.text().strip()
        if not subject or not inp or not out:
            dialogs.show_warning(
                self,
                "Add job",
                "Subject, input folder, and output folder are required.",
            )
            return
        if not Path(inp).is_dir():
            dialogs.show_warning(self, "Add job", "Input folder does not exist.")
            return
        job = ConversionJob.create(
            subject=subject,
            session=session,
            input_path=inp,
            output_path=out,
        )
        self.manager.add_job(job)
        self._refresh_table()
        self.status_label.setText(f"Added job {job.job_id} ({job.subject}).")

    def _selected_job_id(self) -> str | None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return None
        item = self.table.item(rows[0].row(), 0)
        return str(item.data(Qt.ItemDataRole.UserRole) or "") if item else None

    def _refresh_table(self) -> None:
        self.table.setRowCount(0)
        for job in self.manager.jobs:
            row = self.table.rowCount()
            self.table.insertRow(row)
            elapsed = _format_time(job)
            action = _action_hint(job)
            cells = [
                job.subject,
                job.session or "—",
                job.status.value,
                f"{job.progress:.0f}%",
                elapsed,
                action,
            ]
            for col, value in enumerate(cells):
                cell = QTableWidgetItem(value)
                if col == 0:
                    cell.setData(Qt.ItemDataRole.UserRole, job.job_id)
                cell.setFlags(cell.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(row, col, cell)

    def _start(self) -> None:
        if self.manager.is_running:
            dialogs.show_warning(self, "Queue", "Queue is already running.")
            return
        if not any(j.status in {QueueJobStatus.QUEUED, QueueJobStatus.PAUSED} for j in self.manager.jobs):
            dialogs.show_warning(self, "Queue", "No queued jobs to start.")
            return
        self._cleanup_worker()
        self.status_label.setText("Queue running…")
        self._worker = _QueueRunner(self.manager)
        self._thread = start_worker(self._worker)
        self._worker.progress.connect(self._on_job_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.failed.connect(self._on_failed)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.start()

    def _pause(self) -> None:
        self.manager.pause_queue()
        self._refresh_table()
        self.status_label.setText("Queue paused — current job may finish its step.")

    def _resume(self) -> None:
        self.manager.resume_queue()
        self._refresh_table()
        if not self.manager.is_running:
            self._start()
        else:
            self.status_label.setText("Queue resumed.")

    def _cancel_selected(self) -> None:
        job_id = self._selected_job_id()
        if not job_id:
            dialogs.show_warning(self, "Cancel", "Select a job first.")
            return
        self.manager.cancel_job(job_id)
        self._refresh_table()

    def _retry_failed(self) -> None:
        n = self.manager.retry_failed()
        self._refresh_table()
        self.status_label.setText(f"Re-queued {n} failed job(s).")

    def _remove_selected(self) -> None:
        job_id = self._selected_job_id()
        if not job_id:
            return
        job = self.manager.get(job_id)
        if job and job.status in {
            QueueJobStatus.ANALYZING,
            QueueJobStatus.CONVERTING,
            QueueJobStatus.VALIDATING,
        }:
            dialogs.show_warning(self, "Remove", "Cannot remove a running job — cancel it first.")
            return
        self.manager.remove_job(job_id)
        self._refresh_table()

    def _on_job_progress(self, job: object) -> None:
        if not isinstance(job, ConversionJob):
            return
        self._refresh_table()
        self.detail.setText(
            f"{job.subject} | Step: {job.current_step or '—'} | "
            f"Series: {job.current_series or '—'} | Progress: {job.progress:.0f}%"
        )

    def _on_finished(self, _jobs: object) -> None:
        self._refresh_table()
        self.status_label.setText("Queue finished.")
        self.detail.setText("Current: —")
        self._cleanup_worker()

    def _on_failed(self, message: str) -> None:
        self._refresh_table()
        self.status_label.setText("Queue error.")
        dialogs.show_error(self, "Queue failed", message)
        self._cleanup_worker()

    def _cleanup_worker(self) -> None:
        if self._worker is not None:
            self._worker.stop()
        if self._thread is not None and self._thread.isRunning():
            self._thread.quit()
            self._thread.wait(2000)
        self._worker = None
        self._thread = None

    def shutdown(self) -> None:
        self.manager.pause_queue()
        self._cleanup_worker()
        self.manager.save()


def _format_time(job: ConversionJob) -> str:
    if job.start_time and job.end_time:
        return "done"
    if job.start_time:
        return "running"
    return "—"


def _action_hint(job: ConversionJob) -> str:
    if job.status == QueueJobStatus.FAILED:
        return "Retry"
    if job.status in {QueueJobStatus.QUEUED, QueueJobStatus.PAUSED}:
        return "Remove"
    if job.status in {
        QueueJobStatus.ANALYZING,
        QueueJobStatus.CONVERTING,
        QueueJobStatus.VALIDATING,
    }:
        return "Pause"
    return "—"
