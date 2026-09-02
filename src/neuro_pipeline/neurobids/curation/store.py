"""Persist dataset-specific curation rules as inspectable JSON (not in DICOM)."""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from neuro_pipeline.config.paths import default_curation_rules_root
from neuro_pipeline.logging.privacy import safe_folder_label
from neuro_pipeline.neurobids.curation.models import CurationRule, CurationRuleError

LOGGER = logging.getLogger(__name__)


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()

STORE_FORMAT_VERSION = 1


def dataset_id_for(dataset_root: str | Path | None) -> str:
    """Stable, non-path identifier for a dataset (basename + short hash)."""
    raw = str(dataset_root or "").strip()
    label = safe_folder_label(raw) if raw else "unnamed"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]
    safe_label = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in label)[:48]
    return f"{safe_label}-{digest}"


def default_store_path(dataset_root: str | Path | None) -> Path:
    return default_curation_rules_root() / f"{dataset_id_for(dataset_root)}.json"


@dataclass(slots=True)
class CurationRuleStore:
    """In-memory catalog with JSON persistence, scoped to one dataset."""

    dataset_id: str
    path: Path
    rules: list[CurationRule] = field(default_factory=list)
    dataset_label: str = ""

    @classmethod
    def for_dataset(
        cls,
        dataset_root: str | Path | None,
        *,
        path: Path | str | None = None,
    ) -> CurationRuleStore:
        ds_id = dataset_id_for(dataset_root)
        target = Path(path) if path else default_store_path(dataset_root)
        store = cls(
            dataset_id=ds_id,
            path=target,
            dataset_label=safe_folder_label(dataset_root) if dataset_root else "",
        )
        store.load()
        return store

    def load(self) -> None:
        if not self.path.is_file():
            self.rules = []
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("Failed to load curation rules from %s: %s", self.path, exc)
            self.rules = []
            return
        if not isinstance(payload, dict):
            self.rules = []
            return
        file_ds = str(payload.get("dataset_id") or "")
        if file_ds and file_ds != self.dataset_id:
            LOGGER.warning(
                "Curation rules file dataset_id %s does not match %s; loading anyway.",
                file_ds,
                self.dataset_id,
            )
        raw_rules = payload.get("rules") or []
        rules: list[CurationRule] = []
        if isinstance(raw_rules, list):
            for entry in raw_rules:
                if not isinstance(entry, Mapping):
                    continue
                try:
                    rules.append(CurationRule.from_dict(entry))
                except CurationRuleError as exc:
                    LOGGER.warning("Skipping invalid curation rule: %s", exc)
        self.rules = rules

    def save(self) -> Path:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self.to_dict(), indent=2) + "\n",
            encoding="utf-8",
        )
        return self.path

    def to_dict(self) -> dict[str, Any]:
        return {
            "format_version": STORE_FORMAT_VERSION,
            "dataset_id": self.dataset_id,
            "dataset_label": self.dataset_label,
            "rules": [r.to_dict() for r in self.rules],
        }

    def snapshot(self) -> list[dict[str, Any]]:
        return [r.to_dict() for r in self.rules]

    def restore(self, snapshot: Sequence[Mapping[str, Any]]) -> None:
        rules: list[CurationRule] = []
        for entry in snapshot:
            rules.append(CurationRule.from_dict(entry))
        self.rules = rules
        self.save()

    def get(self, rule_id: str) -> CurationRule | None:
        for rule in self.rules:
            if rule.id == rule_id:
                return rule
        return None

    def enabled_rules(self) -> list[CurationRule]:
        return [r for r in self.rules if r.enabled]

    def upsert(self, rule: CurationRule, *, replace_id: str | None = None) -> CurationRule:
        """Insert or replace a rule. Increments version when replacing."""
        now = _utcnow()
        target_id = replace_id or rule.id
        existing = self.get(target_id)
        if existing is not None:
            stored = rule.clone()
            stored.id = existing.id
            stored.version = int(existing.version) + 1
            stored.created_at = existing.created_at
            stored.updated_at = now
            stored.provenance.superseded_version = existing.version
            self.rules = [stored if r.id == existing.id else r for r in self.rules]
            self.save()
            return stored
        stored = rule.clone()
        stored.created_at = stored.created_at or now
        stored.updated_at = now
        if stored.version < 1:
            stored.version = 1
        self.rules.append(stored)
        self.save()
        return stored

    def set_enabled(self, rule_id: str, enabled: bool) -> CurationRule:
        rule = self.get(rule_id)
        if rule is None:
            raise CurationRuleError(f"Unknown curation rule: {rule_id}")
        rule.enabled = bool(enabled)
        rule.updated_at = _utcnow()
        self.save()
        return rule

    def remove(self, rule_id: str) -> CurationRule | None:
        found = self.get(rule_id)
        if found is None:
            return None
        self.rules = [r for r in self.rules if r.id != rule_id]
        self.save()
        return found


__all__ = [
    "CurationRuleStore",
    "STORE_FORMAT_VERSION",
    "dataset_id_for",
    "default_store_path",
]
