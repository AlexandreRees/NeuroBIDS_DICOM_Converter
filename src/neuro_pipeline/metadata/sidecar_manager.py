"""Preserve and validate dcm2niix JSON sidecars."""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path

from neuro_pipeline.metadata.metadata_models import (
    RECOMMENDED_FIELDS,
    MetadataSummary,
    SidecarInfo,
)

LOGGER = logging.getLogger(__name__)


class MetadataManager:
    """Collect / validate / copy JSON sidecars next to NIfTI outputs."""

    def collect_sidecars(self, root: Path | str) -> list[SidecarInfo]:
        root_path = Path(root)
        if not root_path.exists():
            return []
        infos: list[SidecarInfo] = []
        for json_path in sorted(root_path.rglob("*.json")):
            # Skip dataset-level / provenance JSON
            if json_path.name in {
                "dataset_description.json",
                "conversion_provenance.json",
                "conversion_manifest.json",
            }:
                continue
            if "derivatives" in json_path.parts and json_path.name.startswith("conversion_"):
                continue
            info = self.validate_sidecar(json_path)
            stem = json_path.name[: -len(".json")]
            for ext in (".nii.gz", ".nii"):
                candidate = json_path.with_name(stem + ext)
                if candidate.exists():
                    info.nifti_path = candidate
                    break
            infos.append(info)
        return infos

    def validate_sidecar(self, path: Path | str) -> SidecarInfo:
        json_path = Path(path)
        info = SidecarInfo(path=json_path)
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            info.messages.append(f"Could not parse JSON: {exc}")
            return info
        if not isinstance(data, dict):
            info.messages.append("JSON sidecar is not an object")
            return info
        info.data = data
        for field_name in RECOMMENDED_FIELDS:
            if field_name in data and data[field_name] not in (None, ""):
                info.present_fields.append(field_name)
            else:
                info.missing_fields.append(field_name)
                # Optional fields — never fail, only note
                info.messages.append(f"Optional field missing: {field_name}")
        return info

    def copy_sidecar(self, source_json: Path, dest_json: Path) -> Path | None:
        """Copy a sidecar without overwriting an existing destination."""
        source_json = Path(source_json)
        dest_json = Path(dest_json)
        if not source_json.exists():
            return None
        if dest_json.exists():
            LOGGER.info("Sidecar exists, not overwriting: %s", dest_json.name)
            return dest_json
        dest_json.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_json, dest_json)
        return dest_json

    def ensure_sidecars_for_niftis(self, root: Path | str) -> MetadataSummary:
        """Report missing JSON companions for every NIfTI under ``root``."""
        root_path = Path(root)
        summary = MetadataSummary(sidecars=self.collect_sidecars(root_path))
        for nii in list(root_path.rglob("*.nii.gz")) + list(root_path.rglob("*.nii")):
            if "derivatives" in nii.parts:
                continue
            stem = _nifti_stem(nii)
            json_path = nii.parent / f"{stem}.json"
            if not json_path.exists():
                summary.missing_json_for.append(str(nii.relative_to(root_path)))
        return summary

    def summarize(self, root: Path | str) -> MetadataSummary:
        return self.ensure_sidecars_for_niftis(root)


def _nifti_stem(path: Path) -> str:
    name = path.name
    if name.endswith(".nii.gz"):
        return name[: -len(".nii.gz")]
    if name.endswith(".nii"):
        return name[: -len(".nii")]
    return path.stem
