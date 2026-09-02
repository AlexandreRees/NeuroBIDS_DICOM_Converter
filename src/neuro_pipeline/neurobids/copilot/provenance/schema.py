"""Versioned JSON record builders for Copilot provenance."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from neuro_pipeline.logging.privacy import safe_folder_label
from neuro_pipeline.neurobids.copilot.provenance.sanitize import (
    sanitize_for_provenance,
    scrub_text,
    sha256_text,
)

PROVENANCE_SCHEMA_VERSION = 1
RECORD_TURN = "copilot_turn"
RECORD_DECISION = "changeset_decision"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def compact_changeset(changeset: Any) -> dict[str, Any] | None:
    """Compact, exportable ChangeSet metadata (no snapshots / no pixels)."""
    if changeset is None:
        return None
    status = getattr(getattr(changeset, "status", None), "value", None) or getattr(
        changeset, "status", None
    )
    preview = {}
    if hasattr(changeset, "preview"):
        try:
            preview = sanitize_for_provenance(changeset.preview() or {})
        except Exception:  # noqa: BLE001
            preview = {}
    return {
        "id": str(getattr(changeset, "id", "") or ""),
        "status": status,
        "tool_name": str(getattr(changeset, "tool_name", "") or ""),
        "reason": scrub_text(str(getattr(changeset, "reason", "") or ""))[:500],
        "plan_fingerprint": str(getattr(changeset, "plan_fingerprint", "") or ""),
        "n_edits": len(getattr(changeset, "edits", None) or []),
        "affected_subjects": list(getattr(changeset, "affected_subjects", None) or [])[:50],
        "affected_sessions": list(getattr(changeset, "affected_sessions", None) or [])[:50],
        "affected_acquisitions": list(getattr(changeset, "affected_acquisitions", None) or [])[:50],
        "preview": preview,
    }


def build_turn_record(
    *,
    turn_id: str,
    user_request: str,
    provider: str,
    model: str,
    dataset_root: Any = None,
    plan_fingerprint: str = "",
    model_responses: list[dict[str, Any]] | None = None,
    tool_calls: list[dict[str, Any]] | None = None,
    changeset: Any = None,
    stopped_reason: str = "",
    ok: bool = True,
    clarify: bool = False,
    error: dict[str, Any] | None = None,
    message: str = "",
) -> dict[str, Any]:
    """Build a schema-v1 turn provenance record."""
    request_text = scrub_text(user_request or "")
    return {
        "schema_version": PROVENANCE_SCHEMA_VERSION,
        "record_type": RECORD_TURN,
        "event_id": str(uuid4()),
        "turn_id": turn_id,
        "timestamp": _now(),
        "dataset_label": safe_folder_label(dataset_root),
        "plan_fingerprint": plan_fingerprint or "",
        "provider": provider or "",
        "model": model or "",
        "request": {
            "text": request_text[:2000],
            "text_sha256": sha256_text(request_text),
            "n_chars": len(request_text),
        },
        "model_responses": sanitize_for_provenance(list(model_responses or [])),
        "tool_calls": sanitize_for_provenance(list(tool_calls or [])),
        "changeset": compact_changeset(changeset),
        "decision": None,
        "outcome": {
            "ok": bool(ok),
            "clarify": bool(clarify),
            "stopped_reason": stopped_reason or "",
            "message": scrub_text(message or "")[:1000],
            "error": sanitize_for_provenance(error) if error else None,
        },
    }


def build_decision_record(
    *,
    turn_id: str,
    action: str,
    changeset: Any,
    status_before: str,
    message: str = "",
    applied_summary: dict[str, Any] | None = None,
    dataset_root: Any = None,
    plan_fingerprint_after: str = "",
) -> dict[str, Any]:
    """Build a schema-v1 ChangeSet decision record (applied vs rejected)."""
    action_norm = str(action or "").strip().lower()
    if action_norm not in {"applied", "rejected"}:
        raise ValueError(f"Unsupported decision action: {action!r}")
    cs = compact_changeset(changeset) or {}
    status_after = cs.get("status") or (
        "APPLIED" if action_norm == "applied" else "REJECTED"
    )
    return {
        "schema_version": PROVENANCE_SCHEMA_VERSION,
        "record_type": RECORD_DECISION,
        "event_id": str(uuid4()),
        "turn_id": turn_id,
        "timestamp": _now(),
        "dataset_label": safe_folder_label(dataset_root),
        "changeset_id": cs.get("id") or "",
        "decision": {
            "action": action_norm,
            "status_before": status_before,
            "status_after": status_after,
            "message": scrub_text(message or "")[:1000],
            "applied_summary": sanitize_for_provenance(applied_summary)
            if action_norm == "applied"
            else None,
            "plan_fingerprint_after": plan_fingerprint_after or "",
        },
        "changeset": cs,
    }
