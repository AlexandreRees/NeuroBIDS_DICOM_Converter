"""Dataset-specific Curation Rules — structured data, never executable code.

A rule is a JSON-serializable record the deterministic engine interprets.
The LLM may *propose* field/op/value predicates from a whitelist; it never
evaluates expressions, Python, or shell.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping

ALLOWED_CONDITION_FIELDS = frozenset(
    {
        "series_description",
        "protocol_name",
        "sequence_type",
        "fine_sequence_type",
        "modality",
        "smart_name",
    }
)

ALLOWED_OPERATORS = frozenset(
    {
        "equals",
        "contains",
        "startswith",
        "endswith",
        "regex",
    }
)

ALLOWED_ACTION_FIELDS = frozenset(
    {
        "datatype",
        "suffix",
        "task",
        "run",
        "acquisition",
        "direction",
        "include_in_conversion",
    }
)

# Keys that would imply arbitrary code — rejected at parse time.
FORBIDDEN_PAYLOAD_KEYS = frozenset(
    {
        "code",
        "expr",
        "expression",
        "python",
        "script",
        "eval",
        "exec",
        "shell",
        "command",
        "lambda",
        "compile",
        "import",
    }
)

RULE_CATALOG_OPS = frozenset({"save", "replace", "enable", "disable"})

_MAX_REGEX_LEN = 200
_MAX_VALUE_LEN = 256


class CurationRuleError(ValueError):
    """Invalid or unsafe curation-rule payload."""


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _reject_forbidden_keys(payload: Mapping[str, Any], *, where: str) -> None:
    for key in payload:
        lowered = str(key).strip().lower()
        if lowered in FORBIDDEN_PAYLOAD_KEYS:
            raise CurationRuleError(
                f"Rejected {where} key {key!r}: curation rules cannot contain executable code."
            )


@dataclass(slots=True)
class RulePredicate:
    """One whitelist condition (field + operator + literal value)."""

    field: str
    op: str
    value: str

    def to_dict(self) -> dict[str, str]:
        return {"field": self.field, "op": self.op, "value": self.value}

    def summary(self) -> str:
        return f"{self.field} {self.op} {self.value!r}"

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> RulePredicate:
        if not isinstance(data, Mapping):
            raise CurationRuleError("Predicate must be an object.")
        _reject_forbidden_keys(data, where="predicate")
        field_name = str(data.get("field") or "").strip()
        op = str(data.get("op") or "").strip().lower()
        raw_value = data.get("value")
        if raw_value is None or isinstance(raw_value, (dict, list)):
            raise CurationRuleError("Predicate value must be a string or number.")
        value = str(raw_value)
        if field_name not in ALLOWED_CONDITION_FIELDS:
            raise CurationRuleError(
                f"Unsupported condition field {field_name!r}. "
                f"Allowed: {', '.join(sorted(ALLOWED_CONDITION_FIELDS))}."
            )
        if op not in ALLOWED_OPERATORS:
            raise CurationRuleError(
                f"Unsupported operator {op!r}. Allowed: {', '.join(sorted(ALLOWED_OPERATORS))}."
            )
        if len(value) > _MAX_VALUE_LEN:
            raise CurationRuleError("Predicate value exceeds maximum length.")
        if op == "regex" and len(value) > _MAX_REGEX_LEN:
            raise CurationRuleError("Regex predicate exceeds maximum length.")
        if not value and op != "equals":
            raise CurationRuleError("Predicate value is empty.")
        return cls(field=field_name, op=op, value=value)


@dataclass(slots=True)
class RuleCondition:
    """AND-set of predicates. An empty set matches nothing (fail-closed)."""

    all_of: list[RulePredicate] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"all_of": [p.to_dict() for p in self.all_of]}

    def summary(self) -> str:
        if not self.all_of:
            return "(no conditions — matches nothing)"
        return " AND ".join(p.summary() for p in self.all_of)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> RuleCondition:
        if data is None:
            return cls()
        if not isinstance(data, Mapping):
            raise CurationRuleError("Condition must be an object.")
        _reject_forbidden_keys(data, where="condition")
        raw = data.get("all_of")
        if raw is None:
            raise CurationRuleError("Condition requires 'all_of' (list of predicates).")
        if not isinstance(raw, list):
            raise CurationRuleError("condition.all_of must be a list.")
        return cls(all_of=[RulePredicate.from_dict(item) for item in raw])


@dataclass(slots=True)
class RuleAction:
    """Whitelist mapping applied to matching planned acquisitions."""

    mapping: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return dict(self.mapping)

    def to_edit_fields(self) -> dict[str, Any]:
        """kwargs suitable for ``BIDSConversionPlan.apply_edit``."""
        out: dict[str, Any] = {}
        for key, value in self.mapping.items():
            if key == "include_in_conversion":
                out[key] = bool(value)
            elif value is not None:
                out[key] = str(value).strip()
        return out

    def summary(self) -> str:
        if not self.mapping:
            return "(no action)"
        parts = []
        for key, value in sorted(self.mapping.items()):
            parts.append(f"{key}={value!r}")
        return ", ".join(parts)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> RuleAction:
        if data is None:
            return cls()
        if not isinstance(data, Mapping):
            raise CurationRuleError("Action must be an object.")
        _reject_forbidden_keys(data, where="action")
        mapping: dict[str, Any] = {}
        for key, value in data.items():
            name = str(key).strip()
            if name == "include":
                name = "include_in_conversion"
            if name not in ALLOWED_ACTION_FIELDS:
                raise CurationRuleError(
                    f"Unsupported action field {name!r}. "
                    f"Allowed: {', '.join(sorted(ALLOWED_ACTION_FIELDS))}."
                )
            if name == "include_in_conversion":
                if isinstance(value, str):
                    mapping[name] = value.strip().lower() in {"1", "true", "yes", "on"}
                else:
                    mapping[name] = bool(value)
            else:
                if value is None or isinstance(value, (dict, list)):
                    raise CurationRuleError(f"Action {name!r} must be a scalar.")
                text = str(value).strip()
                if len(text) > _MAX_VALUE_LEN:
                    raise CurationRuleError(f"Action {name!r} exceeds maximum length.")
                mapping[name] = text
        if not mapping:
            raise CurationRuleError("Action mapping is empty.")
        return cls(mapping=mapping)


@dataclass(slots=True)
class RuleProvenance:
    """How this rule was created (inspectable; no PHI)."""

    source: str = "user_decision"
    changeset_id: str = ""
    tool_name: str = ""
    approved_at: str = ""
    example_series_uids: list[str] = field(default_factory=list)
    decision_reason: str = ""
    dataset_id: str = ""
    superseded_version: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "changeset_id": self.changeset_id,
            "tool_name": self.tool_name,
            "approved_at": self.approved_at,
            "example_series_uids": list(self.example_series_uids),
            "decision_reason": self.decision_reason,
            "dataset_id": self.dataset_id,
            "superseded_version": self.superseded_version,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> RuleProvenance:
        if not data:
            return cls()
        _reject_forbidden_keys(data, where="provenance")
        source = str(data.get("source") or "user_decision").strip()
        if source not in {"user_decision", "copilot_proposal", "imported"}:
            source = "user_decision"
        superseded = data.get("superseded_version")
        uids = data.get("example_series_uids") or []
        if not isinstance(uids, list):
            uids = []
        return cls(
            source=source,
            changeset_id=str(data.get("changeset_id") or ""),
            tool_name=str(data.get("tool_name") or ""),
            approved_at=str(data.get("approved_at") or ""),
            example_series_uids=[str(u) for u in uids if str(u).strip()],
            decision_reason=str(data.get("decision_reason") or ""),
            dataset_id=str(data.get("dataset_id") or ""),
            superseded_version=int(superseded) if superseded is not None else None,
        )


@dataclass(slots=True)
class CurationRule:
    """One dataset-specific, inspectable, reversible curation rule."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    version: int = 1
    enabled: bool = True
    condition: RuleCondition = field(default_factory=RuleCondition)
    action: RuleAction = field(default_factory=RuleAction)
    evidence: list[str] = field(default_factory=list)
    confidence: float = 0.0
    provenance: RuleProvenance = field(default_factory=RuleProvenance)
    created_at: str = field(default_factory=_utcnow)
    updated_at: str = field(default_factory=_utcnow)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "version": int(self.version),
            "enabled": bool(self.enabled),
            "condition": self.condition.to_dict(),
            "action": self.action.to_dict(),
            "evidence": list(self.evidence),
            "confidence": round(float(self.confidence), 4),
            "provenance": self.provenance.to_dict(),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    def to_llm_dict(self) -> dict[str, Any]:
        """Compact inspectable summary (no executable payload)."""
        return {
            "id": self.id,
            "version": int(self.version),
            "enabled": bool(self.enabled),
            "condition": self.condition.summary(),
            "action": self.action.summary(),
            "confidence": round(float(self.confidence), 3),
            "evidence": list(self.evidence)[:8],
            "source": self.provenance.source,
        }

    def clone(self) -> CurationRule:
        return CurationRule.from_dict(self.to_dict())

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> CurationRule:
        if not isinstance(data, Mapping):
            raise CurationRuleError("Rule must be an object.")
        _reject_forbidden_keys(data, where="rule")
        rule_id = str(data.get("id") or "").strip() or str(uuid.uuid4())
        try:
            version = int(data.get("version") or 1)
        except (TypeError, ValueError) as exc:
            raise CurationRuleError("Rule version must be an integer.") from exc
        if version < 1:
            raise CurationRuleError("Rule version must be >= 1.")
        try:
            confidence = float(data.get("confidence") or 0.0)
        except (TypeError, ValueError) as exc:
            raise CurationRuleError("Rule confidence must be a number.") from exc
        confidence = max(0.0, min(1.0, confidence))
        evidence = data.get("evidence") or []
        if not isinstance(evidence, list):
            raise CurationRuleError("Rule evidence must be a list of strings.")
        return cls(
            id=rule_id,
            version=version,
            enabled=bool(data.get("enabled", True)),
            condition=RuleCondition.from_dict(data.get("condition")),
            action=RuleAction.from_dict(data.get("action")),
            evidence=[str(e) for e in evidence],
            confidence=confidence,
            provenance=RuleProvenance.from_dict(data.get("provenance")),
            created_at=str(data.get("created_at") or _utcnow()),
            updated_at=str(data.get("updated_at") or _utcnow()),
        )


__all__ = [
    "ALLOWED_ACTION_FIELDS",
    "ALLOWED_CONDITION_FIELDS",
    "ALLOWED_OPERATORS",
    "CurationRule",
    "CurationRuleError",
    "FORBIDDEN_PAYLOAD_KEYS",
    "RULE_CATALOG_OPS",
    "RuleAction",
    "RuleCondition",
    "RulePredicate",
    "RuleProvenance",
]
