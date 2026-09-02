"""Request-aware Fake LLM for interactive NeuroBIDS UI Preview/Demo Mode."""

from __future__ import annotations

import json
from typing import Any, Sequence

from neuro_pipeline.neurobids.copilot.llm.provider import LLMProvider
from neuro_pipeline.neurobids.copilot.llm.schemas import (
    AssistantResponseType,
    StructuredAssistantResponse,
    ToolCallRequest,
)
from neuro_pipeline.gui.preview.dataset import UID_002_01_LOC


class PreviewDemoProvider(LLMProvider):
    """Deterministic provider: NL → structured tool calls (no API key).

    Supports multi-step agent loops by answering from ``prior_tool_results``.
    """

    name = "preview_demo"

    def __init__(self, *, model: str = "preview-demo") -> None:
        self._model = model
        self.calls: list[dict[str, Any]] = []

    @property
    def model(self) -> str:
        return self._model

    def generate(
        self,
        *,
        system: str,
        user_payload: str,
        tools: Sequence[dict[str, Any]],
        transcript: Sequence[dict[str, Any]] | None = None,
    ) -> StructuredAssistantResponse:
        self.calls.append({"n_tools": len(list(tools)), "transcript_len": len(list(transcript or []))})
        try:
            payload = json.loads(user_payload)
        except json.JSONDecodeError:
            payload = {"user_request": user_payload}
        request = str(payload.get("user_request") or "").strip()
        req = request.lower()
        prior = list(payload.get("prior_tool_results") or [])

        if prior:
            return _message_from_prior(prior, request)

        if any(w in req for w in ("delete dicom", "shell", "python script", "dcm2niix")):
            return StructuredAssistantResponse(
                type=AssistantResponseType.MESSAGE,
                content=(
                    "I cannot run shell commands, delete files, or invoke dcm2niix. "
                    "I only use registered NeuroBIDS tools on the conversion plan."
                ),
            )

        if "rename" in req and ("sequential" in req or "001" in req or "subject" in req):
            return StructuredAssistantResponse(
                type=AssistantResponseType.TOOL_CALL,
                tool_call=ToolCallRequest(
                    tool_name="rename_subjects",
                    arguments={"mode": "sequential", "start": 1, "preserve_sessions": True},
                ),
            )

        if "exclude" in req and "localizer" in req:
            return StructuredAssistantResponse(
                type=AssistantResponseType.TOOL_CALL,
                tool_call=ToolCallRequest(
                    tool_name="exclude_acquisitions",
                    arguments={
                        "series_uids": [UID_002_01_LOC],
                        "reason": "preview demo exclude localizer",
                    },
                ),
            )

        if "functional" in req or "func" in req or "resting" in req:
            return StructuredAssistantResponse(
                type=AssistantResponseType.TOOL_CALL,
                tool_call=ToolCallRequest(
                    tool_name="find_acquisitions",
                    arguments={"datatype": "func"},
                ),
            )

        if "acquisition" in req or "show me all" in req:
            return StructuredAssistantResponse(
                type=AssistantResponseType.TOOL_CALL,
                tool_call=ToolCallRequest(tool_name="find_acquisitions", arguments={}),
            )

        if "session" in req or "list the subject" in req:
            return StructuredAssistantResponse(
                type=AssistantResponseType.TOOL_CALL,
                tool_call=ToolCallRequest(tool_name="list_subjects", arguments={}),
            )

        if "how many subject" in req or "subjects in" in req or "explain this dataset" in req:
            tool = "list_subjects" if "subject" in req else "inspect_dataset"
            return StructuredAssistantResponse(
                type=AssistantResponseType.TOOL_CALL,
                tool_call=ToolCallRequest(tool_name=tool, arguments={}),
            )

        if any(w in req for w in ("problem", "audit", "issue", "ambiguous", "review")):
            return StructuredAssistantResponse(
                type=AssistantResponseType.TOOL_CALL,
                tool_call=ToolCallRequest(tool_name="inspect_dataset", arguments={}),
            )

        if "rename" in req:
            return StructuredAssistantResponse(
                type=AssistantResponseType.CLARIFY,
                content=(
                    "Which naming strategy should I use? "
                    "For example: sequential IDs (sub-001…) while preserving sessions."
                ),
            )

        return StructuredAssistantResponse(
            type=AssistantResponseType.TOOL_CALL,
            tool_call=ToolCallRequest(tool_name="inspect_dataset", arguments={}),
        )


def _message_from_prior(prior: list[dict[str, Any]], request: str) -> StructuredAssistantResponse:
    last = prior[-1] if prior else {}
    data = last.get("data") or {}
    tool = str(last.get("tool_name") or "")
    if tool == "list_subjects":
        n = data.get("n_subjects")
        subjects = data.get("subjects") or []
        lines = []
        for s in subjects:
            sessions = ", ".join(s.get("session_ids") or []) or "(no session)"
            lines.append(f"- {s.get('subject_id')}: sessions [{sessions}], acq={s.get('n_acquisitions')}")
        body = "\n".join(lines) if lines else "(none)"
        return StructuredAssistantResponse(
            type=AssistantResponseType.MESSAGE,
            content=f"There are {n} subject(s) in the current plan:\n{body}",
        )
    if tool == "find_acquisitions":
        n = data.get("n_matches")
        rows = data.get("acquisitions") or []
        if not rows:
            return StructuredAssistantResponse(
                type=AssistantResponseType.MESSAGE,
                content="No acquisitions matched that filter in the current plan.",
            )
        sample = []
        for row in rows[:8]:
            bids = row.get("bids") if isinstance(row.get("bids"), dict) else {}
            datatype = (bids or {}).get("datatype") or row.get("datatype") or ""
            sample.append(
                f"- {row.get('subject_id')}/{row.get('session_id') or '—'} "
                f"{row.get('series_description') or row.get('series_uid')} → {datatype or '—'}"
            )
        return StructuredAssistantResponse(
            type=AssistantResponseType.MESSAGE,
            content=f"Found {n} acquisition(s):\n" + "\n".join(sample),
        )
    if tool == "inspect_dataset":
        summary = data.get("summary") or {}
        return StructuredAssistantResponse(
            type=AssistantResponseType.MESSAGE,
            content=(
                f"Dataset summary — subjects={summary.get('n_subjects')}, "
                f"acquisitions={summary.get('n_acquisitions')}, "
                f"issues={summary.get('n_metadata_issues')}, "
                f"validation_ok={summary.get('validation_ok')}."
            ),
        )
    return StructuredAssistantResponse(
        type=AssistantResponseType.MESSAGE,
        content=f"Tool `{tool}` completed. Ask another question or propose a ChangeSet.",
    )
