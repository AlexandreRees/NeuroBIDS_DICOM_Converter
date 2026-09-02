"""LLM request/response schemas for NeuroBIDS Copilot (provider-independent)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class AssistantResponseType(str, Enum):
    MESSAGE = "message"
    TOOL_CALL = "tool_call"
    CLARIFY = "clarify"
    ERROR = "error"


@dataclass(slots=True)
class ToolCallRequest:
    """Structured tool invocation produced by an LLM (never raw code)."""

    tool_name: str
    arguments: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": AssistantResponseType.TOOL_CALL.value,
            "tool_name": self.tool_name,
            "arguments": dict(self.arguments),
        }


@dataclass(slots=True)
class StructuredAssistantResponse:
    """Normalized assistant output from any LLMProvider."""

    type: AssistantResponseType
    content: str = ""
    tool_call: ToolCallRequest | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "type": self.type.value,
            "content": self.content,
        }
        if self.tool_call is not None:
            out["tool_call"] = self.tool_call.to_dict()
        return out


@dataclass(slots=True)
class CopilotError:
    """Structured Copilot failure (no secrets / no PHI)."""

    code: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "details": dict(self.details),
        }


@dataclass(slots=True)
class ToolCallTrace:
    """Privacy-safe provenance for one tool invocation."""

    tool_name: str
    arguments: dict[str, Any]
    ok: bool
    error: str = ""
    changeset_id: str = ""
    mutates_data: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class CopilotTurnResult:
    """Final result of one user request handled by :class:`CopilotAgent`."""

    ok: bool
    message: str = ""
    clarify: bool = False
    tool_traces: list[ToolCallTrace] = field(default_factory=list)
    changeset: Any | None = None  # ChangeSet | None
    changeset_dict: dict[str, Any] | None = None
    error: CopilotError | None = None
    provider: str = ""
    model: str = ""
    stopped_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "message": self.message,
            "clarify": self.clarify,
            "tool_traces": [t.to_dict() for t in self.tool_traces],
            "changeset": self.changeset_dict,
            "changeset_status": (
                None
                if self.changeset is None
                else getattr(getattr(self.changeset, "status", None), "value", None)
            ),
            "error": None if self.error is None else self.error.to_dict(),
            "provider": self.provider,
            "model": self.model,
            "stopped_reason": self.stopped_reason,
        }


def parse_assistant_payload(payload: Any) -> StructuredAssistantResponse:
    """Parse a provider payload into a structured response.

    Accepts either a dict or a JSON-compatible mapping. Raises ``ValueError``
    on malformed content (caught by the agent and wrapped as CopilotError).
    """
    if payload is None:
        raise ValueError("Empty LLM response")
    if not isinstance(payload, dict):
        raise ValueError(f"LLM response must be an object, got {type(payload).__name__}")

    raw_type = str(payload.get("type") or "").strip().lower()
    if raw_type in {"message", "text", "answer"}:
        content = str(payload.get("content") or payload.get("message") or "").strip()
        if not content:
            raise ValueError("message response requires non-empty content")
        return StructuredAssistantResponse(
            type=AssistantResponseType.MESSAGE,
            content=content,
            raw=dict(payload),
        )
    if raw_type in {"clarify", "clarification", "question"}:
        content = str(payload.get("content") or payload.get("question") or "").strip()
        if not content:
            raise ValueError("clarify response requires a question")
        return StructuredAssistantResponse(
            type=AssistantResponseType.CLARIFY,
            content=content,
            raw=dict(payload),
        )
    if raw_type in {"tool_call", "tool", "function_call"}:
        name = str(payload.get("tool_name") or payload.get("name") or "").strip()
        if not name:
            raise ValueError("tool_call requires tool_name")
        args = payload.get("arguments") or payload.get("args") or {}
        if not isinstance(args, dict):
            raise ValueError("tool_call arguments must be an object")
        return StructuredAssistantResponse(
            type=AssistantResponseType.TOOL_CALL,
            content=str(payload.get("content") or ""),
            tool_call=ToolCallRequest(tool_name=name, arguments=dict(args)),
            raw=dict(payload),
        )
    if raw_type in {"error"}:
        return StructuredAssistantResponse(
            type=AssistantResponseType.ERROR,
            content=str(payload.get("content") or payload.get("message") or "LLM error"),
            raw=dict(payload),
        )
    raise ValueError(f"Unsupported LLM response type: {raw_type!r}")
