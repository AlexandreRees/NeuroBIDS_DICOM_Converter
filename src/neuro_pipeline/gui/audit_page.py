"""Audit page — DatasetContext + plan.validate() findings (no fake scores)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from neuro_pipeline.gui.audit_summary import AuditReport, build_audit_report
from neuro_pipeline.gui.status_tokens import apply_status

if TYPE_CHECKING:
    from neuro_pipeline.gui.convert_widget import ConvertWidget


class AuditPage(QWidget):
    """Dedicated dataset audit experience."""

    ask_requested = Signal(str)
    review_requested = Signal()
    open_copilot_requested = Signal()

    def __init__(self, convert: ConvertWidget, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._convert = convert
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        outer.addWidget(scroll)
        content = QWidget()
        scroll.setWidget(content)
        root = QVBoxLayout(content)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(12)

        kicker = QLabel("③ AUDIT")
        kicker.setObjectName("pageKicker")
        root.addWidget(kicker)
        title = QLabel("Dataset Audit")
        title.setObjectName("titleLabel")
        root.addWidget(title)

        self.headline = QLabel("")
        self.headline.setObjectName("titleLabel")
        self.headline.setWordWrap(True)
        root.addWidget(self.headline)
        self.counts = QLabel("")
        self.counts.setObjectName("subtitleLabel")
        root.addWidget(self.counts)

        health = QGroupBox("Dataset health")
        self.health_layout = QVBoxLayout(health)
        root.addWidget(health)
        self._health_box = health

        issues_box = QGroupBox("Issues")
        self.issues_layout = QVBoxLayout(issues_box)
        root.addWidget(issues_box)
        self._issues_box = issues_box

        root.addStretch(1)

    def refresh(self) -> None:
        convert = self._convert
        scanning = bool(getattr(convert, "is_scanning", lambda: False)())
        session = convert.copilot_panel.controller.session
        ctx = None
        plan = convert.preview_panel.plan
        if session is not None and plan is not None and plan.items:
            ctx = session.dataset_context()
        report = build_audit_report(ctx=ctx, plan=plan, scanning=scanning)
        self._render(report)

    def _render(self, report: AuditReport) -> None:
        self.headline.setText(report.headline)
        if report.empty:
            self.counts.setText(report.message or "Load a dataset on Discover to run an audit.")
        else:
            self.counts.setText(
                f"{report.n_errors} error(s) · {report.n_warnings} warning(s) · "
                f"{report.n_info} informational"
            )
        _clear_layout(self.health_layout)
        if report.empty:
            empty = QLabel(report.message or "No dataset loaded.")
            empty.setObjectName("statusLabel")
            empty.setWordWrap(True)
            self.health_layout.addWidget(empty)
        else:
            for check in report.checks:
                row = QHBoxLayout()
                status = QLabel("")
                apply_status(status, check.level, check.level)
                title = QLabel(check.title)
                title.setMinimumWidth(180)
                detail = QLabel(check.detail)
                detail.setObjectName("statusLabel")
                detail.setWordWrap(True)
                row.addWidget(status)
                row.addWidget(title)
                row.addWidget(detail, 1)
                if check.ask_prompt and check.level in {"REVIEW", "FAIL"}:
                    ask = QPushButton("Ask NeuroBIDS")
                    ask.clicked.connect(
                        lambda _=False, p=check.ask_prompt: self._ask(p)
                    )
                    row.addWidget(ask)
                wrap = QWidget()
                wrap.setLayout(row)
                self.health_layout.addWidget(wrap)

        _clear_layout(self.issues_layout)
        if report.empty:
            return
        if not report.issues:
            none = QLabel("No issues requiring review.")
            none.setObjectName("statusLabel")
            self.issues_layout.addWidget(none)
            return
        for issue in report.issues:
            block = QVBoxLayout()
            head = QLabel("")
            apply_status(head, issue.level, issue.title)
            head.setWordWrap(True)
            block.addWidget(head)
            if issue.detail:
                detail = QLabel(issue.detail)
                detail.setObjectName("statusLabel")
                detail.setWordWrap(True)
                block.addWidget(detail)
            btns = QHBoxLayout()
            review = QPushButton("Review")
            review.clicked.connect(self.review_requested.emit)
            ask = QPushButton("Ask NeuroBIDS")
            ask.setObjectName("primaryButton")
            ask.clicked.connect(lambda _=False, p=issue.ask_prompt: self._ask(p))
            btns.addWidget(review)
            btns.addWidget(ask)
            btns.addStretch(1)
            block.addLayout(btns)
            wrap = QWidget()
            wrap.setLayout(block)
            self.issues_layout.addWidget(wrap)

    def _ask(self, prompt: str) -> None:
        if prompt:
            self.open_copilot_requested.emit()
            self.ask_requested.emit(prompt)


def _clear_layout(layout: QVBoxLayout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        child = item.layout()
        if widget is not None:
            widget.deleteLater()
        elif child is not None:
            _clear_layout(child)
