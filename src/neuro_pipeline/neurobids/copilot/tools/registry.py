"""Tool registry — future LLM may only see registered tools."""

from __future__ import annotations

from typing import Any, Iterable

from neuro_pipeline.neurobids.copilot.session import CopilotSession
from neuro_pipeline.neurobids.copilot.tools.base import Tool, ToolResult, fail


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if not tool.name:
            raise ValueError("Tool must have a non-empty name")
        if tool.name in self._tools:
            raise ValueError(f"Tool already registered: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return sorted(self._tools)

    def list_schemas(self) -> list[dict[str, Any]]:
        return [self._tools[n].schema() for n in self.names()]

    def to_llm_tools(self) -> list[dict[str, Any]]:
        """Expose registered tools as LLM-compatible definitions (no internals).

        Mutating tools are described as ChangeSet-only (never auto-applied).
        """
        tools: list[dict[str, Any]] = []
        for name in self.names():
            tool = self._tools[name]
            description = tool.description or ""
            if tool.mutates_data and "ChangeSet" not in description:
                description = (
                    f"{description.rstrip()} "
                    "Creates a ChangeSet for user approval; does not apply changes."
                ).strip()
            tools.append(
                {
                    "name": tool.name,
                    "description": description,
                    "kind": tool.kind.value,
                    "mutates_data": tool.mutates_data,
                    "input_schema": dict(tool.input_schema or {}),
                }
            )
        return tools

    def execute(
        self,
        name: str,
        session: CopilotSession,
        params: dict[str, Any] | None = None,
    ) -> ToolResult:
        tool = self._tools.get(name)
        if tool is None:
            return fail(name, f"Unknown tool: {name}")
        try:
            return tool.execute(session, params or {})
        except Exception as exc:  # noqa: BLE001 — surface as tool failure
            return fail(name, str(exc))


def default_registry() -> ToolRegistry:
    """Build the standard NeuroBIDS Copilot tool set."""
    from neuro_pipeline.neurobids.copilot.tools.mutation import (
        ApplyEditTool,
        ExcludeAcquisitionsTool,
        IncludeAcquisitionsTool,
        RenameSessionsTool,
        RenameSubjectsTool,
    )
    from neuro_pipeline.neurobids.copilot.tools.audit import AuditDatasetTool
    from neuro_pipeline.neurobids.copilot.tools.explain import ExplainMappingTool
    from neuro_pipeline.neurobids.copilot.tools.planning import ProposeBidsMappingTool
    from neuro_pipeline.neurobids.copilot.tools.readonly import (
        FindAcquisitionsTool,
        InspectDatasetTool,
        InspectSubjectTool,
        ListSubjectsTool,
    )
    from neuro_pipeline.neurobids.copilot.tools.reasoning import (
        ClassifyAcquisitionsTool,
        ClassifyAcquisitionTool,
        InspectEntitiesTool,
        ListAmbiguousAcquisitionsTool,
        ListAnatomicalTool,
        ListDwiTool,
        ListFieldmapsTool,
        ListFunctionalTool,
        ListMultiechoTool,
        ListSbrefTool,
    )
    from neuro_pipeline.neurobids.copilot.tools.rules import (
        ApplyCurationRulesTool,
        InspectCurationRuleTool,
        ListCurationRulesTool,
        ProposeCurationRuleTool,
        SetCurationRuleEnabledTool,
    )

    registry = ToolRegistry()
    for tool in (
        InspectDatasetTool(),
        ListSubjectsTool(),
        InspectSubjectTool(),
        FindAcquisitionsTool(),
        ClassifyAcquisitionTool(),
        ClassifyAcquisitionsTool(),
        ListAnatomicalTool(),
        ListFunctionalTool(),
        ListDwiTool(),
        ListFieldmapsTool(),
        ListSbrefTool(),
        ListMultiechoTool(),
        InspectEntitiesTool(),
        ListAmbiguousAcquisitionsTool(),
        AuditDatasetTool(),
        ExplainMappingTool(),
        ProposeBidsMappingTool(),
        ListCurationRulesTool(),
        InspectCurationRuleTool(),
        ProposeCurationRuleTool(),
        ApplyCurationRulesTool(),
        SetCurationRuleEnabledTool(),
        RenameSubjectsTool(),
        RenameSessionsTool(),
        ExcludeAcquisitionsTool(),
        IncludeAcquisitionsTool(),
        ApplyEditTool(),
    ):
        registry.register(tool)
    return registry


def register_all(tools: Iterable[Tool]) -> ToolRegistry:
    registry = ToolRegistry()
    for tool in tools:
        registry.register(tool)
    return registry
