"""Copilot session — binds tools to the live BIDSConversionPlan."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

from neuro_pipeline.bids.conversion_plan import BIDSConversionPlan, PlanValidationResult
from neuro_pipeline.models import DicomSeries
from neuro_pipeline.neurobids.dataset_context import DatasetContext
from neuro_pipeline.neurobids.copilot.plan_ops import plan_fingerprint
from neuro_pipeline.neurobids.curation.store import CurationRuleStore


@dataclass(slots=True)
class CopilotSession:
    """Runtime handle for deterministic Copilot tools.

    Holds the authoritative :class:`BIDSConversionPlan` (same object the
    conversion pipeline consumes). Never mutates DICOM files.
    """

    plan: BIDSConversionPlan
    series_list: list[DicomSeries] = field(default_factory=list)
    conversion_busy: bool = False
    detection_method: str = ""
    detection_reason: str = ""
    n_dicom_files: int = 0
    ui_selection: dict[str, str] = field(default_factory=dict)
    last_applied_changeset: Any | None = field(default=None, repr=False)
    curation_rules_path: Any | None = field(default=None, repr=False)
    _dataset_context: DatasetContext | None = field(default=None, repr=False)
    _rule_store: CurationRuleStore | None = field(default=None, repr=False)

    def set_conversion_busy(self, busy: bool) -> None:
        self.conversion_busy = bool(busy)

    def set_ui_selection(self, **kwargs: str) -> None:
        """Record the current GUI selection for Copilot context (metadata only)."""
        allowed = {
            "subject",
            "session",
            "series_uid",
            "description",
            "datatype",
            "suffix",
            "task",
        }
        self.ui_selection = {
            key: str(value).strip()
            for key, value in kwargs.items()
            if key in allowed and str(value or "").strip()
        }

    @property
    def fingerprint(self) -> str:
        return plan_fingerprint(self.plan)

    def dataset_context(self, *, refresh: bool = False) -> DatasetContext:
        if self._dataset_context is None or refresh:
            validation = self.plan.validate()
            self._dataset_context = DatasetContext.from_conversion_plan(
                self.plan,
                series_list=self.series_list,
                validation=validation,
                detection_method=self.detection_method,
                detection_reason=self.detection_reason,
                n_dicom_files=self.n_dicom_files,
            )
        return self._dataset_context

    def invalidate_context_cache(self) -> None:
        self._dataset_context = None

    def curation_store(self, *, refresh: bool = False) -> CurationRuleStore:
        """Dataset-scoped rule catalog (JSON; never written into DICOM)."""
        if self._rule_store is None or refresh:
            self._rule_store = CurationRuleStore.for_dataset(
                self.plan.dataset_root,
                path=self.curation_rules_path,
            )
        return self._rule_store

    def bind_rule_store(self, store: CurationRuleStore | None) -> None:
        self._rule_store = store

    def series_by_uid(self) -> dict[str, DicomSeries]:
        out: dict[str, DicomSeries] = {}
        for series in self.series_list:
            uid = series.series_instance_uid or series.display_name
            out[uid] = series
        # Fall back to plan cache
        for uid, series in getattr(self.plan, "_series_by_uid", {}).items():
            out.setdefault(uid, series)
        return out

    def ensure_not_busy(self) -> None:
        if self.conversion_busy:
            raise RuntimeError("Copilot mutations are blocked while conversion is running.")

    def validate_plan(self) -> PlanValidationResult:
        return self.plan.validate()

    def as_tool_state(self) -> dict[str, Any]:
        return {
            "conversion_busy": self.conversion_busy,
            "plan_fingerprint": self.fingerprint,
            "n_plan_items": len(self.plan.items),
            "n_series": len(self.series_list),
            "ui_selection": dict(self.ui_selection),
        }
