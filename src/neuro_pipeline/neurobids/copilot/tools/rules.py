"""Curation-rule Copilot tools — propose/inspect/apply structured rules only."""

from __future__ import annotations

from typing import Any, Mapping

from neuro_pipeline.neurobids.copilot.changeset import ChangeSet, ChangeSetError
from neuro_pipeline.neurobids.copilot.session import CopilotSession
from neuro_pipeline.neurobids.copilot.tools.base import Tool, ToolKind, ToolResult, fail, ok
from neuro_pipeline.neurobids.copilot.tools.mutation import _changeset_result
from neuro_pipeline.neurobids.curation.engine import CurationRuleEngine, validate_rule
from neuro_pipeline.neurobids.curation.models import (
    ALLOWED_ACTION_FIELDS,
    ALLOWED_CONDITION_FIELDS,
    ALLOWED_OPERATORS,
    CurationRule,
    CurationRuleError,
    RuleAction,
    RuleCondition,
    RuleProvenance,
)
from neuro_pipeline.neurobids.curation.proposal import (
    propose_rule_from_changeset,
    propose_rule_from_examples,
)
from neuro_pipeline.neurobids.curation.store import dataset_id_for

_CONDITION_ITEM = {
    "type": "object",
    "properties": {
        "field": {"type": "string", "enum": sorted(ALLOWED_CONDITION_FIELDS)},
        "op": {"type": "string", "enum": sorted(ALLOWED_OPERATORS)},
        "value": {"type": "string"},
    },
    "required": ["field", "op", "value"],
    "additionalProperties": False,
}


class ListCurationRulesTool(Tool):
    name = "list_curation_rules"
    description = (
        "List dataset-specific curation rules (id, condition, action, enabled, "
        "confidence, version). Does not execute rules."
    )
    kind = ToolKind.READ_ONLY
    input_schema = {
        "type": "object",
        "properties": {"enabled_only": {"type": "boolean", "default": False}},
        "additionalProperties": False,
    }
    output_schema = {"type": "object", "properties": {"rules": {"type": "array"}}}

    def execute(self, session: CopilotSession, params: Mapping[str, Any] | None = None) -> ToolResult:
        params = dict(params or {})
        store = session.curation_store()
        rules = store.enabled_rules() if params.get("enabled_only") else list(store.rules)
        return ok(
            self.name,
            {
                "dataset_id": store.dataset_id,
                "n_rules": len(store.rules),
                "n_enabled": len(store.enabled_rules()),
                "rules": [r.to_llm_dict() for r in rules],
            },
        )


class InspectCurationRuleTool(Tool):
    name = "inspect_curation_rule"
    description = "Inspect one dataset curation rule, including evidence and provenance."
    kind = ToolKind.READ_ONLY
    input_schema = {
        "type": "object",
        "properties": {"rule_id": {"type": "string"}},
        "required": ["rule_id"],
        "additionalProperties": False,
    }
    output_schema = {"type": "object", "properties": {"rule": {"type": "object"}}}

    def execute(self, session: CopilotSession, params: Mapping[str, Any] | None = None) -> ToolResult:
        rule_id = str((params or {}).get("rule_id") or "").strip()
        if not rule_id:
            return fail(self.name, "rule_id is required")
        store = session.curation_store()
        rule = store.get(rule_id)
        if rule is None:
            # allow unique prefix
            matches = [r for r in store.rules if r.id.startswith(rule_id)]
            if len(matches) == 1:
                rule = matches[0]
            else:
                return fail(self.name, f"Unknown curation rule: {rule_id}")
        return ok(self.name, {"rule": rule.to_dict(), "summary": rule.to_llm_dict()})


