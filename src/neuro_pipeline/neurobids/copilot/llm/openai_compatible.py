"""OpenAI-compatible HTTP provider (stdlib only; no openai SDK required)."""

from __future__ import annotations

import json
import logging
import socket
import time
import urllib.error
import urllib.request
from typing import Any, Callable, Sequence

from neuro_pipeline.neurobids.copilot.llm.config import LLMConfig, redact_secret, scrub_secrets
from neuro_pipeline.neurobids.copilot.llm.provider import LLMProvider, LLMProviderError
from neuro_pipeline.neurobids.copilot.llm.schemas import (
    StructuredAssistantResponse,
    parse_assistant_payload,
)

LOGGER = logging.getLogger(__name__)

# Transient upstream failures worth retrying.
_RETRYABLE_HTTP = {408, 429, 500, 502, 503, 504}
_DEFAULT_LOCAL_BASE_URL = "http://localhost:11434/v1"


def _extract_json_content(content: str) -> Any:
    """Parse JSON from model content, tolerating fences/preamble (common with Ollama)."""
    text = (content or "").strip()
    if not text:
        raise ValueError("empty content")
    # Strip Markdown fences if the model wrapped the JSON object.
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Thinking models (e.g. qwen3) may emit prose before the JSON object.
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        return json.loads(text[start : end + 1])
    raise ValueError("content is not valid JSON")


