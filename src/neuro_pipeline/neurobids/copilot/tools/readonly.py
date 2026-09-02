"""Read-only NeuroBIDS Copilot tools."""

from __future__ import annotations

from typing import Any, Mapping

from neuro_pipeline.neurobids.copilot.session import CopilotSession
from neuro_pipeline.neurobids.copilot.tools.base import Tool, ToolKind, ToolResult, fail, ok


class InspectDatasetTool(Tool):
    name = "inspect_dataset"
    description = (
        "Summarize the currently loaded dataset from DatasetContext "
        "(subjects, sessions, acquisitions, modalities, issues)."
    )
    kind = ToolKind.READ_ONLY
    input_schema = {"type": "object", "properties": {}, "additionalProperties": False}
    output_schema = {
        "type": "object",
        "properties": {
            "summary": {"type": "object"},
            "llm_context": {"type": "object"},
        },
    }

    def execute(self, session: CopilotSession, params: Mapping[str, Any] | None = None) -> ToolResult:
        ctx = session.dataset_context(refresh=True)
        validation = session.validate_plan()
        store = session.curation_store()
        summary = {
            "dataset_label": ctx.dataset_label,
            "output_label": ctx.output_label,
            "n_subjects": ctx.n_subjects or len(ctx.subjects),
            "n_sessions": sum(len(s.sessions) for s in ctx.subjects),
            "n_acquisitions": ctx.n_series or len(ctx.iter_acquisitions()),
            "n_dicom_files": ctx.n_dicom_files,
            "modalities": ctx.modalities,
            "datatype_summary": ctx.datatype_summary,
            "detection_method": ctx.detection_method,
            "validation_ok": validation.ok,
            "n_validation_errors": len(validation.errors),
            "n_validation_warnings": len(validation.warnings),
            "n_metadata_issues": len(ctx.metadata_issues),
            "n_curation_rules": len(store.rules),
            "n_enabled_curation_rules": len(store.enabled_rules()),
            "curation_rules": [r.to_llm_dict() for r in store.rules[:20]],
            "issues": [i.to_llm_dict() for i in ctx.metadata_issues[:40]],
        }
        return ok(self.name, {"summary": summary, "llm_context": ctx.to_llm_context()})


class ListSubjectsTool(Tool):
    name = "list_subjects"
    description = "List subject IDs with session/acquisition counts and modalities."
    kind = ToolKind.READ_ONLY
    input_schema = {"type": "object", "properties": {}, "additionalProperties": False}
    output_schema = {"type": "object", "properties": {"subjects": {"type": "array"}}}

    def execute(self, session: CopilotSession, params: Mapping[str, Any] | None = None) -> ToolResult:
        ctx = session.dataset_context(refresh=True)
        subjects = [
            {
                "subject_id": s.subject_id,
                "n_sessions": len(s.sessions),
                "n_acquisitions": s.n_acquisitions,
                "modalities": s.modalities,
                "source_folder": s.source_folder,
                "session_ids": [ses.session_id for ses in s.sessions],
            }
            for s in ctx.subjects
        ]
        return ok(self.name, {"subjects": subjects, "n_subjects": len(subjects)})


class InspectSubjectTool(Tool):
    name = "inspect_subject"
    description = "Inspect one subject: sessions, acquisitions, BIDS mappings, issues."
    kind = ToolKind.READ_ONLY
    input_schema = {
        "type": "object",
        "properties": {"subject_id": {"type": "string"}},
        "required": ["subject_id"],
        "additionalProperties": False,
    }
    output_schema = {"type": "object", "properties": {"subject": {"type": "object"}}}

    def execute(self, session: CopilotSession, params: Mapping[str, Any] | None = None) -> ToolResult:
        params = params or {}
        subject_id = str(params.get("subject_id") or "").strip()
        if not subject_id:
            return fail(self.name, "subject_id is required")
        ctx = session.dataset_context(refresh=True)
        match = _find_subject(ctx.subjects, subject_id)
        if match is None:
            return fail(self.name, f"Subject not found: {subject_id}")
        issues = [
            i.to_dict()
            for i in ctx.metadata_issues
            if i.subject == match.subject_id or _subject_match(i.subject, subject_id)
        ]
        return ok(
            self.name,
            {
                "subject": match.to_dict(),
                "llm": match.to_llm_dict(),
                "issues": issues,
            },
        )


