"""LLM provider configuration (env-based; no hard-coded secrets)."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(slots=True)
class LLMConfig:
    """Provider settings for NeuroBIDS Copilot.

    NeuroBIDS remains fully usable when no API key is configured.
    """

    provider: str = "none"
    model: str = ""
    api_key: str = ""
    base_url: str = ""
    timeout_seconds: float = 60.0
    max_tool_calls: int = 5

    @property
    def is_configured(self) -> bool:
        if self.provider in {"", "none", "off", "disabled"}:
            return False
        if self.provider in {"fake", "mock"}:
            return True
        return bool(self.api_key) or self.provider in {"local"}

    @classmethod
    def from_env(cls) -> LLMConfig:
        provider = (os.environ.get("NEUROBIDS_LLM_PROVIDER") or "none").strip().lower()
        model = (os.environ.get("NEUROBIDS_LLM_MODEL") or "").strip()
        api_key = (os.environ.get("NEUROBIDS_LLM_API_KEY") or "").strip()
        base_url = (os.environ.get("NEUROBIDS_LLM_BASE_URL") or "").strip()
        timeout_raw = (os.environ.get("NEUROBIDS_LLM_TIMEOUT") or "60").strip()
        max_calls_raw = (os.environ.get("NEUROBIDS_LLM_MAX_TOOL_CALLS") or "5").strip()
        try:
            timeout = float(timeout_raw)
        except ValueError:
            timeout = 60.0
        try:
            max_calls = max(1, int(max_calls_raw))
        except ValueError:
            max_calls = 5
        return cls(
            provider=provider,
            model=model,
            api_key=api_key,
            base_url=base_url,
            timeout_seconds=timeout,
            max_tool_calls=max_calls,
        )


def redact_secret(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "****"
    return value[:3] + "…" + value[-2:]
