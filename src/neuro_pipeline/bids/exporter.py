"""Export converted NIfTI outputs into a BIDS dataset layout."""

from __future__ import annotations

import csv
import json
import logging
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Sequence

from neuro_pipeline import __version__
from neuro_pipeline.bids.entities_manager import BIDSEntityResolver
from neuro_pipeline.bids.naming import (
    BidsTarget,
    build_bids_target,
    is_adc_series,
    unique_stem,
)
from neuro_pipeline.bids.subject_manager import SubjectManager
from neuro_pipeline.metadata.sidecar_manager import MetadataManager
from neuro_pipeline.models import ConversionResult, DicomSeries
from neuro_pipeline.utils.exceptions import NeuroPipelineError
from neuro_pipeline.utils.filesystem import ensure_writable_dir

LOGGER = logging.getLogger(__name__)

_SIDECARS = (".json", ".bval", ".bvec")


@dataclass(slots=True)
class BidsExportItem:
    """One exported NIfTI (+ sidecars) record."""

    series: DicomSeries
    source_nifti: Path
    target_nifti: Path
    copied_sidecars: list[Path] = field(default_factory=list)
    skipped: bool = False
    message: str = ""


@dataclass(slots=True)
class BidsExportResult:
    """Summary of a BIDS export pass."""

    bids_root: Path
    items: list[BidsExportItem] = field(default_factory=list)
    dataset_description: Path | None = None
    participants_tsv: Path | None = None
    readme: Path | None = None

    @property
    def exported(self) -> int:
        return sum(1 for i in self.items if not i.skipped)

    @property
    def skipped(self) -> int:
        return sum(1 for i in self.items if i.skipped)