class FindAcquisitionsTool(Tool):
    name = "find_acquisitions"
    description = (
        "Filter acquisitions by subject, session, sequence, modality, "
        "BIDS datatype, include flag, or issue code."
    )
    kind = ToolKind.READ_ONLY
    input_schema = {
        "type": "object",
        "properties": {
            "subject": {"type": "string"},
            "session": {"type": "string"},
            "sequence": {"type": "string"},
            "modality": {"type": "string"},
            "datatype": {"type": "string"},
            "included": {"type": "boolean"},
            "issue_code": {"type": "string"},
        },
        "additionalProperties": False,
    }
    output_schema = {"type": "object", "properties": {"acquisitions": {"type": "array"}}}

    def execute(self, session: CopilotSession, params: Mapping[str, Any] | None = None) -> ToolResult:
        params = dict(params or {})
        ctx = session.dataset_context(refresh=True)
        hits: list[dict[str, Any]] = []
        for subj in ctx.subjects:
            if params.get("subject") and not _subject_match(subj.subject_id, str(params["subject"])):
                continue
            for ses in subj.sessions:
                if params.get("session") and not _session_match(ses.session_id, str(params["session"])):
                    continue
                for acq in ses.acquisitions:
                    if not _acq_matches(acq, params):
                        continue
                    hits.append(
                        {
                            "subject_id": subj.subject_id,
                            "session_id": ses.session_id,
                            **acq.to_llm_dict(),
                            "series_uid": acq.series_uid,
                        }
                    )
        return ok(self.name, {"acquisitions": hits, "n_matches": len(hits), "filters": params})


def _find_subject(subjects, subject_id: str):
    for s in subjects:
        if _subject_match(s.subject_id, subject_id):
            return s
    return None


def _subject_match(left: str, right: str) -> bool:
    a = (left or "").removeprefix("sub-").strip().lower()
    b = (right or "").removeprefix("sub-").strip().lower()
    return bool(a) and a == b


def _session_match(left: str, right: str) -> bool:
    a = (left or "").removeprefix("ses-").strip().lower()
    b = (right or "").removeprefix("ses-").strip().lower()
    return a == b


def _acq_matches(acq, params: Mapping[str, Any]) -> bool:
    if params.get("modality"):
        if (acq.modality or "").lower() != str(params["modality"]).lower():
            return False
    if params.get("sequence"):
        needle = str(params["sequence"]).lower()
        blob = " ".join(
            [
                acq.sequence_type or "",
                acq.fine_sequence_type or "",
                acq.series_description or "",
                acq.protocol_name or "",
            ]
        ).lower()
        if needle not in blob:
            return False
    if params.get("datatype"):
        dt = (acq.bids.datatype if acq.bids else "") or ""
        if dt.lower() != str(params["datatype"]).lower():
            return False
    if "included" in params and params["included"] is not None:
        included = True if acq.bids is None else bool(acq.bids.include)
        if included != bool(params["included"]):
            return False
    if params.get("issue_code"):
        code = str(params["issue_code"])
        if not any(i.code == code for i in acq.metadata_issues):
            # also allow dataset-level codes via requires_manual_mapping heuristic
            if code == "manual_mapping_required" and acq.requires_manual_mapping:
                return True
            if code == "not_convertible" and not acq.convertible_to_nifti:
                return True
            if code == "excluded" and acq.bids is not None and not acq.bids.include:
                return True
            return False
    return True
