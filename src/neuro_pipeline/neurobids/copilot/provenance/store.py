"""Persistent JSONL store + JSON export for Copilot provenance."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from neuro_pipeline.config.paths import resolve_writable_log_dir
from neuro_pipeline.neurobids.copilot.provenance.schema import (
    PROVENANCE_SCHEMA_VERSION,
    RECORD_DECISION,
    RECORD_TURN,
)

LOGGER = logging.getLogger(__name__)


def provenance_enabled() -> bool:
    raw = (os.environ.get("NEUROBIDS_COPILOT_PROVENANCE") or "1").strip().lower()
    return raw not in {"0", "false", "off", "no", "disabled"}


def default_provenance_dir() -> Path:
    from neuro_pipeline.config.paths import user_copilot_provenance_root

    try:
        return user_copilot_provenance_root()
    except Exception:
        return resolve_writable_log_dir() / "copilot_provenance"


class CopilotProvenanceStore:
    """Append-only JSONL provenance log with JSON bundle export."""

    def __init__(self, root: Path | str | None = None) -> None:
        self.root = Path(root) if root is not None else default_provenance_dir()
        self.root.mkdir(parents=True, exist_ok=True)
        self.events_path = self.root / "events.jsonl"
        self._index: dict[str, list[dict[str, Any]]] = {}

    def append(self, record: dict[str, Any]) -> Path:
        if int(record.get("schema_version") or 0) != PROVENANCE_SCHEMA_VERSION:
            raise ValueError(
                f"Unsupported provenance schema_version={record.get('schema_version')!r}; "
                f"expected {PROVENANCE_SCHEMA_VERSION}"
            )
        line = json.dumps(record, ensure_ascii=False, default=str) + "\n"
        with self.events_path.open("a", encoding="utf-8") as fh:
            fh.write(line)
        turn_id = str(record.get("turn_id") or "")
        if turn_id:
            self._index.setdefault(turn_id, []).append(record)
        LOGGER.info(
            "neurobids_copilot_provenance type=%s turn=%s event=%s",
            record.get("record_type"),
            turn_id or "-",
            record.get("event_id"),
        )
        return self.events_path

    def read_all(self) -> list[dict[str, Any]]:
        if not self.events_path.exists():
            return []
        rows: list[dict[str, Any]] = []
        for line in self.events_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
        return rows

    def records_for_turn(self, turn_id: str) -> list[dict[str, Any]]:
        tid = str(turn_id or "")
        return [r for r in self.read_all() if str(r.get("turn_id") or "") == tid]

    def decisions_for_changeset(self, changeset_id: str) -> list[dict[str, Any]]:
        cid = str(changeset_id or "")
        out = []
        for row in self.read_all():
            if row.get("record_type") != RECORD_DECISION:
                continue
            if str(row.get("changeset_id") or "") == cid:
                out.append(row)
                continue
            cs = row.get("changeset") or {}
            if str(cs.get("id") or "") == cid:
                out.append(row)
        return out

    def export_json(
        self,
        destination: Path | str,
        *,
        turn_ids: Iterable[str] | None = None,
    ) -> Path:
        """Export a versioned JSON bundle suitable for audit/share (no secrets)."""
        dest = Path(destination)
        dest.parent.mkdir(parents=True, exist_ok=True)
        rows = self.read_all()
        if turn_ids is not None:
            wanted = {str(t) for t in turn_ids}
            rows = [r for r in rows if str(r.get("turn_id") or "") in wanted]
        payload = {
            "schema_version": PROVENANCE_SCHEMA_VERSION,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "n_records": len(rows),
            "record_types": {
                RECORD_TURN: sum(1 for r in rows if r.get("record_type") == RECORD_TURN),
                RECORD_DECISION: sum(
                    1 for r in rows if r.get("record_type") == RECORD_DECISION
                ),
            },
            "records": rows,
        }
        dest.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False, default=str) + "\n",
            encoding="utf-8",
        )
        return dest


def default_provenance_store() -> CopilotProvenanceStore | None:
    if not provenance_enabled():
        return None
    try:
        return CopilotProvenanceStore()
    except OSError as exc:
        LOGGER.warning("Copilot provenance store unavailable: %s", exc)
        return None
