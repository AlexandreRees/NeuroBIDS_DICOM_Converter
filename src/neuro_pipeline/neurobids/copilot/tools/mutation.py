"""Mutating Copilot tools — produce ChangeSets only (no direct plan apply)."""

from __future__ import annotations

from typing import Any, Mapping

from neuro_pipeline.bids.subject_manager import SubjectManager
from neuro_pipeline.neurobids.copilot.changeset import ChangeSet, ChangeSetError
from neuro_pipeline.neurobids.copilot.session import CopilotSession
from neuro_pipeline.neurobids.copilot.tools.base import Tool, ToolKind, ToolResult, fail, ok


def _changeset_result(tool_name: str, changeset: ChangeSet, *, warnings: list[str] | None = None) -> ToolResult:
    return ok(
        tool_name,
        {
            "changeset": changeset,
            "changeset_dict": changeset.to_dict(),
            "preview": changeset.preview(),
            "status": changeset.status.value,
        },
        warnings=warnings,
    )


class RenameSubjectsTool(Tool):
    name = "rename_subjects"
    description = (
        "Propose sequential or explicit subject renames on the BIDS plan. "
        "Returns a ChangeSet; does not apply changes."
    )
    kind = ToolKind.MUTATING
    input_schema = {
        "type": "object",
        "properties": {
            "mode": {"type": "string", "enum": ["sequential", "mapping"]},
            "mapping": {
                "type": "object",
                "additionalProperties": {"type": "string"},
                "description": "old_subject -> new_subject (bare or sub-*)",
            },
            "start": {"type": "integer", "minimum": 1, "default": 1},
            "width": {"type": "integer", "minimum": 1, "default": 3},
            "preserve_sessions": {"type": "boolean", "default": True},
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

        mode = str(params.get("mode") or "sequential").lower()
        preserve_sessions = bool(params.get("preserve_sessions", True))
        subjects_mgr = SubjectManager()
        reason = str(params.get("reason") or "rename_subjects")

        # Preserve first-seen order of subjects in the plan
        ordered_subjects: list[str] = []
        for item in session.plan.items:
            sid = item.subject or ""
            if sid and sid not in ordered_subjects:
                ordered_subjects.append(sid)

        rename_map: dict[str, str] = {}
        if mode == "mapping":
            raw_map = params.get("mapping") or {}
            if not isinstance(raw_map, dict) or not raw_map:
                return fail(self.name, "mapping mode requires a non-empty mapping object")
            try:
                for old, new in raw_map.items():
                    old_label = subjects_mgr.validate_subject_id(str(old))
                    new_label = subjects_mgr.validate_subject_id(str(new))
                    rename_map[old_label] = new_label
                    # also allow matching with sub- prefix keys already on plan
                    rename_map[str(old).strip()] = new_label
            except ValueError as exc:
                return fail(self.name, str(exc))
        elif mode == "sequential":
            start = int(params.get("start") or 1)
            width = int(params.get("width") or 3)
            for idx, old in enumerate(ordered_subjects):
                try:
                    old_label = subjects_mgr.validate_subject_id(old)
                except ValueError:
                    old_label = old.removeprefix("sub-")
                new_label = str(start + idx).zfill(width)
                subjects_mgr.validate_subject_id(new_label)
                rename_map[old_label] = new_label
                rename_map[old] = new_label
        else:
            return fail(self.name, f"Unsupported mode: {mode}")

        batches: list[tuple[str, dict[str, Any]]] = []
        for item in session.plan.items:
            old = item.subject or ""
            old_bare = old.removeprefix("sub-")
            new_bare = rename_map.get(old) or rename_map.get(old_bare)
            if not new_bare or new_bare == old_bare:
                continue
            fields: dict[str, Any] = {"subject": new_bare}
            if not preserve_sessions:
                # explicit opt-out only — default preserves sessions
                pass
            batches.append((item.source_series_uid, fields))

        if not batches:
            return fail(self.name, "No subject renames to apply (mapping produced no changes).")

        try:
            changeset = ChangeSet.from_edit_batches(
                session.plan,
                batches,
                tool_name=self.name,
                reason=reason,
            )
        except ChangeSetError as exc:
            return fail(self.name, str(exc))
        return _changeset_result(self.name, changeset)


class RenameSessionsTool(Tool):
    name = "rename_sessions"
    description = (
        "Propose session renames (sequential per subject or explicit mapping). "
        "Returns a ChangeSet; does not apply changes."
    )
    kind = ToolKind.MUTATING
    input_schema = {
        "type": "object",
        "properties": {
            "mode": {"type": "string", "enum": ["sequential", "mapping"]},
            "subject_id": {"type": "string"},
            "mapping": {
                "type": "object",
                "additionalProperties": {"type": "string"},
                "description": "old_session -> new_session within subject scope",
            },
            "start": {"type": "integer", "minimum": 1, "default": 1},
            "width": {"type": "integer", "minimum": 1, "default": 2},
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

        mode = str(params.get("mode") or "sequential").lower()
        subject_filter = str(params.get("subject_id") or "").strip()
        subjects_mgr = SubjectManager()
        reason = str(params.get("reason") or "rename_sessions")

        def _subj_key(value: str) -> str:
            try:
                return subjects_mgr.validate_subject_id(value)
            except ValueError:
                return value.removeprefix("sub-").strip()

        def _ses_key(value: str) -> str:
            try:
                label = subjects_mgr.validate_session_id(value)
                return label or ""
            except ValueError:
                return value.removeprefix("ses-").strip()

        batches: list[tuple[str, dict[str, Any]]] = []

        if mode == "mapping":
            raw_map = params.get("mapping") or {}
            if not isinstance(raw_map, dict) or not raw_map:
                return fail(self.name, "mapping mode requires a non-empty mapping object")
            normalized = {_ses_key(str(k)): _ses_key(str(v)) for k, v in raw_map.items()}
            for item in session.plan.items:
                if subject_filter and _subj_key(item.subject) != _subj_key(subject_filter):
                    continue
                old = _ses_key(item.session)
                new = normalized.get(old)
                if new is None or new == old:
                    continue
                batches.append((item.source_series_uid, {"session": new}))
        elif mode == "sequential":
            start = int(params.get("start") or 1)
            width = int(params.get("width") or 2)
            # per-subject ordered unique sessions
            per_subject: dict[str, list[str]] = {}
            for item in session.plan.items:
                sk = _subj_key(item.subject)
                if subject_filter and sk != _subj_key(subject_filter):
                    continue
                ses = _ses_key(item.session)
                if not ses:
                    continue
                per_subject.setdefault(sk, [])
                if ses not in per_subject[sk]:
                    per_subject[sk].append(ses)
            rename_by_subject: dict[str, dict[str, str]] = {}
            for sk, sessions in per_subject.items():
                rename_by_subject[sk] = {
                    old: str(start + idx).zfill(width) for idx, old in enumerate(sessions)
                }
            for item in session.plan.items:
                sk = _subj_key(item.subject)
                if sk not in rename_by_subject:
                    continue
                old = _ses_key(item.session)
                new = rename_by_subject[sk].get(old)
                if not new or new == old:
                    continue
                batches.append((item.source_series_uid, {"session": new}))
        else:
            return fail(self.name, f"Unsupported mode: {mode}")

        if not batches:
            return fail(self.name, "No session renames to apply.")

        try:
            changeset = ChangeSet.from_edit_batches(
                session.plan,
                batches,
                tool_name=self.name,
                reason=reason,
            )
        except ChangeSetError as exc:
            return fail(self.name, str(exc))
        return _changeset_result(self.name, changeset)


class ExcludeAcquisitionsTool(Tool):
    name = "exclude_acquisitions"
    description = "Propose excluding acquisitions from conversion (ChangeSet only)."
    kind = ToolKind.MUTATING
    input_schema = {
        "type": "object",
        "properties": {
            "series_uids": {"type": "array", "items": {"type": "string"}},
            "reason": {"type": "string"},
        },
        "required": ["series_uids"],
        "additionalProperties": False,
    }
    output_schema = {"type": "object", "properties": {"changeset": {"type": "object"}}}

    def execute(self, session: CopilotSession, params: Mapping[str, Any] | None = None) -> ToolResult:
        return _set_include(self, session, params, include=False)


class IncludeAcquisitionsTool(Tool):
    name = "include_acquisitions"
    description = "Propose including previously excluded acquisitions (ChangeSet only)."
    kind = ToolKind.MUTATING
    input_schema = {
        "type": "object",
        "properties": {
            "series_uids": {"type": "array", "items": {"type": "string"}},
            "reason": {"type": "string"},
        },
        "required": ["series_uids"],
        "additionalProperties": False,
    }
    output_schema = {"type": "object", "properties": {"changeset": {"type": "object"}}}

    def execute(self, session: CopilotSession, params: Mapping[str, Any] | None = None) -> ToolResult:
        return _set_include(self, session, params, include=True)


class ApplyEditTool(Tool):
    name = "apply_edit"
    description = (
        "Propose entity/include edits for one acquisition via ChangeSet "
        "(mirrors BIDSConversionPlan.apply_edit fields)."
    )
    kind = ToolKind.MUTATING
    input_schema = {
        "type": "object",
        "properties": {
            "series_uid": {"type": "string"},
            "subject": {"type": "string"},
            "session": {"type": "string"},
            "datatype": {"type": "string"},
            "suffix": {"type": "string"},
            "task": {"type": "string"},
            "run": {"type": "string"},
            "acquisition": {"type": "string"},
            "direction": {"type": "string"},
            "include_in_conversion": {"type": "boolean"},
            "reason": {"type": "string"},
        },
        "required": ["series_uid"],
        "additionalProperties": False,
    }
    output_schema = {"type": "object", "properties": {"changeset": {"type": "object"}}}

    def execute(self, session: CopilotSession, params: Mapping[str, Any] | None = None) -> ToolResult:
        params = dict(params or {})
        try:
            session.ensure_not_busy()
        except RuntimeError as exc:
            return fail(self.name, str(exc))
        uid = str(params.get("series_uid") or "").strip()
        if not uid:
            return fail(self.name, "series_uid is required")
        if session.plan.get(uid) is None:
            return fail(self.name, f"Unknown series_uid in plan: {uid}")

        fields: dict[str, Any] = {}
        for key in (
            "subject",
            "session",
            "datatype",
            "suffix",
            "task",
            "run",
            "acquisition",
            "direction",
            "include_in_conversion",
        ):
            if key in params and params[key] is not None:
                fields[key] = params[key]
        if not fields:
            return fail(self.name, "No editable fields provided")

        try:
            changeset = ChangeSet.from_edit_batches(
                session.plan,
                [(uid, fields)],
                tool_name=self.name,
                reason=str(params.get("reason") or "apply_edit"),
            )
        except ChangeSetError as exc:
            return fail(self.name, str(exc))
        return _changeset_result(self.name, changeset)


def _set_include(
    tool: Tool,
    session: CopilotSession,
    params: Mapping[str, Any] | None,
    *,
    include: bool,
) -> ToolResult:
    params = dict(params or {})
    try:
        session.ensure_not_busy()
    except RuntimeError as exc:
        return fail(tool.name, str(exc))
    uids = [str(u) for u in (params.get("series_uids") or [])]
    if not uids:
        return fail(tool.name, "series_uids is required")
    missing = [u for u in uids if session.plan.get(u) is None]
    if missing:
        return fail(tool.name, f"Unknown series_uids: {', '.join(missing)}")

    batches = [(u, {"include_in_conversion": include}) for u in uids]
    try:
        changeset = ChangeSet.from_edit_batches(
            session.plan,
            batches,
            tool_name=tool.name,
            reason=str(params.get("reason") or tool.name),
        )
    except ChangeSetError as exc:
        return fail(tool.name, str(exc))
    return _changeset_result(tool.name, changeset)
