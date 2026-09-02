"""Propose a CurationRule from an approved user decision (no LLM code)."""

from __future__ import annotations

from collections import Counter
from typing import Mapping, Sequence

from neuro_pipeline.bids.conversion_plan import PlannedAcquisition
from neuro_pipeline.models import DicomSeries
from neuro_pipeline.neurobids.copilot.changeset import ChangeSet, PlanEdit
from neuro_pipeline.neurobids.curation.engine import acquisition_facts, validate_rule
from neuro_pipeline.neurobids.curation.models import (
    ALLOWED_ACTION_FIELDS,
    CurationRule,
    CurationRuleError,
    RuleAction,
    RuleCondition,
    RulePredicate,
    RuleProvenance,
)

_FACT_PRIORITY = (
    "series_description",
    "protocol_name",
    "smart_name",
    "fine_sequence_type",
    "sequence_type",
    "modality",
)

_EDIT_TO_ACTION = {
    "include": "include_in_conversion",
    "include_in_conversion": "include_in_conversion",
    "datatype": "datatype",
    "suffix": "suffix",
    "task": "task",
    "run": "run",
    "acquisition": "acquisition",
    "direction": "direction",
}


def propose_rule_from_changeset(
    changeset: ChangeSet,
    *,
    items: Sequence[PlannedAcquisition],
    series_by_uid: Mapping[str, DicomSeries] | None = None,
    dataset_id: str = "",
    source: str = "copilot_proposal",
) -> CurationRule:
    """Generalize a reusable rule from an approved (or proposed) ChangeSet.

    Uses only whitelist fields. Never encodes series UIDs or subject identity
    into the condition.
    """
    if not changeset.edits:
        raise CurationRuleError("Cannot propose a rule from a ChangeSet with no mapping edits.")

    items_by_uid = {item.source_series_uid: item for item in items}
    series_map = dict(series_by_uid or {})
    action = _common_action(changeset.edits)
    if not action:
        raise CurationRuleError(
            "ChangeSet edits do not share a reusable mapping action "
            "(subject/session renames are not saved as curation rules)."
        )

    uids = sorted({e.series_uid for e in changeset.edits if e.series_uid in items_by_uid})
    if not uids:
        uids = sorted({e.series_uid for e in changeset.edits})
    facts_list = []
    for uid in uids:
        item = items_by_uid.get(uid)
        if item is None:
            continue
        facts_list.append(acquisition_facts(item, series_map.get(uid)))
    if not facts_list:
        raise CurationRuleError("No planned acquisitions available to generalize a condition.")

    predicates, evidence, confidence = _condition_from_facts(facts_list)
    if not predicates:
        raise CurationRuleError(
            "Could not generalize a safe condition from this decision. "
            "Provide an explicit series_description or protocol_name predicate."
        )

    evidence = [
        f"source_changeset={changeset.id}",
        f"source_tool={changeset.tool_name}",
        f"n_example_series={len(uids)}",
        *evidence,
        f"action={action.summary()}",
    ]
    if changeset.reason:
        evidence.append(f"reason={changeset.reason}")

    rule = CurationRule(
        enabled=True,
        condition=RuleCondition(all_of=predicates),
        action=action,
        evidence=evidence,
        confidence=confidence,
        provenance=RuleProvenance(
            source=source,
            changeset_id=changeset.id,
            tool_name=changeset.tool_name or "propose_curation_rule",
            example_series_uids=uids[:20],
            decision_reason=changeset.reason,
            dataset_id=dataset_id,
        ),
    )
    result = validate_rule(rule)
    if not result.ok:
        raise CurationRuleError(result.summary())
    return rule


