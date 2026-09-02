"""Persistent bottom status strip for NeuroBIDS."""

from __future__ import annotations

from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QSizePolicy, QWidget

from neuro_pipeline.gui.status_tokens import apply_status


class WorkspaceStatusBar(QFrame):
    """Planned counts, issues, conversion, and pending ChangeSet."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("statusBarFrame")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 4, 12, 4)
        layout.setSpacing(16)
        self.dataset = QLabel("No dataset")
        self.dataset.setObjectName("monoLabel")
        self.planned = QLabel("")
        self.issues = QLabel("")
        self.structure = QLabel("")
        self.state = QLabel("")
        for w in (self.dataset, self.planned, self.issues, self.structure, self.state):
            w.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
            layout.addWidget(w)
        layout.addStretch(1)
        self.refresh()

    def refresh(
        self,
        *,
        dataset: str = "",
        planned: int = 0,
        issues: int = 0,
        errors: int = 0,
        scanning: bool = False,
        conversion_busy: bool = False,
        pending_changeset: bool = False,
        has_dataset: bool = False,
        structure_ok: bool | None = None,
    ) -> None:
        self.dataset.setText(dataset or "No dataset")
        if scanning:
            apply_status(self.state, "INFO", "Scanning")
        elif conversion_busy:
            apply_status(self.state, "INFO", "Conversion running")
        elif pending_changeset:
            apply_status(self.state, "REVIEW", "1 proposed change awaiting approval")
        elif has_dataset:
            apply_status(self.state, "PASS", "Ready")
        else:
            apply_status(self.state, "INFO", "Ready")

        if has_dataset:
            apply_status(self.planned, "PASS", f"{planned:,} planned")
        else:
            apply_status(self.planned, "INFO", "0 planned")

        if errors:
            apply_status(self.issues, "FAIL", f"{errors} error(s)")
        elif issues:
            apply_status(self.issues, "REVIEW", f"{issues} issue(s)")
        else:
            apply_status(self.issues, "PASS", "0 issues")

        if structure_ok is True:
            apply_status(self.structure, "PASS", "BIDS structure valid")
        elif structure_ok is False:
            apply_status(self.structure, "REVIEW", "BIDS structure needs review")
        else:
            apply_status(self.structure, "INFO", "BIDS structure")
