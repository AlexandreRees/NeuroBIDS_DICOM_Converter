"""CSV exporter for DICOM inventory (series sheet + optional protocol sheet)."""

from __future__ import annotations

import csv
from pathlib import Path

from neuro_pipeline.inventory.models import (
    PROTOCOL_COLUMNS,
    SERIES_INVENTORY_COLUMNS,
    InventoryResult,
)


def export_inventory_csv(
    result: InventoryResult,
    path: Path | str,
    *,
    include_protocol: bool = True,
) -> Path:
    """Write series inventory CSV; optionally also write a protocol CSV sibling."""
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(SERIES_INVENTORY_COLUMNS))
        writer.writeheader()
        for row in result.series_rows:
            writer.writerow({k: _fmt(v) for k, v in row.as_ordered().items()})

    if include_protocol:
        proto = out.with_name(out.stem + "_protocol_completeness.csv")
        with proto.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(PROTOCOL_COLUMNS))
            writer.writeheader()
            for row in result.protocol_rows:
                writer.writerow({k: _fmt(v) for k, v in row.as_ordered().items()})
    return out


def _fmt(value) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return "\\".join(str(v) for v in value)
    return str(value)
