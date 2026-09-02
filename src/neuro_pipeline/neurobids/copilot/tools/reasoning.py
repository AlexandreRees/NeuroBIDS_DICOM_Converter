"""Read-only neuroimaging reasoning tools for NeuroBIDS Copilot.

Wraps existing SequenceClassifier + BIDSEntityResolver plus token evidence
already present on DicomSeries / PlannedAcquisition. Never invents DICOM
tags, BIDS entities, or pixel-derived facts. Never mutates the plan.
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Any, Mapping

from neuro_pipeline.bids.conversion_plan import PlannedAcquisition
from neuro_pipeline.bids.entities_manager import BIDSEntityResolver
from neuro_pipeline.dicom.sequence_classifier import SequenceClassifier
from neuro_pipeline.models import DicomSeries
from neuro_pipeline.neurobids.copilot.session import CopilotSession
from neuro_pipeline.neurobids.copilot.tools.base import Tool, ToolKind, ToolResult, fail, ok

# Observed-text tokens only. Missing tokens → omitted entities, never guessed.
_SBREF = re.compile(r"(?:^|[\s_-])sb[\s_-]*ref(?:[\s_-]|$)|single[\s_-]*band[\s_-]*ref", re.I)
_MULTI_ECHO = re.compile(r"multi[\s_-]*echo|meepi|me[\s_-]epi", re.I)
_ECHO = re.compile(r"(?:^|[\s_-])echo[-_]?(\d+)", re.I)
_RUN = re.compile(r"(?:^|[\s_-])run[-_]?(\d+)", re.I)
_ACQ = re.compile(r"(?:^|[\s_-])acq[-_]?([A-Za-z0-9]+)", re.I)
_PE_AP = re.compile(
    r"(?:^|[\s_-])ap(?:[\s_-]|$)|(?:^|[\s_-])dir[-_]?ap(?:[\s_-]|$)|anterior[\s_-]*posterior",
    re.I,
)
_PE_PA = re.compile(
    r"(?:^|[\s_-])pa(?:[\s_-]|$)|(?:^|[\s_-])dir[-_]?pa(?:[\s_-]|$)|posterior[\s_-]*anterior",
    re.I,
)
_T1_TOKEN = re.compile(r"mprage|mp2rage|t1w|t1[\s_-]|[\s_-]t1(?:[\s_-]|$)", re.I)
_T2_TOKEN = re.compile(r"t2w|t2[\s_-]|[\s_-]t2(?:[\s_-]|$)|(?:^|[\s_-])tse(?:[\s_-]|$)", re.I)
_FLAIR_TOKEN = re.compile(r"flair|darkfluid", re.I)
_REST_TOKEN = re.compile(r"(?:^|[\s_-])rest(?:ing)?(?:[\s_-]|$)|rsfmri", re.I)
_TASK_TOKEN = re.compile(r"(?:^|[\s_-])task(?:[\s_-]|$)|nback|movie", re.I)

_KIND_ENUM = (
    "t1w",
    "t2w",
    "flair",
    "bold",
    "rest",
    "task",
    "dwi",
    "fmap",
    "sbref",
    "multiecho",
    "ambiguous",
    "unclassified",
)

_POLICY = (
    "Tools report observed plan/series fields and deterministic inferences "
    "from SequenceClassifier, BIDSEntityResolver, and tokens in "
    "SeriesDescription/ProtocolName. Missing entities are omitted; they are "
    "never invented."
)


@lru_cache(maxsize=1)
def _classifier() -> SequenceClassifier:
    return SequenceClassifier()


@lru_cache(maxsize=1)
def _resolver() -> BIDSEntityResolver:
    return BIDSEntityResolver()


def reason_acquisition(session: CopilotSession, series_uid: str) -> dict[str, Any] | None:
    """Deterministic classification record, or None if the UID is unknown."""
    item = session.plan.get(series_uid)
    series = session.series_by_uid().get(series_uid)
    if item is None and series is None:
        return None
    return _reason_pair(series_uid, series, item)


def reason_all(session: CopilotSession) -> list[dict[str, Any]]:
    uids: list[str] = []
    for item in session.plan.items:
        uid = item.source_series_uid
        if uid and uid not in uids:
            uids.append(uid)
    for series in session.series_list:
        uid = series.series_instance_uid
        if uid and uid not in uids:
            uids.append(uid)
    out: list[dict[str, Any]] = []
    for uid in uids:
        rec = reason_acquisition(session, uid)
        if rec is not None:
            out.append(rec)
    return out


def filter_by_kind(records: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
    needle = (kind or "").strip().lower()
    if not needle or needle == "all":
        return list(records)
    return [rec for rec in records if _matches_kind(rec, needle)]


def _reason_pair(
    series_uid: str,
    series: DicomSeries | None,
    item: PlannedAcquisition | None,
) -> dict[str, Any]:
    description = _first(
        getattr(series, "series_description", "") if series else "",
        getattr(item, "source_series_description", "") if item else "",
    )
    protocol = _first(
        getattr(series, "protocol_name", "") if series else "",
        getattr(item, "source_protocol_name", "") if item else "",
    )
    blob = f"{description} {protocol}".strip()
    observed_seq = _first(
        getattr(series, "sequence_type", "") if series else "",
        getattr(item, "source_sequence_type", "") if item else "",
        "unknown",
    )
    observed_fine = _first(
        getattr(series, "fine_sequence_type", "") if series else "",
        "",
    )
    plan_entities = _nonempty_entities(
        {
            "datatype": getattr(item, "datatype", "") if item else "",
            "suffix": getattr(item, "suffix", "") if item else "",
            "task": getattr(item, "task", "") if item else "",
            "run": getattr(item, "run", "") if item else "",
            "acquisition": getattr(item, "acquisition", "") if item else "",
            "direction": getattr(item, "direction", "") if item else "",
        }
    )

    evidence: list[str] = []
    if description:
        evidence.append(f"series_description={description}")
    if protocol and protocol != description:
        evidence.append(f"protocol_name={protocol}")
    if observed_seq:
        evidence.append(f"sequence_type={observed_seq}")
    if observed_fine:
        evidence.append(f"fine_sequence_type={observed_fine}")
    for key, value in plan_entities.items():
        evidence.append(f"plan.{key}={value}")
    if series is None:
        evidence.append("plan_only")

    detailed = _classifier().classify_detailed(
        series_description=description,
        protocol_name=protocol,
        modality=_first(getattr(series, "modality", "") if series else "", "MR"),
    )
    for reason in detailed.reason:
        if reason:
            evidence.append(f"classifier:{reason}")

    resolved = _resolver().resolve(
        dicom_metadata={
            "ProtocolName": protocol,
            "SeriesDescription": description,
            "SequenceName": getattr(series, "smart_name", "") if series else "",
        }
    )
    if resolved.matched_pattern:
        evidence.append(f"resolver_pattern={resolved.matched_pattern}")
        if resolved.datatype:
            evidence.append(f"resolver.datatype={resolved.datatype}")
        if resolved.suffix:
            evidence.append(f"resolver.suffix={resolved.suffix}")

    is_sbref = bool(_SBREF.search(blob))
    if is_sbref:
        evidence.append("token=sbref")
    is_multiecho = bool(_MULTI_ECHO.search(blob) or _ECHO.search(blob))
    echo = _search_group(_ECHO, blob)
    if echo:
        evidence.append(f"token=echo-{echo}")
    if _MULTI_ECHO.search(blob):
        evidence.append("token=multi-echo")

    run = _first(plan_entities.get("run", ""), _search_group(_RUN, blob))
    if run and "plan.run=" not in " ".join(evidence):
        if _RUN.search(blob):
            evidence.append(f"token=run-{run}")
    acquisition = _first(plan_entities.get("acquisition", ""), _search_group(_ACQ, blob))
    if acquisition and f"plan.acquisition={acquisition}" not in evidence:
        if _ACQ.search(blob):
            evidence.append(f"token=acq-{acquisition}")

    pe, pe_evidence = _phase_encoding(blob, plan_entities.get("direction", ""))
    evidence.extend(pe_evidence)

    fine = detailed.type.value
    coarse = detailed.coarse.value
    confidence = float(detailed.confidence)
    series_conf = float(getattr(series, "sequence_confidence", 0.0) or 0.0) if series else 0.0
    if series_conf > 0:
        evidence.append(f"sequence_confidence={series_conf:.2f}")

    conflicting_anat = _conflicting_anat(blob)
    conflicting_func = bool(_REST_TOKEN.search(blob) and _TASK_TOKEN.search(blob))
    if conflicting_anat:
        evidence.append("conflicting_tokens=T1w+T2w")
    if conflicting_func:
        evidence.append("conflicting_tokens=rest+task")

    requires_manual = bool(getattr(series, "requires_manual_mapping", False) if series else False)
    if requires_manual:
        evidence.append("requires_manual_mapping=true")

    label, datatype, suffix, task_kind = _labels(
        coarse=coarse,
        fine=fine,
        plan=plan_entities,
        resolved_suffix=resolved.suffix or "",
        resolved_datatype=resolved.datatype or "",
        is_sbref=is_sbref,
        pe=pe,
    )
    observed_fine_u = (observed_fine or "").upper()
    observed_unknown = observed_seq == "unknown" and observed_fine_u in {
        "UNKNOWN",
        "SCOUT",
        "",
    }
    if (requires_manual or observed_unknown) and not is_sbref and observed_fine_u != "LOCALIZER":
        label = "unclassified"
        datatype = _first(plan_entities.get("datatype", ""), "unknown")
        suffix = plan_entities.get("suffix", "") or suffix
        task_kind = ""

    if is_sbref:
        confidence = max(confidence, 0.72)
    if is_multiecho:
        confidence = max(confidence, 0.7)
    if pe:
        confidence = max(confidence, 0.74)

    unclassified = _is_unclassified(
        coarse=coarse,
        fine=fine,
        plan_datatype=plan_entities.get("datatype", ""),
        is_sbref=is_sbref,
        label=label,
        observed_unknown=observed_unknown,
        observed_fine=observed_fine_u,
    )
    ambiguous = bool(
        requires_manual
        or conflicting_anat
        or conflicting_func
        or (unclassified and confidence < 0.5 and fine in {"UNKNOWN", ""})
        or (label == "unclassified" and observed_unknown)
    )
    if conflicting_anat:
        label = "ambiguous_anat"
        confidence = min(confidence, 0.45)
        unclassified = False
        ambiguous = True

    inferred_entities = _nonempty_entities(
        {
            "task": _first(plan_entities.get("task", ""), resolved.task or ""),
            "run": run,
            "acquisition": acquisition,
            "direction": pe or plan_entities.get("direction", ""),
            "echo": echo,
        }
    )
    # Never copy resolver/plan guesses into echo: echo is description-token only.
    if not echo:
        inferred_entities.pop("echo", None)

    reasoning = _reasoning_text(
        label=label,
        coarse=coarse,
        fine=fine,
        classifier_reasons=list(detailed.reason),
        is_sbref=is_sbref,
        is_multiecho=is_multiecho,
        pe=pe,
        ambiguous=ambiguous,
        unclassified=unclassified,
    )

    observed: dict[str, Any] = {
        "series_description": description,
        "protocol_name": protocol,
        "sequence_type": observed_seq,
        "fine_sequence_type": observed_fine,
        "plan_entities": plan_entities,
    }
    inferred: dict[str, Any] = {
        "coarse": coarse,
        "fine": fine,
        "label": label,
        "datatype": datatype,
        "suffix": suffix,
        "task_kind": task_kind,
        "is_sbref": is_sbref,
        "is_multiecho": is_multiecho,
        "phase_encoding": pe,
        "entities": inferred_entities,
    }
    if echo:
        inferred["echo"] = echo
    if run:
        inferred["run"] = run
    if acquisition:
        inferred["acquisition"] = acquisition
    if task_kind:
        inferred["task"] = _first(plan_entities.get("task", ""), task_kind)

    return {
        "series_uid": series_uid,
        "subject": getattr(item, "subject", "") if item else "",
        "session": getattr(item, "session", "") if item else "",
        "observed": observed,
        "inferred": inferred,
        "confidence": round(max(0.0, min(1.0, confidence)), 4),
        "evidence": evidence,
        "reasoning": reasoning,
        "ambiguous": ambiguous,
        "unclassified": unclassified,
        "policy": _POLICY,
    }


def _labels(
    *,
    coarse: str,
    fine: str,
    plan: dict[str, str],
    resolved_suffix: str,
    resolved_datatype: str,
    is_sbref: bool,
    pe: str,
) -> tuple[str, str, str, str]:
    suffix = _first(plan.get("suffix", ""), resolved_suffix)
    datatype = _first(plan.get("datatype", ""), resolved_datatype, coarse)
    task_kind = ""
    if is_sbref:
        return "SBRef", _first(datatype, "func"), _first(suffix, "sbref"), ""
    if fine == "ANAT_T1" or suffix == "T1w":
        return "T1w", "anat", _first(suffix, "T1w"), ""
    if fine == "FLAIR" or suffix.upper() == "FLAIR":
        return "FLAIR", "anat", "FLAIR", ""
    if fine == "ANAT_T2" or suffix == "T2w":
        return "T2w", "anat", _first(suffix, "T2w"), ""
    if fine in {"DWI", "DTI", "DWI_MULTI"} or coarse == "dwi":
        return "DWI", "dwi", _first(suffix, "dwi"), ""
    if fine == "FMAP" or coarse == "fmap":
        label = "fieldmap"
        if pe:
            label = f"fieldmap_{pe}"
        return label, "fmap", _first(suffix, "epi" if pe else "fmap"), ""
    if fine == "FMRI_REST" or (coarse == "func" and (plan.get("task") == "rest")):
        task_kind = "rest"
        return "BOLD_rest", "func", _first(suffix, "bold"), task_kind
    if fine == "FMRI_TASK" or coarse == "func":
        task_kind = "task" if fine == "FMRI_TASK" or plan.get("task") not in {"", "rest"} else "rest"
        if plan.get("task") == "rest":
            task_kind = "rest"
            return "BOLD_rest", "func", _first(suffix, "bold"), task_kind
        return "BOLD_task", "func", _first(suffix, "bold"), task_kind or "task"
    if fine == "LOCALIZER":
        return "localizer", _first(datatype, "unknown"), _first(suffix, "localizer"), ""
    return "unclassified", _first(datatype, "unknown"), suffix, ""


def _is_unclassified(
    *,
    coarse: str,
    fine: str,
    plan_datatype: str,
    is_sbref: bool,
    label: str = "",
    observed_unknown: bool = False,
    observed_fine: str = "",
) -> bool:
    if is_sbref:
        return False
    if label == "unclassified":
        return True
    if observed_unknown:
        return True
    dt = (plan_datatype or "").strip().lower()
    if fine in {"UNKNOWN", ""} and coarse in {"unknown", ""}:
        return True
    if fine == "LOCALIZER" or observed_fine == "LOCALIZER":
        return True
    if dt in {"", "unknown"} and coarse in {"unknown", ""}:
        return True
    if dt in {"", "unknown"} and fine in {"UNKNOWN", "LOCALIZER"}:
        return True
    return False


def _matches_kind(rec: dict[str, Any], kind: str) -> bool:
    inferred = rec.get("inferred") if isinstance(rec.get("inferred"), dict) else {}
    label = str(inferred.get("label") or "")
    suffix = str(inferred.get("suffix") or "")
    coarse = str(inferred.get("coarse") or "")
    task_kind = str(inferred.get("task_kind") or "")
    if kind == "t1w":
        return label == "T1w"
    if kind == "t2w":
        return label == "T2w"
    if kind == "flair":
        return label.upper() == "FLAIR"
    if kind == "sbref":
        return bool(inferred.get("is_sbref")) or label == "SBRef"
    if kind == "multiecho":
        return bool(inferred.get("is_multiecho"))
    if kind == "dwi":
        return label == "DWI" or coarse == "dwi"
    if kind == "fmap":
        return coarse == "fmap" or label.startswith("fieldmap")
    if kind == "rest":
        return (not inferred.get("is_sbref")) and (
            label == "BOLD_rest" or task_kind == "rest"
        )
    if kind == "task":
        return (not inferred.get("is_sbref")) and (
            label == "BOLD_task" or task_kind == "task"
        )
    if kind == "bold":
        return (not inferred.get("is_sbref")) and (
            label.startswith("BOLD") or suffix.lower() == "bold" or coarse == "func"
        )
    if kind == "ambiguous":
        return bool(rec.get("ambiguous"))
    if kind == "unclassified":
        return bool(rec.get("unclassified"))
    return False


def _phase_encoding(blob: str, plan_direction: str) -> tuple[str, list[str]]:
    evidence: list[str] = []
    plan = (plan_direction or "").strip().upper()
    ap = bool(_PE_AP.search(blob))
    pa = bool(_PE_PA.search(blob))
    if ap and pa:
        evidence.append("conflicting_tokens=AP+PA")
        if plan in {"AP", "PA"}:
            evidence.append(f"plan.direction={plan}")
            return plan, evidence
        return "", evidence
    if ap:
        evidence.append("token=AP")
        return "AP", evidence
    if pa:
        evidence.append("token=PA")
        return "PA", evidence
    if plan in {"AP", "PA", "LR", "RL", "IS", "SI"}:
        evidence.append(f"plan.direction={plan}")
        return plan, evidence
    return "", evidence


def _conflicting_anat(blob: str) -> bool:
    if _FLAIR_TOKEN.search(blob):
        return False
    return bool(_T1_TOKEN.search(blob) and _T2_TOKEN.search(blob))


def _reasoning_text(
    *,
    label: str,
    coarse: str,
    fine: str,
    classifier_reasons: list[str],
    is_sbref: bool,
    is_multiecho: bool,
    pe: str,
    ambiguous: bool,
    unclassified: bool,
) -> str:
    parts = [
        f"SequenceClassifier fine={fine} coarse={coarse}.",
    ]
    if classifier_reasons:
        parts.append("Classifier: " + "; ".join(classifier_reasons) + ".")
    if is_sbref:
        parts.append("SBRef token observed in series description/protocol.")
    if is_multiecho:
        parts.append("Multi-echo token or echo-N entity observed in description.")
    if pe:
        parts.append(f"Phase-encoding direction {pe} observed.")
    parts.append(f"Assigned label {label}.")
    if ambiguous:
        parts.append("Flagged ambiguous: do not invent a mapping.")
    if unclassified:
        parts.append("Unclassified for confident BIDS mapping.")
    return " ".join(parts)


def _nonempty_entities(values: Mapping[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in values.items():
        text = str(value or "").strip()
        if text and text.lower() not in {"none", "unknown"}:
            out[key] = text
    return out


def _first(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _search_group(pattern: re.Pattern[str], blob: str) -> str:
    match = pattern.search(blob or "")
    if not match:
        return ""
    for group in match.groups():
        if group:
            return str(group)
    return ""


def _public_record(rec: dict[str, Any]) -> dict[str, Any]:
    """Stable LLM-facing subset (no execute internals)."""
    inferred = dict(rec.get("inferred") or {})
    return {
        "series_uid": rec.get("series_uid"),
        "subject": rec.get("subject"),
        "session": rec.get("session"),
        "label": inferred.get("label"),
        "datatype": inferred.get("datatype"),
        "suffix": inferred.get("suffix"),
        "coarse": inferred.get("coarse"),
        "fine": inferred.get("fine"),
        "task_kind": inferred.get("task_kind"),
        "is_sbref": inferred.get("is_sbref"),
        "is_multiecho": inferred.get("is_multiecho"),
        "phase_encoding": inferred.get("phase_encoding") or None,
        "entities": inferred.get("entities") or {},
        "observed": rec.get("observed"),
        "inferred": inferred,
        "confidence": rec.get("confidence"),
        "evidence": list(rec.get("evidence") or []),
        "reasoning": rec.get("reasoning"),
        "ambiguous": rec.get("ambiguous"),
        "unclassified": rec.get("unclassified"),
    }


def _list_payload(records: list[dict[str, Any]], *, kind: str) -> dict[str, Any]:
    public = [_public_record(r) for r in records]
    return {
        "kind": kind,
        "n_matches": len(public),
        "classifications": public,
        "acquisitions": [
            {"series_uid": r["series_uid"], "label": r["label"], "subject": r["subject"]}
            for r in public
        ],
        "policy": _POLICY,
    }


class ClassifyAcquisitionTool(Tool):
    name = "classify_acquisition"
    description = (
        "Classify one acquisition (T1w/T2w/FLAIR, BOLD rest/task, DWI, "
        "fieldmap AP/PA, SBRef, multi-echo) with observed evidence, confidence, "
        "and reasoning. Read-only. Never invents metadata."
    )
    kind = ToolKind.READ_ONLY
    input_schema = {
        "type": "object",
        "properties": {"series_uid": {"type": "string"}},
        "required": ["series_uid"],
        "additionalProperties": False,
    }
    output_schema = {"type": "object", "properties": {"classification": {"type": "object"}}}

    def execute(self, session: CopilotSession, params: Mapping[str, Any] | None = None) -> ToolResult:
        uid = str((params or {}).get("series_uid") or "").strip()
        if not uid:
            return fail(self.name, "series_uid is required")
        rec = reason_acquisition(session, uid)
        if rec is None:
            return fail(self.name, f"Unknown series_uid: {uid}")
        return ok(self.name, {"classification": _public_record(rec), "policy": _POLICY})


class ClassifyAcquisitionsTool(Tool):
    name = "classify_acquisitions"
    description = (
        "Classify acquisitions in the loaded dataset. Optional kind filter: "
        "t1w, t2w, flair, bold, rest, task, dwi, fmap, sbref, multiecho, "
        "ambiguous, unclassified. Returns evidence and confidence per series. "
        "Read-only. Never invents metadata."
    )
    kind = ToolKind.READ_ONLY
    input_schema = {
        "type": "object",
        "properties": {
            "kind": {"type": "string", "enum": list(_KIND_ENUM)},
            "series_uid": {"type": "string"},
        },
        "additionalProperties": False,
    }
    output_schema = {"type": "object", "properties": {"classifications": {"type": "array"}}}

    def execute(self, session: CopilotSession, params: Mapping[str, Any] | None = None) -> ToolResult:
        params = dict(params or {})
        if params.get("series_uid"):
            rec = reason_acquisition(session, str(params["series_uid"]))
            if rec is None:
                return fail(self.name, f"Unknown series_uid: {params['series_uid']}")
            kind = str(params.get("kind") or "").strip().lower()
            records = [rec] if (not kind or _matches_kind(rec, kind)) else []
            return ok(self.name, _list_payload(records, kind=kind or "one"))
        kind = str(params.get("kind") or "").strip().lower()
        records = filter_by_kind(reason_all(session), kind)
        return ok(self.name, _list_payload(records, kind=kind or "all"))


class ListAnatomicalTool(Tool):
    name = "list_anatomical"
    description = (
        "List anatomical acquisitions. subtype: t1w, t2w, flair, or omit for all "
        "T1w/T2w/FLAIR. Returns evidence and confidence. Read-only."
    )
    kind = ToolKind.READ_ONLY
    input_schema = {
        "type": "object",
        "properties": {"subtype": {"type": "string", "enum": ["t1w", "t2w", "flair"]}},
        "additionalProperties": False,
    }
    output_schema = {"type": "object", "properties": {"classifications": {"type": "array"}}}

    def execute(self, session: CopilotSession, params: Mapping[str, Any] | None = None) -> ToolResult:
        subtype = str((params or {}).get("subtype") or "").strip().lower()
        records = reason_all(session)
        if subtype:
            records = filter_by_kind(records, subtype)
        else:
            records = [r for r in records if any(_matches_kind(r, k) for k in ("t1w", "t2w", "flair"))]
        return ok(self.name, _list_payload(records, kind=subtype or "anatomical"))


class ListFunctionalTool(Tool):
    name = "list_functional"
    description = (
        "List BOLD fMRI acquisitions. subtype: rest, task, or omit for all BOLD "
        "(excludes SBRef). Returns evidence and confidence. Read-only."
    )
    kind = ToolKind.READ_ONLY
    input_schema = {
        "type": "object",
        "properties": {"subtype": {"type": "string", "enum": ["rest", "task", "bold"]}},
        "additionalProperties": False,
    }
    output_schema = {"type": "object", "properties": {"classifications": {"type": "array"}}}

    def execute(self, session: CopilotSession, params: Mapping[str, Any] | None = None) -> ToolResult:
        subtype = str((params or {}).get("subtype") or "bold").strip().lower() or "bold"
        records = filter_by_kind(reason_all(session), subtype)
        return ok(self.name, _list_payload(records, kind=subtype))


class ListDwiTool(Tool):
    name = "list_dwi"
    description = "List DWI/DTI acquisitions with evidence and confidence. Read-only."
    kind = ToolKind.READ_ONLY
    input_schema = {"type": "object", "properties": {}, "additionalProperties": False}
    output_schema = {"type": "object", "properties": {"classifications": {"type": "array"}}}

    def execute(self, session: CopilotSession, params: Mapping[str, Any] | None = None) -> ToolResult:
        records = filter_by_kind(reason_all(session), "dwi")
        return ok(self.name, _list_payload(records, kind="dwi"))


class ListFieldmapsTool(Tool):
    name = "list_fieldmaps"
    description = (
        "List fieldmap acquisitions and AP/PA phase-encoding when evidenced by "
        "plan.direction or description tokens. Returns evidence and confidence. Read-only."
    )
    kind = ToolKind.READ_ONLY
    input_schema = {"type": "object", "properties": {}, "additionalProperties": False}
    output_schema = {"type": "object", "properties": {"classifications": {"type": "array"}}}

    def execute(self, session: CopilotSession, params: Mapping[str, Any] | None = None) -> ToolResult:
        records = filter_by_kind(reason_all(session), "fmap")
        return ok(self.name, _list_payload(records, kind="fmap"))


class ListSbrefTool(Tool):
    name = "list_sbref"
    description = (
        "List SBRef (single-band reference) acquisitions evidenced by description "
        "tokens. Returns evidence and confidence. Read-only. Never invents SBRef."
    )
    kind = ToolKind.READ_ONLY
    input_schema = {"type": "object", "properties": {}, "additionalProperties": False}
    output_schema = {"type": "object", "properties": {"classifications": {"type": "array"}}}

    def execute(self, session: CopilotSession, params: Mapping[str, Any] | None = None) -> ToolResult:
        records = filter_by_kind(reason_all(session), "sbref")
        return ok(self.name, _list_payload(records, kind="sbref"))


class ListMultiechoTool(Tool):
    name = "list_multiecho"
    description = (
        "List multi-echo acquisitions evidenced by echo-N / multi-echo tokens "
        "in series description or protocol. Returns evidence and confidence. Read-only."
    )
    kind = ToolKind.READ_ONLY
    input_schema = {"type": "object", "properties": {}, "additionalProperties": False}
    output_schema = {"type": "object", "properties": {"classifications": {"type": "array"}}}

    def execute(self, session: CopilotSession, params: Mapping[str, Any] | None = None) -> ToolResult:
        records = filter_by_kind(reason_all(session), "multiecho")
        return ok(self.name, _list_payload(records, kind="multiecho"))


class InspectEntitiesTool(Tool):
    name = "inspect_entities"
    description = (
        "Report observed BIDS entities (run, echo, acquisition, direction, task) "
        "from the conversion plan and description tokens. Omits missing entities. "
        "Read-only. Never invents metadata."
    )
    kind = ToolKind.READ_ONLY
    input_schema = {
        "type": "object",
        "properties": {"series_uid": {"type": "string"}},
        "additionalProperties": False,
    }
    output_schema = {"type": "object", "properties": {"entities": {"type": "array"}}}

    def execute(self, session: CopilotSession, params: Mapping[str, Any] | None = None) -> ToolResult:
        params = dict(params or {})
        if params.get("series_uid"):
            rec = reason_acquisition(session, str(params["series_uid"]))
            if rec is None:
                return fail(self.name, f"Unknown series_uid: {params['series_uid']}")
            records = [rec]
        else:
            records = reason_all(session)
        rows: list[dict[str, Any]] = []
        for rec in records:
            inferred = rec.get("inferred") or {}
            entities = dict(inferred.get("entities") or {})
            observed_plan = (rec.get("observed") or {}).get("plan_entities") or {}
            row_evidence = [
                e
                for e in rec.get("evidence") or []
                if e.startswith("plan.") or e.startswith("token=") or e.startswith("series_description=")
            ]
            rows.append(
                {
                    "series_uid": rec["series_uid"],
                    "subject": rec.get("subject"),
                    "session": rec.get("session"),
                    "entities": entities,
                    "observed_plan_entities": observed_plan,
                    "run": inferred.get("run") or entities.get("run"),
                    "echo": inferred.get("echo") or entities.get("echo"),
                    "acquisition": inferred.get("acquisition") or entities.get("acquisition"),
                    "direction": inferred.get("phase_encoding") or entities.get("direction"),
                    "task": inferred.get("task") or entities.get("task"),
                    "confidence": rec.get("confidence"),
                    "evidence": row_evidence or list(rec.get("evidence") or []),
                    "reasoning": rec.get("reasoning"),
                    "ambiguous": rec.get("ambiguous"),
                }
            )
        return ok(
            self.name,
            {
                "n_matches": len(rows),
                "entities": rows,
                "classifications": [_public_record(r) for r in records],
                "acquisitions": [{"series_uid": r["series_uid"]} for r in rows],
                "policy": _POLICY,
            },
        )


class ListAmbiguousAcquisitionsTool(Tool):
    name = "list_ambiguous_acquisitions"
    description = (
        "List ambiguous or unclassified acquisitions (unknown sequence, "
        "conflicting tokens, manual-mapping flags, low-confidence unknowns). "
        "include_unclassified=true (default) includes localizers/unknowns. "
        "Returns evidence and confidence. Read-only."
    )
    kind = ToolKind.READ_ONLY
    input_schema = {
        "type": "object",
        "properties": {
            "include_unclassified": {"type": "boolean"},
            "only_unclassified": {"type": "boolean"},
        },
        "additionalProperties": False,
    }
    output_schema = {"type": "object", "properties": {"classifications": {"type": "array"}}}

    def execute(self, session: CopilotSession, params: Mapping[str, Any] | None = None) -> ToolResult:
        params = dict(params or {})
        only_unclassified = bool(params.get("only_unclassified"))
        include_unclassified = True if params.get("include_unclassified") is None else bool(
            params.get("include_unclassified")
        )
        records = reason_all(session)
        if only_unclassified:
            records = [r for r in records if r.get("unclassified")]
            kind = "unclassified"
        elif include_unclassified:
            records = [r for r in records if r.get("ambiguous") or r.get("unclassified")]
            kind = "ambiguous_or_unclassified"
        else:
            records = [r for r in records if r.get("ambiguous")]
            kind = "ambiguous"
        return ok(self.name, _list_payload(records, kind=kind))


__all__ = [
    "ClassifyAcquisitionTool",
    "ClassifyAcquisitionsTool",
    "InspectEntitiesTool",
    "ListAmbiguousAcquisitionsTool",
    "ListAnatomicalTool",
    "ListDwiTool",
    "ListFieldmapsTool",
    "ListFunctionalTool",
    "ListMultiechoTool",
    "ListSbrefTool",
    "filter_by_kind",
    "reason_acquisition",
    "reason_all",
]
