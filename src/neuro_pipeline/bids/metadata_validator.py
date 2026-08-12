"""Advanced BIDS JSON sidecar validation (advisory; never blocks conversion)."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Iterable

LOGGER = logging.getLogger(__name__)


class MetadataStatus(str, Enum):
    PASS = "PASS"
    WARNING = "WARNING"
    FAIL = "FAIL"


@dataclass(slots=True)
class MetadataValidationResult:
    """Outcome for one JSON sidecar (advanced BIDS metadata rules)."""

    path: Path
    status: MetadataStatus
    missing_fields: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    datatype: str = ""
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["path"] = str(self.path)
        data["status"] = self.status.value
        return data


class MetadataValidator:
    """Validate datatype-specific recommended/required BIDS JSON fields."""

    ANAT_REQUIRED = ("MagneticFieldStrength", "Manufacturer", "SequenceName")
    DWI_REQUIRED = ("DiffusionGradientOrientation",)  # plus companion files checked separately
    DWI_COMPANIONS = ("bvec", "bval")
    FUNC_REQUIRED = ("RepetitionTime", "TaskName")
    FMAP_REQUIRED = ("EchoTime", "PhaseEncodingDirection")

    def validate_file(self, json_path: Path | str) -> MetadataValidationResult:
        path = Path(json_path)
        datatype = self._infer_datatype(path)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            return MetadataValidationResult(
                path=path,
                status=MetadataStatus.FAIL,
                errors=[f"Cannot read JSON: {exc}"],
                datatype=datatype,
                message="Unreadable JSON sidecar",
            )
        if not isinstance(payload, dict):
            return MetadataValidationResult(
                path=path,
                status=MetadataStatus.FAIL,
                errors=["JSON root must be an object"],
                datatype=datatype,
                message="Invalid JSON structure",
            )
        if datatype == "anat":
            return self.validate_anat(payload, path=path)
        if datatype == "dwi":
            return self.validate_dwi(payload, path=path)
        if datatype == "func":
            return self.validate_func(payload, path=path)
        if datatype == "fmap":
            return self.validate_fmap(payload, path=path)
        return MetadataValidationResult(
            path=path,
            status=MetadataStatus.PASS,
            datatype=datatype or "unknown",
            message="No datatype-specific metadata rules applied",
        )

    def validate_anat(
        self, data: dict[str, Any], *, path: Path | None = None
    ) -> MetadataValidationResult:
        return self._validate_fields(
            data,
            required=self.ANAT_REQUIRED,
            path=path or Path("unknown.json"),
            datatype="anat",
        )

    def validate_dwi(
        self, data: dict[str, Any], *, path: Path | None = None
    ) -> MetadataValidationResult:
        json_path = path or Path("unknown.json")
        result = self._validate_fields(
            data,
            required=self.DWI_REQUIRED,
            path=json_path,
            datatype="dwi",
        )
        # Companion gradient files beside the sidecar / nifti stem
        stem = json_path.with_suffix("")
        for ext in self.DWI_COMPANIONS:
            companion = Path(str(stem) + f".{ext}")
            # also try without double suffix from .nii.json style
            alt = json_path.parent / f"{json_path.name.replace('.json', '')}.{ext}"
            if not companion.exists() and not alt.exists():
                # try nifti stem
                for candidate in json_path.parent.glob(json_path.stem.split(".")[0] + f"*.{ext}"):
                    companion = candidate
                    break
            if not companion.exists() and not alt.exists():
                result.missing_fields.append(ext)
                result.warnings.append(f"Missing companion file: .{ext}")
        if result.missing_fields:
            result.status = (
                MetadataStatus.FAIL
                if "DiffusionGradientOrientation" in result.missing_fields
                else MetadataStatus.WARNING
            )
            result.message = "Missing DWI metadata / companions"
        return result

    def validate_func(
        self, data: dict[str, Any], *, path: Path | None = None
    ) -> MetadataValidationResult:
        return self._validate_fields(
            data,
            required=self.FUNC_REQUIRED,
            path=path or Path("unknown.json"),
            datatype="func",
        )

    def validate_fmap(
        self, data: dict[str, Any], *, path: Path | None = None
    ) -> MetadataValidationResult:
        return self._validate_fields(
            data,
            required=self.FMAP_REQUIRED,
            path=path or Path("unknown.json"),
            datatype="fmap",
        )

    def validate_tree(self, root: Path | str) -> list[MetadataValidationResult]:
        base = Path(root)
        results: list[MetadataValidationResult] = []
        for path in sorted(base.rglob("*.json")):
            if path.name in {"dataset_description.json", "conversion_provenance.json"}:
                continue
            if "derivatives" in path.parts:
                continue
            results.append(self.validate_file(path))
        return results

    def write_html_report(
        self, results: Iterable[MetadataValidationResult], output_dir: Path | str
    ) -> Path:
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        rows = []
        for r in results:
            missing = ", ".join(r.missing_fields) if r.missing_fields else "None"
            warn = "; ".join(r.warnings) if r.warnings else "—"
            rows.append(
                "<tr>"
                f"<td>{r.path.name}</td>"
                f"<td>{r.datatype or '—'}</td>"
                f"<td><b>{r.status.value}</b></td>"
                f"<td>{missing}</td>"
                f"<td>{warn}</td>"
                "</tr>"
            )
        html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Metadata validation</title>
<style>
body{{font-family:Segoe UI,Arial,sans-serif;margin:24px;color:#222}}
table{{border-collapse:collapse;width:100%}}
th,td{{border:1px solid #ddd;padding:8px;text-align:left}}
th{{background:#f4f4f4}}
</style></head><body>
<h1>BIDS metadata validation</h1>
<p>Advisory checks only — conversion is never blocked.</p>
<table>
<thead><tr><th>File</th><th>Datatype</th><th>Status</th><th>Missing</th><th>Warnings</th></tr></thead>
<tbody>
{''.join(rows) if rows else '<tr><td colspan="5">No JSON sidecars found</td></tr>'}
</tbody></table>
</body></html>
"""
        path = out / "metadata_validation_report.html"
        path.write_text(html, encoding="utf-8")
        return path

    def _validate_fields(
        self,
        data: dict[str, Any],
        *,
        required: tuple[str, ...],
        path: Path,
        datatype: str,
    ) -> MetadataValidationResult:
        missing = [f for f in required if not self._has(data, f)]
        if not missing:
            return MetadataValidationResult(
                path=path,
                status=MetadataStatus.PASS,
                missing_fields=[],
                datatype=datatype,
                message="PASS",
            )
        return MetadataValidationResult(
            path=path,
            status=MetadataStatus.WARNING,
            missing_fields=missing,
            warnings=[f"Missing recommended field: {f}" for f in missing],
            datatype=datatype,
            message="Missing recommended metadata fields",
        )

    @staticmethod
    def _has(data: dict[str, Any], key: str) -> bool:
        # Accept common aliases for DiffusionGradientOrientation
        if key == "DiffusionGradientOrientation":
            for cand in (
                "DiffusionGradientOrientation",
                "DiffusionGradientDirectionSequence",
                "bvec",
            ):
                if cand in data and data[cand] not in (None, "", []):
                    return True
            return False
        return key in data and data[key] not in (None, "", [])

    @staticmethod
    def _infer_datatype(path: Path) -> str:
        parts = {p.lower() for p in path.parts}
        name = path.name.lower()
        for key in ("anat", "dwi", "func", "fmap"):
            if key in parts:
                return key
        if any(x in name for x in ("t1w", "t2w", "flair", "mprage")):
            return "anat"
        if "dwi" in name or "diff" in name:
            return "dwi"
        if "bold" in name:
            return "func"
        if "fmap" in name or "fieldmap" in name:
            return "fmap"
        return "unknown"
