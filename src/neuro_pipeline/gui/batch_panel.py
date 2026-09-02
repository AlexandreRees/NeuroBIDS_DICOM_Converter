"""Batch conversion page (preserves existing BatchWorker)."""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
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

from neuro_pipeline.batch import BatchJob, BatchJobStatus, BatchManager
from neuro_pipeline.gui import dialogs
from neuro_pipeline.models import ConversionOptions
from neuro_pipeline.workers import BatchWorker, start_worker

LOGGER = logging.getLogger(__name__)


class BatchWidget(QWidget):
    """Batch queue: add folders, map Subject IDs, run BIDS batch conversion."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.manager = BatchManager()
        self._thread = None
        self._worker: BatchWorker | None = None
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(8)

        title = QLabel("Batch")
        title.setObjectName("titleLabel")
        root.addWidget(title)

        out_box = QGroupBox("Output")
        out_layout = QHBoxLayout(out_box)
        self.output_edit = QLineEdit()
        self.output_edit.setPlaceholderText("BIDS dataset root (dataset/sub-001/, …)")
        btn_out = QPushButton("Browse")
        btn_out.clicked.connect(self._browse_output)
        out_layout.addWidget(QLabel("Output:"))
        out_layout.addWidget(self.output_edit, 1)
        out_layout.addWidget(btn_out)
        root.addWidget(out_box)

        table_box = QGroupBox("Queue / subject mapping")
        table_layout = QVBoxLayout(table_box)
        self.status_label = QLabel(
            "Add folders, then set a BIDS Subject ID for each (never inferred from folder names)."
        )
        self.status_label.setObjectName("statusLabel")
        self.status_label.setWordWrap(True)
        table_layout.addWidget(self.status_label)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["Folder", "Subject ID", "Status", "Progress", "Result"]
        )
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col in (1, 2, 3, 4):
            self.table.horizontalHeader().setSectionResizeMode(
                col, QHeaderView.ResizeMode.ResizeToContents
            )
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.itemChanged.connect(self._on_subject_edited)
        table_layout.addWidget(self.table)
        root.addWidget(table_box, stretch=1)

        actions = QHBoxLayout()
        self.add_btn = QPushButton("Add folder")
        self.add_btn.clicked.connect(self._add_folder)
        self.remove_btn = QPushButton("Remove")
        self.remove_btn.clicked.connect(self._remove_selected)
        self.scan_btn = QPushButton("Scan dataset")
        self.scan_btn.clicked.connect(self._scan_dataset)
        self.start_btn = QPushButton("Start batch")
        self.start_btn.setObjectName("primaryButton")
        self.start_btn.clicked.connect(self._start_all)
        self.pause_btn = QPushButton("Pause")
        self.pause_btn.clicked.connect(self._pause)
        self.pause_btn.setEnabled(False)
        for btn in (
            self.add_btn,
            self.remove_btn,
            self.scan_btn,
            self.start_btn,
            self.pause_btn,
        ):
            actions.addWidget(btn)
        actions.addStretch(1)
        root.addLayout(actions)

    def _browse_output(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Select batch output directory")
        if path:
            self.output_edit.setText(path)

    def _ensure_output(self) -> Path | None:
        out = self.output_edit.text().strip()
        if not out:
            dialogs.show_error(self, "Missing output", "Select a batch output directory.")
            return None
        path = Path(out)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _add_folder(self) -> None:
        out = self._ensure_output()
        if out is None:
            return
        path = QFileDialog.getExistingDirectory(self, "Select subject DICOM folder")
        if not path:
            return
        folder = Path(path)
        job = BatchJob.create(folder, out, label=folder.name)
        for existing in self.manager.queue.all_jobs():
            if Path(existing.input_path) == folder:
                dialogs.show_warning(
                    self, "Already queued", f"{folder.name} is already in the queue."
                )
                return
        self.manager.queue.add(job)
        self._refresh_table()
        self.status_label.setText(f"Added {folder.name} — set Subject ID before starting.")

    def _remove_selected(self) -> None:
        rows = sorted({idx.row() for idx in self.table.selectedIndexes()}, reverse=True)
        if not rows:
            dialogs.show_warning(self, "Remove", "Select one or more jobs to remove.")
            return
        jobs = self.manager.queue.all_jobs()
        keep = [job for i, job in enumerate(jobs) if i not in set(rows)]
        self.manager.queue.replace_all(keep)
        self._refresh_table()
        self.status_label.setText(f"{len(keep)} job(s) remaining.")

    def _scan_dataset(self) -> None:
        out = self._ensure_output()
        if out is None:
            return
        inp = QFileDialog.getExistingDirectory(
            self, "Select dataset root (subject001/, subject002/, …)"
        )
        if not inp:
            return
        try:
            jobs = self.manager.discover_datasets(inp, output_root=out)
        except Exception as exc:  # noqa: BLE001
            dialogs.show_error(self, "Batch scan failed", str(exc))
            return
        self._refresh_table()
        self.status_label.setText(
            f"{len(jobs)} subject folder(s) discovered (any depth) — "
            "enter Subject ID for each before Start."
        )

    def _refresh_table(self) -> None:
        self.table.blockSignals(True)
        jobs = self.manager.queue.all_jobs()
        self.table.setRowCount(len(jobs))
        for row, job in enumerate(jobs):
            progress = (
                f"{job.converted_count + job.failed_count}/{job.series_count}"
                if job.series_count
                else "—"
            )
            result = job.error or (
                "OK"
                if job.status == BatchJobStatus.COMPLETED
                else ("Partial" if job.failed_count else "")
            )
            folder_item = QTableWidgetItem(job.label)
            folder_item.setFlags(folder_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, 0, folder_item)

            sub_item = QTableWidgetItem(job.subject_id or "")
            sub_item.setFlags(sub_item.flags() | Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, 1, sub_item)

            for col, value in enumerate((job.status.value, progress, result), start=2):
                item = QTableWidgetItem(value)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                if col == 2 and job.status == BatchJobStatus.FAILED:
                    item.setForeground(Qt.GlobalColor.red)
                elif col == 2 and job.status == BatchJobStatus.COMPLETED:
                    item.setForeground(Qt.GlobalColor.darkGreen)
                self.table.setItem(row, col, item)
        self.table.blockSignals(False)

    def _on_subject_edited(self, item: QTableWidgetItem) -> None:
        if item.column() != 1:
            return
        jobs = self.manager.queue.all_jobs()
        if 0 <= item.row() < len(jobs):
            jobs[item.row()].subject_id = item.text().strip()

    def _sync_subjects_from_table(self) -> None:
        jobs = self.manager.queue.all_jobs()
        for row, job in enumerate(jobs):
            cell = self.table.item(row, 1)
            if cell is not None:
                job.subject_id = cell.text().strip()

    def _options(self) -> ConversionOptions:
        return ConversionOptions(output_layout="bids")

    def _set_busy(self, busy: bool) -> None:
        self.add_btn.setEnabled(not busy)
        self.remove_btn.setEnabled(not busy)
        self.scan_btn.setEnabled(not busy)
        self.start_btn.setEnabled(not busy)
        self.pause_btn.setEnabled(busy)
        self.table.setEnabled(not busy)

    def _start_all(self) -> None:
        self._sync_subjects_from_table()
        jobs = self.manager.queue.all_jobs()
        if not jobs:
            dialogs.show_warning(
                self, "Empty queue", "Add at least one folder before starting."
            )
            return
        missing = [j.label for j in jobs if not (j.subject_id or "").strip()]
        if missing:
            dialogs.show_warning(
                self,
                "Subject ID required",
                "Set a BIDS Subject ID for every job.\n"
                "Never inferred from folder names.\n\n"
                f"Missing: {', '.join(missing[:8])}",
            )
            return
        if self._ensure_output() is None:
            return
        # Ensure shared dataset root
        out = Path(self.output_edit.text().strip())
        for job in jobs:
            job.output_path = str(out)
        self._launch(resume=False)

    def _pause(self) -> None:
        self.manager.request_pause()
        if self._worker is not None:
            self._worker.stop()
        self.status_label.setText("Pause requested…")

    def _launch(self, *, resume: bool) -> None:
        self._cleanup()
        self._set_busy(True)
        self.status_label.setText("Running batch conversion…")
        self._worker = BatchWorker(self.manager, options=self._options(), resume=resume)
        self._thread = start_worker(self._worker)
        self._worker.job_updated.connect(self._on_job_updated)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.failed.connect(self._on_failed)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.start()

    def _on_job_updated(self, _job: BatchJob) -> None:
        self._refresh_table()

    def _on_progress(self, message: str) -> None:
        self.status_label.setText(message)

    def _on_finished(self, _jobs: list) -> None:
        self._set_busy(False)
        self._refresh_table()
        self.status_label.setText("Batch conversion finished.")
        self._cleanup()

    def _on_failed(self, message: str) -> None:
        self._set_busy(False)
        self.status_label.setText("Batch conversion failed.")
        dialogs.show_error(self, "Batch conversion failed", message)
        self._cleanup()

    def _cleanup(self) -> None:
        if self._worker is not None:
            self._worker.stop()
        if self._thread is not None and self._thread.isRunning():
            self._thread.quit()
            self._thread.wait(2000)
        self._worker = None
        self._thread = None

    def shutdown(self) -> None:
        self._cleanup()


BatchConversionPanel = BatchWidget