class ProposeCurationRuleTool(Tool):
    name = "propose_curation_rule"
    description = (
        "Propose a dataset curation rule from an approved user decision "
        "(last applied ChangeSet), example series, or an explicit whitelist "
        "condition/action. Returns a ChangeSet; the rule is saved only after "
        "user approval. Never executes code."
    )
    kind = ToolKind.MUTATING
    input_schema = {
        "type": "object",
        "properties": {
            "from_approved_decision": {"type": "boolean", "default": True},
            "series_uids": {"type": "array", "items": {"type": "string"}},
            "condition": {
                "type": "object",
                "properties": {"all_of": {"type": "array", "items": _CONDITION_ITEM}},
                "required": ["all_of"],
                "additionalProperties": False,
            },
            "action": {
                "type": "object",
                "properties": {
                    "datatype": {"type": "string"},
                    "suffix": {"type": "string"},
                    "task": {"type": "string"},
                    "run": {"type": "string"},
                    "acquisition": {"type": "string"},
                    "direction": {"type": "string"},
                    "include_in_conversion": {"type": "boolean"},
                },
                "additionalProperties": False,
            },
            "enabled": {"type": "boolean", "default": True},
            "reason": {"type": "string"},
        },
        "additionalProperties": False,
    }
    output_schema = {"type": "object", "properties": {"changeset": {"type": "object"}}}

    def execute(self, session: CopilotSession, params: Mapping[str, Any] | None = None) -> ToolResult:
        params = dict(params or {})
        try:
            session.ensure_not_busy()
        except RuntimeError as exc:
            return fail(self.name, str(exc))

        reason = str(params.get("reason") or "propose_curation_rule")
        store = session.curation_store()
        dataset_id = store.dataset_id or dataset_id_for(session.plan.dataset_root)
        series_map = session.series_by_uid()

        try:
            rule = _build_proposed_rule(
                session,
                params,
                dataset_id=dataset_id,
                series_map=series_map,
            )
        except CurationRuleError as exc:
            return fail(self.name, str(exc))

        if "enabled" in params and params["enabled"] is not None:
            rule.enabled = bool(params["enabled"])
        rule.provenance.dataset_id = dataset_id
        rule.provenance.tool_name = self.name
        rule.provenance.decision_reason = reason or rule.provenance.decision_reason

        result = validate_rule(rule)
        if not result.ok:
            return fail(self.name, result.summary())
        warnings = [i.message for i in result.issues if i.level == "warning"]

        existing = _find_same_condition(store.rules, rule)
        operation = "replace" if existing is not None else "save"
        target_id = existing.id if existing is not None else rule.id
        if existing is not None:
            warnings.append(
                f"A rule with the same condition already exists ({existing.id[:8]}); "
                "approval will replace it and increment the version."
            )
            rule.id = existing.id

        engine = CurationRuleEngine()
        preview_batches, matches, match_warnings = engine.collect_edits(
            session.plan, [rule], series_by_uid=series_map
        )
        warnings.extend(match_warnings)

        try:
            changeset = ChangeSet.for_rule(
                session.plan,
                rule=rule,
                operation=operation,
                tool_name=self.name,
                reason=reason,
                edit_batches=preview_batches or None,
                warnings=warnings,
            )
            changeset.target_rule_id = target_id
        except ChangeSetError as exc:
            return fail(self.name, str(exc))

        result_obj = _changeset_result(self.name, changeset, warnings=warnings)
        result_obj.data["proposed_rule"] = rule.to_dict()
        result_obj.data["n_matching_acquisitions"] = len(matches)
        result_obj.data["rule_catalog_op"] = operation
        return result_obj


class ApplyCurationRulesTool(Tool):
    name = "apply_curation_rules"
    description = (
        "Propose applying enabled dataset curation rules to matching "
        "acquisitions. Returns a plan ChangeSet; does not apply and does not "
        "execute arbitrary code."
    )
    kind = ToolKind.MUTATING
    input_schema = {
        "type": "object",
        "properties": {
            "rule_id": {"type": "string"},
            "reason": {"type": "string"},
        },
        "additionalProperties": False,
    }
    output_schema = {"type": "object", "properties": {"changeset": {"type": "object"}}}

    def execute(self, session: CopilotSession, params: Mapping[str, Any] | None = None) -> ToolResult:
        params = dict(params or {})
        try:
            session.ensure_not_busy()
        except RuntimeError as exc:
            return fail(self.name, str(exc))

        store = session.curation_store()
        rule_id = str(params.get("rule_id") or "").strip()
        if rule_id:
            rule = store.get(rule_id)
            if rule is None:
                return fail(self.name, f"Unknown curation rule: {rule_id}")
            if not rule.enabled:
                return fail(self.name, f"Curation rule {rule_id} is disabled.")
            rules = [rule]
        else:
            rules = store.enabled_rules()
        if not rules:
            return fail(self.name, "No enabled curation rules on this dataset.")

        engine = CurationRuleEngine()
        batches, matches, warnings = engine.collect_edits(
            session.plan, rules, series_by_uid=session.series_by_uid()
        )
        if not batches:
            return fail(
                self.name,
                "Enabled rules match no acquisitions that need changes.",
                warnings=warnings,
            )
        reason = str(params.get("reason") or "apply_curation_rules")
        try:
            changeset = ChangeSet.from_edit_batches(
                session.plan,
                batches,
                tool_name=self.name,
                reason=reason,
                warnings=warnings,
            )
        except ChangeSetError as exc:
            return fail(self.name, str(exc))
        result_obj = _changeset_result(self.name, changeset, warnings=warnings)
        result_obj.data["matched_rules"] = sorted({m.rule.id for m in matches})
        result_obj.data["n_matching_acquisitions"] = len(matches)
        return result_obj


