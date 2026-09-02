"""NeuroBIDS Copilot panel — dataset-aware assistant (no BIDS logic)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut, QTextCursor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from neuro_pipeline.gui.copilot_controller import CopilotController, friendly_copilot_error
from neuro_pipeline.gui.status_tokens import apply_status
from neuro_pipeline.neurobids.copilot.changeset import ChangeSet, ChangeSetStatus
from neuro_pipeline.neurobids.copilot.llm.provider import LLMProvider
from neuro_pipeline.neurobids.copilot.llm.schemas import CopilotTurnResult
from neuro_pipeline.neurobids.copilot.session import CopilotSession

if TYPE_CHECKING:
    from neuro_pipeline.gui.bids_preview_panel import BIDSPreviewPanel

_SUGGESTED_ACTIONS = (
    ("Explain this dataset", "Explain this dataset.", "EXPLAIN"),
    ("Find potential problems", "Find potential problems in this dataset.", "AUDIT"),
    ("Review BIDS mappings", "Review the BIDS mappings and list ambiguous acquisitions.", "INSPECT"),
    ("Check longitudinal consistency", "Check longitudinal session consistency across subjects.", "AUDIT"),
)

_CONVERSATION_CSS = """
p { margin: 6px 0; }
.msg-user { color: #243b53; }
.msg-answer { color: #102a43; }
.msg-warning { color: #975a16; }
.msg-error { color: #9b2c2c; }
.msg-proposal { color: #2b6cb0; }
.msg-info { color: #627d98; }
"""

_ROLE_CLASS = {
    "You": ("msg-user", "You"),
    "Answer": ("msg-answer", "Answer"),
    "Copilot": ("msg-answer", "Answer"),
    "Warning": ("msg-warning", "Warning"),
    "Error": ("msg-error", "Error"),
    "Proposal": ("msg-proposal", "Proposed changes"),
    "Tools": ("msg-info", "Info"),
    "Explanation": ("msg-info", "Explanation"),
}


class NeuroBIDSCopilotPanel(QGroupBox):
    """Chat + ChangeSet proposal UI for NeuroBIDS Copilot."""

    status_message = Signal(str)
    plan_refresh_requested = Signal()
    configure_requested = Signal()
    collapse_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("NeuroBIDS Copilot", parent)
        self._preview: BIDSPreviewPanel | None = None
        self._controller = CopilotController(self)
        self._last_selection: dict[str, str] = {}
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        self._build_ui()
        self._connect_controller()
        self._set_proposal_visible(False)
        self._refresh_availability()
        self._update_controls()

    @property
    def controller(self) -> CopilotController:
        return self._controller

    def set_provider(self, provider: LLMProvider | None) -> None:
        self._controller.set_provider(provider)
        self._refresh_availability()
        self._update_controls()

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
        prev = self._controller.session
        if prev is not None:
            session.conversion_busy = prev.conversion_busy
            session.ui_selection = dict(prev.ui_selection)
            session.n_dicom_files = prev.n_dicom_files
            session.detection_method = prev.detection_method
            session.detection_reason = prev.detection_reason
            session.last_applied_changeset = prev.last_applied_changeset
            session.curation_rules_path = prev.curation_rules_path
            session.bind_rule_store(getattr(prev, "_rule_store", None))
        if self._last_selection:
            session.set_ui_selection(**self._last_selection)
        self._controller.bind_session(session)
        self._update_controls()

    def set_conversion_busy(self, busy: bool) -> None:
        self._controller.set_conversion_busy(busy)
        self._update_controls()

    def set_selection(self, **kwargs: str) -> None:
        """Record the current GUI selection on the Copilot session."""
        self._last_selection = {
            key: str(value).strip()
            for key, value in kwargs.items()
            if str(value or "").strip()
        }
        session = self._controller.session
        if session is not None:
            session.set_ui_selection(**self._last_selection)
        self._update_context_hint()
        self._update_controls()

    def explain_mapping(self, series_uid: str = "") -> None:
        """Show a read-only mapping explanation (does not apply anything)."""
        expl = self._controller.explain_mapping_uid(series_uid)
        self._show_explanation(expl, fallback="No mapping is selected to explain.")

    def _on_explain(self) -> None:
        expl = self._controller.explain_current()
        self._show_explanation(
            expl,
            fallback="Nothing to explain yet. Select an acquisition or review a ChangeSet.",
        )

    def _show_explanation(self, expl: object, *, fallback: str = "") -> None:
        from neuro_pipeline.neurobids.copilot.explain import CopilotExplanation

        if not isinstance(expl, CopilotExplanation):
            text = fallback or "Nothing to explain yet."
            self.explanation_view.setPlainText(text)
            self._append_conversation("Explanation", text)
            return
        text = expl.to_text()
        self.explanation_view.setPlainText(text)
        self._append_conversation("Explanation", text)
        self.status.setText("Explanation ready.")

    def submit_prompt(self, text: str, *, send: bool = False) -> None:
        """Populate the input (and optionally send) using the existing ask path."""
        self.input_edit.setPlainText(text)
        if send:
            self._on_send()

    def clear_conversation(self) -> None:
        """Clear chat history only. Pending ChangeSets are not rejected."""
        self.conversation.clear()
        self.status.setText("History cleared.")

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(6)

        toolbar = QHBoxLayout()
        subtitle = QLabel("Dataset-aware research assistant")
        subtitle.setObjectName("subtitleLabel")
        subtitle.setWordWrap(True)
        toolbar.addWidget(subtitle, 1)
        self.clear_btn = QPushButton("Clear history")
        self.clear_btn.setToolTip("Clear the conversation. Proposed changes are not rejected.")
        self.clear_btn.clicked.connect(self.clear_conversation)
        self.hide_btn = QPushButton("Hide")
        self.hide_btn.setToolTip("Collapse the Copilot panel")
        self.hide_btn.clicked.connect(self.collapse_requested.emit)
        toolbar.addWidget(self.clear_btn)
        toolbar.addWidget(self.hide_btn)
        layout.addLayout(toolbar)

        hint = QLabel("I can help you understand, audit, and curate this dataset.")
        hint.setObjectName("statusLabel")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.unavailable_box = QFrame()
        self.unavailable_box.setObjectName("unavailableBanner")
        unavail = QVBoxLayout(self.unavailable_box)
        unavail.setContentsMargins(8, 8, 8, 8)
        un_title = QLabel("Copilot is currently unavailable.")
        un_title.setWordWrap(True)
        unavail.addWidget(un_title)
        un_body = QLabel("The rest of NeuroBIDS remains fully functional.")
        un_body.setObjectName("statusLabel")
        un_body.setWordWrap(True)
        unavail.addWidget(un_body)
        configure = QPushButton("Configure Copilot")
        configure.clicked.connect(self.configure_requested.emit)
        unavail.addWidget(configure)
        layout.addWidget(self.unavailable_box)

        self.state_banner = QLabel("")
        self.state_banner.setWordWrap(True)
        layout.addWidget(self.state_banner)

        self.context_hint = QLabel("")
        self.context_hint.setObjectName("monoLabel")
        self.context_hint.setWordWrap(True)
        layout.addWidget(self.context_hint)

        self.mode_label = QLabel("ASK  ·  INSPECT  ·  EXPLAIN  ·  AUDIT  ·  PROPOSE")
        self.mode_label.setObjectName("pageKicker")
        self.mode_label.setWordWrap(True)
        layout.addWidget(self.mode_label)

        suggested_label = QLabel("Suggested actions")
        suggested_label.setObjectName("pageKicker")
        layout.addWidget(suggested_label)
        self.suggested_buttons: list[QPushButton] = []
        for label, prompt, _mode in _SUGGESTED_ACTIONS:
            btn = QPushButton(label)
            btn.setObjectName("chipButton")
            btn.clicked.connect(lambda _=False, p=prompt: self.submit_prompt(p, send=False))
            self.suggested_buttons.append(btn)
            layout.addWidget(btn)

        self.conversation = QTextEdit()
        self.conversation.setObjectName("copilotConversation")
        self.conversation.setReadOnly(True)
        self.conversation.setMinimumHeight(120)
        self.conversation.setPlaceholderText("Conversation appears here.")
        self.conversation.document().setDefaultStyleSheet(_CONVERSATION_CSS)
        layout.addWidget(self.conversation, stretch=1)

        self.explanation_view = QPlainTextEdit()
        self.explanation_view.setObjectName("copilotExplanation")
        self.explanation_view.setReadOnly(True)
        self.explanation_view.setMaximumHeight(160)
        self.explanation_view.setPlaceholderText(
            "Explain a mapping or ChangeSet to see decision, evidence, and confidence."
        )
        layout.addWidget(self.explanation_view)

        self.input_edit = QPlainTextEdit()
        self.input_edit.setPlaceholderText("Ask NeuroBIDS…")
        self.input_edit.setFixedHeight(56)
        layout.addWidget(self.input_edit)

        row = QHBoxLayout()
        self.send_btn = QPushButton("Ask")
        self.send_btn.setObjectName("primaryButton")
        self.send_btn.clicked.connect(self._on_send)
        row.addWidget(self.send_btn)
        self.explain_btn = QPushButton("Explain")
        self.explain_btn.setToolTip(
            "Show an auditable explanation of the selected mapping or pending ChangeSet."
        )
        self.explain_btn.clicked.connect(self._on_explain)
        row.addWidget(self.explain_btn)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setVisible(False)
        self.cancel_btn.setToolTip("Stop the current Copilot request. Nothing will be applied.")
        self.cancel_btn.clicked.connect(self._on_cancel)
        row.addWidget(self.cancel_btn)
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
        self.proposal_box = QGroupBox("NeuroBIDS proposes changes")
        self.proposal_box.setObjectName("proposalBox")
        prop = QVBoxLayout(self.proposal_box)

        review_banner = QFrame()
        review_banner.setObjectName("proposalBanner")
        review_layout = QVBoxLayout(review_banner)
        review_layout.setContentsMargins(8, 6, 8, 6)
        notice = QLabel("Nothing is applied until you click Apply Changes. Original DICOM files stay untouched.")
        notice.setWordWrap(True)
        review_layout.addWidget(notice)
        prop.addWidget(review_banner)

        self.proposal_state = QLabel("")
        self.proposal_state.setWordWrap(True)
        prop.addWidget(self.proposal_state)

        self.proposal_title = QLabel("")
        self.proposal_title.setObjectName("titleLabel")
        self.proposal_title.setWordWrap(True)
        prop.addWidget(self.proposal_title)

        self.proposal_summary = QLabel("")
        self.proposal_summary.setObjectName("statusLabel")
        self.proposal_summary.setWordWrap(True)
        prop.addWidget(self.proposal_summary)

        diff_label = QLabel("BEFORE → AFTER")
        diff_label.setObjectName("pageKicker")
        prop.addWidget(diff_label)

        self.rename_table = QTableWidget(0, 3)
        self.rename_table.setHorizontalHeaderLabels(["Kind", "Before", "After"])
        header = self.rename_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.rename_table.setMinimumHeight(88)
        self.rename_table.setMaximumHeight(220)
        self.rename_table.setWordWrap(True)
        self.rename_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.rename_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.rename_table.setAlternatingRowColors(True)
        prop.addWidget(self.rename_table)

        self.impact_label = QLabel("")
        self.impact_label.setObjectName("statusLabel")
        self.impact_label.setWordWrap(True)
        prop.addWidget(self.impact_label)

        self.safety_dicom = QLabel("✓ Original DICOM files will not be modified")
        self.safety_plan = QLabel("✓ Changes affect the BIDS plan only")
        self.safety_rev = QLabel("✓ Change is reversible")
        for w in (self.safety_dicom, self.safety_plan, self.safety_rev):
            w.setObjectName("statusPass")
            w.setWordWrap(True)
            prop.addWidget(w)

        meta = QFormLayout()
        self.validation_label = QLabel("—")
        self.changeset_id_label = QLabel("—")
        self.changeset_id_label.setObjectName("monoLabel")
        self.warnings_label = QLabel("")
        self.warnings_label.setWordWrap(True)
        self.warnings_label.setObjectName("statusLabel")
        self.rule_label = QLabel("")
        self.rule_label.setWordWrap(True)
        self.rule_label.setObjectName("statusLabel")
        meta.addRow("Validation:", self.validation_label)
        meta.addRow("ChangeSet ID:", self.changeset_id_label)
        meta.addRow("Warnings:", self.warnings_label)
        meta.addRow("Curation rule:", self.rule_label)
        prop.addLayout(meta)

        self.apply_reason = QLabel("")
        self.apply_reason.setWordWrap(True)
        prop.addWidget(self.apply_reason)

        btn_row = QHBoxLayout()
        self.reject_btn = QPushButton("Reject")
        self.reject_btn.setObjectName("dangerButton")
        self.reject_btn.setMinimumHeight(32)
        self.explain_changeset_btn = QPushButton("Explain")
        self.explain_changeset_btn.setToolTip(
            "Show why this ChangeSet was proposed (evidence, tools, ChangeSet ID)."
        )
        self.explain_changeset_btn.clicked.connect(self._on_explain)
        self.apply_btn = QPushButton("Apply Changes")
        self.apply_btn.setObjectName("primaryButton")
        self.apply_btn.setMinimumHeight(32)
        self.apply_btn.setMinimumWidth(140)
        self.reject_btn.clicked.connect(self._on_reject)
        self.apply_btn.clicked.connect(self._on_apply)
        btn_row.addWidget(self.reject_btn)
        btn_row.addWidget(self.explain_changeset_btn)
        btn_row.addStretch(1)
        btn_row.addWidget(self.apply_btn)
        prop.addLayout(btn_row)

        layout.addWidget(self.proposal_box)

    def _refresh_availability(self) -> None:
        available = self._controller.is_llm_available()
        self.unavailable_box.setVisible(not available)

    def _update_context_hint(self) -> None:
        sel = self._last_selection
        if not sel:
            self.context_hint.setText("")
            return
        bits = []
        if sel.get("subject"):
            sub = sel["subject"]
            bits.append(sub if sub.startswith("sub-") else f"sub-{sub}")
        if sel.get("session"):
            ses = sel["session"]
            bits.append(ses if ses.startswith("ses-") else f"ses-{ses}")
        if sel.get("description"):
            bits.append(sel["description"])
        elif sel.get("datatype"):
            bits.append(sel["datatype"])
        self.context_hint.setText("Selection: " + " · ".join(bits) if bits else "")

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
            if self._controller.session is None or self._controller.session.plan is not self._preview.plan:
                self.rebind_session_from_preview()
            elif self._controller.session is not None:
                self._controller.session.invalidate_context_cache()
                if self._last_selection:
                    self._controller.session.set_ui_selection(**self._last_selection)
        self._append_conversation("You", text)
        self.input_edit.clear()
        self._controller.ask(text)

    def _on_cancel(self) -> None:
        if not self._controller.cancel():
            return
        self._append_conversation(
            "Warning",
            "Request cancelled. Nothing was applied to the plan.",
        )
        self.status.setText("Cancelled.")
        self._update_controls()

    def _on_busy_changed(self, busy: bool) -> None:
        self.loading_bar.setVisible(busy)
        self.cancel_btn.setVisible(busy)
        self._update_controls()
        if busy:
            apply_status(self.state_banner, "INFO", "Thinking…")
            self.status.setText("Thinking…")
        elif not self.status.text().startswith("Applied") and not self.status.text().startswith(
            "Rejected"
        ) and not self.status.text().startswith("Cancelled"):
            self.status.setText("")
            self._refresh_state_banner()

    def _on_response(self, result: object) -> None:
        if not isinstance(result, CopilotTurnResult):
            return
        if result.clarify:
            self._append_conversation("Warning", result.message or "(clarification)")
            self.status.setText("Clarification needed.")
            apply_status(self.state_banner, "REVIEW", "Clarification needed")
            return
        if result.message:
            self._append_conversation("Answer", result.message)
        if result.tool_traces:
            tools = ", ".join(t.tool_name for t in result.tool_traces)
            self._append_conversation("Tools", tools)
        if result.ok and result.changeset is not None:
            self._append_conversation(
                "Proposal",
                "A ChangeSet is ready for review. Reject or Apply below — nothing is applied yet.",
            )
            self.status.setText("Proposed changes ready for review.")
        elif result.ok:
            self.status.setText("Done.")
        self._refresh_proposal()
        self._update_controls()

    def _on_error(self, message: str) -> None:
        self._append_conversation("Error", message)
        self.status.setText(message)
        apply_status(self.state_banner, "FAIL", message)
        self.status_message.emit(message)
        self._update_controls()
        self._refresh_availability()

    def _on_apply(self) -> None:
        if self._preview is not None:
            self._preview.sync_edits_to_plan()
        ok, message = self._controller.apply_pending()
        if ok:
            self._append_conversation("Answer", message)
            self.status.setText(message)
            self.status_message.emit(message)
            self._set_proposal_visible(False)
            apply_status(self.state_banner, "PASS", "Changes applied to the BIDS plan")
        else:
            self._append_conversation("Error", message)
            self.status.setText(message)
            apply_status(self.state_banner, "FAIL", message)
            self.status_message.emit(message)
            if "no longer valid" in message.lower():
                self._refresh_proposal()
        self._update_controls()

    def _on_reject(self) -> None:
        ok, message = self._controller.reject_pending()
        role = "Answer" if ok else "Error"
        self._append_conversation(role, message if ok else message)
        self.status.setText(message)
        if ok:
            apply_status(self.state_banner, "INFO", "Proposal rejected — plan unchanged")
        else:
            apply_status(self.state_banner, "FAIL", message)
        self._set_proposal_visible(False)
        self._update_controls()

    def _on_plan_applied(self) -> None:
        if self._preview is not None:
            self._preview.reload_display()
        self.plan_refresh_requested.emit()
        self.rebind_session_from_preview()

    def _on_preview_plan_changed(self) -> None:
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
        stale = self._controller.pending_stale()
        session = self._controller.session
        conversion_busy = bool(session and session.conversion_busy)
        if stale:
            lines.append("This proposal is stale — the BIDS plan has changed.")
        self.proposal_summary.setText("\n".join(lines))
        self.impact_label.setText(
            f"Impact — {n_subj} subjects, {n_ses} sessions, {n_acq} acquisitions"
        )

        if stale:
            apply_status(self.proposal_state, "REVIEW", "Stale — plan changed. Reject and ask again.")
        elif conversion_busy:
            apply_status(self.proposal_state, "REVIEW", "Conversion is running. Apply is disabled.")
        else:
            apply_status(self.proposal_state, "REVIEW", "Review required before Apply")

        self.rename_table.setRowCount(0)
        pairs: list[tuple[str, str, str]] = []
        renames = preview.get("subject_renames") or {}
        for before, after in sorted({(str(a), str(b)) for a, b in renames.items() if a != b}):
            pairs.append(("subject", before, after))
        for before, after in (preview.get("session_renames") or {}).items():
            if str(before) != str(after):
                pairs.append(("session", str(before), str(after)))
        for change in preview.get("include_changes") or []:
            pairs.append(
                (
                    "include",
                    "Yes" if change.get("before") else "No",
                    "Yes" if change.get("after") else "No",
                )
            )
        for change in preview.get("entity_changes") or []:
            pairs.append(
                (
                    str(change.get("field") or "entity"),
                    str(change.get("before") or "—"),
                    str(change.get("after") or "—"),
                )
            )
        for kind, before, after in pairs:
            row = self.rename_table.rowCount()
            self.rename_table.insertRow(row)
            kind_item = QTableWidgetItem(kind)
            before_item = QTableWidgetItem(before)
            after_item = QTableWidgetItem(after)
            before_item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            after_item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            self.rename_table.setItem(row, 0, kind_item)
            self.rename_table.setItem(row, 1, before_item)
            self.rename_table.setItem(row, 2, after_item)
        self.rename_table.setVisible(bool(pairs))
        if pairs:
            self.rename_table.resizeRowsToContents()

        validation = preview.get("validation")
        if stale:
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

        rule = getattr(cs, "proposed_rule", None)
        op = getattr(cs, "rule_catalog_op", "") or ""
        if rule is not None and op:
            enabled = "enabled" if rule.enabled else "disabled"
            self.rule_label.setText(
                f"{op} v{rule.version} ({enabled}): if {rule.condition.summary()} "
                f"→ {rule.action.summary()}  [confidence {rule.confidence:.2f}]"
            )
            self.rule_label.setVisible(True)
        else:
            self.rule_label.setText("—")
            self.rule_label.setVisible(True)

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
        self.cancel_btn.setEnabled(busy)
        self.cancel_btn.setVisible(busy)
        for btn in self.suggested_buttons:
            btn.setEnabled(not busy)
        applicable = self._controller.is_pending_applicable()
        self.apply_btn.setEnabled(applicable and not busy)
        self.reject_btn.setEnabled(
            self._controller.pending_changeset is not None and not busy
        )
        can_explain = (
            self._controller.pending_changeset is not None
            or bool((self._last_selection or {}).get("series_uid"))
            or (
                self._controller.last_turn is not None
                and self._controller.last_turn.explanation is not None
            )
        )
        self.explain_btn.setEnabled(can_explain and not busy)
        self.explain_changeset_btn.setEnabled(
            self._controller.pending_changeset is not None and not busy
        )
        cs = self._controller.pending_changeset
        if cs is not None and cs.status != ChangeSetStatus.REJECTED:
            self._populate_proposal(cs)
        self._refresh_apply_reason()
        self._refresh_state_banner()
        self._refresh_availability()

    def _refresh_apply_reason(self) -> None:
        cs = self._controller.pending_changeset
        if cs is None:
            self.apply_reason.setText("")
            return
        session = self._controller.session
        if self._controller.busy:
            apply_status(self.apply_reason, "INFO", "Apply disabled — Copilot is still working")
        elif session is not None and session.conversion_busy:
            apply_status(self.apply_reason, "REVIEW", "Apply disabled — conversion is running")
        elif self._controller.pending_stale():
            apply_status(self.apply_reason, "REVIEW", "Apply disabled — proposal is stale")
        elif not self._controller.is_pending_applicable():
            apply_status(self.apply_reason, "REVIEW", "Apply disabled — ChangeSet is not valid")
        else:
            apply_status(self.apply_reason, "PASS", "Ready to apply to the BIDS plan only")

    def _refresh_state_banner(self) -> None:
        if self._controller.busy:
            apply_status(self.state_banner, "INFO", "Thinking…")
            return
        session = self._controller.session
        if session is not None and session.conversion_busy:
            apply_status(self.state_banner, "REVIEW", "Conversion running — Apply is disabled")
            return
        if self._controller.pending_stale():
            apply_status(self.state_banner, "REVIEW", friendly_copilot_error("stale_changeset"))
            return
        if self._controller.pending_changeset is not None:
            apply_status(self.state_banner, "REVIEW", "Proposed change awaiting approval")
            return
        if not self._controller.is_llm_available():
            apply_status(self.state_banner, "INFO", "Copilot unavailable — the rest of NeuroBIDS still works")
            return
        has_plan = (
            self._preview is not None
            and self._preview.plan is not None
            and bool(self._preview.plan.items)
        )
        if not has_plan:
            apply_status(self.state_banner, "INFO", "Load a dataset to ask NeuroBIDS")
            return
        text = self.status.text().strip()
        if "applied" in text.lower():
            apply_status(self.state_banner, "PASS", text)
        elif "rejected" in text.lower():
            apply_status(self.state_banner, "INFO", text)
        elif "cancelled" in text.lower():
            apply_status(self.state_banner, "INFO", text)
        elif text in {"", "Done.", "History cleared.", "Thinking…"}:
            self.state_banner.setText("")
        elif text:
            apply_status(self.state_banner, "FAIL", text)

    def _append_conversation(self, role: str, text: str) -> None:
        css, label = _ROLE_CLASS.get(role, ("msg-info", role))
        safe = (
            (text or "")
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace("\n", "<br>")
        )
        html = f"<p class='{css}'><b>{label}:</b> {safe}</p>"
        self.conversation.moveCursor(QTextCursor.MoveOperation.End)
        self.conversation.insertHtml(html)
        self.conversation.append("")
        self.conversation.moveCursor(QTextCursor.MoveOperation.End)
