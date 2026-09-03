"""Thin GUI controller for NeuroBIDS Copilot (no BIDS logic in widgets)."""

from __future__ import annotations

import logging
from typing import Callable

from PySide6.QtCore import QObject, Qt, Signal

from neuro_pipeline.neurobids.copilot.changeset import ChangeSet, ChangeSetError, ChangeSetStatus
from neuro_pipeline.neurobids.copilot.explain import (
    CopilotExplanation,
    explain_changeset,
    explain_mapping,
)
from neuro_pipeline.neurobids.copilot.llm.agent import CopilotAgent
from neuro_pipeline.neurobids.copilot.llm.config import LLMConfig
from neuro_pipeline.neurobids.copilot.llm.provider import LLMProvider
from neuro_pipeline.neurobids.copilot.llm.schemas import CopilotTurnResult
from neuro_pipeline.neurobids.copilot.plan_ops import plan_fingerprint
from neuro_pipeline.neurobids.copilot.provenance import (
    CopilotProvenanceStore,
    build_decision_record,
    default_provenance_store,
)
from neuro_pipeline.neurobids.copilot.session import CopilotSession
from neuro_pipeline.neurobids.copilot.tools.registry import ToolRegistry, default_registry
from neuro_pipeline.workers import CopilotWorker, start_worker

LOGGER = logging.getLogger(__name__)

