"""Transactional ChangeSet around an existing :class:`BIDSConversionPlan`."""

from __future__ import annotations

import copy
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from neuro_pipeline.bids.conversion_plan import (
    BIDSConversionPlan,
    PlanValidationIssue,
    PlanValidationResult,
)
from neuro_pipeline.neurobids.copilot.plan_ops import (
    apply_edits_to_plan,
    clone_plan,
    plan_fingerprint,
    snapshot_items,
)
from neuro_pipeline.neurobids.curation.engine import validate_rule
from neuro_pipeline.neurobids.curation.models import CurationRule, RULE_CATALOG_OPS


class ChangeSetStatus(str, Enum):
    DRAFT = "DRAFT"
    VALIDATED = "VALIDATED"
    APPROVED = "APPROVED"
    APPLIED = "APPLIED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"
    ROLLED_BACK = "ROLLED_BACK"


class ChangeSetError(RuntimeError):
    """Raised when a ChangeSet cannot be validated or applied safely."""


@dataclass(slots=True)
class PlanEdit:
    """One field-level change for a planned acquisition."""

    series_uid: str
    field: str
    before: Any
    after: Any

    def to_dict(self) -> dict[str, Any]:
        return {
            "series_uid": self.series_uid,
            "field": self.field,
            "before": self.before,
            "after": self.after,
        }


