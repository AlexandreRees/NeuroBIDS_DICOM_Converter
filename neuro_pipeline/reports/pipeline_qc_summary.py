"""Aggregate validation and QC outputs into a publication-ready HTML summary."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import pandas as pd

from neuro_pipeline.bids_constants import BIDS_SPEC_VERSION
from neuro_pipeline.reports.generator import write_html_report
from neuro_pipeline.utils.extensions import PIPELINE_VERSION
from neuro_pipeline.utils.paths import ProjectPaths

LOGGER = logging.getLogger(__name__)


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _load_csv(path: Path) -> pd.DataFrame:
    if not path.is_file():
        return pd.DataFrame()
    return pd.read_csv(path, dtype=str).fillna("")


def _conversion_overview(conversion: pd.DataFrame) -> dict[str, int]:
    if conversion.empty:
        return {
            "participants": 0,
            "sessions": 0,
            "converted_success": 0,
            "converted_failed": 0,
        }
    participants = conversion["participant_id"].nunique() if "participant_id" in conversion else 0
    session_cols = [c for c in ("participant_id", "session_label") if c in conversion.columns]
    sessions = (
        conversion.drop_duplicates(subset=session_cols).shape[0] if len(session_cols) == 2 else 0
    )
    status_col = conversion.get("status", pd.Series(dtype=str))
    return {
        "participants": int(participants),
        "sessions": int(sessions),
        "converted_success": int((status_col == "success").sum()),
        "converted_failed": int((status_col == "failed").sum()),
    }


def _modality_qc_status(qc_detail: pd.DataFrame, modality: str) -> str:
    if qc_detail.empty or "modality" not in qc_detail.columns:
        return "not run"
    subset = qc_detail[qc_detail["modality"] == modality]
    if subset.empty:
        return "no data"
    if "status" not in subset.columns:
        return "unknown"
    statuses = set(subset["status"].astype(str))
    if "fail" in statuses:
        return "fail"
    if "warn" in statuses:
        return "warn"
    if statuses <= {"pass"}:
        return "pass"
    return ", ".join(sorted(statuses))


def _blocked_modalities_summary(blocklist: dict[str, Any]) -> str:
    blocked = blocklist.get("blocked_modalities", blocklist)
    if not isinstance(blocked, dict) or not blocked:
        return "none"
    parts: list[str] = []
    for session_key, modalities in blocked.items():
        if not isinstance(modalities, dict):
            continue
        for modality, reasons in modalities.items():
            reason_text = "; ".join(reasons) if isinstance(reasons, list) else str(reasons)
            parts.append(f"{session_key}/{modality}: {reason_text}")
    return "; ".join(parts) if parts else "none"


def _provenance_summary(manifest: dict[str, Any]) -> dict[str, str]:
    provenance = manifest.get("provenance", manifest)
    software = provenance.get("software_versions", manifest.get("software_versions", {}))
    if not isinstance(software, dict):
        software = {}
    return {
        "pipeline version": str(provenance.get("pipeline_version", manifest.get("pipeline_version", PIPELINE_VERSION))),
        "git commit": str(provenance.get("git_commit", manifest.get("git_commit", "unknown"))),
        "Python version": str(provenance.get("python_version", manifest.get("python_version", "unknown"))),
        "dcm2niix version": str(software.get("dcm2niix", manifest.get("dcm2niix_version", "unknown"))),
        "BIDS version": str(provenance.get("bids_version", manifest.get("bids_version", BIDS_SPEC_VERSION))),
        "execution date": str(provenance.get("execution_date", manifest.get("generated_at", "unknown"))),
    }


def _acquisition_table(acquisition: pd.DataFrame) -> list[dict[str, str]]:
    if acquisition.empty:
        return []
    rows: list[dict[str, str]] = []
    for _, row in acquisition.iterrows():
        acquisition_label = str(row.get("expected_acquisition", "") or row.get("found_acquisition", ""))
        datatype = str(row.get("bids_datatype", "") or row.get("expected_datatype", ""))
        rows.append(
            {
                "participant": str(row.get("participant", row.get("participant_id", ""))),
                "session": str(row.get("session", row.get("session_label", ""))),
                "acquisition": acquisition_label,
                "datatype": datatype,
                "status": str(row.get("validation_status", row.get("status", ""))),
                "error message": str(row.get("error_message", "")),
            }
        )
    return rows


def _geometry_table(geometry: pd.DataFrame) -> list[dict[str, str]]:
    if geometry.empty:
        return []
    return geometry.head(500).to_dict(orient="records")


def build_qc_summary_payload(paths: ProjectPaths) -> dict[str, Any]:
    """Collect all inputs for the pipeline QC summary report."""
    conversion = _load_csv(paths.conversion_report_csv)
    acquisition = _load_csv(paths.acquisition_validation_csv)
    qc_detail = _load_csv(paths.qc_detail_csv)
    qc_summary = _load_csv(paths.qc_summary_csv)
    geometry = _load_csv(paths.geometry_validation_csv)
    blocklist = _load_json(paths.acquisition_blocklist_json)
    manifest = _load_json(paths.pipeline_manifest_json)
    acquisition_json = _load_json(paths.acquisition_validation_json)

    overview = _conversion_overview(conversion)
    geometry_errors = int((geometry.get("status", pd.Series(dtype=str)) == "error").sum()) if not geometry.empty else 0
    geometry_warnings = int((geometry.get("status", pd.Series(dtype=str)) == "warning").sum()) if not geometry.empty else 0

    summary: dict[str, Any] = {
        "participants": overview["participants"],
        "sessions": overview["sessions"],
        "successfully converted datasets": overview["converted_success"],
        "failed datasets": overview["converted_failed"],
        "anatomical QC status": _modality_qc_status(qc_detail, "anat"),
        "functional QC status": _modality_qc_status(qc_detail, "func"),
        "diffusion QC status": _modality_qc_status(qc_detail, "dwi"),
        "blocked modalities": _blocked_modalities_summary(blocklist),
        "acquisition validation passed": str(acquisition_json.get("passed", "unknown")),
        "geometry validation errors": geometry_errors,
        "geometry validation warnings": geometry_warnings,
        "QC volumes scanned": int(len(qc_detail)),
        "QC sessions summarized": int(len(qc_summary)),
    }
    summary.update(_provenance_summary(manifest))
    return {
        "summary": summary,
        "acquisition_rows": _acquisition_table(acquisition),
        "geometry_rows": _geometry_table(geometry),
    }


def generate_pipeline_qc_summary_html(paths: ProjectPaths) -> Path:
    """Write derivatives/qc/pipeline_qc_summary.html from existing pipeline artifacts."""
    paths.validate_writable(paths.derivatives / "qc")
    payload = build_qc_summary_payload(paths)
    output = paths.pipeline_qc_summary_html
    write_html_report(
        output,
        title="Neuro BIDS Pipeline QC Summary",
        summary=payload["summary"],
        sections=[
            ("Acquisition Summary", payload["acquisition_rows"]),
            ("Geometry Validation", payload["geometry_rows"]),
        ],
    )
    LOGGER.info("Wrote pipeline QC summary: %s", output)
    return output
