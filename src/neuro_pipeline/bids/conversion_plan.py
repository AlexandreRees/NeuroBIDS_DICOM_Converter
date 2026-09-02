"""In-memory BIDS conversion plan (never modifies DICOM)."""

from __future__ import annotations

import copy
import json
import logging
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

from neuro_pipeline.bids.entities_manager import BIDSEntityResolver
from neuro_pipeline.bids.naming import (
    build_bids_target,
    build_fallback_nifti_target,
    dwi_acquisition,
    is_adc_series,
    sanitize_bids_label,
    unique_stem,
)
from neuro_pipeline.bids.subject_manager import SubjectManager
from neuro_pipeline.models import DicomSeries

LOGGER = logging.getLogger(__name__)

_LABEL_RE = re.compile(r"^[A-Za-z0-9]+$")
_RUN_RE = re.compile(r"_run-([A-Za-z0-9]+)(?:_|$)")
_EDITABLE_FIELDS = frozenset(
    {
        "subject",
        "session",
        "task",
        "run",
        "acquisition",
        "direction",
        "datatype",
        "suffix",
        "include_in_conversion",
    }
)


@dataclass(slots=True)
class PlanValidationIssue:
    """One validation problem in a conversion plan."""

    level: str  # "error" | "warning"
    message: str
    series_uid: str = ""


@dataclass(slots=True)
class PlanValidationResult:
    """Outcome of :meth:`BIDSConversionPlan.validate`."""

    ok: bool
    issues: list[PlanValidationIssue] = field(default_factory=list)

    @property
    def errors(self) -> list[PlanValidationIssue]:
        return [i for i in self.issues if i.level == "error"]

    @property
    def warnings(self) -> list[PlanValidationIssue]:
        return [i for i in self.issues if i.level == "warning"]

    def summary(self) -> str:
        if self.ok and not self.issues:
            return "Plan is valid."
        lines = [f"{i.level.upper()}: {i.message}" for i in self.issues]
        return "\n".join(lines)


@dataclass(slots=True)
class PlannedAcquisition:
    """One planned BIDS output derived from a discovered DICOM series."""

    source_series_uid: str
    source_series_number: int | None
    source_series_description: str
    source_patient_id: str = ""
    source_protocol_name: str = ""
    source_sequence_type: str = "unknown"
    source_smart_name: str = ""
    source_subject_folder: str = ""
    original_patient_id: str = ""
    subject: str = ""
    session: str = ""
    datatype: str = ""
    suffix: str = ""
    task: str = ""
    run: str = ""
    acquisition: str = ""
    direction: str = ""
    intended_filename: str = ""
    include_in_conversion: bool = True
    confidence_score: float = 0.0
    classification_source: str = ""
    naming_rule_applied: str = ""

    def entity_overrides(self) -> dict[str, str]:
        out: dict[str, str] = {}
        for key in ("datatype", "suffix", "task", "run", "acquisition", "direction"):
            val = getattr(self, key)
            if val not in (None, ""):
                out[key] = str(val)
        return out

    def to_user_dict(self) -> dict[str, Any]:
        """Serialize user-editable choices only (never DICOM paths)."""
        return {
            "series_uid": self.source_series_uid,
            "subject": self.subject,
            "session": self.session,
            "datatype": self.datatype,
            "suffix": self.suffix,
            "task": self.task,
            "run": self.run,
            "acquisition": self.acquisition,
            "direction": self.direction,
            "include": self.include_in_conversion,
            "intended_filename": self.intended_filename,
            "naming_rule_applied": self.naming_rule_applied,
        }

    def clone(self) -> PlannedAcquisition:
        return copy.deepcopy(self)