@dataclass(slots=True)
class ChangeSet:
    """Proposed modification to the in-memory BIDS conversion plan.

    Does not mutate DICOM files or the filesystem. Application updates only
    the existing :class:`BIDSConversionPlan` via ``apply_edit``.
    """

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    reason: str = ""
    tool_name: str = ""
    status: ChangeSetStatus = ChangeSetStatus.DRAFT
    reversible: bool = True
    plan_fingerprint: str = ""
    edits: list[PlanEdit] = field(default_factory=list)
    # series_uid → kwargs for BIDSConversionPlan.apply_edit
    edit_batches: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    before_snapshot: list[dict[str, Any]] = field(default_factory=list)
    after_snapshot: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    validation_result: PlanValidationResult | None = None
    affected_subjects: list[str] = field(default_factory=list)
    affected_sessions: list[str] = field(default_factory=list)
    affected_acquisitions: list[str] = field(default_factory=list)
    # Auditable explanation provenance (optional; never required to apply).
    evidence: list[str] = field(default_factory=list)
    tools_consulted: list[str] = field(default_factory=list)
    confidence: float | None = None
    # Optional dataset curation rule persisted only after user approval.
    rule_catalog_op: str = ""  # save | replace | enable | disable | ""
    proposed_rule: CurationRule | None = None
    target_rule_id: str = ""
    # Internal rollback snapshot (cloned PlannedAcquisition list)
    _rollback_items: list[Any] = field(default_factory=list, repr=False)
    _applied_fingerprint: str = field(default="", repr=False)
    _rule_rollback: list[dict[str, Any]] = field(default_factory=list, repr=False)
    _rule_applied: bool = field(default=False, repr=False)

    # ------------------------------------------------------------------
    # Construction helpers
    # ------------------------------------------------------------------

    @classmethod
    def from_edit_batches(
        cls,
        plan: BIDSConversionPlan,
        edit_batches: list[tuple[str, dict[str, Any]]],
        *,
        tool_name: str,
        reason: str = "",
        warnings: list[str] | None = None,
        proposed_rule: CurationRule | None = None,
        rule_catalog_op: str = "",
    ) -> ChangeSet:
        """Build a DRAFT ChangeSet by simulating edits on a cloned plan."""
        if not edit_batches:
            raise ChangeSetError("ChangeSet requires at least one edit.")

        before = snapshot_items(plan)
        fp = plan_fingerprint(plan)
        simulated = clone_plan(plan)
        apply_edits_to_plan(simulated, edit_batches, refresh=True)
        after = snapshot_items(simulated)

        field_edits = _diff_snapshots(before, after)
        if not field_edits:
            raise ChangeSetError("Proposed edits produce no plan differences.")

        subjects: set[str] = set()
        sessions: set[str] = set()
        acqs: set[str] = set()
        for edit in field_edits:
            acqs.add(edit.series_uid)
            item = simulated.get(edit.series_uid)
            if item is not None:
                if item.subject:
                    subjects.add(item.subject)
                if item.session:
                    sessions.add(item.session)
            # Also record before subjects when renaming subjects
            for snap in before:
                if snap.get("series_uid") == edit.series_uid and snap.get("subject"):
                    subjects.add(str(snap["subject"]))

        return cls(
            reason=reason,
            tool_name=tool_name,
            status=ChangeSetStatus.DRAFT,
            plan_fingerprint=fp,
            edits=field_edits,
            edit_batches=copy.deepcopy(edit_batches),
            before_snapshot=before,
            after_snapshot=after,
            warnings=list(warnings or []),
            affected_subjects=sorted(subjects),
            affected_sessions=sorted(sessions),
            affected_acquisitions=sorted(acqs),
            proposed_rule=proposed_rule,
            rule_catalog_op=str(rule_catalog_op or "").strip().lower(),
            target_rule_id=(proposed_rule.id if proposed_rule is not None else ""),
            _rollback_items=[item.clone() for item in plan.items],
        )

    @classmethod
    def for_rule(
        cls,
        plan: BIDSConversionPlan,
        *,
        rule: CurationRule,
        operation: str,
        tool_name: str,
        reason: str = "",
        edit_batches: list[tuple[str, dict[str, Any]]] | None = None,
        warnings: list[str] | None = None,
    ) -> ChangeSet:
        """Build a ChangeSet that persists a catalog rule after approval.

        Optional ``edit_batches`` apply the mapping first (decision → plan),
        then save the rule. Catalog-only operations have no plan edits.
        """
        op = str(operation or "").strip().lower()
        if op not in RULE_CATALOG_OPS:
            raise ChangeSetError(
                f"Unsupported rule catalog operation {operation!r}. "
                f"Allowed: {', '.join(sorted(RULE_CATALOG_OPS))}."
            )
        batches = list(edit_batches or [])
        if batches:
            cs = cls.from_edit_batches(
                plan,
                batches,
                tool_name=tool_name,
                reason=reason,
                warnings=warnings,
                proposed_rule=rule,
                rule_catalog_op=op,
            )
            cs.evidence = list(rule.evidence)
            cs.confidence = float(rule.confidence)
            return cs
        before = snapshot_items(plan)
        return cls(
            reason=reason,
            tool_name=tool_name,
            status=ChangeSetStatus.DRAFT,
            plan_fingerprint=plan_fingerprint(plan),
            edits=[],
            edit_batches=[],
            before_snapshot=before,
            after_snapshot=before,
            warnings=list(warnings or []),
            evidence=list(rule.evidence),
            confidence=float(rule.confidence),
            proposed_rule=rule,
            rule_catalog_op=op,
            target_rule_id=rule.id,
            _rollback_items=[item.clone() for item in plan.items],
        )

    # ------------------------------------------------------------------
    # API
    # ------------------------------------------------------------------

    def preview(self) -> dict[str, Any]:
        """Human-readable structured representation of proposed changes."""
        subject_renames: dict[str, str] = {}
        session_renames: dict[str, str] = {}
        include_changes: list[dict[str, Any]] = []
        entity_changes: list[dict[str, Any]] = []

        before_by_uid = {s["series_uid"]: s for s in self.before_snapshot}
        after_by_uid = {s["series_uid"]: s for s in self.after_snapshot}

        for uid in sorted(set(before_by_uid) | set(after_by_uid)):
            b = before_by_uid.get(uid, {})
            a = after_by_uid.get(uid, {})
            if b.get("subject") != a.get("subject"):
                subject_renames[str(b.get("subject"))] = str(a.get("subject"))
            b_ses = f"{b.get('subject')}/{b.get('session')}"
            a_ses = f"{a.get('subject')}/{a.get('session')}"
            if b.get("session") != a.get("session") or b.get("subject") != a.get("subject"):
                if b.get("session") or a.get("session"):
                    session_renames[b_ses] = a_ses
            if b.get("include") != a.get("include"):
                include_changes.append(
                    {
                        "series_uid": uid,
                        "before": b.get("include"),
                        "after": a.get("include"),
                        "filename_after": a.get("intended_filename"),
                    }
                )
            for key in ("datatype", "suffix", "task", "run", "acquisition", "direction"):
                if b.get(key) != a.get(key):
                    entity_changes.append(
                        {
                            "series_uid": uid,
                            "field": key,
                            "before": b.get(key),
                            "after": a.get(key),
                        }
                    )

        return {
            "id": self.id,
            "status": self.status.value,
            "tool": self.tool_name,
            "reason": self.reason,
            "created_at": self.created_at,
            "reversible": self.reversible,
            "warnings": list(self.warnings),
            "affected": {
                "subjects": list(self.affected_subjects),
                "sessions": list(self.affected_sessions),
                "acquisitions": list(self.affected_acquisitions),
            },
            "subject_renames": subject_renames,
            "session_renames": session_renames,
            "include_changes": include_changes,
            "entity_changes": entity_changes,
            "edits": [e.to_dict() for e in self.edits],
            "validation": None
            if self.validation_result is None
            else {
                "ok": self.validation_result.ok,
                "errors": len(self.validation_result.errors),
                "warnings": len(self.validation_result.warnings),
                "summary": self.validation_result.summary(),
            },
            "rule": None if self.proposed_rule is None else self.proposed_rule.to_llm_dict(),
            "rule_catalog_op": self.rule_catalog_op or None,
        }

    def validate(
        self,
        plan: BIDSConversionPlan,
        *,
        conversion_busy: bool = False,
        rule_store: Any | None = None,
    ) -> PlanValidationResult:
        """Validate proposed edits / rule on a clone without applying them."""
        self._assert_can_operate(plan, conversion_busy=conversion_busy, require_draftish=True)
        self._validate_rule_payload(rule_store=rule_store)
        if self.edit_batches:
            simulated = clone_plan(plan)
            apply_edits_to_plan(simulated, self.edit_batches, refresh=True)
            result = simulated.validate()
        else:
            result = PlanValidationResult(ok=True, issues=[])
        self.validation_result = result
        self.status = ChangeSetStatus.VALIDATED
        if result.errors:
            self.warnings.append(
                f"Plan validation reported {len(result.errors)} error(s); "
                "review before approval (NIfTI conversion may still be allowed by the app)."
            )
        return result

    def apply(
        self,
        plan: BIDSConversionPlan,
        *,
        conversion_busy: bool = False,
        require_validated: bool = True,
        rule_store: Any | None = None,
    ) -> None:
        """Apply plan edits and/or persist a proposed rule. Never touches DICOM."""
        if conversion_busy:
            self.status = ChangeSetStatus.FAILED
            raise ChangeSetError("Cannot apply ChangeSet while conversion is running.")
        if self.status == ChangeSetStatus.APPLIED:
            raise ChangeSetError("ChangeSet already applied.")
        if self.status in {ChangeSetStatus.REJECTED, ChangeSetStatus.FAILED}:
            raise ChangeSetError(f"Cannot apply ChangeSet in status {self.status.value}.")
        if require_validated and self.status not in {
            ChangeSetStatus.VALIDATED,
            ChangeSetStatus.APPROVED,
        }:
            self.validate(plan, conversion_busy=False, rule_store=rule_store)
        current_fp = plan_fingerprint(plan)
        if current_fp != self.plan_fingerprint:
            self.status = ChangeSetStatus.FAILED
            raise ChangeSetError(
                "Stale ChangeSet: the BIDS conversion plan changed since this "
                "ChangeSet was created. Regenerate the ChangeSet."
            )
        self._rollback_items = [item.clone() for item in plan.items]
        if self.rule_catalog_op:
            if rule_store is None:
                self.status = ChangeSetStatus.FAILED
                raise ChangeSetError("Rule catalog operation requires a CurationRuleStore.")
            self._rule_rollback = rule_store.snapshot()
        try:
            if self.edit_batches:
                apply_edits_to_plan(plan, self.edit_batches, refresh=True)
            if self.rule_catalog_op:
                self._apply_rule_catalog(rule_store)
                self._rule_applied = True
        except Exception as exc:  # noqa: BLE001
            if self.edit_batches:
                plan.items = [item.clone() for item in self._rollback_items]
                plan._validated = False
                plan.refresh_filenames()
            if self._rule_rollback and rule_store is not None and self._rule_applied:
                rule_store.restore(self._rule_rollback)
                self._rule_applied = False
            self.status = ChangeSetStatus.FAILED
            raise ChangeSetError(f"Failed to apply ChangeSet: {exc}") from exc
        self.status = ChangeSetStatus.APPLIED
        self._applied_fingerprint = plan_fingerprint(plan)

    def rollback(
        self,
        plan: BIDSConversionPlan,
        *,
        conversion_busy: bool = False,
        rule_store: Any | None = None,
    ) -> None:
        """Restore plan items and rule catalog captured before the last apply."""
        if conversion_busy:
            raise ChangeSetError("Cannot rollback ChangeSet while conversion is running.")
        if self.status != ChangeSetStatus.APPLIED:
            raise ChangeSetError("Only APPLIED ChangeSets can be rolled back.")
        if not self.reversible:
            raise ChangeSetError("ChangeSet is not reversible.")
        if self.edit_batches and not self._rollback_items:
            raise ChangeSetError("No rollback snapshot available.")
        if self.edit_batches:
            plan.items = [item.clone() for item in self._rollback_items]
            plan._validated = False
            plan.refresh_filenames()
        if self._rule_applied:
            if rule_store is None:
                raise ChangeSetError("Rule catalog rollback requires a CurationRuleStore.")
            rule_store.restore(self._rule_rollback)
            self._rule_applied = False
        self.status = ChangeSetStatus.ROLLED_BACK

    def reject(self) -> None:
        if self.status == ChangeSetStatus.APPLIED:
            raise ChangeSetError("Reject an applied ChangeSet via rollback instead.")
        self.status = ChangeSetStatus.REJECTED

    def approve(self) -> None:
        if self.status not in {ChangeSetStatus.VALIDATED, ChangeSetStatus.DRAFT}:
            raise ChangeSetError(f"Cannot approve ChangeSet in status {self.status.value}.")
        if self.status == ChangeSetStatus.DRAFT:
            raise ChangeSetError("Validate the ChangeSet before approval.")
        self.status = ChangeSetStatus.APPROVED

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "created_at": self.created_at,
            "reason": self.reason,
            "tool_name": self.tool_name,
            "status": self.status.value,
            "reversible": self.reversible,
            "plan_fingerprint": self.plan_fingerprint,
            "warnings": list(self.warnings),
            "affected_subjects": list(self.affected_subjects),
            "affected_sessions": list(self.affected_sessions),
            "affected_acquisitions": list(self.affected_acquisitions),
            "evidence": list(self.evidence),
            "tools_consulted": list(self.tools_consulted),
            "confidence": self.confidence,
            "edits": [e.to_dict() for e in self.edits],
            "before_snapshot": list(self.before_snapshot),
            "after_snapshot": list(self.after_snapshot),
            "preview": self.preview(),
            "rule_catalog_op": self.rule_catalog_op or None,
            "proposed_rule": None if self.proposed_rule is None else self.proposed_rule.to_dict(),
        }

    def _validate_rule_payload(self, *, rule_store: Any | None) -> None:
        from neuro_pipeline.neurobids.curation.engine import validate_rule

        op = (self.rule_catalog_op or "").strip().lower()
        if not op:
            return
        if op not in RULE_CATALOG_OPS:
            raise ChangeSetError(f"Unsupported rule catalog operation {op!r}.")
        if op in {"save", "replace"}:
            if self.proposed_rule is None:
                raise ChangeSetError("Rule catalog save requires a proposed_rule.")
            result = validate_rule(self.proposed_rule)
            if not result.ok:
                raise ChangeSetError(f"Invalid curation rule: {result.summary()}")
            for issue in result.issues:
                if issue.level == "warning" and issue.message not in self.warnings:
                    self.warnings.append(issue.message)
        elif op in {"enable", "disable"}:
            rule_id = self.target_rule_id or (
                self.proposed_rule.id if self.proposed_rule is not None else ""
            )
            if not rule_id:
                raise ChangeSetError("enable/disable requires target_rule_id.")
            if rule_store is not None and rule_store.get(rule_id) is None:
                raise ChangeSetError(f"Unknown curation rule: {rule_id}")

    def _apply_rule_catalog(self, rule_store: Any) -> None:
        from datetime import datetime, timezone

        op = (self.rule_catalog_op or "").strip().lower()
        now = datetime.now(timezone.utc).isoformat()
        if op in {"save", "replace"}:
            if self.proposed_rule is None:
                raise ChangeSetError("Rule catalog save requires a proposed_rule.")
            rule = self.proposed_rule.clone()
            rule.provenance.changeset_id = self.id
            rule.provenance.approved_at = now
            if not rule.provenance.tool_name:
                rule.provenance.tool_name = self.tool_name
            saved = rule_store.upsert(
                rule,
                replace_id=self.target_rule_id or None,
            )
            self.proposed_rule = saved
            self.target_rule_id = saved.id
            return
        if op in {"enable", "disable"}:
            rule_id = self.target_rule_id or (
                self.proposed_rule.id if self.proposed_rule is not None else ""
            )
            saved = rule_store.set_enabled(rule_id, enabled=(op == "enable"))
            self.proposed_rule = saved
            return
        raise ChangeSetError(f"Unsupported rule catalog operation {op!r}.")

    # ------------------------------------------------------------------
    # Guards
    # ------------------------------------------------------------------

    def _assert_can_operate(
        self,
        plan: BIDSConversionPlan,
        *,
        conversion_busy: bool,
        require_draftish: bool,
    ) -> None:
        if conversion_busy:
            raise ChangeSetError("Cannot operate on ChangeSet while conversion is running.")
        if require_draftish and self.status not in {
            ChangeSetStatus.DRAFT,
            ChangeSetStatus.VALIDATED,
            ChangeSetStatus.APPROVED,
        }:
            raise ChangeSetError(f"ChangeSet status {self.status.value} is not operable.")
        if plan_fingerprint(plan) != self.plan_fingerprint:
            raise ChangeSetError(
                "Stale ChangeSet: plan fingerprint mismatch. Regenerate the ChangeSet."
            )


def _diff_snapshots(
    before: list[dict[str, Any]],
    after: list[dict[str, Any]],
) -> list[PlanEdit]:
    before_map = {s["series_uid"]: s for s in before}
    after_map = {s["series_uid"]: s for s in after}
    edits: list[PlanEdit] = []
    keys = (
        "subject",
        "session",
        "datatype",
        "suffix",
        "task",
        "run",
        "acquisition",
        "direction",
        "include",
        "intended_filename",
    )
    for uid in sorted(set(before_map) | set(after_map)):
        b = before_map.get(uid, {})
        a = after_map.get(uid, {})
        for key in keys:
            if b.get(key) != a.get(key):
                edits.append(
                    PlanEdit(
                        series_uid=uid,
                        field=key,
                        before=b.get(key),
                        after=a.get(key),
                    )
                )
    return edits


__all__ = [
    "ChangeSet",
    "ChangeSetError",
    "ChangeSetStatus",
    "PlanEdit",
]