class SetCurationRuleEnabledTool(Tool):
    name = "set_curation_rule_enabled"
    description = (
        "Propose enabling or disabling a saved dataset curation rule. "
        "Returns a ChangeSet; the catalog change is saved only after approval."
    )
    kind = ToolKind.MUTATING
    input_schema = {
        "type": "object",
        "properties": {
            "rule_id": {"type": "string"},
            "enabled": {"type": "boolean"},
            "reason": {"type": "string"},
        },
        "required": ["rule_id", "enabled"],
        "additionalProperties": False,
    }
    output_schema = {"type": "object", "properties": {"changeset": {"type": "object"}}}

    def execute(self, session: CopilotSession, params: Mapping[str, Any] | None = None) -> ToolResult:
        params = dict(params or {})
        try:
            session.ensure_not_busy()
        except RuntimeError as exc:
            return fail(self.name, str(exc))
        rule_id = str(params.get("rule_id") or "").strip()
        if not rule_id:
            return fail(self.name, "rule_id is required")
        store = session.curation_store()
        rule = store.get(rule_id)
        if rule is None:
            return fail(self.name, f"Unknown curation rule: {rule_id}")
        enabled = bool(params.get("enabled"))
        if rule.enabled is enabled:
            return fail(self.name, f"Rule {rule_id} is already {'enabled' if enabled else 'disabled'}.")
        proposed = rule.clone()
        proposed.enabled = enabled
        op = "enable" if enabled else "disable"
        try:
            changeset = ChangeSet.for_rule(
                session.plan,
                rule=proposed,
                operation=op,
                tool_name=self.name,
                reason=str(params.get("reason") or op),
            )
            changeset.target_rule_id = rule.id
        except ChangeSetError as exc:
            return fail(self.name, str(exc))
        return _changeset_result(self.name, changeset)


def _build_proposed_rule(
    session: CopilotSession,
    params: Mapping[str, Any],
    *,
    dataset_id: str,
    series_map: Mapping[str, Any],
) -> CurationRule:
    explicit_condition = params.get("condition")
    explicit_action = params.get("action")
    from_decision = bool(params.get("from_approved_decision", True))
    uids = [str(u) for u in (params.get("series_uids") or []) if str(u).strip()]

    if explicit_condition is not None or explicit_action is not None:
        if explicit_condition is None or explicit_action is None:
            raise CurationRuleError("Explicit proposals require both condition and action.")
        rule = CurationRule(
            condition=RuleCondition.from_dict(explicit_condition),
            action=RuleAction.from_dict(explicit_action),
            evidence=["explicit_whitelist_payload"],
            confidence=0.6,
            provenance=RuleProvenance(source="copilot_proposal", dataset_id=dataset_id),
        )
        if uids:
            rule.provenance.example_series_uids = uids[:20]
            rule.evidence.append(f"n_example_series={len(uids)}")
        return rule

    last = getattr(session, "last_applied_changeset", None)
    if from_decision and isinstance(last, ChangeSet) and last.edits:
        return propose_rule_from_changeset(
            last,
            items=session.plan.items,
            series_by_uid=series_map,
            dataset_id=dataset_id,
            source="copilot_proposal",
        )

    if uids:
        items = []
        missing = []
        for uid in uids:
            item = session.plan.get(uid)
            if item is None:
                missing.append(uid)
            else:
                items.append(item)
        if missing:
            raise CurationRuleError(f"Unknown series_uids: {', '.join(missing)}")
        # Infer action from the current mapping of examples (must be shared)
        action = _shared_current_action(items)
        if action is None:
            raise CurationRuleError(
                "Example series do not share a reusable mapping action. "
                "Provide an explicit action object."
            )
        return propose_rule_from_examples(
            items=items,
            series_by_uid=series_map,
            action=action,
            dataset_id=dataset_id,
            reason=str(params.get("reason") or ""),
        )

    if from_decision:
        raise CurationRuleError(
            "No approved user decision is available. Apply a mapping ChangeSet first, "
            "or pass series_uids / an explicit condition and action."
        )
    raise CurationRuleError(
        "Cannot propose a rule without an approved decision, series_uids, "
        "or an explicit condition and action."
    )


def _shared_current_action(items: list) -> RuleAction | None:
    if not items:
        return None
    keys = ("datatype", "suffix", "task", "run", "acquisition", "direction", "include_in_conversion")
    mapping: dict[str, Any] = {}
    first = items[0]
    for key in keys:
        value = getattr(first, key)
        if all(getattr(item, key) == value for item in items):
            if key == "include_in_conversion":
                mapping[key] = bool(value)
            elif value not in (None, ""):
                mapping[key] = str(value)
    # A rule that only copies datatype+suffix+task from already-identical rows
    # is useful for new series; drop identity-only empty mapping
    useful = {
        k: v
        for k, v in mapping.items()
        if k in {"task", "run", "acquisition", "direction", "suffix", "datatype", "include_in_conversion"}
    }
    if not useful:
        return None
    try:
        return RuleAction.from_dict(useful)
    except CurationRuleError:
        return None


def _find_same_condition(rules: list[CurationRule], candidate: CurationRule) -> CurationRule | None:
    cand = candidate.condition.to_dict()
    for rule in rules:
        if rule.condition.to_dict() == cand:
            return rule
    return None
