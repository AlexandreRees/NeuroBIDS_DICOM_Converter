"""Read-only dataset audit for NeuroBIDS Copilot.

Deterministic findings from DatasetContext, the conversion plan, and the
existing SequenceClassifier-backed reasoner. Never mutates the plan or
DICOM. Recommendations are text only — not ChangeSets.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any, Mapping

from neuro_pipeline.neurobids.copilot.session import CopilotSession
from neuro_pipeline.neurobids.copilot.tools.base import Tool, ToolKind, ToolResult, ok
from neuro_pipeline.neurobids.copilot.tools.reasoning import reason_all

_POLICY = (
    "Read-only audit. Findings are observed from the loaded plan and "
    "deterministic classifiers. Copilot may summarize and recommend actions "
    "but must never apply ChangeSets or invent metadata."
)

_LABEL_RE = re.compile(r"^[A-Za-z0-9]+$")
_VALID_PE = {"AP", "PA", "LR", "RL", "IS", "SI"}
_CORE_DATATYPES = {"anat", "func", "dwi", "fmap"}
_AUDIT_CODES = (
    "unmapped",
    "ambiguous_mapping",
    "missing_expected_modality",
    "inconsistent_structure",
    "missing_metadata",
    "suspicious_entity",
    "fieldmap_association",
    "excluded",
)


def audit_session(session: CopilotSession) -> dict[str, Any]:
    """Build the full audit payload (no I/O, no mutations)."""
    ctx = session.dataset_context(refresh=True)
    series_map = session.series_by_uid()
    reasoned = {r["series_uid"]: r for r in reason_all(session)}
    findings: list[dict[str, Any]] = []

    rows = _iter_rows(ctx)
    findings.extend(_finding_unmapped(rows, reasoned))
    findings.extend(_finding_ambiguous(rows, reasoned))
    findings.extend(_finding_excluded(rows))
    findings.extend(_finding_missing_expected(rows))
    findings.extend(_finding_structure(rows))
    findings.extend(_finding_missing_metadata(rows, series_map))
    findings.extend(_finding_suspicious_entities(rows, series_map, session))
    findings.extend(_finding_fieldmaps(rows, reasoned))

    n_errors = sum(1 for f in findings if f["severity"] == "error")
    n_warnings = sum(1 for f in findings if f["severity"] == "warning")
    n_info = sum(1 for f in findings if f["severity"] == "info")
    return {
        "findings": findings,
        "n_findings": len(findings),
        "n_errors": n_errors,
        "n_warnings": n_warnings,
        "n_info": n_info,
        "codes": [f["code"] for f in findings],
        "issues": [{"code": f["code"], "severity": f["severity"], "n": f["n_affected"]} for f in findings],
        "acquisitions": _flatten_affected(findings),
        "n_matches": sum(f["n_affected"] for f in findings),
        "summary": {
            "n_findings": len(findings),
            "n_errors": n_errors,
            "n_warnings": n_warnings,
            "n_info": n_info,
            "n_subjects": ctx.n_subjects or len(ctx.subjects),
            "codes": [f["code"] for f in findings],
        },
        "auto_applied": False,
        "recommendations": [f["recommendation"] for f in findings],
        "policy": _POLICY,
    }


def _iter_rows(ctx) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for subj in ctx.subjects:
        for ses in subj.sessions:
            for acq in ses.acquisitions:
                bids = acq.bids
                included = True if bids is None else bool(bids.include)
                datatype = (bids.datatype if bids else "") or ""
                rows.append(
                    {
                        "series_uid": acq.series_uid,
                        "subject": subj.subject_id,
                        "session": ses.session_id,
                        "description": acq.series_description or "",
                        "protocol": acq.protocol_name or "",
                        "modality": acq.modality or "",
                        "sequence_type": acq.sequence_type or "",
                        "fine_sequence_type": acq.fine_sequence_type or "",
                        "num_images": int(acq.num_images or 0),
                        "include": included,
                        "datatype": datatype,
                        "suffix": (bids.suffix if bids else "") or "",
                        "task": (bids.task if bids else "") or "",
                        "run": (bids.run if bids else "") or "",
                        "acquisition": (bids.acquisition if bids else "") or "",
                        "direction": (bids.direction if bids else "") or "",
                        "requires_manual_mapping": bool(acq.requires_manual_mapping),
                        "convertible": bool(acq.convertible_to_nifti),
                    }
                )
    return rows


def _affected(row: dict[str, Any]) -> dict[str, str]:
    return {
        "series_uid": row["series_uid"],
        "subject": row["subject"],
        "session": row["session"],
        "description": row["description"],
        "datatype": row["datatype"],
    }


def _finding(
    *,
    code: str,
    severity: str,
    title: str,
    message: str,
    evidence: list[str],
    affected: list[dict[str, Any]],
    recommendation: str,
) -> dict[str, Any]:
    return {
        "code": code,
        "severity": severity,
        "title": title,
        "message": message,
        "evidence": list(dict.fromkeys(evidence))[:24],
        "affected": affected,
        "n_affected": len(affected),
        "recommendation": recommendation,
    }


def _finding_unmapped(rows: list[dict[str, Any]], reasoned: dict[str, Any]) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    evidence: list[str] = []
    for row in rows:
        if not row["include"]:
            continue
        rec = reasoned.get(row["series_uid"]) or {}
        dt = (row["datatype"] or "").lower()
        unclassified = bool(rec.get("unclassified"))
        if dt in {"", "unknown"} or unclassified:
            hits.append(_affected(row))
            evidence.append(
                f"{row['series_uid']}: datatype={row['datatype'] or '(empty)'} "
                f"description={row['description']}"
            )
    if not hits:
        return []
    return [
        _finding(
            code="unmapped",
            severity="warning",
            title="Unmapped acquisitions",
            message=(
                f"{len(hits)} included acquisition(s) have an empty/unknown BIDS "
                "datatype or are unclassified."
            ),
            evidence=evidence,
            affected=hits,
            recommendation=(
                "Inspect each series with classify_acquisition or propose_bids_mapping. "
                "Do not invent a datatype. Apply a ChangeSet only after explicit approval."
            ),
        )
    ]


def _finding_ambiguous(rows: list[dict[str, Any]], reasoned: dict[str, Any]) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    evidence: list[str] = []
    for row in rows:
        rec = reasoned.get(row["series_uid"]) or {}
        if not (rec.get("ambiguous") or row["requires_manual_mapping"]):
            continue
        hits.append(_affected(row))
        evidence.append(
            f"{row['series_uid']}: requires_manual_mapping={row['requires_manual_mapping']} "
            f"reasoner_ambiguous={bool(rec.get('ambiguous'))} "
            f"label={(rec.get('inferred') or {}).get('label') or rec.get('label')}"
        )
    if not hits:
        return []
    return [
        _finding(
            code="ambiguous_mapping",
            severity="warning",
            title="Ambiguous mappings",
            message=f"{len(hits)} acquisition(s) have ambiguous or conflicting mappings.",
            evidence=evidence,
            affected=hits,
            recommendation=(
                "Prefer manual review. Call classify_acquisition for evidence; "
                "do not auto-assign BIDS entities."
            ),
        )
    ]


def _finding_excluded(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    hits = [_affected(row) for row in rows if not row["include"]]
    if not hits:
        return []
    evidence = [
        f"{row['series_uid']}: include=false description={row['description']}"
        for row in rows
        if not row["include"]
    ]
    return [
        _finding(
            code="excluded",
            severity="info",
            title="Excluded acquisitions",
            message=f"{len(hits)} acquisition(s) are excluded from conversion.",
            evidence=evidence,
            affected=hits,
            recommendation=(
                "Confirm exclusions (reports/scouts). Use include_acquisitions only if "
                "the user explicitly wants them converted; never auto-apply."
            ),
        )
    ]


def _finding_missing_expected(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_subject: dict[str, set[str]] = defaultdict(set)
    subjects: list[str] = []
    for row in rows:
        sid = row["subject"]
        if sid not in subjects:
            subjects.append(sid)
        if not row["include"]:
            continue
        dt = (row["datatype"] or "").lower()
        if dt in _CORE_DATATYPES:
            by_subject[sid].add(dt)
    n_subj = len(subjects)
    if n_subj < 2:
        return []
    prevalence = defaultdict(int)
    for dts in by_subject.values():
        for dt in dts:
            prevalence[dt] += 1
    expected = {dt for dt, n in prevalence.items() if n > n_subj / 2}
    affected: list[dict[str, Any]] = []
    evidence: list[str] = []
    for sid in subjects:
        missing = sorted(expected - by_subject.get(sid, set()))
        if not missing:
            continue
        evidence.append(f"subject={sid} missing={','.join(missing)}")
        sample = next((r for r in rows if row_subject(r, sid) and r["include"]), None)
        if sample:
            item = _affected(sample)
            item["missing_datatypes"] = ",".join(missing)
            affected.append(item)
    if not affected:
        return []
    return [
        _finding(
            code="missing_expected_modality",
            severity="warning",
            title="Missing expected modalities",
            message=(
                f"Datatype(s) present in a majority of subjects are missing for "
                f"{len(affected)} subject(s). Expected majority datatypes: "
                f"{', '.join(sorted(expected)) or '(none)'}."
            ),
            evidence=evidence,
            affected=affected,
            recommendation=(
                "Confirm whether the missing modality was not acquired. "
                "Do not invent series. Review mappings if the data exist but are unmapped."
            ),
        )
    ]


def row_subject(row: dict[str, Any], subject: str) -> bool:
    a = (row.get("subject") or "").removeprefix("sub-").strip().lower()
    b = (subject or "").removeprefix("sub-").strip().lower()
    return a == b


def _finding_structure(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_subj_ses: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for row in rows:
        if not row["include"]:
            continue
        dt = (row["datatype"] or "").lower()
        if dt in _CORE_DATATYPES:
            by_subj_ses[row["subject"]][row["session"] or ""].add(dt)
    affected: list[dict[str, Any]] = []
    evidence: list[str] = []
    for subject, sessions in by_subj_ses.items():
        if len(sessions) < 2:
            continue
        union: set[str] = set()
        for dts in sessions.values():
            union |= dts
        for session_id, dts in sessions.items():
            missing = sorted(union - dts)
            if not missing:
                continue
            evidence.append(
                f"subject={subject} session={session_id or '(none)'} "
                f"missing={','.join(missing)}"
            )
            sample = next(
                (
                    r
                    for r in rows
                    if row_subject(r, subject) and (r["session"] or "") == session_id
                ),
                None,
            )
            if sample:
                item = _affected(sample)
                item["missing_datatypes"] = ",".join(missing)
                affected.append(item)
    empty_session = [
        _affected(r)
        for r in rows
        if r["include"] and not (r["session"] or "").strip()
        and any((x["session"] or "").strip() for x in rows)
    ]
    if empty_session:
        evidence.append("Some included series have an empty session while others do not.")
        affected.extend(empty_session)
    if not affected:
        return []
    return [
        _finding(
            code="inconsistent_structure",
            severity="warning",
            title="Inconsistent subject/session structure",
            message=(
                f"{len(evidence)} structural inconsistency finding(s) "
                "(longitudinal datatype gaps or mixed empty/non-empty sessions)."
            ),
            evidence=evidence,
            affected=affected,
            recommendation=(
                "Compare sessions with inspect_subject. Do not invent missing "
                "acquisitions. Rename sessions only via an approved ChangeSet."
            ),
        )
    ]


def _finding_missing_metadata(
    rows: list[dict[str, Any]],
    series_map: Mapping[str, Any],
) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    evidence: list[str] = []
    for row in rows:
        series = series_map.get(row["series_uid"])
        missing: list[str] = []
        if not (row["description"] or "").strip() and not (row["protocol"] or "").strip():
            missing.append("series_description")
        if not (row["modality"] or "").strip() and not getattr(series, "modality", ""):
            missing.append("modality")
        n_img = row["num_images"]
        if series is not None:
            n_img = int(getattr(series, "num_images", 0) or n_img)
        if n_img <= 0:
            missing.append("num_images")
        if row["include"] and (row["datatype"] or "").lower() in {"", "unknown"}:
            missing.append("bids.datatype")
        if row["include"] and (row["datatype"] or "").lower() in _CORE_DATATYPES:
            if row["datatype"] == "dwi" and not row["acquisition"]:
                missing.append("dwi.acquisition")
            if row["datatype"] == "func" and not row["task"] and (row["suffix"] or "").lower() != "sbref":
                missing.append("func.task")
            if row["datatype"] == "fmap" and not row["direction"]:
                missing.append("fmap.direction")
        if not missing:
            continue
        hits.append(_affected(row))
        evidence.append(f"{row['series_uid']}: missing {', '.join(missing)}")
    if not hits:
        return []
    return [
        _finding(
            code="missing_metadata",
            severity="warning",
            title="Missing metadata",
            message=f"{len(hits)} acquisition(s) are missing observed plan/series fields needed for BIDS.",
            evidence=evidence,
            affected=hits,
            recommendation=(
                "Fill only fields evidenced by DICOM/plan tools. Never invent "
                "PatientName, paths, or entities the tools did not return."
            ),
        )
    ]


def _finding_suspicious_entities(
    rows: list[dict[str, Any]],
    series_map: Mapping[str, Any],
    session: CopilotSession,
) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    evidence: list[str] = []
    for row in rows:
        if not row["include"]:
            continue
        flags: list[str] = []
        dt = (row["datatype"] or "").lower()
        if row["task"] and dt in {"anat", "dwi"}:
            flags.append(f"task={row['task']} on datatype={dt}")
        if row["direction"] and row["direction"].upper() not in _VALID_PE:
            flags.append(f"direction={row['direction']} not a standard PE label")
        for name, value in (
            ("task", row["task"]),
            ("run", row["run"]),
            ("acquisition", row["acquisition"]),
            ("direction", row["direction"]),
            ("suffix", row["suffix"]),
        ):
            if not value:
                continue
            token = str(value).removeprefix(f"{name}-")
            if dt in _CORE_DATATYPES and not _LABEL_RE.fullmatch(token):
                flags.append(f"invalid {name} label {value!r}")
        if dt == "func" and not row["task"] and (row["suffix"] or "").lower() == "sbref":
            flags.append("func/sbref missing task entity")
        if flags:
            hits.append(_affected(row))
            evidence.append(f"{row['series_uid']}: " + "; ".join(flags))
    validation = session.validate_plan()
    for issue in validation.issues:
        if issue.level != "error":
            continue
        uid = issue.series_uid or ""
        if not uid or any(h["series_uid"] == uid for h in hits):
            if uid:
                evidence.append(f"plan.validate: {issue.message}")
            continue
        row = next((r for r in rows if r["series_uid"] == uid), None)
        if row is None:
            continue
        hits.append(_affected(row))
        evidence.append(f"plan.validate[{issue.level}]: {issue.message}")
    if not hits:
        return []
    return [
        _finding(
            code="suspicious_entity",
            severity="warning",
            title="Suspicious BIDS entities",
            message=f"{len(hits)} acquisition(s) have entity values that conflict with datatype or BIDS labels.",
            evidence=evidence,
            affected=hits,
            recommendation=(
                "Correct entities with apply_edit after user approval. "
                "Do not invent task/run/echo/direction values."
            ),
        )
    ]


def _finding_fieldmaps(rows: list[dict[str, Any]], reasoned: dict[str, Any]) -> list[dict[str, Any]]:
    included = [r for r in rows if r["include"]]
    dataset_has_fmap = any((r["datatype"] or "").lower() == "fmap" for r in included)
    by_ses: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in included:
        by_ses[(row["subject"], row["session"])].append(row)

    hits: list[dict[str, Any]] = []
    evidence: list[str] = []
    seen: set[str] = set()

    def _add(row: dict[str, Any], note: str) -> None:
        uid = row["series_uid"]
        if uid in seen:
            return
        seen.add(uid)
        hits.append(_affected(row))
        evidence.append(note)

    for (subject, session_id), items in by_ses.items():
        fmaps = [r for r in items if (r["datatype"] or "").lower() == "fmap"]
        funcs_dwi = [
            r for r in items if (r["datatype"] or "").lower() in {"func", "dwi"}
        ]
        pe: set[str] = set()
        for fmap in fmaps:
            rec = reasoned.get(fmap["series_uid"]) or {}
            direction = (
                fmap["direction"]
                or (rec.get("inferred") or {}).get("phase_encoding")
                or ""
            ).upper()
            if direction in _VALID_PE:
                pe.add(direction)
        if "AP" in pe and "PA" not in pe:
            for fmap in fmaps:
                _add(
                    fmap,
                    f"{fmap['series_uid']}: AP fieldmap without PA pair in {subject} {session_id}",
                )
        if "PA" in pe and "AP" not in pe:
            for fmap in fmaps:
                _add(
                    fmap,
                    f"{fmap['series_uid']}: PA fieldmap without AP pair in {subject} {session_id}",
                )
        if fmaps and not funcs_dwi:
            for fmap in fmaps:
                _add(
                    fmap,
                    f"{fmap['series_uid']}: fmap has no func/dwi in the same session to associate with",
                )
        if dataset_has_fmap and funcs_dwi and not fmaps:
            for acq in funcs_dwi:
                _add(
                    acq,
                    f"{acq['series_uid']}: {acq['datatype']} in {subject} {session_id} has no fieldmap in-session",
                )

    if not hits:
        return []
    return [
        _finding(
            code="fieldmap_association",
            severity="warning",
            title="Fieldmap association issues",
            message=(
                f"{len(hits)} acquisition(s) have unpaired PE-polar fieldmaps, "
                "fmaps without a target, or func/dwi without an in-session fieldmap."
            ),
            evidence=evidence,
            affected=hits,
            recommendation=(
                "Pair AP/PA fieldmaps in the same session when both exist. "
                "Do not invent IntendedFor. Apply mapping edits only after approval."
            ),
        )
    ]


def _flatten_affected(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for finding in findings:
        for item in finding.get("affected") or []:
            uid = str(item.get("series_uid") or "")
            if not uid or uid in seen:
                continue
            seen.add(uid)
            out.append(item)
    return out


class AuditDatasetTool(Tool):
    name = "audit_dataset"
    description = (
        "Read-only dataset audit: unmapped and ambiguous mappings, missing expected "
        "modalities, inconsistent subject/session structure, missing metadata, "
        "suspicious BIDS entities, fieldmap association issues, and excluded "
        "acquisitions. Returns severity, evidence, and affected series. "
        "Never modifies the plan or DICOM. Optional code filter: "
        + ", ".join(_AUDIT_CODES)
        + "."
    )
    kind = ToolKind.READ_ONLY
    input_schema = {
        "type": "object",
        "properties": {
            "code": {"type": "string", "enum": list(_AUDIT_CODES)},
            "severity": {"type": "string", "enum": ["error", "warning", "info"]},
        },
        "additionalProperties": False,
    }
    output_schema = {
        "type": "object",
        "properties": {
            "findings": {"type": "array"},
            "n_findings": {"type": "integer"},
        },
    }

    def execute(self, session: CopilotSession, params: Mapping[str, Any] | None = None) -> ToolResult:
        params = dict(params or {})
        payload = audit_session(session)
        code = str(params.get("code") or "").strip().lower()
        severity = str(params.get("severity") or "").strip().lower()
        findings = list(payload["findings"])
        if code:
            findings = [f for f in findings if f["code"] == code]
        if severity:
            findings = [f for f in findings if f["severity"] == severity]
        if code or severity:
            payload = dict(payload)
            payload["findings"] = findings
            payload["n_findings"] = len(findings)
            payload["n_errors"] = sum(1 for f in findings if f["severity"] == "error")
            payload["n_warnings"] = sum(1 for f in findings if f["severity"] == "warning")
            payload["n_info"] = sum(1 for f in findings if f["severity"] == "info")
            payload["codes"] = [f["code"] for f in findings]
            payload["issues"] = [
                {"code": f["code"], "severity": f["severity"], "n": f["n_affected"]}
                for f in findings
            ]
            payload["acquisitions"] = _flatten_affected(findings)
            payload["n_matches"] = sum(f["n_affected"] for f in findings)
            payload["summary"] = dict(payload.get("summary") or {})
            payload["summary"]["n_findings"] = len(findings)
            payload["summary"]["codes"] = payload["codes"]
            payload["filter"] = {k: v for k, v in (("code", code), ("severity", severity)) if v}
        return ok(self.name, payload)


__all__ = ["AuditDatasetTool", "audit_session"]