# User-facing messages (no stack traces / secrets)
_ERROR_MESSAGES = {
    "provider_unavailable": (
        "AI Copilot is not configured. NeuroBIDS still works without an AI provider. "
        "Open Settings to choose Disabled, Local AI (Ollama), or an OpenAI-compatible API."
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
    "mutation_rejected": "The proposed change was rejected. The BIDS plan was not modified.",
    "approval_required": "Proposed changes require your explicit Apply before anything is changed.",
    "provider_http_error": "The LLM provider returned an error. Check Settings → Test connection.",
    "provider_error": "The LLM provider is unavailable. Check Settings → Test connection.",
    "model_unavailable": "The configured model is not available on the provider.",
    "invalid_configuration": "Copilot configuration is incomplete. Review Settings → NeuroBIDS Copilot.",
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
    connection_test_finished = Signal(object)  # ConnectionProbeResult

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._session: CopilotSession | None = None
        self._registry: ToolRegistry = default_registry()
        self._provider: LLMProvider | None = None
        self._config = LLMConfig.from_env()
        self._pending: ChangeSet | None = None
        self._last_turn: CopilotTurnResult | None = None
        self._busy = False
        self._force_sync = False
        self._thread = None
        self._worker: CopilotWorker | None = None
        self._sync_plan: Callable[[], None] | None = None
        self._turn_id = 0
        self._provenance_store: CopilotProvenanceStore | None = default_provenance_store()
        self._probe_thread = None
        self._probe_worker = None
        self.last_connection_status: str = ""
        self.last_connection_message: str = ""

    @property
    def session(self) -> CopilotSession | None:
        return self._session

    @property
    def pending_changeset(self) -> ChangeSet | None:
        return self._pending

    @property
    def last_turn(self) -> CopilotTurnResult | None:
        return self._last_turn

    @property
    def busy(self) -> bool:
        return self._busy

    def set_provider(self, provider: LLMProvider | None) -> None:
        self._provider = provider

    def is_llm_available(self) -> bool:
        if self._provider is not None:
            from neuro_pipeline.neurobids.copilot.llm.provider import UnavailableLLMProvider

            return not isinstance(self._provider, UnavailableLLMProvider)
        return bool(self._config and self._config.is_configured)

    def set_config(self, config: LLMConfig) -> None:
        self._config = config

    def reload_config_from_env(self) -> LLMConfig:
        """Reload LLM settings from the process environment and clear injected providers."""
        self._config = LLMConfig.from_env()
        # Drop injected providers so the next ask rebuilds from config,
        # unless a test/demo provider was explicitly Unavailable-safe Fake.
        self._provider = None
        return self._config

    def current_config(self) -> LLMConfig:
        return self._config

    def test_connection(self, *, sync: bool = False) -> bool:
        """Probe the configured LLM provider without blocking the GUI (default)."""
        from neuro_pipeline.neurobids.copilot.llm.connection import probe_llm_connection
        from neuro_pipeline.workers import LLMConnectionTestWorker, start_worker

        config = self._config or LLMConfig.from_env()
        if sync:
            result = probe_llm_connection(config)
            self.connection_test_finished.emit(result)
            return True
        if self._probe_worker is not None:
            self.error.emit("A connection test is already running.")
            return False
        self._probe_worker = LLMConnectionTestWorker(config)
        self._probe_thread = start_worker(self._probe_worker)
        assert self._probe_thread is not None and self._probe_worker is not None
        self._probe_worker.finished_result.connect(
            self._on_probe_finished,
            type=Qt.ConnectionType.QueuedConnection,  # type: ignore[arg-type]
        )
        self._probe_worker.failed.connect(
            self._on_probe_failed,
            type=Qt.ConnectionType.QueuedConnection,  # type: ignore[arg-type]
        )
        self._probe_thread.finished.connect(self._probe_worker.deleteLater)
        self._probe_thread.finished.connect(self._probe_thread.deleteLater)
        self._probe_thread.finished.connect(self._clear_probe_handles)
        self._probe_thread.start()
        return True

    def _on_probe_finished(self, result: object) -> None:
        self.last_connection_status = str(getattr(result, "status", "") or "")
        self.last_connection_message = str(getattr(result, "message", "") or "")
        self.connection_test_finished.emit(result)

    def _on_probe_failed(self, message: str) -> None:
        from neuro_pipeline.neurobids.copilot.llm.connection import ConnectionProbeResult

        result = ConnectionProbeResult(
            status="provider_unavailable",
            message=message or "Connection test failed.",
        )
        self.last_connection_status = result.status
        self.last_connection_message = result.message
        self.connection_test_finished.emit(result)

    def _clear_probe_handles(self) -> None:
        self._probe_worker = None
        self._probe_thread = None

    def set_provenance_store(self, store: CopilotProvenanceStore | None) -> None:
        self._provenance_store = store

    def set_sync_plan_callback(self, callback: Callable[[], None] | None) -> None:
        """Optional hook to flush Preview table edits into the live plan."""
        self._sync_plan = callback

    def bind_session(self, session: CopilotSession | None) -> None:
        self._session = session
        self._last_turn = None
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
        self._turn_id += 1
        turn = self._turn_id
        agent = CopilotAgent(
            session=self._session,
            registry=self._registry,
            provider=self._provider,
            config=self._config,
            provenance_store=self._provenance_store,
        )
        use_sync = self._force_sync if sync is None else sync
        if use_sync:
            self._set_busy(True)
            try:
                self._on_worker_started()
                result = agent.handle(text)
                if turn == self._turn_id:
                    self._on_worker_response(result)
            except Exception as exc:  # noqa: BLE001
                LOGGER.exception("Copilot sync ask failed")
                if turn == self._turn_id:
                    self._on_worker_error(str(exc))
            finally:
                if turn == self._turn_id:
                    self._on_worker_finished()
            return True

        self._cleanup_worker()
        self._worker = CopilotWorker(agent, text)
        self._thread = start_worker(self._worker)
        assert self._thread is not None and self._worker is not None
        self._worker.started.connect(self._on_worker_started)
        self._worker.response_ready.connect(
            lambda result, t=turn: self._deliver_response(t, result),
            type=Qt.ConnectionType.QueuedConnection,  # type: ignore[arg-type]
        )
        self._worker.error.connect(
            lambda message, t=turn: self._deliver_error(t, message),
            type=Qt.ConnectionType.QueuedConnection,  # type: ignore[arg-type]
        )
        self._worker.finished.connect(
            lambda t=turn: self._deliver_finished(t),
            type=Qt.ConnectionType.QueuedConnection,  # type: ignore[arg-type]
        )
        self._thread.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)
        self._set_busy(True)
        self._thread.start()
        return True

    def cancel(self) -> bool:
        """Stop an in-flight request. Never applies a ChangeSet."""
        if not self._busy:
            return False
        self._turn_id += 1
        self._cleanup_worker()
        self._set_busy(False)
        return True

    def _deliver_response(self, turn: int, result: object) -> None:
        if turn != self._turn_id:
            return
        self._on_worker_response(result)

    def _deliver_error(self, turn: int, message: str) -> None:
        if turn != self._turn_id:
            return
        self._on_worker_error(message)

    def _deliver_finished(self, turn: int) -> None:
        if turn != self._turn_id:
            return
        self._on_worker_finished()

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
        self._last_turn = turn
        if turn.changeset is not None:
            self._pending = turn.changeset
            # Validate immediately so Apply can be enabled when safe
            try:
                if self._session is not None:
                    self._pending.validate(
                        self._session.plan,
                        conversion_busy=self._session.conversion_busy,
                        rule_store=self._session.curation_store(),
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
        text = (message or "").strip()
        lower = text.lower()
        if "provider_unavailable" in lower or "no llm provider" in lower:
            self.error.emit(friendly_copilot_error("provider_unavailable"))
            return
        if "timed out" in lower or "timeout" in lower:
            self.error.emit(friendly_copilot_error("timeout"))
            return
        if "malformed" in lower:
            self.error.emit(friendly_copilot_error("malformed_response", text))
            return
        # Never dump stack traces into the conversation panel.
        if "traceback" in lower:
            self.error.emit(friendly_copilot_error("provider_error"))
            return
        self.error.emit(text or friendly_copilot_error("malformed_response"))

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
        status_before = cs.status.value
        turn_id = (
            self._last_turn.provenance_turn_id
            if self._last_turn is not None
            else ""
        )
        if busy:
            return False, friendly_copilot_error("conversion_busy")
        try:
            if cs.status == ChangeSetStatus.DRAFT:
                cs.validate(plan, conversion_busy=busy, rule_store=self._session.curation_store())
            if cs.status == ChangeSetStatus.VALIDATED:
                cs.approve()
            cs.apply(
                plan,
                conversion_busy=busy,
                require_validated=True,
                rule_store=self._session.curation_store(),
            )
        except ChangeSetError as exc:
            msg = str(exc)
            if "fingerprint" in msg.lower() or "stale" in msg.lower():
                return False, friendly_copilot_error("stale_changeset")
            if "conversion" in msg.lower() and "running" in msg.lower():
                return False, friendly_copilot_error("conversion_busy")
            return False, msg
        preview = cs.preview() if hasattr(cs, "preview") else {}
        applied_summary = {
            "n_edits": len(cs.edits or []),
            "subject_renames": dict((preview or {}).get("subject_renames") or {}),
            "n_include_changes": len((preview or {}).get("include_changes") or []),
            "n_entity_changes": len((preview or {}).get("entity_changes") or []),
            "plan_fingerprint_before": cs.plan_fingerprint,
            "plan_fingerprint_after": plan_fingerprint(plan),
        }
        message = "Proposed changes applied to the BIDS conversion plan."
        if cs.rule_catalog_op and cs.proposed_rule is not None:
            rule = cs.proposed_rule
            message = (
                "Proposed changes applied to the BIDS conversion plan. "
                f"Saved dataset curation rule {rule.id[:8]} (v{rule.version})."
            )
        self._record_decision(
            turn_id=turn_id,
            action="applied",
            changeset=cs,
            status_before=status_before,
            message=message,
            applied_summary=applied_summary,
            plan_fingerprint_after=plan_fingerprint(plan),
        )
        self._session.last_applied_changeset = cs
        self._session.invalidate_context_cache()
        self._pending = None
        self.changeset_updated.emit()
        self.plan_applied.emit()
        return True, message

    def reject_pending(self) -> tuple[bool, str]:
        if self._pending is None:
            return False, "No proposed changes to reject."
        cs = self._pending
        status_before = cs.status.value
        turn_id = (
            self._last_turn.provenance_turn_id
            if self._last_turn is not None
            else ""
        )
        try:
            cs.reject()
        except ChangeSetError as exc:
            return False, str(exc)
        status = cs.status
        message = f"Proposal rejected ({status.value}). Plan unchanged."
        self._record_decision(
            turn_id=turn_id,
            action="rejected",
            changeset=cs,
            status_before=status_before,
            message=message,
            applied_summary=None,
            plan_fingerprint_after=plan_fingerprint(self._session.plan)
            if self._session is not None
            else "",
        )
        self._pending = None
        self.changeset_updated.emit()
        return True, message

    def _record_decision(
        self,
        *,
        turn_id: str,
        action: str,
        changeset: ChangeSet,
        status_before: str,
        message: str,
        applied_summary: dict | None,
        plan_fingerprint_after: str,
    ) -> None:
        store = self._provenance_store
        if store is None:
            return
        try:
            record = build_decision_record(
                turn_id=turn_id or "",
                action=action,
                changeset=changeset,
                status_before=status_before,
                message=message,
                applied_summary=applied_summary,
                dataset_root=None
                if self._session is None
                else self._session.plan.dataset_root,
                plan_fingerprint_after=plan_fingerprint_after,
            )
            store.append(record)
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("Failed to persist Copilot provenance decision: %s", exc)

    def explain_pending(self) -> CopilotExplanation | None:
        """Explain the pending ChangeSet. Read-only; never applies."""
        if self._pending is None:
            return None
        traces = self._last_turn.tool_traces if self._last_turn is not None else None
        if self._last_turn is not None and self._last_turn.explanation is not None:
            expl = self._last_turn.explanation
            if getattr(expl, "changeset_id", "") == self._pending.id:
                return expl
        return explain_changeset(self._pending, tool_traces=traces)

    def explain_mapping_uid(self, series_uid: str = "") -> CopilotExplanation | None:
        """Explain the current (or given) acquisition mapping. Read-only."""
        if self._session is None:
            return None
        uid = (series_uid or "").strip() or str(
            (self._session.ui_selection or {}).get("series_uid") or ""
        ).strip()
        if not uid:
            return None
        try:
            return explain_mapping(self._session, uid)
        except KeyError:
            return None

    def explain_current(self) -> CopilotExplanation | None:
        """ChangeSet explanation if pending, otherwise selected mapping."""
        pending = self.explain_pending()
        if pending is not None:
            return pending
        if self._last_turn is not None and self._last_turn.explanation is not None:
            return self._last_turn.explanation
        return self.explain_mapping_uid()

    def notify_plan_edited(self) -> None:
        """Call when Preview edits may have changed the live plan."""
        self.changeset_updated.emit()
