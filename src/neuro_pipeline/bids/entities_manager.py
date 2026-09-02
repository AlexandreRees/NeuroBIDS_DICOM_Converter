"""Config-driven BIDS entity resolution from DICOM / JSON metadata."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

import yaml

from neuro_pipeline.config.paths import project_root, resource_root
from neuro_pipeline.utils.resources import resolve_config

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class ResolvedEntities:
    """Resolved BIDS datatype / entities for one series."""

    datatype: str = "unknown"
    suffix: str = "unknown"
    subject: str | None = None
    session: str | None = None
    task: str | None = None
    acquisition: str | None = None
    direction: str | None = None
    run: str | None = None
    matched_pattern: str | None = None
    extras: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, str]:
        out: dict[str, str] = {"datatype": self.datatype, "suffix": self.suffix}
        for key in ("subject", "session", "task", "acquisition", "direction", "run"):
            val = getattr(self, key)
            if val:
                out[key] = str(val)
        out.update(self.extras)
        return out


class BIDSEntityResolver:
    """Map protocol / sequence labels to BIDS entities via YAML rules."""

    def __init__(self, config_path: Path | str | None = None) -> None:
        self.config_path = Path(config_path) if config_path else self._default_config()
        self._rules = self._load(self.config_path)

    @staticmethod
    def _default_config() -> Path:
        return resolve_config("bids_entities.yaml")

    def _load(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            LOGGER.warning("BIDS entities config missing: %s", path)
            return {}
        with path.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
        return data if isinstance(data, dict) else {}

    def resolve(
        self,
        *,
        dicom_metadata: Mapping[str, Any] | None = None,
        json_metadata: Mapping[str, Any] | None = None,
        user_input: Mapping[str, Any] | None = None,
        probe_text: str | None = None,
    ) -> ResolvedEntities:
        """Resolve entities from metadata and optional user overrides."""
        dicom_metadata = dict(dicom_metadata or {})
        json_metadata = dict(json_metadata or {})
        user_input = dict(user_input or {})

        text = (probe_text or "").strip()
        if not text:
            for source in (json_metadata, dicom_metadata):
                for key in (
                    "ProtocolName",
                    "SeriesDescription",
                    "SequenceName",
                    "PulseSequenceName",
                ):
                    val = source.get(key)
                    if val:
                        text = str(val)
                        break
                if text:
                    break

        resolved = ResolvedEntities()
        match = self._match_patterns(text.lower() if text else "")
        if match is not None:
            entities, pattern = match
            resolved.matched_pattern = pattern
            resolved.datatype = str(entities.get("datatype") or resolved.datatype)
            resolved.suffix = str(entities.get("suffix") or resolved.suffix)
            for key in ("task", "acquisition", "direction", "run"):
                if entities.get(key):
                    setattr(resolved, key, str(entities[key]))
            for key, val in entities.items():
                if key not in {
                    "datatype",
                    "suffix",
                    "task",
                    "acquisition",
                    "direction",
                    "run",
                    "subject",
                    "session",
                }:
                    resolved.extras[str(key)] = str(val)

        # User overrides always win for identity / entity labels
        if user_input.get("subject"):
            resolved.subject = str(user_input["subject"])
        if user_input.get("session"):
            resolved.session = str(user_input["session"])
        if user_input.get("task"):
            resolved.task = str(user_input["task"])
        if user_input.get("acquisition"):
            resolved.acquisition = str(user_input["acquisition"])
        if user_input.get("direction"):
            resolved.direction = str(user_input["direction"])
        if user_input.get("run"):
            resolved.run = str(user_input["run"])
        if user_input.get("datatype"):
            resolved.datatype = str(user_input["datatype"])
        if user_input.get("suffix"):
            resolved.suffix = str(user_input["suffix"])

        return resolved

    def _match_patterns(self, text: str) -> tuple[dict[str, Any], str] | None:
        if not text:
            return None
        for _datatype, block in self._rules.items():
            if not isinstance(block, dict):
                continue
            patterns = block.get("patterns") or []
            if not isinstance(patterns, list):
                continue
            for entry in patterns:
                if not isinstance(entry, dict):
                    continue
                regex = str(entry.get("regex") or "")
                if not regex:
                    continue
                try:
                    if re.search(regex, text, flags=re.IGNORECASE):
                        entities = entry.get("entities") or {}
                        if isinstance(entities, dict):
                            return dict(entities), regex
                except re.error as exc:
                    LOGGER.warning("Invalid entity regex %r: %s", regex, exc)
        return None
