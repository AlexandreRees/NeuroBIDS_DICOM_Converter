"""LLM provider configuration (env-based; no hard-coded secrets)."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(slots=True)
class LLMConfig:
    """Provider settings for NeuroBIDS Copilot.

    NeuroBIDS remains fully usable when no API key is configured.
    Secrets must come from the environment — never from source files.
    """

    provider: str = "none"
    model: str = ""
    api_key: str = ""
    base_url: str = ""
    timeout_seconds: float = 60.0
    max_tool_calls: int = 5
    max_retries: int = 2
    retry_backoff_seconds: float = 0.5

    @property
    def is_configured(self) -> bool:
        if self.provider in {"", "none", "off", "disabled"}:
            return False
        if self.provider in {"fake", "mock"}:
            return True
        if self.provider in {"local"}:
            return True
        return bool(self.api_key)

    @property
    def uses_openai_compatible_http(self) -> bool:
        return self.provider in {"openai", "compatible", "azure", "local"}

    @classmethod
    def from_env(cls) -> LLMConfig:
        provider = (os.environ.get("NEUROBIDS_LLM_PROVIDER") or "none").strip().lower()
        model = (os.environ.get("NEUROBIDS_LLM_MODEL") or "").strip()
        api_key = (os.environ.get("NEUROBIDS_LLM_API_KEY") or "").strip()
        base_url = (os.environ.get("NEUROBIDS_LLM_BASE_URL") or "").strip()
        timeout_raw = (os.environ.get("NEUROBIDS_LLM_TIMEOUT") or "60").strip()
        max_calls_raw = (os.environ.get("NEUROBIDS_LLM_MAX_TOOL_CALLS") or "5").strip()
        retries_raw = (os.environ.get("NEUROBIDS_LLM_MAX_RETRIES") or "2").strip()
        backoff_raw = (os.environ.get("NEUROBIDS_LLM_RETRY_BACKOFF") or "0.5").strip()
        try:
            timeout = float(timeout_raw)
        except ValueError:
            timeout = 60.0
        try:
            max_calls = max(1, int(max_calls_raw))
        except ValueError:
            max_calls = 5
        try:
            max_retries = max(0, int(retries_raw))
        except ValueError:
            max_retries = 2
        try:
            backoff = max(0.0, float(backoff_raw))
        except ValueError:
            backoff = 0.5
        return cls(
            provider=provider,
            model=model,
            api_key=api_key,
            base_url=base_url
            or ("http://localhost:11434/v1" if provider == "local" else ""),
            timeout_seconds=timeout
            if os.environ.get("NEUROBIDS_LLM_TIMEOUT")
            else (300.0 if provider == "local" else timeout),
            max_tool_calls=max_calls,
            max_retries=max_retries,
            retry_backoff_seconds=backoff,
        )

    def apply_to_environ(self, *, include_api_key: bool = True) -> None:
        """Write non-secret (and optional secret) settings into the process env.

        Used by the Settings UI for the current session only. API keys are never
        written to disk by NeuroBIDS.
        """
        provider = (self.provider or "none").strip().lower() or "none"
        os.environ["NEUROBIDS_LLM_PROVIDER"] = provider
        if self.model:
            os.environ["NEUROBIDS_LLM_MODEL"] = self.model
        else:
            os.environ.pop("NEUROBIDS_LLM_MODEL", None)
        if self.base_url:
            os.environ["NEUROBIDS_LLM_BASE_URL"] = self.base_url
        elif provider == "local":
            os.environ["NEUROBIDS_LLM_BASE_URL"] = "http://localhost:11434/v1"
        else:
            os.environ.pop("NEUROBIDS_LLM_BASE_URL", None)
        if include_api_key:
            if self.api_key:
                os.environ["NEUROBIDS_LLM_API_KEY"] = self.api_key
            else:
                os.environ.pop("NEUROBIDS_LLM_API_KEY", None)

    @property
    def api_key_configured(self) -> bool:
        return bool(self.api_key)

    @property
    def provider_label(self) -> str:
        provider = (self.provider or "none").strip().lower()
        return {
            "none": "Disabled",
            "off": "Disabled",
            "disabled": "Disabled",
            "local": "Local AI (Ollama)",
            "openai": "OpenAI-compatible API",
            "compatible": "OpenAI-compatible API",
            "azure": "OpenAI-compatible API (Azure)",
        }.get(provider, provider or "Disabled")


def redact_secret(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "****"
    return value[:3] + "…" + value[-2:]


def scrub_secrets(text: str, *secrets: str) -> str:
    """Remove known secrets from an error/log string."""
    out = str(text or "")
    for secret in secrets:
        if secret and secret in out:
            out = out.replace(secret, redact_secret(secret))
    return out
