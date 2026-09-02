"""CopilotAgent — controlled NL → structured tool calls → ToolRegistry."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from neuro_pipeline.logging.privacy import safe_folder_label
from neuro_pipeline.neurobids.copilot.changeset import ChangeSet
from neuro_pipeline.neurobids.copilot.explain import explain_turn, stamp_changeset
from neuro_pipeline.neurobids.copilot.llm.config import LLMConfig
from neuro_pipeline.neurobids.copilot.llm.prompts import (
    NEUROBIDS_COPILOT_SYSTEM_PROMPT,
    build_user_payload,
)
from neuro_pipeline.neurobids.copilot.llm.provider import (
    LLMProvider,
    LLMProviderError,
    UnavailableLLMProvider,
    build_provider_from_config,
)
from neuro_pipeline.neurobids.copilot.llm.schemas import (
    AssistantResponseType,
    CopilotError,
    CopilotTurnResult,
    ToolCallTrace,
)
from neuro_pipeline.neurobids.copilot.llm.validation import (
    ToolArgumentValidationError,
    validate_tool_arguments,
)
from neuro_pipeline.neurobids.copilot.plan_ops import plan_fingerprint
from neuro_pipeline.neurobids.copilot.provenance import (
    CopilotProvenanceStore,
    build_turn_record,
)
from neuro_pipeline.neurobids.copilot.provenance.sanitize import sanitize_for_provenance
from neuro_pipeline.neurobids.copilot.session import CopilotSession
from neuro_pipeline.neurobids.copilot.tools.registry import ToolRegistry, default_registry

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class CopilotAgent:
    """Provider-independent agent loop over registered NeuroBIDS tools."""

    session: CopilotSession
    registry: ToolRegistry = field(default_factory=default_registry)
    provider: LLMProvider | None = None
    config: LLMConfig = field(default_factory=LLMConfig.from_env)
    max_tool_calls: int | None = None
    provenance_store: CopilotProvenanceStore | None = None

    def __post_init__(self) -> None:
        if self.provider is None:
            try:
                self.provider = build_provider_from_config(self.config)
            except LLMProviderError:
                self.provider = UnavailableLLMProvider()
        if self.max_tool_calls is None:
            self.max_tool_calls = int(self.config.max_tool_calls or 5)
        # Provenance store is optional; GUI controller binds the default store.
        # Benchmarks/FakeLLM leave this None unless a test injects one.

    def handle(self, user_request: str) -> CopilotTurnResult:
        """Handle one natural-language request (never applies ChangeSets)."""
        request = (user_request or "").strip()
        provider = self.provider or UnavailableLLMProvider()
        provider_name = getattr(provider, "name", "unknown")
        model_name = getattr(provider, "model", "") or self.config.model
        turn_id = str(uuid4())
        model_responses: list[dict[str, Any]] = []
        tool_call_logs: list[dict[str, Any]] = []

        LOGGER.info(
            "neurobids_copilot_request provider=%s model=%s dataset=%s turn=%s",
            provider_name,
            model_name,
            safe_folder_label(self.session.plan.dataset_root),
            turn_id,
        )

        def _finish(result: CopilotTurnResult) -> CopilotTurnResult:
            result.provenance_turn_id = turn_id
            self._persist_turn(
                turn_id=turn_id,
                user_request=request,
                provider_name=provider_name,
                model_name=model_name,
                model_responses=model_responses,
                tool_call_logs=tool_call_logs,
                result=result,
            )
            return result

        if not request:
            return _finish(
                CopilotTurnResult(
                    ok=False,
                    error=CopilotError("empty_request", "User request is empty"),
                    provider=provider_name,
                    model=model_name,
                    stopped_reason="empty_request",
                )
            )

        try:
            ctx = self.session.dataset_context(refresh=True)
            llm_context = ctx.to_llm_context()
        except Exception as exc:  # noqa: BLE001
            return _finish(
                CopilotTurnResult(
                    ok=False,
                    error=CopilotError("empty_dataset", f"Failed to build dataset context: {exc}"),
                    provider=provider_name,
                    model=model_name,
                    stopped_reason="empty_dataset",
                )
            )

        if not self.session.plan.items:
            return _finish(
                CopilotTurnResult(
                    ok=False,
                    error=CopilotError(
                        "empty_dataset", "No acquisitions are loaded in the current plan"
                    ),
                    provider=provider_name,
                    model=model_name,
                    stopped_reason="empty_dataset",
                )
            )

        selection = dict(getattr(self.session, "ui_selection", None) or {})
        if selection:
            llm_context = dict(llm_context)
            llm_context["current_selection"] = selection

        dumped_ctx = json.dumps(llm_context, ensure_ascii=False)
        if "PatientName" in dumped_ctx:
            return _finish(
                CopilotTurnResult(
                    ok=False,
                    error=CopilotError(
                        "privacy_violation", "LLM context unexpectedly contained PatientName"
                    ),
                    provider=provider_name,
                    model=model_name,
                    stopped_reason="privacy_violation",
                )
            )

        tools = self.registry.to_llm_tools()
        transcript: list[dict[str, Any]] = []
        prior_results: list[dict[str, Any]] = []
        traces: list[ToolCallTrace] = []
        last_tool_name = ""
        last_tool_data: dict[str, Any] | None = None
        max_calls = max(1, int(self.max_tool_calls or 5))

        for _step in range(max_calls):
            user_payload = build_user_payload(
                user_request=request,
                dataset_context=llm_context,
                tool_definitions=tools,
                prior_tool_results=prior_results,
            )
            try:
                assistant = provider.generate(
                    system=NEUROBIDS_COPILOT_SYSTEM_PROMPT,
                    user_payload=user_payload,
                    tools=tools,
                    transcript=transcript,
                )
            except LLMProviderError as exc:
                from neuro_pipeline.neurobids.copilot.llm.config import scrub_secrets

                safe_msg = scrub_secrets(str(exc), getattr(self.config, "api_key", ""))
                return _finish(
                    CopilotTurnResult(
                        ok=False,
                        tool_traces=traces,
                        error=CopilotError(getattr(exc, "code", "provider_error"), safe_msg),
                        provider=provider_name,
                        model=model_name,
                        stopped_reason=getattr(exc, "code", "provider_error"),
                    )
                )
            except Exception as exc:  # noqa: BLE001
                return _finish(
                    CopilotTurnResult(
                        ok=False,
                        tool_traces=traces,
                        error=CopilotError(
                            "malformed_response", f"Malformed LLM response: {exc}"
                        ),
                        provider=provider_name,
                        model=model_name,
                        stopped_reason="malformed_response",
                    )
                )

            model_responses.append(sanitize_for_provenance(assistant.to_dict()))

            if assistant.type == AssistantResponseType.ERROR:
                return _finish(
                    CopilotTurnResult(
                        ok=False,
                        message=assistant.content,
                        tool_traces=traces,
                        error=CopilotError(
                            "llm_error", assistant.content or "LLM returned an error"
                        ),
                        provider=provider_name,
                        model=model_name,
                        stopped_reason="llm_error",
                    )
                )

            if assistant.type == AssistantResponseType.CLARIFY:
                return _finish(
                    CopilotTurnResult(
                        ok=True,
                        message=assistant.content,
                        clarify=True,
                        tool_traces=traces,
                        provider=provider_name,
                        model=model_name,
                        stopped_reason="clarify",
                    )
                )

            if assistant.type == AssistantResponseType.MESSAGE:
                return _finish(
                    _attach_explanation(
                        CopilotTurnResult(
                            ok=True,
                            message=assistant.content,
                            tool_traces=traces,
                            provider=provider_name,
                            model=model_name,
                            stopped_reason="message",
                        ),
                        last_tool_name=last_tool_name,
                        last_tool_data=last_tool_data,
                    )
                )

            call = assistant.tool_call
            if call is None:
                return _finish(
                    CopilotTurnResult(
                        ok=False,
                        tool_traces=traces,
                        error=CopilotError("malformed_response", "tool_call missing body"),
                        provider=provider_name,
                        model=model_name,
                        stopped_reason="malformed_response",
                    )
                )

            tool = self.registry.get(call.tool_name)
            if tool is None:
                tool_call_logs.append(
                    {
                        "tool_name": call.tool_name,
                        "arguments": sanitize_for_provenance(dict(call.arguments)),
                        "ok": False,
                        "error": "invalid_tool_name",
                        "result": None,
                        "changeset_id": "",
                        "mutates_data": False,
                    }
                )
                return _finish(
                    CopilotTurnResult(
                        ok=False,
                        tool_traces=traces,
                        error=CopilotError(
                            "invalid_tool_name",
                            f"Tool not registered: {call.tool_name}",
                            {"tool_name": call.tool_name},
                        ),
                        provider=provider_name,
                        model=model_name,
                        stopped_reason="invalid_tool_name",
                    )
                )

            try:
                validate_tool_arguments(tool.input_schema, call.arguments)
            except ToolArgumentValidationError as exc:
                tool_call_logs.append(
                    {
                        "tool_name": call.tool_name,
                        "arguments": sanitize_for_provenance(dict(call.arguments)),
                        "ok": False,
                        "error": exc.message,
                        "result": None,
                        "changeset_id": "",
                        "mutates_data": bool(tool.mutates_data),
                    }
                )
                return _finish(
                    CopilotTurnResult(
                        ok=False,
                        tool_traces=traces,
                        error=CopilotError(
                            "invalid_tool_arguments",
                            exc.message,
                            {"tool_name": call.tool_name},
                        ),
                        provider=provider_name,
                        model=model_name,
                        stopped_reason="invalid_tool_arguments",
                    )
                )

            if call.tool_name in {
                "apply_changeset",
                "rollback_changeset",
                "exec_rule",
                "eval_rule",
                "run_curation_code",
                "execute_rule",
            }:
                return _finish(
                    CopilotTurnResult(
                        ok=False,
                        tool_traces=traces,
                        error=CopilotError(
                            "forbidden_tool",
                            "LLM may not apply or rollback ChangeSets",
                        ),
                        provider=provider_name,
                        model=model_name,
                        stopped_reason="forbidden_tool",
                    )
                )

            result = self.registry.execute(call.tool_name, self.session, call.arguments)
            changeset = None
            changeset_id = ""
            if result.ok and isinstance(result.data.get("changeset"), ChangeSet):
                changeset = result.data["changeset"]
                changeset_id = changeset.id

            traces.append(
                ToolCallTrace(
                    tool_name=call.tool_name,
                    arguments=dict(call.arguments),
                    ok=result.ok,
                    error=result.error,
                    changeset_id=changeset_id,
                    mutates_data=tool.mutates_data,
                )
            )
            LOGGER.info(
                "neurobids_copilot_tool tool=%s ok=%s mutates=%s changeset_id=%s",
                call.tool_name,
                result.ok,
                tool.mutates_data,
                changeset_id or "-",
            )

            safe_data = _sanitize_tool_data_for_llm(result.data) if result.ok else None
            tool_call_logs.append(
                {
                    "tool_name": call.tool_name,
                    "arguments": sanitize_for_provenance(dict(call.arguments)),
                    "ok": bool(result.ok),
                    "error": result.error or "",
                    "result": sanitize_for_provenance(safe_data) if safe_data is not None else None,
                    "changeset_id": changeset_id,
                    "mutates_data": bool(tool.mutates_data),
                }
            )

            if not result.ok:
                return _finish(
                    CopilotTurnResult(
                        ok=False,
                        tool_traces=traces,
                        error=CopilotError(
                            "tool_execution_failure",
                            result.error or "Tool execution failed",
                            {"tool_name": call.tool_name},
                        ),
                        provider=provider_name,
                        model=model_name,
                        stopped_reason="tool_execution_failure",
                    )
                )

            last_tool_name = call.tool_name
            last_tool_data = safe_data

            if tool.mutates_data:
                preview = result.data.get("preview") or (
                    changeset.preview() if changeset is not None else {}
                )
                message = (
                    "Proposed changes are ready for review. "
                    "A ChangeSet was created and has NOT been applied."
                )
                if isinstance(preview, dict) and preview.get("subject_renames"):
                    message += f" Subject renames: {preview.get('subject_renames')}"
                return _finish(
                    _attach_explanation(
                        CopilotTurnResult(
                            ok=True,
                            message=message,
                            tool_traces=traces,
                            changeset=changeset,
                            changeset_dict=result.data.get("changeset_dict")
                            or (changeset.to_dict() if changeset is not None else None),
                            provider=provider_name,
                            model=model_name,
                            stopped_reason="awaiting_approval",
                        ),
                        last_tool_name=last_tool_name,
                        last_tool_data=last_tool_data,
                    )
                )

            prior_results.append(
                {
                    "tool_name": call.tool_name,
                    "ok": True,
                    "data": safe_data,
                }
            )
            transcript.append(
                {
                    "role": "assistant",
                    "content": json.dumps(
                        {
                            "type": "tool_call",
                            "tool_name": call.tool_name,
                            "arguments": call.arguments,
                        },
                        ensure_ascii=False,
                    ),
                }
            )
            transcript.append(
                {
                    "role": "user",
                    "content": json.dumps(
                        {"type": "tool_result", "tool_name": call.tool_name, "data": safe_data},
                        ensure_ascii=False,
                        default=str,
                    ),
                }
            )

        return _finish(
            CopilotTurnResult(
                ok=False,
                message="Stopped after reaching the maximum number of tool calls.",
                tool_traces=traces,
                error=CopilotError(
                    "max_tool_calls",
                    f"Exceeded max_tool_calls={max_calls}",
                ),
                provider=provider_name,
                model=model_name,
                stopped_reason="max_tool_calls",
            )
        )

    def _persist_turn(
        self,
        *,
        turn_id: str,
        user_request: str,
        provider_name: str,
        model_name: str,
        model_responses: list[dict[str, Any]],
        tool_call_logs: list[dict[str, Any]],
        result: CopilotTurnResult,
    ) -> None:
        store = self.provenance_store
        if store is None:
            return
        try:
            record = build_turn_record(
                turn_id=turn_id,
                user_request=user_request,
                provider=provider_name,
                model=model_name,
                dataset_root=self.session.plan.dataset_root,
                plan_fingerprint=plan_fingerprint(self.session.plan),
                model_responses=model_responses,
                tool_calls=tool_call_logs,
                changeset=result.changeset,
                stopped_reason=result.stopped_reason,
                ok=result.ok,
                clarify=result.clarify,
                error=None if result.error is None else result.error.to_dict(),
                message=result.message,
            )
            store.append(record)
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("Failed to persist Copilot provenance turn: %s", exc)


def _attach_explanation(
    result: CopilotTurnResult,
    *,
    last_tool_name: str = "",
    last_tool_data: dict[str, Any] | None = None,
) -> CopilotTurnResult:
    """Stamp an auditable explanation onto a turn. Never auto-applies."""
    result.last_tool_data = last_tool_data
    result.explanation = explain_turn(
        traces=result.tool_traces,
        changeset=result.changeset,
        last_tool_name=last_tool_name,
        last_tool_data=last_tool_data,
    )
    if result.changeset is not None:
        stamp_changeset(result.changeset, result.tool_traces, result.explanation)
    return result


def _looks_like_absolute_path(value: str) -> bool:
    if value.startswith("/") and "/" in value[1:]:
        return True
    if len(value) > 2 and value[1] == ":" and value[0].isalpha():
        return True
    return False


def _sanitize_tool_data_for_llm(data: dict[str, Any]) -> dict[str, Any]:
    """Drop non-serializable / sensitive objects before re-feeding the LLM."""
    out: dict[str, Any] = {}
    for key, value in data.items():
        key_l = str(key).lower()
        if key == "changeset":
            continue
        if key_l in {"patientname", "patient_name", "api_key", "authorization"}:
            continue
        if key == "changeset_dict" and isinstance(value, dict):
            out[key] = {
                "id": value.get("id"),
                "status": value.get("status"),
                "tool_name": value.get("tool_name"),
                "preview": value.get("preview"),
            }
            continue
        if isinstance(value, str):
            out[key] = "[redacted_path]" if _looks_like_absolute_path(value) else value
        elif isinstance(value, (int, float, bool)) or value is None:
            out[key] = value
        elif isinstance(value, dict):
            out[key] = _sanitize_tool_data_for_llm(value)
        elif isinstance(value, list):
            cleaned: list[Any] = []
            for v in value:
                if hasattr(v, "apply"):
                    continue
                if isinstance(v, dict):
                    cleaned.append(_sanitize_tool_data_for_llm(v))
                elif isinstance(v, str) and _looks_like_absolute_path(v):
                    cleaned.append("[redacted_path]")
                else:
                    cleaned.append(v)
            out[key] = cleaned
        else:
            out[key] = str(type(value).__name__)
    return out
