"""Official / structural BIDS dataset validation."""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

LOGGER = logging.getLogger(__name__)


class BIDSValidationStatus(str, Enum):
    PASS = "PASS"
    WARNING = "WARNING"
    FAIL = "FAIL"


@dataclass(slots=True)
class BIDSValidationResult:
    """Outcome of validating a BIDS dataset."""

    status: BIDSValidationStatus
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    summary: str = ""
    validator_backend: str = ""
    dataset_path: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status.value,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
            "summary": self.summary,
            "validator_backend": self.validator_backend,
            "dataset_path": self.dataset_path,
        }


class BIDSValidator:
    """Validate a BIDS directory via ``bids-validator`` or a structural fallback.

    Prefer the official CLI when installed. If missing, run a lightweight
    structural check so the app remains usable, and surface a clear warning
    that the official validator was not found.
    """

    def __init__(self, *, bids_validator_path: str | None = None) -> None:
        self._requested = (bids_validator_path or "").strip()

    def locate_validator(self) -> Path | None:
        """Return path to ``bids-validator`` if available."""
        candidates: list[Path] = []
        if self._requested:
            candidates.append(Path(self._requested))
        which = shutil.which("bids-validator")
        if which:
            candidates.append(Path(which))
        which_js = shutil.which("bids-validator.cmd")  # Windows npm shim
        if which_js:
            candidates.append(Path(which_js))
        # Future bundled locations next to the app / resources
        from neuro_pipeline.config.paths import project_root, resource_root

        root = project_root()
        for base in (root, resource_root(), root / "bin", root / "tools"):
            candidates.extend(
                [
                    base / "bids-validator",
                    base / "bids-validator.exe",
                    base / "bids-validator.cmd",
                ]
            )
        for path in candidates:
            if path and path.exists():
                return path.resolve()
        return None

    def validate(self, dataset_path: Path | str) -> BIDSValidationResult:
        """Validate ``dataset_path`` and return a structured result."""
        root = Path(dataset_path)
        if not root.exists() or not root.is_dir():
            return BIDSValidationResult(
                status=BIDSValidationStatus.FAIL,
                errors=[f"Dataset path does not exist or is not a folder: {root}"],
                summary="BIDS validation failed: missing dataset path",
                validator_backend="none",
                dataset_path=str(root),
            )

        exe = self.locate_validator()
        if exe is not None:
            return self._run_official(exe, root)
        # Fallback structural validation + explicit missing-tool warning
        result = self._structural_validate(root)
        result.warnings.insert(
            0,
            "bids-validator executable was not found. "
            "Install Node.js bids-validator for full official checks, "
            "or place it on PATH / next to the application for bundled use.",
        )
        if result.status == BIDSValidationStatus.PASS:
            result.status = BIDSValidationStatus.WARNING
            result.summary = "Structural BIDS checks passed (official validator missing)"
        result.validator_backend = "structural-fallback"
        return result

    def _run_official(self, exe: Path, root: Path) -> BIDSValidationResult:
        try:
            completed = subprocess.run(
                [str(exe), str(root), "--json"],
                capture_output=True,
                text=True,
                check=False,
                timeout=300,
            )
        except Exception as exc:  # noqa: BLE001
            return BIDSValidationResult(
                status=BIDSValidationStatus.FAIL,
                errors=[f"Failed to run bids-validator: {exc}"],
                summary="Official BIDS validator could not be executed",
                validator_backend=str(exe),
                dataset_path=str(root),
            )

        errors: list[str] = []
        warnings: list[str] = []
        # Parse JSON when possible; fall back to text
        payload = None
        text = (completed.stdout or "").strip()
        if text:
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                payload = None

        if isinstance(payload, dict):
            for issue in payload.get("issues", {}).get("errors", []) or []:
                errors.append(_format_issue(issue))
            for issue in payload.get("issues", {}).get("warnings", []) or []:
                warnings.append(_format_issue(issue))
        else:
            if completed.returncode != 0:
                err = (completed.stderr or completed.stdout or "bids-validator failed").strip()
                errors.append(err[:2000])
            elif completed.stderr:
                warnings.append(completed.stderr.strip()[:1000])

        if errors or completed.returncode != 0:
            status = BIDSValidationStatus.FAIL
            summary = f"BIDS validation failed ({len(errors)} error(s))"
        elif warnings:
            status = BIDSValidationStatus.WARNING
            summary = f"BIDS validation passed with {len(warnings)} warning(s)"
        else:
            status = BIDSValidationStatus.PASS
            summary = "BIDS validation passed"

        return BIDSValidationResult(
            status=status,
            errors=errors,
            warnings=warnings,
            summary=summary,
            validator_backend=str(exe),
            dataset_path=str(root),
        )

    def _structural_validate(self, root: Path) -> BIDSValidationResult:
        errors: list[str] = []
        warnings: list[str] = []

        desc = root / "dataset_description.json"
        if not desc.exists():
            errors.append("Missing required file: dataset_description.json")
        else:
            try:
                data = json.loads(desc.read_text(encoding="utf-8"))
                if "Name" not in data or "BIDSVersion" not in data:
                    warnings.append(
                        "dataset_description.json should include Name and BIDSVersion"
                    )
            except Exception as exc:  # noqa: BLE001
                errors.append(f"Invalid dataset_description.json: {exc}")

        if not (root / "README").exists() and not (root / "README.md").exists():
            warnings.append("Missing recommended README file")

        if not (root / "participants.tsv").exists():
            warnings.append("Missing recommended participants.tsv")

        subjects = [p for p in root.iterdir() if p.is_dir() and p.name.startswith("sub-")]
        if not subjects:
            errors.append("No subject directories found (expected sub-*)")
        else:
            for sub in subjects:
                has_data = any(
                    (sub / dt).is_dir() and any((sub / dt).rglob("*.nii*"))
                    for dt in ("anat", "dwi", "func", "fmap", "perf", "eeg", "meg")
                )
                # Also allow ses-* nesting
                sessions = [p for p in sub.iterdir() if p.is_dir() and p.name.startswith("ses-")]
                if sessions:
                    has_data = has_data or any(
                        any((ses / dt).rglob("*.nii*") for dt in ("anat", "dwi", "func", "fmap"))
                        for ses in sessions
                    )
                if not has_data:
                    warnings.append(f"{sub.name}: no NIfTI data found under anat/dwi/func/fmap")

                for nii in sub.rglob("*.nii.gz"):
                    stem = nii.name[: -len(".nii.gz")]
                    json_side = nii.with_name(f"{stem}.json")
                    if not json_side.exists():
                        warnings.append(f"Missing JSON sidecar for {nii.relative_to(root)}")

        if errors:
            status = BIDSValidationStatus.FAIL
            summary = f"Structural BIDS checks failed ({len(errors)} error(s))"
        elif warnings:
            status = BIDSValidationStatus.WARNING
            summary = f"Structural BIDS checks passed with {len(warnings)} warning(s)"
        else:
            status = BIDSValidationStatus.PASS
            summary = "Structural BIDS checks passed"

        return BIDSValidationResult(
            status=status,
            errors=errors,
            warnings=warnings,
            summary=summary,
            validator_backend="structural-fallback",
            dataset_path=str(root),
        )


def _format_issue(issue: object) -> str:
    if isinstance(issue, dict):
        key = issue.get("key") or issue.get("code") or "issue"
        reason = issue.get("reason") or issue.get("message") or str(issue)
        files = issue.get("files") or []
        file_hint = ""
        if files and isinstance(files, list) and isinstance(files[0], dict):
            file_hint = f" ({files[0].get('file', {}).get('relativePath', '')})"
        return f"{key}: {reason}{file_hint}"
    return str(issue)