@dataclass(slots=True)
class BIDSConversionPlan:
    """Predicted BIDS layout + optional user edits (DICOM input stays read-only)."""

    items: list[PlannedAcquisition] = field(default_factory=list)
    dataset_root: str = ""
    output_root: str = ""
    _baseline: list[PlannedAcquisition] = field(default_factory=list, repr=False)
    _series_by_uid: dict[str, DicomSeries] = field(default_factory=dict, repr=False)
    _validated: bool = False

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    @classmethod
    def from_series(
        cls,
        series_list: Sequence[DicomSeries],
        *,
        dataset_root: Path | str = "",
        output_root: Path | str = "",
        subject_override: str = "",
        session_override: str = "",
        entity_resolver: BIDSEntityResolver | None = None,
        subject_manager: SubjectManager | None = None,
        naming_rules: "SmartNamingRulesEngine | None" = None,
    ) -> BIDSConversionPlan:
        """Build an automatic plan from classified ``DicomSeries`` objects.

        Entity priority: user naming rules → classifier/resolver → default BIDS helpers.
        Never touches DICOM files.
        """
        from neuro_pipeline.bids.naming_rules import SmartNamingRulesEngine

        resolver = entity_resolver or BIDSEntityResolver()
        subjects = subject_manager or SubjectManager()
        rules_engine = naming_rules
        if rules_engine is None:
            # Optional layer — empty rules ⇒ identical to previous behaviour.
            try:
                rules_engine = SmartNamingRulesEngine.load()
            except Exception:  # noqa: BLE001
                rules_engine = SmartNamingRulesEngine([])
        plan = cls(
            dataset_root=str(dataset_root or ""),
            output_root=str(output_root or ""),
        )
        ordered = _sorted_series(series_list)
        unique_patients = {s.patient_id for s in ordered}
        apply_subject = bool((subject_override or "").strip()) and len(unique_patients) <= 1
        session_label = _normalize_session(subjects, session_override)

        for series in ordered:
            uid = series.series_instance_uid or series.display_name
            plan._series_by_uid[uid] = series
            if apply_subject:
                subject = _normalize_subject(subjects, subject_override)
            else:
                subject = _normalize_subject(
                    subjects, sanitize_bids_label(series.patient_id, fallback="unknown")
                )

            overrides = _resolve_auto_entities(
                series,
                resolver=resolver,
                subject=subject,
                session=session_label,
            )
            # Classifier / resolver first, then user rules win.
            rule_name = ""
            if rules_engine is not None and rules_engine.rules:
                overrides, rule_name = rules_engine.apply_to_entities(series, overrides)

            item = PlannedAcquisition(
                source_series_uid=uid,
                source_series_number=series.series_number,
                source_series_description=series.series_description or series.protocol_name,
                source_patient_id=series.patient_id or "",
                source_protocol_name=series.protocol_name or "",
                source_sequence_type=series.sequence_type or "unknown",
                source_smart_name=series.smart_name or "",
                source_subject_folder=getattr(series, "source_subject_folder", "") or "",
                original_patient_id=(
                    getattr(series, "dicom_patient_id", "") or ""
                ),
                subject=str(overrides.get("subject") or subject),
                session=str(overrides.get("session") or session_label or ""),
                datatype=str(overrides.get("datatype") or series.sequence_type or ""),
                suffix=str(overrides.get("suffix") or ""),
                task=str(overrides.get("task") or ""),
                run=str(overrides.get("run") or ""),
                acquisition=str(overrides.get("acquisition") or ""),
                direction=str(overrides.get("direction") or ""),
                include_in_conversion=True,
                confidence_score=float(
                    series.sequence_confidence or series.detection_confidence or 0.0
                ),
                classification_source=_classification_source(series),
                naming_rule_applied=rule_name,
            )
            # Fill suffix/task/direction defaults via naming helpers when still empty
            _fill_defaults_from_target(item, series)
            # Ensure DWI (incl. ADC maps classified as dwi) always get an acq label
            if (item.datatype or "").lower() == "dwi" and not item.acquisition:
                item.acquisition = dwi_acquisition(series)
            if is_adc_series(series) and not item.acquisition:
                item.acquisition = dwi_acquisition(series)
            # Re-apply rule actions so defaults do not overwrite explicit rule outputs
            if rule_name and rules_engine is not None:
                match = rules_engine.match(series)
                if match is not None:
                    for key, value in match.actions.items():
                        if key in {
                            "datatype",
                            "suffix",
                            "task",
                            "run",
                            "acquisition",
                            "direction",
                            "subject",
                            "session",
                        }:
                            setattr(item, key, value)
                    item.naming_rule_applied = match.rule.name
            plan.items.append(item)

        plan.refresh_filenames(seed_existing_from_output=True)
        plan._baseline = [item.clone() for item in plan.items]
        plan._validated = False
        return plan

    # ------------------------------------------------------------------
    # Mutations (in-memory only)
    # ------------------------------------------------------------------

    def get(self, series_uid: str) -> PlannedAcquisition | None:
        for item in self.items:
            if item.source_series_uid == series_uid:
                return item
        return None

    def apply_edit(self, series_uid: str, **fields: Any) -> PlannedAcquisition:
        """Apply user edits to one planned item. Invalid keys are ignored."""
        item = self.get(series_uid)
        if item is None:
            raise KeyError(f"Unknown series_uid in plan: {series_uid}")
        for key, value in fields.items():
            if key not in _EDITABLE_FIELDS:
                continue
            if key == "include_in_conversion":
                item.include_in_conversion = bool(value)
            elif key in {"subject", "session", "task", "run", "acquisition", "direction", "datatype", "suffix"}:
                setattr(item, key, "" if value is None else str(value).strip())
        self._validated = False
        return item

    def refresh_filenames(self, *, seed_existing_from_output: bool = False) -> None:
        """Recalculate ``intended_filename`` from current entities (no DICOM I/O).

        Included series always receive a usable NIfTI filename. When raw BIDS
        naming is unavailable (ADC, unclassified), a deterministic fallback is
        generated — BIDS-invalid ≠ conversion-invalid.
        """
        used: dict[tuple[str, str], set[str]] = defaultdict(set)
        if seed_existing_from_output and self.output_root:
            root = Path(self.output_root)
            if root.is_dir():
                for existing in root.rglob("*.nii.gz"):
                    try:
                        rel = existing.relative_to(root)
                    except ValueError:
                        continue
                    if len(rel.parts) >= 3 and rel.parts[0].startswith("sub-"):
                        used[("_disk", "")].add(existing.name[: -len(".nii.gz")])

        for item in self.items:
            if not item.include_in_conversion:
                item.intended_filename = ""
                continue
            series = self._series_by_uid.get(item.source_series_uid)
            if series is None:
                series = _synthetic_series(item)
            subject = sanitize_bids_label(item.subject.removeprefix("sub-"), fallback="")
            session = (item.session or "").removeprefix("ses-").strip() or None
            if not subject:
                subject = "unknown"
                item.subject = subject

            # Auto-fill DWI acquisition before building targets
            dtype = (item.datatype or series.sequence_type or "").lower()
            if dtype == "dwi" or is_adc_series(series):
                auto_acq = dwi_acquisition(series)
                current = sanitize_bids_label(item.acquisition, fallback="")
                if not current:
                    item.acquisition = auto_acq
                elif current.lower() != auto_acq.lower() and current.lower() in auto_acq.lower():
                    # Prefer the richer deterministic label over truncated rule labels
                    item.acquisition = auto_acq

            target = build_bids_target(
                series,
                subject,
                session,
                entity_overrides=item.entity_overrides(),
            )
            used_fallback = False
            if target is None:
                # No raw-BIDS target (ADC / unclassified) → still convert to NIfTI
                target = build_fallback_nifti_target(
                    series,
                    subject,
                    session,
                    run=item.run or None,
                )
                used_fallback = True
                item.datatype = item.datatype or target.datatype
            else:
                item.datatype = target.datatype

            key = (subject, session or "")
            # Mirror exporter: auto-unique when user did not set run
            if item.run:
                stem = target.filename_stem
                # Still avoid colliding with an already-claimed stem
                if stem in used[key] or stem in used[("_disk", "")]:
                    stem = unique_stem(used[key] | used[("_disk", "")], stem)
                    extracted = _run_from_stem(stem)
                    if extracted:
                        item.run = extracted
            else:
                stem = unique_stem(used[key] | used[("_disk", "")], target.filename_stem)
                extracted = _run_from_stem(stem)
                if extracted:
                    item.run = extracted
            used[key].add(stem)
            # Keep suffix aligned with final stem token when empty
            if not item.suffix and "_" in stem:
                item.suffix = stem.rsplit("_", 1)[-1]
            if used_fallback and not item.naming_rule_applied:
                item.naming_rule_applied = "fallback_nifti"
            item.intended_filename = f"{stem}.nii.gz"

            # Ultimate safety net — must never leave an included series nameless
            if not item.intended_filename.strip():
                uid = (item.source_series_uid or "x").replace(".", "")
                frag = sanitize_bids_label(uid[-12:], fallback="series")
                parts = [f"sub-{subject}"]
                if session:
                    parts.append(f"ses-{session}")
                parts.append(f"series-{frag}")
                stem = "_".join(parts)
                stem = unique_stem(used[key] | used[("_disk", "")], stem)
                used[key].add(stem)
                item.intended_filename = f"{stem}.nii.gz"
        self._validated = False

    def reset_changes(self) -> None:
        """Discard user modifications and restore the automatic plan."""
        self.items = [item.clone() for item in self._baseline]
        self._validated = False

    def mark_validated(self, ok: bool = True) -> None:
        self._validated = bool(ok)

    @property
    def is_validated(self) -> bool:
        return self._validated

    # ------------------------------------------------------------------
    # Validation / queries
    # ------------------------------------------------------------------

    def validate(self) -> PlanValidationResult:
        """Check duplicate filenames, labels, required entities, run consistency.

        ``ok`` reflects *BIDS plan* validity only. Callers must not abort
        DICOM→NIfTI conversion solely because ``ok`` is False.
        """
        issues: list[PlanValidationIssue] = []
        included = [i for i in self.items if i.include_in_conversion]
        if not included:
            issues.append(
                PlanValidationIssue("error", "No series are included for conversion.")
            )

        seen_names: dict[str, str] = {}
        for item in included:
            uid = item.source_series_uid
            subject = (item.subject or "").removeprefix("sub-").strip()
            session = (item.session or "").removeprefix("ses-").strip()
            if not subject or not _LABEL_RE.fullmatch(subject):
                issues.append(
                    PlanValidationIssue(
                        "error",
                        f"Invalid subject label for series {item.source_series_description!r}.",
                        uid,
                    )
                )
            if session and not _LABEL_RE.fullmatch(session):
                issues.append(
                    PlanValidationIssue(
                        "error",
                        f"Invalid session label for series {item.source_series_description!r}.",
                        uid,
                    )
                )
            datatype = (item.datatype or "").lower()
            non_raw_bids = datatype in {"", "unknown", "derivatives", "other"}
            if datatype not in {"anat", "func", "dwi", "fmap"}:
                issues.append(
                    PlanValidationIssue(
                        "warning" if item.intended_filename else "error",
                        (
                            f"Non-BIDS / fallback datatype {datatype!r} for "
                            f"{item.source_series_description!r}."
                            if non_raw_bids
                            else f"Missing/invalid BIDS datatype for "
                            f"{item.source_series_description!r}."
                        ),
                        uid,
                    )
                )
            if datatype == "func" and not sanitize_bids_label(item.task, fallback=""):
                issues.append(
                    PlanValidationIssue(
                        "error",
                        f"Func series requires task: {item.source_series_description!r}.",
                        uid,
                    )
                )
            if datatype == "fmap" and not sanitize_bids_label(item.direction, fallback=""):
                issues.append(
                    PlanValidationIssue(
                        "warning",
                        f"Fmap series missing direction: {item.source_series_description!r}.",
                        uid,
                    )
                )
            if datatype == "dwi" and not sanitize_bids_label(item.acquisition, fallback=""):
                issues.append(
                    PlanValidationIssue(
                        "warning",
                        f"DWI series missing acquisition label: {item.source_series_description!r}.",
                        uid,
                    )
                )
            if is_adc_series(_synthetic_series(item)) or (
                "adc" in (item.source_series_description or "").lower()
            ):
                issues.append(
                    PlanValidationIssue(
                        "warning",
                        f"ADC excluded from raw BIDS (NIfTI conversion still allowed): "
                        f"{item.source_series_description!r}.",
                        uid,
                    )
                )
            for label_name, label_val in (
                ("task", item.task),
                ("run", item.run),
                ("acquisition", item.acquisition),
                ("direction", item.direction),
                ("suffix", item.suffix),
            ):
                if label_val and not _LABEL_RE.fullmatch(str(label_val).removeprefix(f"{label_name}-")):
                    # direction/suffix may be short tokens; require alnum
                    cleaned = sanitize_bids_label(str(label_val), fallback="")
                    if cleaned != str(label_val).removeprefix(f"{label_name}-"):
                        # Fallback descriptive stems may contain underscores in suffix token
                        if non_raw_bids and label_name == "suffix":
                            issues.append(
                                PlanValidationIssue(
                                    "warning",
                                    f"Non-BIDS fallback suffix {label_val!r} for "
                                    f"{item.source_series_description!r}.",
                                    uid,
                                )
                            )
                        else:
                            issues.append(
                                PlanValidationIssue(
                                    "error",
                                    f"Invalid BIDS {label_name} label {label_val!r} "
                                    f"for {item.source_series_description!r}.",
                                    uid,
                                )
                            )
            if not item.intended_filename:
                # Should be unreachable after refresh_filenames() for included series
                issues.append(
                    PlanValidationIssue(
                        "error",
                        f"No planned filename for {item.source_series_description!r}.",
                        uid,
                    )
                )
                continue
            elif non_raw_bids or (item.naming_rule_applied or "") == "fallback_nifti":
                issues.append(
                    PlanValidationIssue(
                        "warning",
                        f"Non-BIDS fallback filename {item.intended_filename!r} for "
                        f"{item.source_series_description!r}.",
                        uid,
                    )
                )
            key = f"{subject}|{session}|{item.intended_filename}"
            if key in seen_names:
                issues.append(
                    PlanValidationIssue(
                        "error",
                        f"Duplicate planned filename {item.intended_filename!r} "
                        f"(also used by series {seen_names[key]}).",
                        uid,
                    )
                )
            else:
                seen_names[key] = item.source_series_description or uid

            if item.run:
                run_clean = str(item.run).removeprefix("run-")
                if not run_clean.isdigit():
                    issues.append(
                        PlanValidationIssue(
                            "warning",
                            f"Run label {item.run!r} is not numeric for "
                            f"{item.source_series_description!r}.",
                            uid,
                        )
                    )

        # Recommend explicit runs when several series share entities
        groups: dict[tuple, list[PlannedAcquisition]] = defaultdict(list)
        for item in included:
            groups[
                (
                    item.subject,
                    item.session,
                    item.datatype,
                    item.suffix,
                    item.task,
                    item.acquisition,
                    item.direction,
                )
            ].append(item)
        for _key, members in groups.items():
            if len(members) < 2:
                continue
            filenames = {m.intended_filename for m in members if m.intended_filename}
            if len(filenames) < len(members):
                # Duplicate filenames already reported above.
                continue
            if any(not str(m.run or "").strip() for m in members):
                issues.append(
                    PlanValidationIssue(
                        "warning",
                        "Multiple series share BIDS entities; consider setting unique run "
                        f"labels ({members[0].source_series_description!r}, …).",
                        members[0].source_series_uid,
                    )
                )

        ok = not any(i.level == "error" for i in issues)
        self._validated = ok
        return PlanValidationResult(ok=ok, issues=issues)

    def included_series(self, series_list: Sequence[DicomSeries]) -> list[DicomSeries]:
        """Return series that remain included for conversion."""
        include = {
            i.source_series_uid
            for i in self.items
            if i.include_in_conversion
        }
        out: list[DicomSeries] = []
        for series in series_list:
            uid = series.series_instance_uid or series.display_name
            if uid in include:
                out.append(series)
        return out

    def filter_for_patient(self, patient_id: str) -> BIDSConversionPlan:
        """Return a shallow plan containing only items for one DICOM PatientID."""
        items = [i.clone() for i in self.items if i.source_patient_id == patient_id]
        baseline = [i.clone() for i in self._baseline if i.source_patient_id == patient_id]
        series = {
            uid: s
            for uid, s in self._series_by_uid.items()
            if s.patient_id == patient_id
        }
        return BIDSConversionPlan(
            items=items,
            dataset_root=self.dataset_root,
            output_root=self.output_root,
            _baseline=baseline,
            _series_by_uid=series,
            _validated=self._validated,
        )

    def tree_paths(self) -> list[str]:
        """Relative preview paths for included series (no files written)."""
        paths: list[str] = []
        for item in self.items:
            if not item.include_in_conversion or not item.intended_filename:
                continue
            sub = f"sub-{(item.subject or '').removeprefix('sub-')}"
            parts = [sub]
            session = (item.session or "").removeprefix("ses-").strip()
            if session:
                parts.append(f"ses-{session}")
            parts.append(item.datatype or "unknown")
            parts.append(item.intended_filename)
            paths.append("/".join(parts))
        return paths

    # ------------------------------------------------------------------
    # JSON I/O (user choices only — never writes into DICOM folders)
    # ------------------------------------------------------------------

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "version": 1,
            "dataset_root": self.dataset_root,
            "output_root": self.output_root,
            "items": [item.to_user_dict() for item in self.items],
        }

    def save_json(self, path: Path | str) -> Path:
        out = Path(path)
        if self.dataset_root:
            try:
                out.resolve().relative_to(Path(self.dataset_root).resolve())
                raise ValueError(
                    "Refusing to write conversion_plan.json inside the DICOM input folder."
                )
            except ValueError as exc:
                if "Refusing" in str(exc):
                    raise
                # relative_to failed → path is outside dataset_root — OK
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(self.to_json_dict(), indent=2) + "\n", encoding="utf-8")
        return out

    def apply_user_json(self, data: dict[str, Any] | list[Any]) -> None:
        """Apply saved user choices onto the current automatic plan."""
        items_data: list[dict[str, Any]]
        if isinstance(data, list):
            items_data = [d for d in data if isinstance(d, dict)]
        else:
            raw = data.get("items")
            if isinstance(raw, list):
                items_data = [d for d in raw if isinstance(d, dict)]
            elif "series_uid" in data:
                items_data = [data]
            else:
                items_data = []
        by_uid = {d.get("series_uid") or d.get("source_series_uid"): d for d in items_data}
        for item in self.items:
            payload = by_uid.get(item.source_series_uid)
            if not payload:
                continue
            self.apply_edit(
                item.source_series_uid,
                subject=str(payload.get("subject", item.subject)).removeprefix("sub-"),
                session=str(payload.get("session", item.session) or "").removeprefix("ses-"),
                task=payload.get("task", item.task),
                run=payload.get("run", item.run),
                acquisition=payload.get("acquisition", item.acquisition),
                direction=payload.get("direction", item.direction),
                datatype=payload.get("datatype", item.datatype),
                suffix=payload.get("suffix", item.suffix),
                include_in_conversion=payload.get(
                    "include",
                    payload.get("include_in_conversion", item.include_in_conversion),
                ),
            )
        self.refresh_filenames()

    @classmethod
    def load_json(
        cls,
        path: Path | str,
        series_list: Sequence[DicomSeries],
        *,
        dataset_root: Path | str = "",
        output_root: Path | str = "",
        subject_override: str = "",
        session_override: str = "",
    ) -> BIDSConversionPlan:
        """Rebuild automatic plan from series, then apply JSON user choices."""
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        plan = cls.from_series(
            series_list,
            dataset_root=dataset_root or (data.get("dataset_root") if isinstance(data, dict) else ""),
            output_root=output_root or (data.get("output_root") if isinstance(data, dict) else ""),
            subject_override=subject_override,
            session_override=session_override,
        )
        if isinstance(data, (dict, list)):
            plan.apply_user_json(data)
        return plan


