"""Deterministic CurationRule engine — no eval, exec, or imported user code."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from neuro_pipeline.bids.conversion_plan import BIDSConversionPlan, PlannedAcquisition
from neuro_pipeline.models import DicomSeries
from neuro_pipeline.neurobids.curation.models import (
    CurationRule,
    RuleCondition,
    RulePredicate,
)

@dataclass(slots=True)
class RuleMatch:
    """One acquisition matched by an enabled rule."""

    rule: CurationRule
    series_uid: str
    fields: dict[str, Any]


@dataclass(slots=True)
class RuleValidationIssue:
    level: str  # error | warning
    message: str
    rule_id: str = ""


@dataclass(slots=True)
class RuleValidationResult:
    ok: bool
    issues: list[RuleValidationIssue] = field(default_factory=list)

    def summary(self) -> str:
        if self.ok and not self.issues:
            return "Curation rule is valid."
        return "\n".join(f"{i.level.upper()}: {i.message}" for i in self.issues)


def acquisition_facts(
    item: PlannedAcquisition,
    series: DicomSeries | None = None,
) -> dict[str, str]:
    """Metadata facts used for matching. Never includes PatientName or paths."""
    desc = (series.series_description if series else "") or item.source_series_description
    proto = (series.protocol_name if series else "") or item.source_protocol_name
    seq = (series.sequence_type if series else "") or item.source_sequence_type
    fine = (series.fine_sequence_type if series else "") or ""
    modality = (series.modality if series else "") or ""
    smart = (series.smart_name if series else "") or item.source_smart_name
    return {
        "series_description": str(desc or ""),
        "protocol_name": str(proto or ""),
        "sequence_type": str(seq or ""),
        "fine_sequence_type": str(fine or ""),
        "modality": str(modality or ""),
        "smart_name": str(smart or ""),
    }


def predicate_matches(predicate: RulePredicate, facts: Mapping[str, str]) -> bool:
    actual = str(facts.get(predicate.field, "") or "")
    needle = predicate.value
    op = predicate.op
    if op == "equals":
        return actual.lower() == needle.lower()
    if op == "contains":
        return needle.lower() in actual.lower()
    if op == "startswith":
        return actual.lower().startswith(needle.lower())
    if op == "endswith":
        return actual.lower().endswith(needle.lower())
    if op == "regex":
        try:
            compiled = re.compile(needle, flags=re.IGNORECASE)
        except re.error:
            return False
        return compiled.search(actual) is not None
    return False


def condition_matches(condition: RuleCondition, facts: Mapping[str, str]) -> bool:
    if not condition.all_of:
        return False
    return all(predicate_matches(p, facts) for p in condition.all_of)


def validate_rule(rule: CurationRule) -> RuleValidationResult:
    issues: list[RuleValidationIssue] = []
    if not rule.condition.all_of:
        issues.append(
            RuleValidationIssue("error", "Rule condition is empty (matches nothing).", rule.id)
        )
    for pred in rule.condition.all_of:
        if pred.op == "regex":
            try:
                re.compile(pred.value)
            except re.error as exc:
                issues.append(
                    RuleValidationIssue(
                        "error",
                        f"Invalid regex {pred.value!r}: {exc}",
                        rule.id,
                    )
                )
    if not rule.action.mapping:
        issues.append(RuleValidationIssue("error", "Rule action is empty.", rule.id))
    if not (0.0 <= float(rule.confidence) <= 1.0):
        issues.append(RuleValidationIssue("error", "Confidence must be between 0 and 1.", rule.id))
    datatype = str(rule.action.mapping.get("datatype") or "").strip().lower()
    if datatype and datatype not in {"anat", "func", "dwi", "fmap"}:
        issues.append(
            RuleValidationIssue(
                "warning",
                f"Datatype {datatype!r} is not a standard BIDS folder (anat/func/dwi/fmap).",
                rule.id,
            )
        )
    ok = not any(i.level == "error" for i in issues)
    return RuleValidationResult(ok=ok, issues=issues)


class CurationRuleEngine:
    """Match and propose plan edits from enabled rules (never mutates DICOM)."""

    def match_item(
        self,
        rules: Sequence[CurationRule],
        item: PlannedAcquisition,
        series: DicomSeries | None = None,
    ) -> CurationRule | None:
        """Return the first enabled matching rule (stable: created_at, id)."""
        facts = acquisition_facts(item, series)
        enabled = [r for r in rules if r.enabled]
        enabled.sort(key=lambda r: (r.created_at, r.id))
        for rule in enabled:
            if condition_matches(rule.condition, facts):
                return rule
        return None

    def collect_edits(
        self,
        plan: BIDSConversionPlan,
        rules: Sequence[CurationRule],
        series_by_uid: Mapping[str, DicomSeries] | None = None,
    ) -> tuple[list[tuple[str, dict[str, Any]]], list[RuleMatch], list[str]]:
        """Build ``(series_uid, apply_edit kwargs)`` for matching items.

        Does not apply anything. Skips no-op field sets. Warns on multi-match.
        """
        series_map = dict(series_by_uid or {})
        batches: list[tuple[str, dict[str, Any]]] = []
        matches: list[RuleMatch] = []
        warnings: list[str] = []
        enabled = [r for r in rules if r.enabled]
        if not enabled:
            return [], [], []

        for item in plan.items:
            uid = item.source_series_uid
            series = series_map.get(uid)
            facts = acquisition_facts(item, series)
            hits = [r for r in enabled if condition_matches(r.condition, facts)]
            if not hits:
                continue
            hits.sort(key=lambda r: (r.created_at, r.id))
            rule = hits[0]
            if len(hits) > 1:
                others = ", ".join(r.id[:8] for r in hits[1:])
                warnings.append(
                    f"Series {uid} matched {len(hits)} rules; using {rule.id[:8]} "
                    f"(ignored {others})."
                )
            fields = _non_noop_fields(item, rule.action.to_edit_fields())
            if not fields:
                continue
            batches.append((uid, fields))
            matches.append(RuleMatch(rule=rule, series_uid=uid, fields=fields))
        return batches, matches, warnings


def _non_noop_fields(item: PlannedAcquisition, fields: Mapping[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in fields.items():
        if key == "include_in_conversion":
            if bool(item.include_in_conversion) != bool(value):
                out[key] = bool(value)
            continue
        current = getattr(item, key, None)
        if str(current or "") != str(value or ""):
            out[key] = value
    return out


__all__ = [
    "CurationRuleEngine",
    "RuleMatch",
    "RuleValidationIssue",
    "RuleValidationResult",
    "acquisition_facts",
    "condition_matches",
    "predicate_matches",
    "validate_rule",
]