class OpenAICompatibleProvider(LLMProvider):
    """Chat Completions client for OpenAI-compatible endpoints.

    The model must return a JSON object in the assistant message content
    matching NeuroBIDS Copilot structured response schemas. The provider
    never executes tools, touches the filesystem, or applies ChangeSets.
    """

    name = "openai_compatible"

    def __init__(
        self,
        config: LLMConfig,
        *,
        urlopen: Callable[..., Any] | None = None,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        self._config = config
        provider = (config.provider or "").lower()
        if provider not in {"local"} and not config.api_key:
            raise LLMProviderError(
                "NEUROBIDS_LLM_API_KEY is required for OpenAI-compatible providers",
                code="provider_unavailable",
            )
        if provider == "local" and not (self._config.base_url or "").strip():
            # Ollama OpenAI-compatible default; override with NEUROBIDS_LLM_BASE_URL.
            self._config.base_url = _DEFAULT_LOCAL_BASE_URL
        self._urlopen = urlopen or urllib.request.urlopen
        self._sleep = sleep or time.sleep
        self.last_usage: dict[str, int] = {}
        self.last_raw_response: dict[str, Any] = {}
        if provider == "azure":
            self.name = "azure_openai_compatible"
        elif provider == "local":
            self.name = "local_openai_compatible"

    @property
    def model(self) -> str:
        return self._config.model or "gpt-4o-mini"

    def _endpoint(self) -> str:
        default = "https://api.openai.com/v1"
        url = (self._config.base_url or default).rstrip("/")
        if url.endswith("/chat/completions"):
            return url
        return f"{url}/chat/completions"

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self._config.api_key:
            headers["Authorization"] = f"Bearer {self._config.api_key}"
        return headers

    def _build_messages(
        self,
        *,
        system: str,
        user_payload: str,
        tools: Sequence[dict[str, Any]],
        transcript: Sequence[dict[str, Any]] | None,
    ) -> list[dict[str, str]]:
        tool_names = [str(t.get("name") or "") for t in tools if t.get("name")]
        system_full = (
            f"{system}\n\n"
            "You MUST reply with a single JSON object only "
            '(type=message|clarify|tool_call). '
            f"Allowed tool_name values: {tool_names}. "
            "Do not invent tools. Do not return Python, shell, or filesystem commands."
        )
        messages: list[dict[str, str]] = [
            {"role": "system", "content": system_full},
            {"role": "user", "content": user_payload},
        ]
        for item in transcript or []:
            role = str(item.get("role") or "user")
            content = str(item.get("content") or "")
            if content:
                messages.append({"role": role, "content": content})
        return messages

    def generate(
        self,
        *,
        system: str,
        user_payload: str,
        tools: Sequence[dict[str, Any]],
        transcript: Sequence[dict[str, Any]] | None = None,
    ) -> StructuredAssistantResponse:
        body = {
            "model": self.model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": self._build_messages(
                system=system,
                user_payload=user_payload,
                tools=tools,
                transcript=transcript,
            ),
        }
        payload_bytes = json.dumps(body).encode("utf-8")
        url = self._endpoint()
        LOGGER.info(
            "neurobids_llm_request provider=%s model=%s endpoint=%s key=%s retries=%s",
            self.name,
            self.model,
            url.split("?")[0],
            redact_secret(self._config.api_key),
            self._config.max_retries,
        )

        attempts = int(self._config.max_retries) + 1
        last_error: LLMProviderError | None = None
        for attempt in range(attempts):
            try:
                raw = self._post_once(url, payload_bytes)
                return self._parse_response(raw)
            except LLMProviderError as exc:
                last_error = exc
                if not self._should_retry(exc) or attempt >= attempts - 1:
                    raise
                delay = float(self._config.retry_backoff_seconds) * (2**attempt)
                LOGGER.warning(
                    "neurobids_llm_retry attempt=%s/%s code=%s delay=%.2fs",
                    attempt + 1,
                    attempts,
                    getattr(exc, "code", "provider_error"),
                    delay,
                )
                if delay > 0:
                    self._sleep(delay)
        assert last_error is not None
        raise last_error

    def _should_retry(self, exc: LLMProviderError) -> bool:
        code = getattr(exc, "code", "")
        if code in {"timeout", "provider_http_error", "provider_error"}:
            # HTTPError detail may encode status in message "LLM HTTP error: 429"
            msg = str(exc)
            for status in _RETRYABLE_HTTP:
                if str(status) in msg:
                    return True
            return code in {"timeout", "provider_error"}
        return False

    def _post_once(self, url: str, payload_bytes: bytes) -> str:
        req = urllib.request.Request(
            url,
            data=payload_bytes,
            method="POST",
            headers=self._headers(),
        )
        try:
            with self._urlopen(req, timeout=self._config.timeout_seconds) as resp:
                return resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            status = int(getattr(exc, "code", 0) or 0)
            # Never include response body (may echo secrets).
            raise LLMProviderError(
                f"LLM HTTP error: {status}",
                code="provider_http_error" if status in _RETRYABLE_HTTP or status >= 500 else "provider_http_error",
            ) from None
        except (TimeoutError, socket.timeout) as exc:
            raise LLMProviderError("LLM request timed out", code="timeout") from None
        except urllib.error.URLError as exc:
            reason = scrub_secrets(str(getattr(exc, "reason", exc)), self._config.api_key)
            # URLError reason sometimes wraps timeout
            if "timed out" in reason.lower() or "timeout" in reason.lower():
                raise LLMProviderError("LLM request timed out", code="timeout") from None
            raise LLMProviderError(
                f"LLM request failed: {reason}",
                code="provider_error",
            ) from None
        except Exception as exc:  # noqa: BLE001
            msg = scrub_secrets(str(exc), self._config.api_key)
            if "timed out" in msg.lower() or "timeout" in msg.lower():
                raise LLMProviderError("LLM request timed out", code="timeout") from None
            raise LLMProviderError(f"LLM request failed: {msg}", code="provider_error") from None

    def _parse_response(self, raw: str) -> StructuredAssistantResponse:
        self.last_usage = {}
        self.last_raw_response = {}
        try:
            parsed = json.loads(raw)
            self.last_raw_response = parsed if isinstance(parsed, dict) else {}
            usage = parsed.get("usage") if isinstance(parsed, dict) else None
            if isinstance(usage, dict):
                self.last_usage = {
                    "prompt_tokens": int(usage.get("prompt_tokens") or 0),
                    "completion_tokens": int(usage.get("completion_tokens") or 0),
                    "total_tokens": int(
                        usage.get("total_tokens")
                        or (
                            int(usage.get("prompt_tokens") or 0)
                            + int(usage.get("completion_tokens") or 0)
                        )
                    ),
                }
            content = parsed["choices"][0]["message"]["content"]
            if isinstance(content, list):
                # Some compatible APIs return content parts
                texts = [
                    str(part.get("text") or "")
                    for part in content
                    if isinstance(part, dict)
                ]
                content = "".join(texts)
            if not isinstance(content, str):
                payload = content
            else:
                payload = _extract_json_content(content)
        except Exception as exc:  # noqa: BLE001
            raise LLMProviderError(
                "Malformed LLM provider response",
                code="malformed_response",
            ) from None
        try:
            return parse_assistant_payload(payload)
        except ValueError as exc:
            raise LLMProviderError(
                scrub_secrets(f"Malformed LLM structured content: {exc}", self._config.api_key),
                code="malformed_response",
            ) from None
