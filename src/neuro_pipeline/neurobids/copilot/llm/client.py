"""Thin LLM client facade — delegates to :class:`CopilotAgent`."""

from __future__ import annotations

from neuro_pipeline.neurobids.copilot.llm.agent import CopilotAgent
from neuro_pipeline.neurobids.copilot.llm.config import LLMConfig
from neuro_pipeline.neurobids.copilot.llm.provider import LLMProvider
from neuro_pipeline.neurobids.copilot.llm.schemas import CopilotTurnResult
from neuro_pipeline.neurobids.copilot.session import CopilotSession
from neuro_pipeline.neurobids.copilot.tools.registry import ToolRegistry, default_registry


class CopilotLLMClient:
    """Provider-independent entry point for natural-language Copilot turns.

    Does not grant the LLM filesystem access, code execution, or ChangeSet.apply().
    """

    def __init__(
        self,
        session: CopilotSession,
        *,
        provider: LLMProvider | None = None,
        registry: ToolRegistry | None = None,
        config: LLMConfig | None = None,
        max_tool_calls: int | None = None,
    ) -> None:
        self.agent = CopilotAgent(
            session=session,
            registry=registry or default_registry(),
            provider=provider,
            config=config or LLMConfig.from_env(),
            max_tool_calls=max_tool_calls,
        )

    def handle(self, user_request: str) -> CopilotTurnResult:
        return self.agent.handle(user_request)
