"""Interactive BIDS conversion preview panel (plan-only; DICOM stays read-only)."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from neuro_pipeline.bids.conversion_plan import BIDSConversionPlan
from neuro_pipeline.gui import dialogs
from neuro_pipeline.models import DicomSeries

_COLUMNS = (
    "Include",
    "Subject",
    "Session",
    "Source Series",
    "Detected Type",
    "Naming Rule",
    "BIDS datatype",
    "Suffix",
    "Task",
    "Run",
    "Acquisition",
    "Direction",
    "Filename",
)

_EDITABLE = {
    0: "include",
    1: "subject",
    2: "session",
    6: "datatype",
    7: "suffix",
    8: "task",
    9: "run",
    10: "acquisition",
    11: "direction",
}


class BIDSPreviewPanel(QGroupBox):
    """Tree + editable table bound to a :class:`BIDSConversionPlan`."""

    plan_changed = Signal()
    continue_requested = Signal()
    status_message = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("BIDS Preview", parent)
        self._plan: BIDSConversionPlan | None = None
        self._series: list[DicomSeries] = []
        self._dataset_root = ""
        self._output_root = ""
        self._subject_override = ""
        self._session_override = ""
        self._updating = False
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(6)

        hint = QLabel(
            "Preview of the planned BIDS layout. Edits change the conversion plan only — "
            "DICOM input files are never renamed, moved, or modified."
        )
        hint.setObjectName("statusLabel")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Planned BIDS structure"])
        self.tree.setMinimumHeight(120)
        self.tree.setMaximumHeight(200)
        self.tree.setAnimated(True)
        layout.addWidget(self.tree)

        self.table = QTableWidget(0, len(_COLUMNS))
        self.table.setHorizontalHeaderLabels(list(_COLUMNS))
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setMinimumHeight(140)
        self.table.itemChanged.connect(self._on_item_changed)
        layout.addWidget(self.table)

        self.status = QLabel("No preview yet — select an input folder.")
        self.status.setObjectName("statusLabel")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        buttons = QHBoxLayout()
        self.refresh_btn = QPushButton("Refresh Preview")
        self.reset_btn = QPushButton("Reset Changes")
        self.validate_btn = QPushButton("Validate Plan")
        self.save_btn = QPushButton("Save Plan…")
        self.load_btn = QPushButton("Load Plan…")
        self.continue_btn = QPushButton("Continue to Conversion")
        self.continue_btn.setObjectName("primaryButton")
        for btn in (
            self.refresh_btn,
            self.reset_btn,
            self.validate_btn,
            self.save_btn,
            self.load_btn,
            self.continue_btn,
        ):
            buttons.addWidget(btn)
        layout.addLayout(buttons)

        self.refresh_btn.clicked.connect(self.refresh_preview)
        self.reset_btn.clicked.connect(self.reset_changes)
        self.validate_btn.clicked.connect(self.validate_plan)
        self.save_btn.clicked.connect(self.save_plan)
        self.load_btn.clicked.connect(self.load_plan)
        self.continue_btn.clicked.connect(self._on_continue)

    @property
    def plan(self) -> BIDSConversionPlan | None:
        return self._plan

    def set_context(
        self,
        *,
        series: list[DicomSeries] | None = None,
        dataset_root: str = "",
        output_root: str = "",
        subject_override: str = "",
        session_override: str = "",
    ) -> None:
        if series is not None:
            self._series = list(series)
        if dataset_root:
            self._dataset_root = dataset_root
        if output_root is not None:
            self._output_root = output_root
        self._subject_override = subject_override
        self._session_override = session_override

    def rebuild_plan(self) -> None:
        """Create a fresh automatic plan from the current series context."""
        if not self._series:
            self._plan = None
            self._populate()
            self.status.setText("No DICOM series available for preview.")
            return
        self._plan = BIDSConversionPlan.from_series(
            self._series,
            dataset_root=self._dataset_root,
            output_root=self._output_root,
            subject_override=self._subject_override,
            session_override=self._session_override,
        )
        self._populate()
        self.status.setText(
            f"Automatic plan: {sum(1 for i in self._plan.items if i.include_in_conversion)} "
            f"of {len(self._plan.items)} series included."
        )
        self.plan_changed.emit()

    def sync_edits_to_plan(self) -> None:
        """Flush table edits into the live :class:`BIDSConversionPlan`."""
        self._sync_table_into_plan()

    def reload_display(self) -> None:
        """Repaint tree/table from the current plan (e.g. after ChangeSet.apply)."""
        self._populate()
        self.status.setText("Preview updated from applied Copilot changes.")
        self.status_message.emit(self.status.text())
        self.plan_changed.emit()

    def refresh_preview(self) -> None:
        """Recalculate planned filenames from the current table edits."""
        if self._plan is None:
            self.rebuild_plan()
            return
        self._sync_table_into_plan()
        self._plan.refresh_filenames(seed_existing_from_output=True)
        self._populate()
        self.status.setText("Preview refreshed from current edits.")
        self.status_message.emit(self.status.text())
        self.plan_changed.emit()

    def reset_changes(self) -> None:
        if self._plan is None:
            return
        self._plan.reset_changes()
        self._populate()
        self.status.setText("User modifications discarded — automatic plan restored.")
        self.status_message.emit(self.status.text())
        self.plan_changed.emit()

    def validate_plan(self) -> bool:
        if self._plan is None:
            dialogs.show_warning(self, "BIDS plan", "No conversion plan to validate.")
            return False
        self._sync_table_into_plan()
        self._plan.refresh_filenames(seed_existing_from_output=True)
        self._populate()
        result = self._plan.validate()
        n_err = len(result.errors)
        n_warn = len(result.warnings)
        status = (
            f"NIfTI conversion: READY | BIDS validation: "
            f"{n_warn} warning(s) / {n_err} error(s)"
        )
        self.status.setText(status)
        self.status_message.emit(self.status.text())
        if result.ok and not result.issues:
            dialogs.show_info(self, "Plan valid", result.summary())
        elif result.ok:
            dialogs.show_info(
                self,
                "Plan valid with warnings",
                status + "\n\n" + result.summary(),
            )
        else:
            dialogs.show_warning(
                self,
                "BIDS validation issues",
                (
                    status
                    + "\n\nNIfTI conversion can still proceed.\n\n"
                    + result.summary()
                ),
            )
        return result.ok

    def save_plan(self) -> None:
        if self._plan is None:
            dialogs.show_warning(self, "Save plan", "No conversion plan to save.")
            return
        self._sync_table_into_plan()
        default_dir = self._output_root or str(Path.home())
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save conversion plan",
            str(Path(default_dir) / "conversion_plan.json"),
            "JSON (*.json)",
        )
        if not path:
            return
        try:
            saved = self._plan.save_json(path)
        except Exception as exc:  # noqa: BLE001
            dialogs.show_error(self, "Save plan failed", str(exc))
            return
        self.status.setText(f"Saved user choices to {saved}")
        dialogs.show_info(
            self,
            "Plan saved",
            f"Saved conversion plan (user choices only):\n{saved}\n\n"
            "DICOM files were not modified.",
        )

    def load_plan(self) -> None:
        if not self._series:
            dialogs.show_warning(self, "Load plan", "Scan a DICOM folder first.")
            return
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Load conversion plan",
            self._output_root or str(Path.home()),
            "JSON (*.json)",
        )
        if not path:
            return
        try:
            self._plan = BIDSConversionPlan.load_json(
                path,
                self._series,
                dataset_root=self._dataset_root,
                output_root=self._output_root,
                subject_override=self._subject_override,
                session_override=self._session_override,
            )
        except Exception as exc:  # noqa: BLE001
            dialogs.show_error(self, "Load plan failed", str(exc))
            return
        self._populate()
        self.status.setText(f"Loaded user choices from {path}")
        self.plan_changed.emit()

    def _on_continue(self) -> None:
        if self._plan is None:
            dialogs.show_warning(self, "BIDS plan", "No conversion plan to continue.")
            return
        self._sync_table_into_plan()
        self._plan.refresh_filenames(seed_existing_from_output=True)
        self._populate()
        result = self._plan.validate()
        n_err = len(result.errors)
        n_warn = len(result.warnings)
        self.status.setText(
            f"NIfTI conversion: READY | BIDS validation: "
            f"{n_warn} warning(s) / {n_err} error(s)"
        )
        self.status_message.emit(self.status.text())
        if not result.ok:
            dialogs.show_warning(
                self,
                "BIDS issues remain",
                (
                    "BIDS validation reported problems.\n"
                    "NIfTI conversion can still continue.\n\n"
                    + result.summary()
                ),
            )
        self.continue_requested.emit()

    def _populate(self) -> None:
        self._updating = True
        try:
            self._populate_tree()
            self._populate_table()
        finally:
            self._updating = False

    def _populate_tree(self) -> None:
        self.tree.clear()
        if self._plan is None:
            return
        # nested: subject -> session? -> datatype -> filename
        subjects: dict[str, QTreeWidgetItem] = {}
        sessions: dict[tuple[str, str], QTreeWidgetItem] = {}
        datatypes: dict[tuple[str, str, str], QTreeWidgetItem] = {}
        source_shown: set[str] = set()
        for item in self._plan.items:
            if not item.include_in_conversion or not item.intended_filename:
                continue
            sub = f"sub-{(item.subject or '').removeprefix('sub-')}"
            if sub not in subjects:
                subjects[sub] = QTreeWidgetItem([sub])
                self.tree.addTopLevelItem(subjects[sub])
            sub_item = subjects[sub]
            folder = (getattr(item, "source_subject_folder", "") or "").strip()
            if folder and sub not in source_shown:
                sub_item.addChild(QTreeWidgetItem([f"source: {folder}"]))
                source_shown.add(sub)
            ses = (item.session or "").removeprefix("ses-").strip()
            ses_key = (sub, ses)
            if ses:
                if ses_key not in sessions:
                    sessions[ses_key] = QTreeWidgetItem([f"ses-{ses}"])
                    sub_item.addChild(sessions[ses_key])
                parent = sessions[ses_key]
            else:
                parent = sub_item
            dt_key = (sub, ses, item.datatype or "unknown")
            if dt_key not in datatypes:
                datatypes[dt_key] = QTreeWidgetItem([item.datatype or "unknown"])
                parent.addChild(datatypes[dt_key])
            datatypes[dt_key].addChild(QTreeWidgetItem([item.intended_filename]))
        self.tree.expandAll()

    def _populate_table(self) -> None:
        self.table.setRowCount(0)
        if self._plan is None:
            return
        for item in self._plan.items:
            row = self.table.rowCount()
            self.table.insertRow(row)
            values = [
                "Yes" if item.include_in_conversion else "No",
                item.subject,
                item.session,
                item.source_series_description,
                item.classification_source or item.source_sequence_type,
                item.naming_rule_applied or "—",
                item.datatype,
                item.suffix,
                item.task,
                item.run,
                item.acquisition,
                item.direction,
                item.intended_filename,
            ]
            for col, value in enumerate(values):
                cell = QTableWidgetItem(str(value))
                if col not in _EDITABLE:
                    cell.setFlags(cell.flags() & ~Qt.ItemFlag.ItemIsEditable)
                if col == 0:
                    cell.setFlags(
                        (cell.flags() | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEditable)
                        & ~Qt.ItemFlag.ItemIsUserCheckable
                    )
                    # Use Yes/No text for include (simpler than checkboxes across platforms)
                cell.setData(Qt.ItemDataRole.UserRole, item.source_series_uid)
                self.table.setItem(row, col, cell)

    def _sync_table_into_plan(self) -> None:
        if self._plan is None:
            return
        for row in range(self.table.rowCount()):
            uid_item = self.table.item(row, 0)
            if uid_item is None:
                continue
            uid = str(uid_item.data(Qt.ItemDataRole.UserRole) or "")
            if not uid:
                continue

            def _text(col: int) -> str:
                cell = self.table.item(row, col)
                return (cell.text() if cell else "").strip()

            include_raw = _text(0).lower()
            include = include_raw in {"yes", "y", "true", "1", "include"}
            self._plan.apply_edit(
                uid,
                include_in_conversion=include,
                subject=_text(1),
                session=_text(2),
                datatype=_text(6),
                suffix=_text(7),
                task=_text(8),
                run=_text(9),
                acquisition=_text(10),
                direction=_text(11),
            )

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if self._updating or self._plan is None:
            return
        # Lightweight: mark dirty; Refresh rebuilds filenames.
        self._plan.mark_validated(False)
        self.plan_changed.emit()
