"""NeuroBIDS Copilot — deterministic tools + optional LLM adapter."""

from neuro_pipeline.neurobids.copilot.changeset import ChangeSet, ChangeSetStatus, PlanEdit
from neuro_pipeline.neurobids.copilot.llm import (
    CopilotAgent,
    CopilotError,
    CopilotLLMClient,
    CopilotTurnResult,
    FakeLLMProvider,
    LLMConfig,
    LLMProvider,
)
from neuro_pipeline.neurobids.copilot.session import CopilotSession
from neuro_pipeline.neurobids.copilot.tools.base import Tool, ToolKind, ToolResult
from neuro_pipeline.neurobids.copilot.tools.registry import ToolRegistry, default_registry

__all__ = [
    "ChangeSet",
    "ChangeSetStatus",
    "CopilotAgent",
    "CopilotError",
    "CopilotLLMClient",
    "CopilotSession",
    "CopilotTurnResult",
    "FakeLLMProvider",
    "LLMConfig",
    "LLMProvider",
    "PlanEdit",
    "Tool",
    "ToolKind",
    "ToolRegistry",
    "ToolResult",
    "default_registry",
]
