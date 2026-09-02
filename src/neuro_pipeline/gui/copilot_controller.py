"""Thin GUI controller for NeuroBIDS Copilot (no BIDS logic in widgets)."""

from __future__ import annotations

import logging
from typing import Callable

from PySide6.QtCore import QObject, Qt, Signal

from neuro_pipeline.neurobids.copilot.changeset import ChangeSet, ChangeSetError, ChangeSetStatus
from neuro_pipeline.neurobids.copilot.llm.agent import CopilotAgent
from neuro_pipeline.neurobids.copilot.llm.config import LLMConfig
from neuro_pipeline.neurobids.copilot.llm.provider import LLMProvider
from neuro_pipeline.neurobids.copilot.llm.schemas import CopilotTurnResult
from neuro_pipeline.neurobids.copilot.plan_ops import plan_fingerprint
from neuro_pipeline.neurobids.copilot.session import CopilotSession
from neuro_pipeline.neurobids.copilot.tools.registry import ToolRegistry, default_registry
from neuro_pipeline.workers import CopilotWorker, start_worker

LOGGER = logging.getLogger(__name__)

# User-facing messages (no stack traces / secrets)
_ERROR_MESSAGES = {
    "provider_unavailable": (
        "No LLM provider is configured. Set NEUROBIDS_LLM_PROVIDER and credentials "
        "if you want natural-language assistance. Preview editing still works."
    ),
    "timeout": "The Copilot request timed out. Please try again.",
    "malformed_response": "The Copilot returned an unexpected response. Please try again.",
    "invalid_tool_name": "The Copilot requested an unknown tool. The request was not executed.",
    "invalid_tool_arguments": "The Copilot proposed invalid tool arguments. Nothing was changed.",
    "tool_execution_failure": "A Copilot tool failed. Nothing was applied to the plan.",
    "empty_dataset": "No BIDS conversion plan is loaded. Scan a DICOM folder first.",
    "empty_request": "Please enter a question or curation request.",
    "max_tool_calls": "The Copilot reached its step limit. Try a more specific request.",
    "stale_changeset": (
        "This proposal is no longer valid because the BIDS plan has changed. "
        "Please generate a new proposal."
    ),
    "conversion_busy": "Conversion is running. Wait until it finishes before applying changes.",
}


def friendly_copilot_error(code: str, fallback: str = "") -> str:
    return _ERROR_MESSAGES.get(code) or fallback or "Copilot request failed."


