"""Read-only explanation tool — auditable mapping evidence, no hidden CoT."""

from __future__ import annotations

from typing import Any, Mapping

from neuro_pipeline.neurobids.copilot.explain import explain_mapping
from neuro_pipeline.neurobids.copilot.session import CopilotSession
from neuro_pipeline.neurobids.copilot.tools.base import Tool, ToolKind, ToolResult, fail, ok


class ExplainMappingTool(Tool):
    name = "explain_mapping"
    description = (
        "Return an auditable explanation of a planned BIDS mapping: decision, "
        "evidence used, tools consulted, relevant metadata, confidence, and "
        "affected acquisitions. Read-only. Quotes tool/plan evidence only; "
        "never invents metadata or exposes hidden chain-of-thought."
    )
    kind = ToolKind.READ_ONLY
    input_schema = {
        "type": "object",
        "properties": {"series_uid": {"type": "string"}},
        "required": ["series_uid"],
        "additionalProperties": False,
    }
    output_schema = {"type": "object", "properties": {"explanation": {"type": "object"}}}

    def execute(self, session: CopilotSession, params: Mapping[str, Any] | None = None) -> ToolResult:
        uid = str((params or {}).get("series_uid") or "").strip()
        if not uid:
            uid = str((getattr(session, "ui_selection", None) or {}).get("series_uid") or "").strip()
        if not uid:
            return fail(self.name, "series_uid is required")
        try:
            expl = explain_mapping(session, uid)
        except KeyError:
            return fail(self.name, f"Unknown series_uid: {uid}")
        return ok(self.name, {"explanation": expl.to_dict()})