def propose_rule_from_examples(
    *,
    items: Sequence[PlannedAcquisition],
    series_by_uid: Mapping[str, DicomSeries] | None = None,
    action: RuleAction,
    dataset_id: str = "",
    reason: str = "",
    source: str = "copilot_proposal",
) -> CurationRule:
    """Build a rule from example series plus an explicit mapping action."""
    if not items:
        raise CurationRuleError("At least one example acquisition is required.")
    series_map = dict(series_by_uid or {})
    facts_list = [acquisition_facts(item, series_map.get(item.source_series_uid)) for item in items]
    predicates, evidence, confidence = _condition_from_facts(facts_list)
    if not predicates:
        raise CurationRuleError("Could not generalize a condition from the example series.")
    uids = [item.source_series_uid for item in items]
    rule = CurationRule(
        enabled=True,
        condition=RuleCondition(all_of=predicates),
        action=action,
        evidence=[
            f"n_example_series={len(items)}",
            *evidence,
            f"action={action.summary()}",
        ]
        + ([f"reason={reason}"] if reason else []),
        confidence=confidence,
        provenance=RuleProvenance(
            source=source,
            tool_name="propose_curation_rule",
            example_series_uids=uids[:20],
            decision_reason=reason,
            dataset_id=dataset_id,
        ),
    )
    result = validate_rule(rule)
    if not result.ok:
        raise CurationRuleError(result.summary())
    return rule


def _common_action(edits: Sequence[PlanEdit]) -> RuleAction | None:
    """Intersect mapping-field edits that have the same after-value for every series."""
    by_field: dict[str, dict[str, Any]] = {}
    series_seen: set[str] = set()
    for edit in edits:
        action_key = _EDIT_TO_ACTION.get(edit.field)
        if action_key is None or action_key not in ALLOWED_ACTION_FIELDS:
            continue
        series_seen.add(edit.series_uid)
        by_field.setdefault(action_key, {})[edit.series_uid] = edit.after

    if not by_field or not series_seen:
        return None

    mapping: dict[str, Any] = {}
    for field_name, per_uid in by_field.items():
        values = {per_uid.get(uid) for uid in series_seen}
        # Only keep fields that were edited on every series to the same value
        if len(values) != 1:
            continue
        if not all(uid in per_uid for uid in series_seen):
            continue
        value = next(iter(values))
        if field_name == "include_in_conversion":
            mapping[field_name] = bool(value)
        else:
            mapping[field_name] = "" if value is None else str(value).strip()
    if not mapping:
        return None
    return RuleAction(mapping=mapping)


def _condition_from_facts(
    facts_list: Sequence[Mapping[str, str]],
) -> tuple[list[RulePredicate], list[str], float]:
    """Pick the most specific *shared* exact-match facts (fail closed if none)."""
    n = len(facts_list)
    evidence: list[str] = []
    predicates: list[RulePredicate] = []

    for field_name in _FACT_PRIORITY:
        values = [str(f.get(field_name, "") or "").strip() for f in facts_list]
        nonempty = [v for v in values if v]
        if len(nonempty) != n:
            continue
        lowered = {v.lower() for v in nonempty}
        if len(lowered) != 1:
            continue
        canonical = nonempty[0]
        if field_name == "sequence_type" and canonical.lower() in {"", "unknown"}:
            continue
        if field_name == "modality" and not predicates:
            # Modality-only (e.g. all MR) is too broad to be a safe rule.
            continue
        predicates.append(
            RulePredicate(field=field_name, op="equals", value=canonical)
        )
        counts = Counter(v.lower() for v in nonempty)
        evidence.append(f"shared {field_name}={canonical!r} (n={counts.most_common(1)[0][1]})")
        # Prefer a small specific set: description/protocol/smart_name is enough
        if field_name in {"series_description", "protocol_name", "smart_name"} and len(predicates) >= 1:
            # Keep additional sequence_type if it is also shared and informative
            continue

    # Drop modality if we already have a more specific predicate
    if any(p.field != "modality" for p in predicates):
        predicates = [p for p in predicates if p.field != "modality"]

    # Cap predicates to avoid overfitting (description + sequence is plenty)
    preferred = [p for p in predicates if p.field in {"series_description", "protocol_name", "smart_name"}]
    extra = [p for p in predicates if p.field in {"fine_sequence_type", "sequence_type"}]
    if preferred:
        chosen = preferred[:2] + extra[:1]
    else:
        chosen = predicates[:2]

    if not chosen:
        return [], evidence, 0.0

    fields = {p.field for p in chosen}
    if "series_description" in fields or "protocol_name" in fields or "smart_name" in fields:
        confidence = 0.9 if n >= 2 else 0.8
    elif "fine_sequence_type" in fields:
        confidence = 0.65
    elif "sequence_type" in fields:
        confidence = 0.5
    else:
        confidence = 0.35
    return chosen, evidence, confidence


__all__ = [
    "propose_rule_from_changeset",
    "propose_rule_from_examples",
]
