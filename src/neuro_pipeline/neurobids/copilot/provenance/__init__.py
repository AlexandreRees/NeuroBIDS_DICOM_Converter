"""Versioned Copilot provenance logging (privacy-safe, exportable).

Records the controlled path:

  request → model response → tool calls/args/results → ChangeSet →
  approval/rejection → applied result

Never stores API keys, DICOM pixel bytes, absolute DICOM paths, or PatientName.
"""

from __future__ import annotations

from neuro_pipeline.neurobids.copilot.provenance.sanitize import sanitize_for_provenance
from neuro_pipeline.neurobids.copilot.provenance.schema import (
    PROVENANCE_SCHEMA_VERSION,
    build_decision_record,
    build_turn_record,
    compact_changeset,
)
from neuro_pipeline.neurobids.copilot.provenance.store import (
    CopilotProvenanceStore,
    default_provenance_store,
    provenance_enabled,
)

__all__ = [
    "PROVENANCE_SCHEMA_VERSION",
    "CopilotProvenanceStore",
    "build_decision_record",
    "build_turn_record",
    "compact_changeset",
    "default_provenance_store",
    "provenance_enabled",
    "sanitize_for_provenance",
]
