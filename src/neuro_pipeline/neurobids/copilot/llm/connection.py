"""Lightweight LLM provider connection probe (no tool execution)."""

from __future__ import annotations

import json
import logging
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable

from neuro_pipeline.neurobids.copilot.llm.config import LLMConfig, scrub_secrets
from neuro_pipeline.neurobids.copilot.llm.provider import LLMProviderError

LOGGER = logging.getLogger(__name__)

_DEFAULT_LOCAL = "http://localhost:11434/v1"


@dataclass(slots=True)
class ConnectionProbeResult:
    """Result of a non-blocking (worker) connection test."""

    status: str
    message: str

    @property
    def ok(self) -> bool:
        return self.status == "connected"


def _models_url(base_url: str) -> str:
    url = (base_url or "").rstrip("/")
    if not url:
        url = "https://api.openai.com/v1"
    if url.endswith("/models"):
        return url
    if url.endswith("/chat/completions"):
        url = url[: -len("/chat/completions")]
    return f"{url}/models"


def probe_llm_connection(
    config: LLMConfig,
    *,
    urlopen: Callable[..., Any] | None = None,
) -> ConnectionProbeResult:
    """Test that a provider endpoint is reachable without running Copilot tools.

    Status values:
      connected | provider_unavailable | model_unavailable |
      invalid_configuration | timeout
    """
    provider = (config.provider or "none").strip().lower()
    if provider in {"", "none", "off", "disabled"}:
        return ConnectionProbeResult(
            status="invalid_configuration",
            message="AI Copilot is not configured. Choose Local AI or an OpenAI-compatible API.",
        )
    if provider in {"fake", "mock"}:
        return ConnectionProbeResult(status="connected", message="Fake provider ready (tests only).")

    if provider not in {"local", "openai", "compatible", "azure"}:
        return ConnectionProbeResult(
            status="invalid_configuration",
            message=f"Unknown provider '{provider}'. Use none, local, openai, compatible, or azure.",
        )

    if provider != "local" and not (config.api_key or "").strip():
        return ConnectionProbeResult(
            status="invalid_configuration",
            message="API key is not configured for this remote provider.",
        )

    base = (config.base_url or "").strip() or (_DEFAULT_LOCAL if provider == "local" else "https://api.openai.com/v1")
    url = _models_url(base)
    headers = {"Accept": "application/json"}
    if config.api_key:
        headers["Authorization"] = f"Bearer {config.api_key}"

    opener = urlopen or urllib.request.urlopen
    req = urllib.request.Request(url, method="GET", headers=headers)
    timeout = min(float(config.timeout_seconds or 30.0), 30.0)
    try:
        with opener(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except (TimeoutError, socket.timeout):
        return ConnectionProbeResult(status="timeout", message="Connection timed out.")
    except urllib.error.HTTPError as exc:
        status = int(getattr(exc, "code", 0) or 0)
        if status in {401, 403}:
            return ConnectionProbeResult(
                status="invalid_configuration",
                message="Provider rejected the credentials (unauthorized).",
            )
        if status == 404:
            return ConnectionProbeResult(
                status="provider_unavailable",
                message="Provider endpoint was not found. Check the base URL.",
            )
        return ConnectionProbeResult(
            status="provider_unavailable",
            message=f"Provider returned HTTP {status}.",
        )
    except urllib.error.URLError as exc:
        reason = scrub_secrets(str(getattr(exc, "reason", exc)), config.api_key)
        if "timed out" in reason.lower():
            return ConnectionProbeResult(status="timeout", message="Connection timed out.")
        if provider == "local":
            return ConnectionProbeResult(
                status="provider_unavailable",
                message="Ollama is not available. Start Ollama locally, then test again.",
            )
        return ConnectionProbeResult(
            status="provider_unavailable",
            message=f"Provider unavailable: {reason}",
        )
    except Exception as exc:  # noqa: BLE001
        LOGGER.exception("LLM connection probe failed")
        msg = scrub_secrets(str(exc), config.api_key)
        return ConnectionProbeResult(status="provider_unavailable", message=msg)

    model = (config.model or "").strip()
    if not model:
        return ConnectionProbeResult(
            status="invalid_configuration",
            message="Connected to the provider, but no model name is set.",
        )

    # Optional model presence check when the payload lists models.
    try:
        payload = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        payload = {}
    names: set[str] = set()
    if isinstance(payload, dict):
        data = payload.get("data") or payload.get("models") or []
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    name = str(item.get("id") or item.get("name") or "").strip()
                    if name:
                        names.add(name)
                elif isinstance(item, str):
                    names.add(item.strip())
    if names and model not in names and not any(model.startswith(n) or n.startswith(model) for n in names):
        return ConnectionProbeResult(
            status="model_unavailable",
            message=f"Provider is reachable, but model '{model}' was not listed.",
        )

    where = "local Ollama" if provider == "local" else "remote API"
    return ConnectionProbeResult(
        status="connected",
        message=f"Connected to {where} (model: {model}).",
    )


def raise_if_unavailable(config: LLMConfig) -> None:
    """Raise LLMProviderError when configuration cannot support live calls."""
    if not config.is_configured:
        raise LLMProviderError(
            "No LLM provider configured.",
            code="provider_unavailable",
        )
