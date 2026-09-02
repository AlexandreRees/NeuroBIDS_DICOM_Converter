"""Shared Copilot types and plan fingerprinting (no filesystem I/O)."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from neuro_pipeline.bids.conversion_plan import BIDSConversionPlan, PlannedAcquisition


def plan_fingerprint(plan: BIDSConversionPlan) -> str:
    """Stable hash of editable plan state for stale-ChangeSet detection."""
    payload = [
        item.to_user_dict()
        | {
            "source_series_description": item.source_series_description,
            "source_sequence_type": item.source_sequence_type,
            "confidence_score": item.confidence_score,
            "classification_source": item.classification_source,
        }
        for item in plan.items
    ]
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def snapshot_items(plan: BIDSConversionPlan) -> list[dict[str, Any]]:
    return [item.to_user_dict() for item in plan.items]


def clone_plan(plan: BIDSConversionPlan) -> BIDSConversionPlan:
    """Deep-copy an in-memory plan (items + series cache). Never touches DICOM."""
    cloned = BIDSConversionPlan(
        items=[item.clone() for item in plan.items],
        dataset_root=plan.dataset_root,
        output_root=plan.output_root,
    )
    cloned._series_by_uid = dict(getattr(plan, "_series_by_uid", {}) or {})
    cloned._baseline = [item.clone() for item in getattr(plan, "_baseline", [])]
    cloned._validated = False
    return cloned


def apply_edits_to_plan(
    plan: BIDSConversionPlan,
    edits: list[tuple[str, dict[str, Any]]],
    *,
    refresh: bool = True,
) -> None:
    """Apply ``(series_uid, fields)`` edits via existing ``apply_edit`` API."""
    for series_uid, fields in edits:
        plan.apply_edit(series_uid, **fields)
    if refresh:
        plan.refresh_filenames()


def item_key(item: PlannedAcquisition) -> str:
    return item.source_series_uid
