"""Auditable Copilot explanations (evidence-based, no hidden chain-of-thought).

Explanations are built from registered tool outputs, plan fields, and
ChangeSet diffs. They never include LLM scratchpads, thoughts, or PHI.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from neuro_pipeline.neurobids.copilot.changeset import ChangeSet, PlanEdit

# Never copy these into an explanation (hidden CoT / provider internals).
_HIDDEN_KEYS = frozenset(
    {
        "thinking",
        "thoughts",
        "thought",
        "chain_of_thought",
        "chain-of-thought",
        "scratchpad",
        "hidden_reasoning",
        "cot",
        "private_reasoning",
        "inner_monologue",
    }
)

_PHI_KEYS = frozenset(
    {
        "patientname",
        "patient_name",
        "patientid",
        "patient_id",
        "api_key",
        "authorization",
        "source_dir",
        "sample_file",
    }
)

_METADATA_KEEP = frozenset(
    {
        "series_uid",
        "series_description",
        "protocol_name",
        "sequence_type",
        "fine_sequence_type",
        "datatype",
        "suffix",
        "task",
        "run",
        "acquisition",
        "direction",
        "echo",
        "label",
        "coarse",
        "fine",
        "modality",
        "n_edits",
        "n_subjects",
        "n_sessions",
        "n_acquisitions",
        "tool_name",
        "ambiguous",
        "unclassified",
        "task_kind",
        "phase_encoding",
        "is_sbref",
        "is_multiecho",
        "subject",
        "session",
        "include",
    }
)


@dataclass(slots=True)
class CopilotExplanation:
    """Concise, auditable account of a mapping or proposal."""

    decision: str
    evidence: list[str] = field(default_factory=list)
    tools_consulted: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    confidence: float | None = None
    affected_acquisitions: list[str] = field(default_factory=list)
    changeset_id: str = ""
    source: str = "turn"  # mapping | changeset | turn

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "decision": self.decision,
            "evidence": list(self.evidence),
            "tools_consulted": list(self.tools_consulted),
            "metadata": sanitize_metadata(self.metadata),
            "confidence": self.confidence,
            "affected_acquisitions": list(self.affected_acquisitions),
            "changeset_id": self.changeset_id,
            "source": self.source,
        }
        for key in list(payload):
            if str(key).lower() in _HIDDEN_KEYS:
                payload.pop(key, None)
        return payload

    def to_text(self) -> str:
        """User-facing explanation. No hidden reasoning fields."""
        lines = [f"Decision: {self.decision or '—'}"]
        if self.evidence:
            lines.append("Evidence:")
            for item in self.evidence:
                lines.append(f"  - {item}")
        else:
            lines.append("Evidence: (none recorded)")
        tools = ", ".join(self.tools_consulted) if self.tools_consulted else "(none)"
        lines.append(f"Tools consulted: {tools}")
        meta = sanitize_metadata(self.metadata)
        if meta:
            bits = [f"{k}={_fmt(v)}" for k, v in meta.items()]
            lines.append("Metadata: " + "; ".join(bits))
        else:
            lines.append("Metadata: (none)")
        if self.confidence is None:
            lines.append("Confidence: n/a")
        else:
            lines.append(f"Confidence: {self.confidence:.2f}")
        affected = ", ".join(self.affected_acquisitions) if self.affected_acquisitions else "(none)"
        lines.append(f"Affected acquisitions: {affected}")
        if self.changeset_id:
            lines.append(f"ChangeSet ID: {self.changeset_id}")
        return "\n".join(lines)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> CopilotExplanation | None:
        if not isinstance(data, Mapping):
            return None
        cleaned = {k: v for k, v in data.items() if str(k).lower() not in _HIDDEN_KEYS}
        conf = cleaned.get("confidence")
        confidence: float | None
        try:
            confidence = None if conf is None or conf == "" else float(conf)
        except (TypeError, ValueError):
            confidence = None
        return cls(
            decision=str(cleaned.get("decision") or ""),
            evidence=[str(x) for x in (cleaned.get("evidence") or []) if str(x).strip()],
            tools_consulted=_unique_tools(cleaned.get("tools_consulted") or []),
            metadata=sanitize_metadata(cleaned.get("metadata") or {}),
            confidence=confidence,
            affected_acquisitions=[
                str(u) for u in (cleaned.get("affected_acquisitions") or []) if str(u).strip()
            ],
            changeset_id=str(cleaned.get("changeset_id") or ""),
            source=str(cleaned.get("source") or "turn"),
        )


def sanitize_metadata(value: Any) -> dict[str, Any]:
    """Keep observed plan/series fields only (no PHI, paths, or CoT)."""
    if not isinstance(value, Mapping):
        return {}
    out: dict[str, Any] = {}
    for key, raw in value.items():
        key_s = str(key)
        key_l = key_s.lower()
        if key_l in _HIDDEN_KEYS or key_l in _PHI_KEYS:
            continue
        if key_l not in _METADATA_KEEP:
            continue
        cleaned = _sanitize_value(raw)
        if cleaned is not None:
            out[key_s] = cleaned
    return out


def evidence_from_edits(edits: Iterable[PlanEdit]) -> list[str]:
    lines: list[str] = []
    for edit in edits:
        uid = (edit.series_uid or "").strip()
        field = edit.field or "field"
        before = _fmt(edit.before)
        after = _fmt(edit.after)
        prefix = f"{uid}: " if uid else ""
        lines.append(f"{prefix}{field}: {before} → {after}")
    return lines


def explain_mapping(session: Any, series_uid: str) -> CopilotExplanation:
    """Deterministic mapping explanation from classifier + plan fields."""
    from neuro_pipeline.neurobids.copilot.tools.reasoning import reason_acquisition

    uid = (series_uid or "").strip()
    rec = reason_acquisition(session, uid) if uid else None
    if rec is None:
        raise KeyError(uid or "(empty)")

    inferred = rec.get("inferred") if isinstance(rec.get("inferred"), dict) else {}
    observed = rec.get("observed") if isinstance(rec.get("observed"), dict) else {}
    label = str(inferred.get("label") or rec.get("label") or "")
    datatype = str(
        inferred.get("datatype")
        or rec.get("datatype")
        or ""
    )
    suffix = str(inferred.get("suffix") or rec.get("suffix") or "")
    item = session.plan.get(uid) if getattr(session, "plan", None) is not None else None
    if item is not None:
        datatype = str(item.datatype or datatype)
        suffix = str(item.suffix or suffix)

    if rec.get("ambiguous"):
        decision = (
            f"Ambiguous acquisition ({label or 'unclassified'}); "
            f"current mapping is {datatype or '—'}/{suffix or '—'}"
        )
    elif rec.get("unclassified"):
        decision = f"Unclassified acquisition; current mapping is {datatype or '—'}/{suffix or '—'}"
    elif datatype or suffix:
        decision = f"Mapped as {datatype or '—'}/{suffix or '—'}"
        if label:
            decision += f" (label={label})"
    else:
        decision = f"Classified as {label or 'unknown'}"

    evidence = [str(x) for x in (rec.get("evidence") or []) if str(x).strip()]
    reasoning = str(rec.get("reasoning") or "").strip()
    if reasoning and reasoning not in evidence:
        evidence.append(reasoning)

    metadata = {
        "series_uid": uid,
        "label": label,
        "datatype": datatype,
        "suffix": suffix,
        "subject": rec.get("subject") or (item.subject if item is not None else ""),
        "session": rec.get("session") or (item.session if item is not None else ""),
        "series_description": observed.get("series_description") or observed.get("description") or "",
        "protocol_name": observed.get("protocol_name") or "",
        "sequence_type": observed.get("sequence_type") or "",
        "fine_sequence_type": observed.get("fine_sequence_type") or observed.get("fine") or "",
        "task": (inferred.get("entities") or {}).get("task") or (item.task if item is not None else ""),
        "run": (inferred.get("entities") or {}).get("run") or (item.run if item is not None else ""),
        "ambiguous": bool(rec.get("ambiguous")),
        "unclassified": bool(rec.get("unclassified")),
        "is_sbref": inferred.get("is_sbref"),
        "is_multiecho": inferred.get("is_multiecho"),
        "phase_encoding": inferred.get("phase_encoding") or "",
    }

    conf = rec.get("confidence")
    try:
        confidence = None if conf is None else float(conf)
    except (TypeError, ValueError):
        confidence = None

    return CopilotExplanation(
        decision=decision,
        evidence=evidence,
        tools_consulted=["classify_acquisition"],
        metadata=sanitize_metadata(metadata),
        confidence=confidence,
        affected_acquisitions=[uid],
        changeset_id="",
        source="mapping",
    )


def explain_changeset(
    changeset: ChangeSet,
    *,
    tool_traces: Iterable[Any] | None = None,
) -> CopilotExplanation:
    """Explanation of a proposed ChangeSet (never applies it)."""
    tool = changeset.tool_name or "proposed edit"
    n_edits = len(changeset.edits)
    reason = (changeset.reason or "").strip()
    title = tool.replace("_", " ").strip()
    decision = f"Proposed {title}"
    if n_edits:
        decision += f" ({n_edits} edit{'s' if n_edits != 1 else ''})"
    if reason:
        decision += f": {reason}"

    evidence: list[str] = []
    if reason:
        evidence.append(f"reason={reason}")
    if changeset.evidence:
        evidence.extend(str(x) for x in changeset.evidence if str(x).strip())
    evidence.extend(evidence_from_edits(changeset.edits))
    for warn in changeset.warnings or []:
        if str(warn).strip():
            evidence.append(f"warning: {warn}")

    tools = _unique_tools(
        list(changeset.tools_consulted or [])
        + [getattr(t, "tool_name", "") for t in (tool_traces or [])]
        + [tool]
    )

    preview = changeset.preview()
    metadata = {
        "tool_name": tool,
        "n_edits": n_edits,
        "n_subjects": len(changeset.affected_subjects),
        "n_sessions": len(changeset.affected_sessions),
        "n_acquisitions": len(changeset.affected_acquisitions),
    }
    if preview.get("subject_renames"):
        metadata["label"] = "subject_rename"

    conf = changeset.confidence
    try:
        confidence = None if conf is None else float(conf)
    except (TypeError, ValueError):
        confidence = None

    return CopilotExplanation(
        decision=decision,
        evidence=_dedupe(evidence),
        tools_consulted=tools,
        metadata=sanitize_metadata(metadata),
        confidence=confidence,
        affected_acquisitions=list(changeset.affected_acquisitions),
        changeset_id=changeset.id,
        source="changeset",
    )


def explain_from_tool_data(
    tool_name: str,
    data: Mapping[str, Any] | None,
    *,
    traces: Iterable[Any] | None = None,
) -> CopilotExplanation | None:
    """Build an explanation from a sanitized tool payload (no LLM text)."""
    payload = data if isinstance(data, Mapping) else {}
    tools = _unique_tools(
        [tool_name] + [getattr(t, "tool_name", "") for t in (traces or [])]
    )

    if isinstance(payload.get("explanation"), Mapping):
        expl = CopilotExplanation.from_dict(payload["explanation"])
        if expl is not None:
            if tool_name and tool_name not in expl.tools_consulted:
                expl.tools_consulted = _unique_tools(expl.tools_consulted + [tool_name])
            expl.tools_consulted = _unique_tools(expl.tools_consulted + tools)
            return expl

    if isinstance(payload.get("classification"), Mapping):
        return _from_classification(payload["classification"], tools)

    proposals = payload.get("proposals")
    if isinstance(proposals, list) and proposals:
        return _from_proposals(proposals, tools)

    findings = payload.get("findings")
    if isinstance(findings, list):
        return _from_audit(payload, tools)

    return None


def explain_turn(
    *,
    traces: Iterable[Any] | None = None,
    changeset: ChangeSet | None = None,
    last_tool_name: str = "",
    last_tool_data: Mapping[str, Any] | None = None,
) -> CopilotExplanation | None:
    """Prefer ChangeSet, then last tool payload. Never copies LLM chain-of-thought."""
    trace_list = list(traces or [])
    if changeset is not None:
        expl = explain_changeset(changeset, tool_traces=trace_list)
        from_tool = explain_from_tool_data(
            last_tool_name, last_tool_data, traces=trace_list
        )
        if from_tool is not None:
            expl.tools_consulted = _unique_tools(
                expl.tools_consulted + from_tool.tools_consulted
            )
            extra = [e for e in from_tool.evidence if e not in expl.evidence]
            expl.evidence.extend(extra)
            if expl.confidence is None:
                expl.confidence = from_tool.confidence
        return expl

    from_tool = explain_from_tool_data(last_tool_name, last_tool_data, traces=trace_list)
    if from_tool is not None:
        from_tool.source = "turn"
        from_tool.tools_consulted = _unique_tools(from_tool.tools_consulted + [
            getattr(t, "tool_name", "") for t in trace_list
        ])
        return from_tool

    if not trace_list:
        return None
    return CopilotExplanation(
        decision="Inspected the dataset with registered tools (no mapping change proposed).",
        evidence=[f"tools={', '.join(getattr(t, 'tool_name', '') for t in trace_list)}"],
        tools_consulted=_unique_tools(getattr(t, "tool_name", "") for t in trace_list),
        metadata={},
        confidence=None,
        affected_acquisitions=[],
        changeset_id="",
        source="turn",
    )


def stamp_changeset(
    changeset: ChangeSet,
    traces: Iterable[Any] | None = None,
    explanation: CopilotExplanation | None = None,
) -> None:
    """Attach provenance onto a ChangeSet without changing apply/validate."""
    names = _unique_tools(
        list(changeset.tools_consulted or [])
        + [getattr(t, "tool_name", "") for t in (traces or [])]
        + [changeset.tool_name]
    )
    changeset.tools_consulted = names
    if explanation is not None:
        if not changeset.evidence:
            changeset.evidence = list(explanation.evidence)
        if changeset.confidence is None:
            changeset.confidence = explanation.confidence


def _from_classification(rec: Mapping[str, Any], tools: list[str]) -> CopilotExplanation:
    inferred = rec.get("inferred") if isinstance(rec.get("inferred"), dict) else {}
    observed = rec.get("observed") if isinstance(rec.get("observed"), dict) else {}
    uid = str(rec.get("series_uid") or "")
    label = str(inferred.get("label") or rec.get("label") or "")
    datatype = str(inferred.get("datatype") or rec.get("datatype") or "")
    suffix = str(inferred.get("suffix") or rec.get("suffix") or "")
    if rec.get("ambiguous"):
        decision = f"Ambiguous classification ({label or 'unclassified'})"
    elif rec.get("unclassified"):
        decision = "Unclassified acquisition"
    else:
        decision = f"Classified as {label or datatype or 'unknown'}"
        if datatype or suffix:
            decision += f" → {datatype or '—'}/{suffix or '—'}"
    evidence = [str(x) for x in (rec.get("evidence") or []) if str(x).strip()]
    reasoning = str(rec.get("reasoning") or "").strip()
    if reasoning and reasoning not in evidence:
        evidence.append(reasoning)
    conf = rec.get("confidence")
    try:
        confidence = None if conf is None else float(conf)
    except (TypeError, ValueError):
        confidence = None
    return CopilotExplanation(
        decision=decision,
        evidence=evidence,
        tools_consulted=tools,
        metadata=sanitize_metadata(
            {
                "series_uid": uid,
                "label": label,
                "datatype": datatype,
                "suffix": suffix,
                "series_description": observed.get("series_description") or "",
                "protocol_name": observed.get("protocol_name") or "",
                "sequence_type": observed.get("sequence_type") or "",
                "ambiguous": rec.get("ambiguous"),
                "unclassified": rec.get("unclassified"),
            }
        ),
        confidence=confidence,
        affected_acquisitions=[uid] if uid else [],
        changeset_id="",
        source="mapping",
    )


def _from_proposals(proposals: list[Any], tools: list[str]) -> CopilotExplanation:
    first = next((p for p in proposals if isinstance(p, Mapping)), None)
    if first is None:
        return CopilotExplanation(
            decision="No mapping proposals were generated.",
            tools_consulted=tools,
            source="mapping",
        )
    proposed = first.get("proposed") if isinstance(first.get("proposed"), dict) else {}
    uid = str(first.get("series_uid") or "")
    datatype = str(proposed.get("datatype") or "")
    suffix = str(proposed.get("suffix") or "")
    decision = f"Proposed mapping {datatype or '—'}/{suffix or '—'}"
    if len(proposals) > 1:
        decision += f" ({len(proposals)} acquisitions)"
    evidence = [str(x) for x in (first.get("evidence") or []) if str(x).strip()]
    for warn in first.get("warnings") or []:
        if str(warn).strip():
            evidence.append(f"warning: {warn}")
    conf = first.get("confidence")
    try:
        confidence = None if conf is None else float(conf)
    except (TypeError, ValueError):
        confidence = None
    affected = [
        str(p.get("series_uid"))
        for p in proposals
        if isinstance(p, Mapping) and p.get("series_uid")
    ]
    return CopilotExplanation(
        decision=decision,
        evidence=evidence,
        tools_consulted=tools,
        metadata=sanitize_metadata(
            {
                "series_uid": uid,
                "datatype": datatype,
                "suffix": suffix,
                "task": proposed.get("task") or "",
                "run": proposed.get("run") or "",
                "ambiguous": first.get("ambiguous"),
            }
        ),
        confidence=confidence,
        affected_acquisitions=affected,
        changeset_id="",
        source="mapping",
    )


def _from_audit(payload: Mapping[str, Any], tools: list[str]) -> CopilotExplanation:
    findings = [f for f in (payload.get("findings") or []) if isinstance(f, Mapping)]
    n = int(payload.get("n_findings") or len(findings))
    decision = f"Dataset audit: {n} finding{'s' if n != 1 else ''}"
    evidence: list[str] = []
    affected: list[str] = []
    for finding in findings:
        code = finding.get("code") or finding.get("id") or "finding"
        severity = finding.get("severity") or ""
        ev = finding.get("evidence") or []
        line = f"{severity}: {code}".strip(": ")
        if ev:
            line += " — " + "; ".join(str(x) for x in ev[:3])
        evidence.append(line)
        for item in finding.get("affected") or []:
            if isinstance(item, Mapping) and (item.get("series_uid") or item.get("uid")):
                affected.append(str(item.get("series_uid") or item.get("uid")))
            elif isinstance(item, str) and item.strip():
                affected.append(item)
    return CopilotExplanation(
        decision=decision,
        evidence=evidence,
        tools_consulted=tools,
        metadata=sanitize_metadata(
            {
                "n_acquisitions": payload.get("n_acquisitions"),
            }
        ),
        confidence=None,
        affected_acquisitions=_dedupe(affected),
        changeset_id="",
        source="turn",
    )


def _sanitize_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        if _looks_like_absolute_path(value):
            return None
        return value
    if isinstance(value, Mapping):
        return sanitize_metadata(value)
    if isinstance(value, list):
        cleaned = [_sanitize_value(v) for v in value]
        return [v for v in cleaned if v is not None]
    return None


def _looks_like_absolute_path(value: str) -> bool:
    if value.startswith("/") and "/" in value[1:]:
        return True
    if len(value) > 2 and value[1] == ":" and value[0].isalpha():
        return True
    return False


def _fmt(value: Any) -> str:
    if value is None or value == "":
        return "—"
    return str(value)


def _unique_tools(names: Iterable[Any]) -> list[str]:
    out: list[str] = []
    for name in names:
        text = str(name or "").strip()
        if text and text not in out:
            out.append(text)
    return out


def _dedupe(items: Iterable[str]) -> list[str]:
    out: list[str] = []
    for item in items:
        if item and item not in out:
            out.append(item)
    return out
