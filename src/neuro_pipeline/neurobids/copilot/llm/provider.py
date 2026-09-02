"""Provider-independent LLM interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Sequence

from neuro_pipeline.neurobids.copilot.llm.schemas import (
    StructuredAssistantResponse,
    parse_assistant_payload,
)


class LLMProviderError(RuntimeError):
    """Raised when a provider cannot complete a generation request."""

    def __init__(self, message: str, *, code: str = "provider_error") -> None:
        super().__init__(message)
        self.code = code


class LLMProvider(ABC):
    """Abstract LLM backend.

    Implementations must return structured JSON-compatible payloads that
    :func:`parse_assistant_payload` can normalize. Providers must never be
    given filesystem access or tool execution capabilities.
    """

    name: str = "base"

    @property
    def model(self) -> str:
        return ""

    @abstractmethod
    def generate(
        self,
        *,
        system: str,
        user_payload: str,
        tools: Sequence[dict[str, Any]],
        transcript: Sequence[dict[str, Any]] | None = None,
    ) -> StructuredAssistantResponse:
        """Produce one structured assistant response."""


class UnavailableLLMProvider(LLMProvider):
    """Default provider when no API key / backend is configured."""

    name = "none"

    def generate(
        self,
        *,
        system: str,
        user_payload: str,
        tools: Sequence[dict[str, Any]],
        transcript: Sequence[dict[str, Any]] | None = None,
    ) -> StructuredAssistantResponse:
        raise LLMProviderError(
            "No LLM provider configured. Set NEUROBIDS_LLM_PROVIDER "
            "(and credentials if required). NeuroBIDS tools remain usable without an LLM.",
            code="provider_unavailable",
        )


class FakeLLMProvider(LLMProvider):
    """Deterministic mock provider for unit tests."""

    name = "fake"

    def __init__(
        self,
        responses: Sequence[dict[str, Any] | StructuredAssistantResponse],
        *,
        model: str = "fake-model",
    ) -> None:
        self._responses = list(responses)
        self._model = model
        self._index = 0
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
        self.calls.append(
            {
                "system_len": len(system or ""),
                "user_payload": user_payload,
                "n_tools": len(list(tools)),
                "transcript_len": len(list(transcript or [])),
            }
        )
        if self._index >= len(self._responses):
            raise LLMProviderError("FakeLLMProvider has no more scripted responses", code="timeout")
        payload = self._responses[self._index]
        self._index += 1
        if isinstance(payload, StructuredAssistantResponse):
            return payload
        return parse_assistant_payload(payload)


def build_provider_from_config(config: Any) -> LLMProvider:
    """Factory: create a provider from :class:`LLMConfig` without importing GUI/conversion."""
    from neuro_pipeline.neurobids.copilot.llm.config import LLMConfig

    if not isinstance(config, LLMConfig):
        config = LLMConfig.from_env()
    provider = (config.provider or "none").lower()
    if provider in {"none", "off", "disabled", ""}:
        return UnavailableLLMProvider()
    if provider in {"fake", "mock"}:
        # Empty fake — tests should inject FakeLLMProvider explicitly.
        return FakeLLMProvider([], model=config.model or "fake-model")
    if provider in {"openai", "compatible"}:
        from neuro_pipeline.neurobids.copilot.llm.openai_compatible import OpenAICompatibleProvider

        return OpenAICompatibleProvider(config)
    raise LLMProviderError(
        f"Unsupported LLM provider: {provider!r}",
        code="unsupported_provider",
    )
