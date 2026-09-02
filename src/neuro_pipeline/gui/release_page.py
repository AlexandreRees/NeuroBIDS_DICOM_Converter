"""Release-readiness view — existing validators only, no fake certification."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from neuro_pipeline.gui import dialogs
from neuro_pipeline.gui.audit_summary import build_audit_report
from neuro_pipeline.gui.status_tokens import apply_status

if TYPE_CHECKING:
    from neuro_pipeline.gui.convert_widget import ConvertWidget


class ReleasePage(QWidget):
    """Summarize whether existing checks support a BIDS release."""

    review_requested = Signal()
    ask_requested = Signal(str)

    def __init__(self, convert: ConvertWidget, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._convert = convert
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(12)

        kicker = QLabel("⑤ RELEASE")
        kicker.setObjectName("pageKicker")
        root.addWidget(kicker)
        title = QLabel("Release readiness")
        title.setObjectName("titleLabel")
        root.addWidget(title)
        sub = QLabel(
            "These checks reuse the current BIDS plan and DatasetContext. "
            "NeuroBIDS does not certify that data are publication-ready."
        )
        sub.setObjectName("subtitleLabel")
        sub.setWordWrap(True)
        root.addWidget(sub)

        self.headline = QLabel("")
        self.headline.setWordWrap(True)
        root.addWidget(self.headline)

        checks = QGroupBox("Checks")
        self.checks_layout = QVBoxLayout(checks)
        root.addWidget(checks)

        before = QGroupBox("Before release")
        self.before_layout = QVBoxLayout(before)
        root.addWidget(before)

        row = QHBoxLayout()
        review_btn = QPushButton("Review issues")
        review_btn.clicked.connect(self.review_requested.emit)
        self.report_btn = QPushButton("Generate Release Report")
        self.report_btn.setObjectName("primaryButton")
        self.report_btn.clicked.connect(self._generate_report)
        row.addWidget(review_btn)
        row.addWidget(self.report_btn)
        row.addStretch(1)
        root.addLayout(row)
        self.status = QLabel("")
        self.status.setObjectName("statusLabel")
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        root.addStretch(1)

    def refresh(self) -> None:
        convert = self._convert
        scanning = bool(getattr(convert, "is_scanning", lambda: False)())
        session = convert.copilot_panel.controller.session
        plan = convert.preview_panel.plan
        ctx = session.dataset_context() if session is not None and plan and plan.items else None
        report = build_audit_report(ctx=ctx, plan=plan, scanning=scanning)
        self._report = report
        apply_status(
            self.headline,
            "INFO" if report.empty else ("REVIEW" if report.n_review or report.n_errors else "PASS"),
            report.headline,
        )
        _clear(self.checks_layout)
        wanted = {
            "structure": "BIDS structure",
            "validation": "BIDS validation",
            "metadata": "Metadata",
            "privacy": "De-identification",
            "mappings": "Manual review",
        }
        if report.empty:
            empty = QLabel(report.message or "Load a dataset first.")
            empty.setObjectName("statusLabel")
            self.checks_layout.addWidget(empty)
        else:
            by_key = {c.key: c for c in report.checks}
            for key, title in wanted.items():
                check = by_key.get(key)
                row = QLabel("")
                if check is None:
                    apply_status(row, "INFO", title)
                else:
                    apply_status(row, check.level, f"{title}  —  {check.detail}")
                row.setWordWrap(True)
                self.checks_layout.addWidget(row)
            prov = QLabel("")
            apply_status(prov, "PASS", "Provenance — conversion reports record dcm2niix and plan choices")
            prov.setWordWrap(True)
            self.checks_layout.addWidget(prov)

        _clear(self.before_layout)
        if report.empty:
            self.report_btn.setEnabled(False)
            return
        self.report_btn.setEnabled(True)
        review_items = [i for i in report.issues if i.level in {"REVIEW", "FAIL"}]
        if not review_items:
            ok = QLabel("No outstanding review items from current checks.")
            ok.setObjectName("statusLabel")
            self.before_layout.addWidget(ok)
            return
        for issue in review_items[:12]:
            row = QLabel("")
            apply_status(row, issue.level, issue.title)
            row.setWordWrap(True)
            self.before_layout.addWidget(row)

    def _generate_report(self) -> None:
        report = getattr(self, "_report", None)
        if report is None or report.empty:
            dialogs.show_warning(self, "Release report", "Load a dataset first.")
            return
        default = self._convert.output_edit.text().strip() or str(Path.home())
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save release-readiness report",
            str(Path(default) / "neurobids_release_readiness.txt"),
            "Text (*.txt)",
        )
        if not path:
            return
        try:
            Path(path).write_text(report.to_text_report(), encoding="utf-8")
        except OSError as exc:
            dialogs.show_error(self, "Could not write report", str(exc))
            return
        self.status.setText(f"Wrote {path}")
        dialogs.show_info(
            self,
            "Release report",
            "Wrote a summary of existing NeuroBIDS checks.\n"
            "This is not a publication-readiness certificate.\n\n"
            f"{path}",
        )


def _clear(layout: QVBoxLayout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.deleteLater()
