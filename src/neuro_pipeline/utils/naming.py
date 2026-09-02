"""Smart filename engine driven by YAML naming rules."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml

from neuro_pipeline.utils.filesystem import sanitize_filename

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class NamingRule:
    """One pattern → output name mapping."""

    pattern: str
    name: str
    match: str = "contains"  # contains | exact | regex

    def matches(self, text: str) -> bool:
        needle = text.casefold()
        pattern = self.pattern.casefold()
        mode = self.match.casefold()
        if mode == "exact":
            return needle == pattern
        if mode == "regex":
            return re.search(self.pattern, text, flags=re.IGNORECASE) is not None
        return pattern in needle


class SmartFilenameEngine:
    """Map DICOM series descriptions onto short, researcher-friendly names."""

    def __init__(self, rules: Sequence[NamingRule] | None = None) -> None:
        self._rules: list[NamingRule] = list(rules or [])

    @classmethod
    def from_yaml(cls, path: Path) -> SmartFilenameEngine:
        """Load naming rules from a YAML file."""
        with path.open("r", encoding="utf-8") as handle:
            payload = yaml.safe_load(handle) or {}
        return cls.from_mapping(payload)

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> SmartFilenameEngine:
        """Build an engine from an in-memory rules document."""
        raw_rules = payload.get("rules", [])
        rules: list[NamingRule] = []
        for item in raw_rules:
            if not isinstance(item, Mapping):
                continue
            pattern = str(item.get("pattern", "")).strip()
            name = str(item.get("name", "")).strip()
            if not pattern or not name:
                continue
            rules.append(
                NamingRule(
                    pattern=pattern,
                    name=name,
                    match=str(item.get("match", "contains")).strip() or "contains",
                )
            )
        return cls(rules)

    @property
    def rules(self) -> list[NamingRule]:
        return list(self._rules)

    def resolve(self, *candidates: str) -> str:
        """Return the first matching smart name, else a sanitized original."""
        texts = [c.strip() for c in candidates if c and str(c).strip()]
        for text in texts:
            for rule in self._rules:
                if rule.matches(text):
                    LOGGER.debug("Naming rule %r matched %r → %s", rule.pattern, text, rule.name)
                    return sanitize_filename(rule.name)
        original = texts[0] if texts else "unnamed"
        return sanitize_filename(original)

    def apply_to_stem(self, series_description: str, protocol_name: str = "") -> str:
        """Convenience wrapper used by the converter after dcm2niix."""
        return self.resolve(series_description, protocol_name)
