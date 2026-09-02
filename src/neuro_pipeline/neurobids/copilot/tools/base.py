"""Tool interface for NeuroBIDS Copilot."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping

from neuro_pipeline.neurobids.copilot.session import CopilotSession


class ToolKind(str, Enum):
    READ_ONLY = "read_only"
    PLANNING = "planning"
    MUTATING = "mutating"


@dataclass(slots=True)
class ToolResult:
    """Deterministic tool output (never includes DICOM pixels)."""

    ok: bool
    tool_name: str
    data: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "tool": self.tool_name,
            "data": self.data,
            "error": self.error,
            "warnings": list(self.warnings),
        }


class Tool(ABC):
    """Typed, registered Copilot tool.

    Mutating tools return a ChangeSet and never modify DICOM or apply
    plan edits directly — application happens only via ChangeSet.apply()
    after explicit approval.
    """

    name: str = ""
    description: str = ""
    kind: ToolKind = ToolKind.READ_ONLY
    input_schema: dict[str, Any] = {}
    output_schema: dict[str, Any] = {}

    @property
    def mutates_data(self) -> bool:
        return self.kind == ToolKind.MUTATING

    def schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "kind": self.kind.value,
            "mutates_data": self.mutates_data,
            "input_schema": dict(self.input_schema),
            "output_schema": dict(self.output_schema),
        }

    @abstractmethod
    def execute(
        self,
        session: CopilotSession,
        params: Mapping[str, Any] | None = None,
    ) -> ToolResult:
        """Run the tool deterministically against ``session``."""


def fail(tool_name: str, message: str, *, warnings: list[str] | None = None) -> ToolResult:
    return ToolResult(ok=False, tool_name=tool_name, error=message, warnings=list(warnings or []))


def ok(
    tool_name: str,
    data: dict[str, Any],
    *,
    warnings: list[str] | None = None,
) -> ToolResult:
    return ToolResult(ok=True, tool_name=tool_name, data=data, warnings=list(warnings or []))