def _sorted_series(series_list: Sequence[DicomSeries]) -> list[DicomSeries]:
    return sorted(
        series_list,
        key=lambda s: (
            s.patient_id or "",
            s.series_number if s.series_number is not None else 10**9,
            s.series_description or "",
            s.series_instance_uid or "",
        ),
    )


def _classification_source(series: DicomSeries) -> str:
    if series.detection_plugin:
        return f"plugin:{series.detection_plugin}"
    if series.fine_sequence_type:
        return f"SequenceClassifier:{series.fine_sequence_type}"
    if series.sequence_type:
        return f"SequenceClassifier:{series.sequence_type}"
    return "unknown"


def _normalize_subject(manager: SubjectManager, value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        return "unknown"
    try:
        return manager.validate_subject_id(raw)
    except ValueError:
        return sanitize_bids_label(raw, fallback="unknown")


def _normalize_session(manager: SubjectManager, value: str) -> str | None:
    raw = (value or "").strip()
    if not raw:
        return None
    try:
        return manager.validate_session_id(raw)
    except ValueError:
        cleaned = raw.removeprefix("ses-").strip()
        return cleaned or None


def _resolve_auto_entities(
    series: DicomSeries,
    *,
    resolver: BIDSEntityResolver,
    subject: str,
    session: str | None,
) -> dict[str, str]:
    resolved = resolver.resolve(
        dicom_metadata={
            "ProtocolName": series.protocol_name,
            "SeriesDescription": series.series_description,
            "SequenceName": series.smart_name,
        },
        user_input={"subject": subject, "session": session},
    )
    out = resolved.to_dict()
    if series.sequence_type and series.sequence_type != "unknown":
        if out.get("datatype") in {None, "", "unknown"}:
            out["datatype"] = series.sequence_type
        else:
            out["datatype"] = series.sequence_type
    return {k: str(v) for k, v in out.items() if v}


def _fill_defaults_from_target(item: PlannedAcquisition, series: DicomSeries) -> None:
    target = build_bids_target(
        series,
        item.subject,
        item.session or None,
        entity_overrides=item.entity_overrides(),
    )
    if target is None:
        return
    item.datatype = item.datatype or target.datatype
    if not item.suffix and "_" in target.filename_stem:
        item.suffix = target.filename_stem.rsplit("_", 1)[-1]
    # Pull task/acq/dir tokens when missing
    stem = target.filename_stem
    if not item.task:
        m = re.search(r"_task-([A-Za-z0-9]+)", stem)
        if m:
            item.task = m.group(1)
    if not item.acquisition:
        m = re.search(r"_acq-([A-Za-z0-9]+)", stem)
        if m:
            item.acquisition = m.group(1)
    if not item.direction:
        m = re.search(r"_dir-([A-Za-z0-9]+)", stem)
        if m:
            item.direction = m.group(1)


def _run_from_stem(stem: str) -> str:
    m = _RUN_RE.search(stem)
    return m.group(1) if m else ""


def _synthetic_series(item: PlannedAcquisition) -> DicomSeries:
    """Minimal series stand-in when rebuilding filenames without live objects."""
    root = Path(".")
    return DicomSeries(
        patient_id=item.source_patient_id or "unknown",
        study_description="",
        series_description=item.source_series_description,
        protocol_name=item.source_protocol_name,
        series_number=item.source_series_number,
        acquisition_number=None,
        modality="MR",
        num_images=0,
        source_dir=root,
        sample_file=root / "x.dcm",
        sequence_type=item.source_sequence_type or item.datatype or "unknown",
        smart_name=item.source_smart_name,
        series_instance_uid=item.source_series_uid,
    )
