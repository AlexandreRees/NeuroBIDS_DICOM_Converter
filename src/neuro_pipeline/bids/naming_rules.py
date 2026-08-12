"""User-defined BIDS naming rules (optional layer above classification).

Priority when resolving entities for a conversion plan / inventory:

1. User-defined rules (this module)
2. Existing sequence classification / BIDS entity resolver
3. Default BIDS naming helpers

This module never modifies DICOM files and does not replace the classifier.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from neuro_pipeline.bids.naming import sanitize_bids_label
from neuro_pipeline.config.paths import default_bids_naming_rules_json
from neuro_pipeline.models import DicomSeries

LOGGER = logging.getLogger(__name__)

_LABEL_RE = re.compile(r"^[A-Za-z0-9]+$")
_ALLOWED_ACTIONS = frozenset(
    {"task", "datatype", "suffix", "run", "acquisition", "direction", "session", "subject"}
)
_ALLOWED_DATATYPES = frozenset({"anat", "func", "dwi", "fmap"})

# Condition keys: FieldName_operator
_CONDITION_OPS = ("contains", "equals", "startswith", "endswith", "regex", "matches")


@dataclass(slots=True)
class NamingRule:
    """One lab-defined BIDS naming rule."""

    name: str
    enabled: bool = True
    priority: int = 100
    conditions: dict[str, str] = field(default_factory=dict)
    actions: dict[str, str] = field(default_factory=dict)

    def condition_summary(self) -> str:
        if not self.conditions:
            return "(no conditions)"
        parts = [f"{k}={v}" for k, v in self.conditions.items()]
        return "; ".join(parts)

    def action_summary(self) -> str:
        if not self.actions:
            return "(no actions)"
        return "; ".join(f"{k}={v}" for k, v in self.actions.items())

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "enabled": self.enabled,
            "priority": int(self.priority),
            "conditions": dict(self.conditions),
            "actions": dict(self.actions),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> NamingRule:
        return cls(
            name=str(data.get("name") or "Unnamed rule"),
            enabled=bool(data.get("enabled", True)),
            priority=int(data.get("priority", 100)),
            conditions={str(k): str(v) for k, v in dict(data.get("conditions") or {}).items()},
            actions={str(k): str(v) for k, v in dict(data.get("actions") or {}).items()},
        )


@dataclass(slots=True)
class RuleValidationIssue:
    level: str  # error | warning
    message: str
    rule_name: str = ""


@dataclass(slots=True)
class RuleMatch:
    """Result of applying the highest-priority matching rule."""

    rule: NamingRule
    actions: dict[str, str]


@dataclass(slots=True)
class RuleValidationResult:
    ok: bool
    issues: list[RuleValidationIssue] = field(default_factory=list)

    def summary(self) -> str:
        if self.ok and not self.issues:
            return "Naming rules are valid."
        return "\n".join(f"{i.level.upper()}: {i.message}" for i in self.issues)


class SmartNamingRulesEngine:
    """Evaluate user naming rules against classified DICOM series metadata."""

    def __init__(self, rules: Sequence[NamingRule] | None = None) -> None:
        self.rules: list[NamingRule] = list(rules or [])

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    @staticmethod
    def default_path() -> Path:
        return default_bids_naming_rules_json()

    @classmethod
    def load(cls, path: Path | str | None = None) -> SmartNamingRulesEngine:
        target = Path(path) if path else cls.default_path()
        if not target.is_file():
            return cls([])
        try:
            data = json.loads(target.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("Failed to load naming rules from %s: %s", target, exc)
            return cls([])
        return cls.from_json_dict(data if isinstance(data, dict) else {})

    def save(self, path: Path | str | None = None) -> Path:
        target = Path(path) if path else self.default_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(self.to_json_dict(), indent=2) + "\n",
            encoding="utf-8",
        )
        return target

    def to_json_dict(self) -> dict[str, Any]:
        return {"version": 1, "rules": [r.to_dict() for r in self.rules]}

    @classmethod
    def from_json_dict(cls, data: Mapping[str, Any]) -> SmartNamingRulesEngine:
        raw = data.get("rules") if isinstance(data, Mapping) else None
        rules: list[NamingRule] = []
        if isinstance(raw, list):
            for entry in raw:
                if isinstance(entry, Mapping):
                    rules.append(NamingRule.from_dict(entry))
        return cls(rules)

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate(self) -> RuleValidationResult:
        issues: list[RuleValidationIssue] = []
        priorities: dict[int, list[str]] = {}
        names: dict[str, int] = {}
        for rule in self.rules:
            if not (rule.name or "").strip():
                issues.append(
                    RuleValidationIssue("error", "Rule name is required.", rule.name)
                )
            names[rule.name] = names.get(rule.name, 0) + 1
            priorities.setdefault(int(rule.priority), []).append(rule.name)
            if not rule.conditions:
                issues.append(
                    RuleValidationIssue(
                        "warning",
                        f"Rule {rule.name!r} has no conditions (matches nothing).",
                        rule.name,
                    )
                )
            for key, value in rule.conditions.items():
                field_name, op = _parse_condition_key(key)
                if not field_name or op not in _CONDITION_OPS:
                    issues.append(
                        RuleValidationIssue(
                            "error",
                            f"Invalid condition key {key!r} in rule {rule.name!r}. "
                            f"Use FieldName_contains|equals|startswith|endswith|regex.",
                            rule.name,
                        )
                    )
                if op == "regex":
                    try:
                        re.compile(str(value))
                    except re.error as exc:
                        issues.append(
                            RuleValidationIssue(
                                "error",
                                f"Invalid regex in rule {rule.name!r}: {exc}",
                                rule.name,
                            )
                        )
            if not rule.actions:
                issues.append(
                    RuleValidationIssue(
                        "error",
                        f"Rule {rule.name!r} has no actions.",
                        rule.name,
                    )
                )
            for action, value in rule.actions.items():
                if action not in _ALLOWED_ACTIONS:
                    issues.append(
                        RuleValidationIssue(
                            "error",
                            f"Unsupported action {action!r} in rule {rule.name!r}.",
                            rule.name,
                        )
                    )
                    continue
                raw = str(value).strip().removeprefix(f"{action}-")
                cleaned = sanitize_bids_label(raw, fallback="")
                if not cleaned or not _LABEL_RE.fullmatch(cleaned):
                    issues.append(
                        RuleValidationIssue(
                            "error",
                            f"Invalid BIDS {action} value {value!r} in rule {rule.name!r}.",
                            rule.name,
                        )
                    )
                if action == "datatype" and cleaned.lower() not in _ALLOWED_DATATYPES:
                    issues.append(
                        RuleValidationIssue(
                            "error",
                            f"Invalid datatype {value!r} in rule {rule.name!r}.",
                            rule.name,
                        )
                    )
        for name, count in names.items():
            if count > 1:
                issues.append(
                    RuleValidationIssue(
                        "warning",
                        f"Duplicate rule name {name!r} ({count} times).",
                        name,
                    )
                )
        for priority, rule_names in priorities.items():
            if len(rule_names) > 1:
                issues.append(
                    RuleValidationIssue(
                        "error",
                        f"Duplicate priority {priority}: {', '.join(rule_names)}.",
                        rule_names[0],
                    )
                )
        # Conflicting enabled rules: same conditions different actions — warn
        enabled = [r for r in self.rules if r.enabled]
        for i, a in enumerate(enabled):
            for b in enabled[i + 1 :]:
                if a.conditions == b.conditions and a.actions != b.actions:
                    issues.append(
                        RuleValidationIssue(
                            "warning",
                            f"Conflicting rules {a.name!r} and {b.name!r} share "
                            "identical conditions but different actions "
                            f"(priority {a.priority} vs {b.priority}).",
                            a.name,
                        )
                    )
        ok = not any(i.level == "error" for i in issues)
        return RuleValidationResult(ok=ok, issues=issues)

    # ------------------------------------------------------------------
    # Matching
    # ------------------------------------------------------------------

    def match(self, series: DicomSeries) -> RuleMatch | None:
        """Return the highest-priority (lowest number) enabled matching rule."""
        enabled = [r for r in self.rules if r.enabled]
        enabled.sort(key=lambda r: (int(r.priority), r.name))
        fields = _series_fields(series)
        for rule in enabled:
            if _conditions_match(rule.conditions, fields):
                actions = {
                    k: sanitize_bids_label(str(v), fallback=str(v))
                    for k, v in rule.actions.items()
                    if k in _ALLOWED_ACTIONS and v not in (None, "")
                }
                if actions.get("datatype"):
                    actions["datatype"] = actions["datatype"].lower()
                return RuleMatch(rule=rule, actions=actions)
        return None

    def apply_to_entities(
        self,
        series: DicomSeries,
        entities: Mapping[str, str],
    ) -> tuple[dict[str, str], str]:
        """Merge matched rule actions over ``entities``.

        Returns ``(merged_entities, rule_name_or_empty)``.
        """
        out = {k: str(v) for k, v in entities.items() if v not in (None, "")}
        match = self.match(series)
        if match is None:
            return out, ""
        out.update(match.actions)
        return out, match.rule.name


def _series_fields(series: DicomSeries) -> dict[str, str]:
    return {
        "ProtocolName": series.protocol_name or "",
        "SeriesDescription": series.series_description or "",
        "SequenceName": series.smart_name or "",
        "Modality": series.modality or "",
        "SequenceType": series.sequence_type or "",
        "FineSequenceType": series.fine_sequence_type or "",
        "PatientID": series.patient_id or "",
        "SmartName": series.smart_name or "",
    }


def _parse_condition_key(key: str) -> tuple[str, str]:
    text = str(key or "")
    for op in _CONDITION_OPS:
        suffix = f"_{op}"
        if text.endswith(suffix):
            return text[: -len(suffix)], op
    # shorthand: ProtocolName -> contains
    if text:
        return text, "contains"
    return "", ""


def _conditions_match(conditions: Mapping[str, str], fields: Mapping[str, str]) -> bool:
    if not conditions:
        return False
    for key, expected in conditions.items():
        field_name, op = _parse_condition_key(key)
        actual = str(fields.get(field_name, "") or "")
        needle = str(expected or "")
        if op == "contains":
            if needle.lower() not in actual.lower():
                return False
        elif op == "equals" or op == "matches":
            if actual.lower() != needle.lower():
                return False
        elif op == "startswith":
            if not actual.lower().startswith(needle.lower()):
                return False
        elif op == "endswith":
            if not actual.lower().endswith(needle.lower()):
                return False
        elif op == "regex":
            try:
                if not re.search(needle, actual, flags=re.IGNORECASE):
                    return False
            except re.error:
                return False
        else:
            return False
    return True
