"""Application configuration models."""

from __future__ import annotations

from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any, Mapping


@dataclass(slots=True)
class AppConfig:
    """Runtime configuration loaded from YAML."""

    compression: bool = True
    one_folder_per_patient: bool = True
    preserve_json: bool = True
    smart_naming: bool = True
    validate_output: bool = True
    output_layout: str = "nifti"  # "nifti" | "bids"
    threads: int = 4
    output_format: str = "nii.gz"
    dcm2niix_path: str = "auto"
    log_dir: str = ""
    naming_rules_path: str = ""
    logging_enabled: bool = True

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> AppConfig:
        """Build a config object from a YAML mapping, ignoring unknown keys."""
        payload = dict(data)
        logging_block = payload.pop("logging", None)
        if isinstance(logging_block, Mapping):
            if "enabled" in logging_block:
                payload["logging_enabled"] = bool(logging_block["enabled"])
        elif isinstance(logging_block, bool):
            payload["logging_enabled"] = logging_block

        path_value = payload.get("dcm2niix_path", "auto")
        if path_value is None or str(path_value).strip() == "":
            payload["dcm2niix_path"] = "auto"

        known = {f.name for f in fields(cls)}
        kwargs = {key: value for key, value in payload.items() if key in known}
        return cls(**kwargs)

    def resolved_log_dir(self, app_root: Path | None = None) -> Path:  # noqa: ARG002
        """Return the directory where conversion.log should be written.

        ``app_root`` is accepted for API compatibility but is **not** used as a
        writable default (Program Files is read-only after install).
        """
        from neuro_pipeline.config.paths import resolve_writable_log_dir

        preferred = self.log_dir if str(self.log_dir or "").strip() else None
        return resolve_writable_log_dir(preferred)

    @property
    def uses_auto_dcm2niix(self) -> bool:
        return str(self.dcm2niix_path or "auto").strip().lower() in {"", "auto"}
