"""NeuroBIDS Copilot LLM adapter (provider-independent).

The rest of NeuroBIDS must not import a concrete vendor SDK.
Tools remain deterministic; the LLM only proposes structured tool calls.
"""

from neuro_pipeline.neurobids.copilot.llm.agent import CopilotAgent
from neuro_pipeline.neurobids.copilot.llm.client import CopilotLLMClient
from neuro_pipeline.neurobids.copilot.llm.config import LLMConfig
from neuro_pipeline.neurobids.copilot.llm.provider import (
    FakeLLMProvider,
    LLMProvider,
    LLMProviderError,
    UnavailableLLMProvider,
    build_provider_from_config,
)
from neuro_pipeline.neurobids.copilot.llm.schemas import (
    AssistantResponseType,
    CopilotError,
    CopilotTurnResult,
    StructuredAssistantResponse,
    ToolCallRequest,
    parse_assistant_payload,
)

__all__ = [
    "AssistantResponseType",
    "CopilotAgent",
    "CopilotError",
    "CopilotLLMClient",
    "CopilotTurnResult",
    "FakeLLMProvider",
    "LLMConfig",
    "LLMProvider",
    "LLMProviderError",
    "StructuredAssistantResponse",
    "ToolCallRequest",
    "UnavailableLLMProvider",
    "build_provider_from_config",
    "parse_assistant_payload",
]
