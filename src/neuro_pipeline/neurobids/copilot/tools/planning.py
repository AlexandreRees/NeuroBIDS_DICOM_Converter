"""Planning tools — deterministic mapping proposals (no LLM invention)."""

from __future__ import annotations

from typing import Any, Mapping

from neuro_pipeline.bids.entities_manager import BIDSEntityResolver
from neuro_pipeline.bids.naming import (
    build_bids_target,
    build_fallback_nifti_target,
    dwi_acquisition,
    is_adc_series,
)
from neuro_pipeline.bids.naming_rules import SmartNamingRulesEngine
from neuro_pipeline.neurobids.copilot.session import CopilotSession
from neuro_pipeline.neurobids.copilot.tools.base import Tool, ToolKind, ToolResult, fail, ok


class ProposeBidsMappingTool(Tool):
    name = "propose_bids_mapping"
    description = (
        "Propose BIDS mapping for one or more acquisitions using the existing "
        "deterministic classifier / entity resolver / naming helpers. "
        "Does not invent mappings and does not modify the plan."
    )
    kind = ToolKind.PLANNING
    input_schema = {
        "type": "object",
        "properties": {
            "series_uid": {"type": "string"},
            "series_uids": {"type": "array", "items": {"type": "string"}},
        },
        "additionalProperties": False,
    }
    output_schema = {"type": "object", "properties": {"proposals": {"type": "array"}}}

    def execute(self, session: CopilotSession, params: Mapping[str, Any] | None = None) -> ToolResult:
        params = params or {}
        uids: list[str] = []
        if params.get("series_uid"):
            uids.append(str(params["series_uid"]))
        if params.get("series_uids"):
            uids.extend(str(u) for u in params["series_uids"])
        uids = list(dict.fromkeys(uids))
        if not uids:
            return fail(self.name, "series_uid or series_uids is required")

        resolver = BIDSEntityResolver()
        try:
            rules = SmartNamingRulesEngine.load()
        except Exception:  # noqa: BLE001
            rules = SmartNamingRulesEngine([])

        series_map = session.series_by_uid()
        proposals: list[dict[str, Any]] = []
        warnings: list[str] = []

        for uid in uids:
            item = session.plan.get(uid)
            series = series_map.get(uid)
            if item is None and series is None:
                warnings.append(f"Unknown series_uid: {uid}")
                continue
            if series is None:
                warnings.append(f"No DicomSeries metadata cached for {uid}; using plan fields only.")
                proposals.append(
                    {
                        "series_uid": uid,
                        "current": None if item is None else item.to_user_dict(),
                        "proposed": None if item is None else item.to_user_dict(),
                        "confidence": getattr(item, "confidence_score", 0.0) if item else 0.0,
                        "evidence": ["plan_only"],
                        "warnings": ["Missing series metadata; proposal mirrors current plan."],
                        "ambiguous": False,
                    }
                )
                continue

            resolved = resolver.resolve(
                dicom_metadata={
                    "ProtocolName": series.protocol_name,
                    "SeriesDescription": series.series_description,
                    "SequenceName": series.smart_name,
                },
                user_input={
                    "subject": (item.subject if item else "") or "",
                    "session": (item.session if item else "") or "",
                },
            )
            overrides = {
                "datatype": resolved.datatype,
                "suffix": resolved.suffix,
                "task": resolved.task or "",
                "run": resolved.run or "",
                "acquisition": resolved.acquisition or "",
                "direction": resolved.direction or "",
                "subject": (item.subject if item else "") or "",
                "session": (item.session if item else "") or "",
            }
            if series.sequence_type and series.sequence_type != "unknown":
                overrides["datatype"] = series.sequence_type
            rule_name = ""
            if rules.rules:
                overrides, rule_name = rules.apply_to_entities(series, overrides)

            subject = str(overrides.get("subject") or (item.subject if item else "") or "unknown")
            session_label = str(overrides.get("session") or (item.session if item else "") or "") or None
            subject_bare = subject.removeprefix("sub-")
            session_bare = session_label.removeprefix("ses-") if session_label else None

            entity_overrides = {
                k: str(overrides.get(k) or "")
                for k in ("datatype", "suffix", "task", "run", "acquisition", "direction")
                if overrides.get(k)
            }
            target = build_bids_target(
                series,
                subject_bare,
                session_bare,
                entity_overrides=entity_overrides or None,
            )
            used_fallback = False
            evidence = [
                f"sequence_type={series.sequence_type}",
                f"fine_sequence_type={series.fine_sequence_type}",
                f"resolver_pattern={resolved.matched_pattern or 'none'}",
            ]
            if rule_name:
                evidence.append(f"naming_rule={rule_name}")
            if target is None:
                target = build_fallback_nifti_target(
                    series,
                    subject_bare,
                    session_bare,
                    run=str(overrides.get("run") or "") or None,
                )
                used_fallback = True
                evidence.append("fallback_nifti_target")
            if is_adc_series(series):
                evidence.append("adc_detected")
                if not entity_overrides.get("acquisition"):
                    entity_overrides["acquisition"] = dwi_acquisition(series)

            proposed = {
                "series_uid": uid,
                "subject": subject_bare,
                "session": session_bare or "",
                "datatype": (target.datatype if target else "") or str(overrides.get("datatype") or ""),
                "suffix": str(overrides.get("suffix") or ""),
                "task": str(overrides.get("task") or ""),
                "run": str(overrides.get("run") or ""),
                "acquisition": str(overrides.get("acquisition") or ""),
                "direction": str(overrides.get("direction") or ""),
                "intended_filename": (
                    f"{target.filename_stem}.nii.gz" if target is not None else ""
                ),
                "include": True if item is None else item.include_in_conversion,
                "naming_rule_applied": rule_name,
            }
            # Prefer entity tokens embedded in the stem when overrides left blanks
            if target is not None:
                stem = target.filename_stem
                if not proposed["task"] and "_task-" in stem:
                    proposed["task"] = stem.split("_task-")[1].split("_")[0]
                if not proposed["run"] and "_run-" in stem:
                    proposed["run"] = stem.split("_run-")[1].split("_")[0]
                if not proposed["suffix"]:
                    proposed["suffix"] = stem.split("_")[-1]

            current = None if item is None else item.to_user_dict()
            prop_warnings: list[str] = []
            if used_fallback:
                prop_warnings.append("Raw BIDS target unavailable; fallback NIfTI naming proposed.")
            if series.requires_manual_mapping:
                prop_warnings.append("Series flagged as requiring manual mapping.")
            if not series.convertible_to_nifti:
                prop_warnings.append("Series may not be convertible to NIfTI.")

            ambiguous = bool(series.requires_manual_mapping) or (
                (series.sequence_confidence or 0.0) < 0.5 and series.sequence_type == "unknown"
            )
            proposals.append(
                {
                    "series_uid": uid,
                    "current": current,
                    "proposed": proposed,
                    "confidence": float(series.sequence_confidence or series.detection_confidence or 0.0),
                    "evidence": evidence,
                    "warnings": prop_warnings,
                    "ambiguous": ambiguous,
                }
            )

        if not proposals:
            return fail(self.name, "No proposals could be generated.", warnings=warnings)
        return ok(self.name, {"proposals": proposals}, warnings=warnings)