class CopilotController(QObject):
    """Owns session binding, background asks, and ChangeSet approve/reject."""

    busy_changed = Signal(bool)
    response_ready = Signal(object)  # CopilotTurnResult
    error = Signal(str)
    changeset_updated = Signal()
    plan_applied = Signal()  # preview should refresh

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._session: CopilotSession | None = None
        self._registry: ToolRegistry = default_registry()
        self._provider: LLMProvider | None = None
        self._config = LLMConfig.from_env()
        self._pending: ChangeSet | None = None
        self._busy = False
        self._force_sync = False
        self._thread = None
        self._worker: CopilotWorker | None = None
        self._sync_plan: Callable[[], None] | None = None

    @property
    def session(self) -> CopilotSession | None:
        return self._session

    @property
    def pending_changeset(self) -> ChangeSet | None:
        return self._pending

    @property
    def busy(self) -> bool:
        return self._busy

    def set_provider(self, provider: LLMProvider | None) -> None:
        self._provider = provider

    def set_config(self, config: LLMConfig) -> None:
        self._config = config

    def set_sync_plan_callback(self, callback: Callable[[], None] | None) -> None:
        """Optional hook to flush Preview table edits into the live plan."""
        self._sync_plan = callback

    def bind_session(self, session: CopilotSession | None) -> None:
        self._session = session
        self.clear_pending()

    def set_conversion_busy(self, busy: bool) -> None:
        if self._session is not None:
            self._session.set_conversion_busy(busy)
        self.changeset_updated.emit()

    def clear_pending(self) -> None:
        self._pending = None
        self.changeset_updated.emit()

    def _flush_plan(self) -> None:
        if self._sync_plan is not None:
            self._sync_plan()
        if self._session is not None:
            self._session.invalidate_context_cache()

    def ask(self, user_request: str, *, sync: bool | None = None) -> bool:
        """Start a Copilot turn. Returns False if not started.

        ``sync=True`` runs on the caller thread (tests / debugging).
        Default is background ``CopilotWorker`` so the GUI stays responsive.
        """
        if self._busy:
            self.error.emit("A Copilot request is already running.")
            return False
        if self._session is None or not self._session.plan.items:
            self.error.emit(friendly_copilot_error("empty_dataset"))
            return False
        text = (user_request or "").strip()
        if not text:
            self.error.emit(friendly_copilot_error("empty_request"))
            return False

        self._flush_plan()
        agent = CopilotAgent(
            session=self._session,
            registry=self._registry,
            provider=self._provider,
            config=self._config,
        )
        use_sync = self._force_sync if sync is None else sync
        if use_sync:
            self._set_busy(True)
            try:
                self._on_worker_started()
                result = agent.handle(text)
                self._on_worker_response(result)
            except Exception as exc:  # noqa: BLE001
                LOGGER.exception("Copilot sync ask failed")
                self._on_worker_error(str(exc))
            finally:
                self._on_worker_finished()
            return True

        self._cleanup_worker()
        self._worker = CopilotWorker(agent, text)
        self._thread = start_worker(self._worker)
        assert self._thread is not None and self._worker is not None
        self._worker.started.connect(self._on_worker_started)
        self._worker.response_ready.connect(
            self._on_worker_response,
            type=Qt.ConnectionType.QueuedConnection,  # type: ignore[arg-type]
        )
        self._worker.error.connect(
            self._on_worker_error,
            type=Qt.ConnectionType.QueuedConnection,  # type: ignore[arg-type]
        )
        self._worker.finished.connect(
            self._on_worker_finished,
            type=Qt.ConnectionType.QueuedConnection,  # type: ignore[arg-type]
        )
        self._thread.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)
        self._set_busy(True)
        self._thread.start()
        return True

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.busy_changed.emit(busy)

    def _on_worker_started(self) -> None:
        LOGGER.info("neurobids_copilot_gui_started")

    def _on_worker_response(self, result: object) -> None:
        turn = result if isinstance(result, CopilotTurnResult) else None
        if turn is None:
            self.error.emit(friendly_copilot_error("malformed_response"))
            return
        if turn.changeset is not None:
            self._pending = turn.changeset
            # Validate immediately so Apply can be enabled when safe
            try:
                if self._session is not None:
                    self._pending.validate(
                        self._session.plan,
                        conversion_busy=self._session.conversion_busy,
                    )
            except ChangeSetError as exc:
                LOGGER.info("changeset validate after turn: %s", exc)
            self.changeset_updated.emit()
        if not turn.ok and turn.error is not None:
            msg = friendly_copilot_error(turn.error.code, turn.error.message)
            # Still emit response so conversation can show details
            self.response_ready.emit(turn)
            self.error.emit(msg)
            return
        self.response_ready.emit(turn)

    def _on_worker_error(self, message: str) -> None:
        self.error.emit(message or friendly_copilot_error("malformed_response"))

    def set_force_sync(self, enabled: bool) -> None:
        """When True, ``ask()`` runs on the calling thread (for unit tests)."""
        self._force_sync = bool(enabled)

    def _on_worker_finished(self) -> None:
        self._set_busy(False)
        thread = self._thread
        self._worker = None
        self._thread = None
        if thread is not None and thread.isRunning():
            thread.quit()

    def _cleanup_worker(self) -> None:
        if self._worker is not None:
            self._worker.stop()
        thread = self._thread
        self._worker = None
        self._thread = None
        if thread is not None and thread.isRunning():
            thread.quit()
            thread.wait(3000)

    def is_pending_applicable(self) -> bool:
        cs = self._pending
        if cs is None or self._session is None:
            return False
        if self._busy or self._session.conversion_busy:
            return False
        if cs.status not in {ChangeSetStatus.VALIDATED, ChangeSetStatus.APPROVED}:
            return False
        return plan_fingerprint(self._session.plan) == cs.plan_fingerprint

    def pending_stale(self) -> bool:
        cs = self._pending
        if cs is None or self._session is None:
            return False
        if cs.status in {ChangeSetStatus.REJECTED, ChangeSetStatus.APPLIED, ChangeSetStatus.FAILED}:
            return False
        return plan_fingerprint(self._session.plan) != cs.plan_fingerprint

    def apply_pending(self) -> tuple[bool, str]:
        """Approve + apply pending ChangeSet. Never starts conversion."""
        if self._pending is None or self._session is None:
            return False, "No proposed changes to apply."
        self._flush_plan()
        cs = self._pending
        plan = self._session.plan
        busy = self._session.conversion_busy
        if busy:
            return False, friendly_copilot_error("conversion_busy")
        try:
            if cs.status == ChangeSetStatus.DRAFT:
                cs.validate(plan, conversion_busy=busy)
            if cs.status == ChangeSetStatus.VALIDATED:
                cs.approve()
            cs.apply(plan, conversion_busy=busy, require_validated=True)
        except ChangeSetError as exc:
            msg = str(exc)
            if "fingerprint" in msg.lower() or "stale" in msg.lower():
                return False, friendly_copilot_error("stale_changeset")
            if "conversion" in msg.lower() and "running" in msg.lower():
                return False, friendly_copilot_error("conversion_busy")
            return False, msg
        self._session.invalidate_context_cache()
        self._pending = None
        self.changeset_updated.emit()
        self.plan_applied.emit()
        return True, "Proposed changes applied to the BIDS conversion plan."

    def reject_pending(self) -> tuple[bool, str]:
        if self._pending is None:
            return False, "No proposed changes to reject."
        try:
            self._pending.reject()
        except ChangeSetError as exc:
            return False, str(exc)
        status = self._pending.status
        self._pending = None
        self.changeset_updated.emit()
        return True, f"Proposal rejected ({status.value}). Plan unchanged."

    def notify_plan_edited(self) -> None:
        """Call when Preview edits may have changed the live plan."""
        self.changeset_updated.emit()