class BIDSExporter:
    """Copy conversion outputs into a valid minimal BIDS dataset.

    Never overwrites existing files. Sidecars (JSON / bval / bvec) are preserved
    when present next to the source NIfTI. Session folders are optional.
    """

    def __init__(
        self,
        bids_root: Path | str,
        *,
        subject_id: str | None = None,
        session_id: str | None = None,
        entity_resolver: BIDSEntityResolver | None = None,
        subject_manager: SubjectManager | None = None,
        conversion_plan: "BIDSConversionPlan | None" = None,
    ) -> None:
        self.bids_root = Path(bids_root)
        self.subject_id = (subject_id or "").strip()
        self.session_id = (session_id or "").strip()
        self.entity_resolver = entity_resolver or BIDSEntityResolver()
        self.subject_manager = subject_manager or SubjectManager()
        self.metadata_manager = MetadataManager()
        self.conversion_plan = conversion_plan

    def export(
        self,
        conversion_results: Sequence[ConversionResult],
        *,
        dataset_name: str = "NeuroPipeline BIDS Dataset",
        conversion_plan: "BIDSConversionPlan | None" = None,
    ) -> BidsExportResult:
        plan = conversion_plan if conversion_plan is not None else self.conversion_plan
        root = ensure_writable_dir(self.bids_root, create=True)
        used_stems: set[str] = set()
        for existing in root.rglob("*.nii.gz"):
            try:
                rel = existing.relative_to(root)
            except ValueError:
                continue
            if len(rel.parts) >= 3 and rel.parts[0].startswith("sub-"):
                used_stems.add(existing.name[: -len(".nii.gz")])

        items: list[BidsExportItem] = []
        subjects: dict[str, dict[str, str]] = {}
        default_sub = (self.subject_id or "").strip()
        if not default_sub and plan is None:
            raise NeuroPipelineError(
                "Subject ID is required for BIDS export. Never infer from folder names."
            )
        default_sub_label = (
            self.subject_manager.validate_subject_id(default_sub) if default_sub else ""
        )
        global_session: str | None = None
        if self.session_id:
            global_session = self.subject_manager.validate_session_id(self.session_id)

        for result in conversion_results:
            if not result.success:
                continue
            series = result.series
            uid = series.series_instance_uid or series.display_name
            planned = plan.get(uid) if plan is not None else None
            if planned is not None and not planned.include_in_conversion:
                continue

            if planned is not None and planned.subject:
                sub_label = self.subject_manager.validate_subject_id(planned.subject)
                session_label = (
                    self.subject_manager.validate_session_id(planned.session)
                    if planned.session
                    else global_session
                )
                overrides = planned.entity_overrides()
            else:
                if not default_sub_label:
                    raise NeuroPipelineError(
                        "Subject ID is required for BIDS export. Never infer from folder names."
                    )
                sub_label = default_sub_label
                session_label = global_session
                overrides = self._resolve_entities(series)

            subjects.setdefault(
                sub_label,
                {
                    "participant_id": f"sub-{sub_label}",
                    "patient_id_token": series.patient_id or "",
                },
            )

            self.subject_manager.create_bids_subject(root, sub_label, session_label)

            for nifti in _iter_niftis(result.output_files):
                if is_adc_series(series, nifti_name=nifti.name):
                    item = self._export_adc_derivative(
                        series=series,
                        source_nifti=nifti,
                        subject_label=sub_label,
                    )
                    items.append(item)
                    continue

                target = build_bids_target(
                    series,
                    sub_label,
                    session_label,
                    entity_overrides=overrides,
                    nifti_name=nifti.name,
                )
                if target is None:
                    LOGGER.info(
                        "Skipping BIDS placement for unclassified series: %s",
                        series.display_name,
                    )
                    continue

                preferred_stem = None
                if planned is not None and planned.intended_filename:
                    preferred_stem = planned.intended_filename
                    for ext in (".nii.gz", ".nii"):
                        if preferred_stem.endswith(ext):
                            preferred_stem = preferred_stem[: -len(ext)]
                            break

                item = self._export_one(
                    series=series,
                    source_nifti=nifti,
                    target=target,
                    subject_label=sub_label,
                    session_label=session_label,
                    used_stems=used_stems,
                    preferred_stem=preferred_stem,
                )
                items.append(item)

        ds = self._write_dataset_description(root, dataset_name=dataset_name)
        participants = self._write_participants(root, subjects.values())
        readme = self._write_readme(root, dataset_name=dataset_name)

        return BidsExportResult(
            bids_root=root,
            items=items,
            dataset_description=ds,
            participants_tsv=participants,
            readme=readme,
        )

    def _resolve_entities(self, series: DicomSeries) -> dict[str, str]:
        resolved = self.entity_resolver.resolve(
            dicom_metadata={
                "ProtocolName": series.protocol_name,
                "SeriesDescription": series.series_description,
                "SequenceName": series.smart_name,
            },
            user_input={
                "subject": self.subject_id or None,
                "session": self.session_id or None,
            },
        )
        out = resolved.to_dict()
        # Prefer classifier datatype when known and resolver is unknown
        if series.sequence_type and series.sequence_type != "unknown":
            if out.get("datatype") in {None, "", "unknown"}:
                out["datatype"] = series.sequence_type
            elif out.get("datatype") != series.sequence_type:
                # Keep classifier as ground truth for layout; keep entity extras
                out["datatype"] = series.sequence_type
        return {k: str(v) for k, v in out.items() if v}

    def _export_adc_derivative(
        self,
        *,
        series: DicomSeries,
        source_nifti: Path,
        subject_label: str,
    ) -> BidsExportItem:
        """Copy ADC maps under derivatives/non-BIDS (excluded from BIDS tree)."""
        dest_dir = (
            self.bids_root
            / "derivatives"
            / "non-BIDS"
            / f"sub-{subject_label}"
            / "adc"
        )
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_nii = dest_dir / source_nifti.name
        if dest_nii.exists():
            return BidsExportItem(
                series=series,
                source_nifti=source_nifti,
                target_nifti=dest_nii,
                skipped=True,
                message="ADC exists in derivatives/non-BIDS — skipped",
            )
        shutil.copy2(source_nifti, dest_nii)
        copied: list[Path] = []
        for suffix in _SIDECARS:
            src_side = source_nifti.parent / f"{_nifti_stem(source_nifti)}{suffix}"
            if not src_side.exists():
                continue
            dest_side = dest_dir / f"{_nifti_stem(dest_nii)}{suffix}"
            if not dest_side.exists():
                shutil.copy2(src_side, dest_side)
                copied.append(dest_side)
        LOGGER.info("ADC retained outside BIDS: %s", dest_nii)
        return BidsExportItem(
            series=series,
            source_nifti=source_nifti,
            target_nifti=dest_nii,
            copied_sidecars=copied,
            skipped=False,
            message="adc→derivatives/non-BIDS",
        )

    def _export_one(
        self,
        *,
        series: DicomSeries,
        source_nifti: Path,
        target: BidsTarget,
        subject_label: str,
        session_label: str | None,
        used_stems: set[str],
        preferred_stem: str | None = None,
    ) -> BidsExportItem:
        if preferred_stem:
            stem = preferred_stem
        else:
            stem = unique_stem(used_stems, target.filename_stem)
        used_stems.add(stem)
        dest_dir = self.bids_root / f"sub-{subject_label}"
        if session_label:
            dest_dir = dest_dir / f"ses-{session_label}"
        dest_dir = dest_dir / target.datatype
        dest_dir.mkdir(parents=True, exist_ok=True)

        dest_nii = dest_dir / f"{stem}.nii.gz"
        if source_nifti.name.endswith(".nii") and not source_nifti.name.endswith(".nii.gz"):
            dest_nii = dest_dir / f"{stem}.nii"

        if dest_nii.exists():
            LOGGER.warning("BIDS target exists, not overwriting: %s", dest_nii.name)
            return BidsExportItem(
                series=series,
                source_nifti=source_nifti,
                target_nifti=dest_nii,
                skipped=True,
                message="Target exists — skipped (no overwrite)",
            )

        shutil.copy2(source_nifti, dest_nii)
        copied: list[Path] = []
        for suffix in _SIDECARS:
            src_side = source_nifti.parent / f"{_nifti_stem(source_nifti)}{suffix}"
            if not src_side.exists():
                continue
            dest_side = dest_dir / f"{stem}{suffix}"
            copied_path = self.metadata_manager.copy_sidecar(src_side, dest_side)
            if copied_path is not None:
                copied.append(copied_path)

        rel_ses = f"ses-{session_label}/" if session_label else ""
        LOGGER.info(
            "BIDS export: %s → sub-%s/%s%s/%s",
            source_nifti.name,
            subject_label,
            rel_ses,
            target.datatype,
            dest_nii.name,
        )
        return BidsExportItem(
            series=series,
            source_nifti=source_nifti,
            target_nifti=dest_nii,
            copied_sidecars=copied,
            skipped=False,
            message="exported",
        )

    def _write_dataset_description(self, root: Path, *, dataset_name: str) -> Path:
        path = root / "dataset_description.json"
        if path.exists():
            LOGGER.info("dataset_description.json exists — not overwriting")
            return path
        payload = {
            "Name": dataset_name,
            "BIDSVersion": "1.8.0",
            "DatasetType": "raw",
            "GeneratedBy": [
                {
                    "Name": "NeuroPipeline DICOM Converter",
                    "Version": __version__,
                    "Description": "Optional BIDS export from dcm2niix conversion outputs",
                }
            ],
            "HowToAcknowledge": "Please cite the software and acquisition site as appropriate.",
            "License": "Insufficient information — fill before public release",
        }
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        return path

    def _write_participants(
        self,
        root: Path,
        rows: Iterable[dict[str, str]],
    ) -> Path:
        path = root / "participants.tsv"
        new_rows = {r["participant_id"]: r for r in rows}
        existing: dict[str, dict[str, str]] = {}
        if path.exists():
            with path.open("r", encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle, delimiter="\t")
                for row in reader:
                    pid = row.get("participant_id", "")
                    if pid:
                        existing[pid] = dict(row)
            for pid, row in new_rows.items():
                if pid not in existing:
                    existing[pid] = {
                        "participant_id": pid,
                        "sex": "n/a",
                        "age": "n/a",
                    }
            ordered = [existing[k] for k in sorted(existing)]
        else:
            ordered = [
                {
                    "participant_id": r["participant_id"],
                    "sex": "n/a",
                    "age": "n/a",
                }
                for r in sorted(new_rows.values(), key=lambda x: x["participant_id"])
            ]

        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=["participant_id", "sex", "age"],
                delimiter="\t",
                lineterminator="\n",
            )
            writer.writeheader()
            writer.writerows(ordered)
        return path

    def _write_readme(self, root: Path, *, dataset_name: str) -> Path:
        path = root / "README"
        if path.exists():
            LOGGER.info("README exists — not overwriting")
            return path
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        path.write_text(
            (
                f"{dataset_name}\n"
                f"{'=' * len(dataset_name)}\n\n"
                "This BIDS dataset was generated by NeuroPipeline DICOM Converter "
                f"(v{__version__}) on {stamp}.\n\n"
                "Notes\n"
                "-----\n"
                "- Source DICOM files were not modified.\n"
                "- NIfTI files were produced with dcm2niix; JSON sidecars are preserved when present.\n"
                "- Participant sex/age are placeholders (n/a); update before sharing.\n"
                "- Review and complete `dataset_description.json` before public release.\n"
            ),
            encoding="utf-8",
        )
        return path


def _iter_niftis(paths: Sequence[Path]) -> list[Path]:
    out: list[Path] = []
    for path in paths:
        name = path.name.lower()
        if name.endswith(".nii.gz") or name.endswith(".nii"):
            out.append(path)
    return out


def _nifti_stem(path: Path) -> str:
    name = path.name
    if name.endswith(".nii.gz"):
        return name[: -len(".nii.gz")]
    if name.endswith(".nii"):
        return name[: -len(".nii")]
    return path.stem
