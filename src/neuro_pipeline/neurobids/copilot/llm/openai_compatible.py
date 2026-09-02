"""Optional OpenAI-compatible HTTP provider (no hard dependency on openai SDK)."""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Any, Sequence

from neuro_pipeline.neurobids.copilot.llm.config import LLMConfig, redact_secret
from neuro_pipeline.neurobids.copilot.llm.provider import LLMProvider, LLMProviderError
from neuro_pipeline.neurobids.copilot.llm.schemas import (
    StructuredAssistantResponse,
    parse_assistant_payload,
)

LOGGER = logging.getLogger(__name__)


class OpenAICompatibleProvider(LLMProvider):
    """Minimal Chat Completions client for OpenAI-compatible endpoints.

    Expects the model to return a JSON object in the assistant message content
    matching NeuroBIDS Copilot structured response schemas.
    """

    name = "openai_compatible"

    def __init__(self, config: LLMConfig) -> None:
        self._config = config
        if not config.api_key:
            raise LLMProviderError(
                "NEUROBIDS_LLM_API_KEY is required for OpenAI-compatible providers",
                code="provider_unavailable",
            )

    @property
    def model(self) -> str:
        return self._config.model or "gpt-4o-mini"

    def generate(
        self,
        *,
        system: str,
        user_payload: str,
        tools: Sequence[dict[str, Any]],
        transcript: Sequence[dict[str, Any]] | None = None,
    ) -> StructuredAssistantResponse:
        url = (self._config.base_url or "https://api.openai.com/v1").rstrip("/")
        if not url.endswith("/chat/completions"):
            url = f"{url}/chat/completions"

        messages: list[dict[str, str]] = [
            {"role": "system", "content": system},
            {"role": "user", "content": user_payload},
        ]
        for item in transcript or []:
            role = str(item.get("role") or "user")
            content = str(item.get("content") or "")
            if content:
                messages.append({"role": role, "content": content})

        body = {
            "model": self.model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": messages,
        }
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._config.api_key}",
            },
        )
        LOGGER.info(
            "neurobids_llm_request provider=%s model=%s key=%s",
            self.name,
            self.model,
            redact_secret(self._config.api_key),
        )
        try:
            with urllib.request.urlopen(req, timeout=self._config.timeout_seconds) as resp:
                raw = resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            raise LLMProviderError(
                f"LLM HTTP error: {exc.code}",
                code="provider_http_error",
            ) from exc
        except TimeoutError as exc:
            raise LLMProviderError("LLM request timed out", code="timeout") from exc
        except Exception as exc:  # noqa: BLE001
            raise LLMProviderError(f"LLM request failed: {exc}", code="provider_error") from exc

        try:
            parsed = json.loads(raw)
            content = parsed["choices"][0]["message"]["content"]
            payload = json.loads(content) if isinstance(content, str) else content
        except Exception as exc:  # noqa: BLE001
            raise LLMProviderError(
                "Malformed LLM provider response",
                code="malformed_response",
            ) from exc
        return parse_assistant_payload(payload)
