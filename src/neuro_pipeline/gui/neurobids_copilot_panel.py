"""NeuroBIDS Copilot panel — assistant beside BIDS Preview (no BIDS logic)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut, QTextCursor
from PySide6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from neuro_pipeline.gui.copilot_controller import CopilotController, friendly_copilot_error
from neuro_pipeline.neurobids.copilot.changeset import ChangeSet, ChangeSetStatus
from neuro_pipeline.neurobids.copilot.llm.provider import LLMProvider
from neuro_pipeline.neurobids.copilot.llm.schemas import CopilotTurnResult
from neuro_pipeline.neurobids.copilot.session import CopilotSession

if TYPE_CHECKING:
    from neuro_pipeline.gui.bids_preview_panel import BIDSPreviewPanel


class NeuroBIDSCopilotPanel(QGroupBox):
    """Chat + ChangeSet proposal UI for NeuroBIDS Copilot."""

    status_message = Signal(str)
    plan_refresh_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("NeuroBIDS Copilot", parent)
        self._preview: BIDSPreviewPanel | None = None
        self._controller = CopilotController(self)
        self._build_ui()
        self._connect_controller()
        self._set_proposal_visible(False)
        self._update_controls()

    @property
    def controller(self) -> CopilotController:
        return self._controller

    def set_provider(self, provider: LLMProvider | None) -> None:
        self._controller.set_provider(provider)

    def bind_preview(self, preview: BIDSPreviewPanel) -> None:
        """Attach to the live BIDS Preview plan (source of truth)."""
        if self._preview is not None:
            try:
                self._preview.plan_changed.disconnect(self._on_preview_plan_changed)
            except (RuntimeError, TypeError):
                pass
        self._preview = preview
        preview.plan_changed.connect(self._on_preview_plan_changed)
        self._controller.set_sync_plan_callback(preview.sync_edits_to_plan)
        self.rebind_session_from_preview()

    def rebind_session_from_preview(self) -> None:
        if self._preview is None or self._preview.plan is None:
            self._controller.bind_session(None)
            self._update_controls()
            return
        series = list(getattr(self._preview, "_series", []) or [])
        session = CopilotSession(
            plan=self._preview.plan,
            series_list=series,
            conversion_busy=False,
        )
        # Preserve busy flag if rebinding mid-conversion
        prev = self._controller.session
        if prev is not None:
            session.conversion_busy = prev.conversion_busy
        self._controller.bind_session(session)
        self._update_controls()

    def set_conversion_busy(self, busy: bool) -> None:
        self._controller.set_conversion_busy(busy)
        self._update_controls()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(6)

        hint = QLabel("Ask NeuroBIDS to inspect or curate your BIDS conversion plan.")
        hint.setObjectName("statusLabel")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.conversation = QTextEdit()
        self.conversation.setReadOnly(True)
        self.conversation.setMinimumHeight(140)
        self.conversation.setPlaceholderText("Conversation appears here.")
        layout.addWidget(self.conversation, stretch=1)

        self.input_edit = QPlainTextEdit()
        self.input_edit.setPlaceholderText("Ask NeuroBIDS…")
        self.input_edit.setFixedHeight(56)
        layout.addWidget(self.input_edit)

        row = QHBoxLayout()
        self.send_btn = QPushButton("Ask")
        self.send_btn.setObjectName("primaryButton")
        self.send_btn.clicked.connect(self._on_send)
        row.addWidget(self.send_btn)
        self.loading_bar = QProgressBar()
        self.loading_bar.setRange(0, 0)
        self.loading_bar.setFixedHeight(12)
        self.loading_bar.setVisible(False)
        row.addWidget(self.loading_bar, 1)
        self.status = QLabel("")
        self.status.setObjectName("statusLabel")
        self.status.setWordWrap(True)
        row.addWidget(self.status, 2)
        layout.addLayout(row)

        shortcut = QShortcut(QKeySequence("Ctrl+Return"), self.input_edit)
        shortcut.activated.connect(self._on_send)

        # --- Proposed Changes ---
        self.proposal_box = QGroupBox("Proposed Changes")
        prop = QVBoxLayout(self.proposal_box)

        self.proposal_title = QLabel("")
        self.proposal_title.setWordWrap(True)
        prop.addWidget(self.proposal_title)

        self.proposal_summary = QLabel("")
        self.proposal_summary.setObjectName("statusLabel")
        self.proposal_summary.setWordWrap(True)
        prop.addWidget(self.proposal_summary)

        self.rename_table = QTableWidget(0, 2)
        self.rename_table.setHorizontalHeaderLabels(["Before", "After"])
        self.rename_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.rename_table.setMaximumHeight(140)
        self.rename_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        prop.addWidget(self.rename_table)

        meta = QFormLayout()
        self.validation_label = QLabel("—")
        self.changeset_id_label = QLabel("—")
        self.warnings_label = QLabel("")
        self.warnings_label.setWordWrap(True)
        self.warnings_label.setObjectName("statusLabel")
        meta.addRow("Validation:", self.validation_label)
        meta.addRow("ChangeSet ID:", self.changeset_id_label)
        meta.addRow("Warnings:", self.warnings_label)
        prop.addLayout(meta)

        btn_row = QHBoxLayout()
        self.reject_btn = QPushButton("Reject")
        self.apply_btn = QPushButton("Apply Changes")
        self.apply_btn.setObjectName("primaryButton")
        self.reject_btn.clicked.connect(self._on_reject)
        self.apply_btn.clicked.connect(self._on_apply)
        btn_row.addStretch(1)
        btn_row.addWidget(self.reject_btn)
        btn_row.addWidget(self.apply_btn)
        prop.addLayout(btn_row)

        layout.addWidget(self.proposal_box)

    def _connect_controller(self) -> None:
        c = self._controller
        c.busy_changed.connect(self._on_busy_changed)
        c.response_ready.connect(self._on_response)
        c.error.connect(self._on_error)
        c.changeset_updated.connect(self._refresh_proposal)
        c.plan_applied.connect(self._on_plan_applied)

    def _on_send(self) -> None:
        text = self.input_edit.toPlainText().strip()
        if not text:
            return
        if self._preview is not None:
            self._preview.sync_edits_to_plan()
            # Ensure session points at the current plan object
            if self._controller.session is None or self._controller.session.plan is not self._preview.plan:
                self.rebind_session_from_preview()
            elif self._controller.session is not None:
                self._controller.session.invalidate_context_cache()
        self._append_conversation("You", text)
        self.input_edit.clear()
        self._controller.ask(text)

    def _on_busy_changed(self, busy: bool) -> None:
        self.loading_bar.setVisible(busy)
        self._update_controls()
        if busy:
            self.status.setText("Thinking…")
        elif not self.status.text().startswith("Applied") and not self.status.text().startswith(
            "Rejected"
        ):
            self.status.setText("")

    def _on_response(self, result: object) -> None:
        if not isinstance(result, CopilotTurnResult):
            return
        if result.clarify:
            self._append_conversation("Copilot", result.message or "(clarification)")
            self.status.setText("Clarification needed.")
            return
        if result.message:
            self._append_conversation("Copilot", result.message)
        if result.tool_traces:
            tools = ", ".join(t.tool_name for t in result.tool_traces)
            self._append_conversation("Tools", tools)
        if result.ok and result.changeset is not None:
            self.status.setText("Proposed changes ready for review.")
        elif result.ok:
            self.status.setText("Done.")
        self._refresh_proposal()
        self._update_controls()

    def _on_error(self, message: str) -> None:
        self._append_conversation("Error", message)
        self.status.setText(message)
        self.status_message.emit(message)
        self._update_controls()

    def _on_apply(self) -> None:
        if self._preview is not None:
            self._preview.sync_edits_to_plan()
        ok, message = self._controller.apply_pending()
        if ok:
            self._append_conversation("Copilot", message)
            self.status.setText(message)
            self.status_message.emit(message)
            self._set_proposal_visible(False)
        else:
            self._append_conversation("Error", message)
            self.status.setText(message)
            self.status_message.emit(message)
            if "no longer valid" in message.lower():
                self._refresh_proposal()
        self._update_controls()

    def _on_reject(self) -> None:
        ok, message = self._controller.reject_pending()
        self._append_conversation("Copilot", message if ok else message)
        self.status.setText(message)
        self._set_proposal_visible(False)
        self._update_controls()

    def _on_plan_applied(self) -> None:
        if self._preview is not None:
            self._preview.reload_display()
        self.plan_refresh_requested.emit()
        self.rebind_session_from_preview()

    def _on_preview_plan_changed(self) -> None:
        # Keep session on the same plan object; detect stale proposals after flush
        if self._preview is not None:
            self._preview.sync_edits_to_plan()
            if self._preview.plan is not None:
                if self._controller.session is None:
                    self.rebind_session_from_preview()
                elif self._controller.session.plan is not self._preview.plan:
                    self.rebind_session_from_preview()
        self._controller.notify_plan_edited()
        self._update_controls()
        if self._controller.pending_stale():
            self.status.setText(friendly_copilot_error("stale_changeset"))
            self.validation_label.setText("STALE — plan changed")

    def _refresh_proposal(self) -> None:
        cs = self._controller.pending_changeset
        if cs is None:
            self._set_proposal_visible(False)
            return
        if cs.status == ChangeSetStatus.REJECTED:
            self._set_proposal_visible(False)
            return
        self._set_proposal_visible(True)
        self._populate_proposal(cs)
        self._update_controls()

    def _populate_proposal(self, cs: ChangeSet) -> None:
        preview = cs.preview()
        tool = cs.tool_name or preview.get("tool") or "proposed edit"
        title = tool.replace("_", " ").strip().title()
        self.proposal_title.setText(title)

        affected = preview.get("affected") or {}
        n_subj = len(affected.get("subjects") or cs.affected_subjects)
        n_ses = len(affected.get("sessions") or cs.affected_sessions)
        n_acq = len(affected.get("acquisitions") or cs.affected_acquisitions)
        lines = [
            f"{n_subj} subject(s) affected",
            f"{n_ses} session(s) affected",
            f"{n_acq} acquisition(s) affected",
        ]
        if self._controller.pending_stale():
            lines.append("This proposal is stale — the BIDS plan has changed.")
        self.proposal_summary.setText("\n".join(lines))

        renames = preview.get("subject_renames") or {}
        self.rename_table.setRowCount(0)
        # Deduplicate rename pairs
        pairs = sorted({(str(a), str(b)) for a, b in renames.items() if a != b})
        for before, after in pairs:
            row = self.rename_table.rowCount()
            self.rename_table.insertRow(row)
            self.rename_table.setItem(row, 0, QTableWidgetItem(before))
            self.rename_table.setItem(row, 1, QTableWidgetItem(after))
        self.rename_table.setVisible(bool(pairs))

        validation = preview.get("validation")
        if self._controller.pending_stale():
            self.validation_label.setText("STALE")
        elif validation is None and cs.status == ChangeSetStatus.VALIDATED:
            ok = cs.validation_result.ok if cs.validation_result else True
            self.validation_label.setText("PASS" if ok else "ISSUES (see warnings)")
        elif isinstance(validation, dict):
            self.validation_label.setText(
                "PASS" if validation.get("ok") else "ISSUES (see warnings)"
            )
        else:
            self.validation_label.setText(cs.status.value)

        self.changeset_id_label.setText(cs.id)
        warns = list(cs.warnings or [])
        if isinstance(validation, dict) and validation.get("summary"):
            warns.append(str(validation["summary"]))
        self.warnings_label.setText("; ".join(warns) if warns else "None")

    def _set_proposal_visible(self, visible: bool) -> None:
        self.proposal_box.setVisible(visible)

    def _update_controls(self) -> None:
        busy = self._controller.busy
        has_plan = (
            self._preview is not None
            and self._preview.plan is not None
            and bool(self._preview.plan.items)
        )
        self.send_btn.setEnabled(not busy and has_plan)
        self.input_edit.setEnabled(not busy)
        applicable = self._controller.is_pending_applicable()
        self.apply_btn.setEnabled(applicable and not busy)
        self.reject_btn.setEnabled(
            self._controller.pending_changeset is not None and not busy
        )

    def _append_conversation(self, role: str, text: str) -> None:
        self.conversation.moveCursor(QTextCursor.MoveOperation.End)
        self.conversation.append(f"<b>{role}:</b> {text}")
        self.conversation.moveCursor(QTextCursor.MoveOperation.End)
