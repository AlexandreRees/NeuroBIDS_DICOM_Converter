"""Optional facial defacing for anatomical MRI volumes."""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

import pandas as pd

from mri_anonymization.constants import ANATOMICAL_MARKERS, NIFTI_SUFFIXES
from mri_anonymization.models import PipelineStats

LOGGER = logging.getLogger("mri_anonymization")


def is_nifti(path: Path) -> bool:
    """Return True if *path* is a NIfTI file."""
    name = path.name.lower()
    return any(name.endswith(suffix) for suffix in NIFTI_SUFFIXES)


def is_anatomical(path: Path) -> bool:
    """Return True if a NIfTI file is anatomical and eligible for defacing."""
    if not is_nifti(path) or "_defaced" in path.name:
        return False
    if any(marker in path.name for marker in ANATOMICAL_MARKERS):
        return True
    return "anat" in path.parts


def resolve_pydeface() -> str | None:
    """Locate pydeface executable."""
    return shutil.which("pydeface")


def resolve_fsl_deface() -> str | None:
    """Locate FSL deface executable."""
    return shutil.which("deface") or shutil.which("fsl_deface")


def deface_volume(input_path: Path, output_path: Path) -> tuple[str, bool, str]:
    """Deface one anatomical volume; returns tool, success, message."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    pydeface = resolve_pydeface()
    if pydeface:
        result = subprocess.run(
            [pydeface, str(input_path), "--outfile", str(output_path)],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0 and output_path.is_file():
            return "pydeface", True, ""
        message = (result.stderr or result.stdout or "pydeface failed").strip()

    fsl = resolve_fsl_deface()
    if fsl:
        result = subprocess.run(
            [fsl, str(input_path), str(output_path)],
            capture_output=True,
            text=True,
            check=False,
        )
        success = result.returncode == 0 and output_path.is_file()
        message = (result.stderr or result.stdout or "").strip()
        return "fsl_deface", success, message

    return "none", False, "No defacing tool available (install pydeface or FSL deface)"


def run_defacing(public_dataset: Path, stats: PipelineStats) -> pd.DataFrame:
    """Deface anatomical volumes in the public dataset."""
    records: list[dict[str, str]] = []

    for input_path in sorted(public_dataset.rglob("*")):
        if not input_path.is_file() or not is_anatomical(input_path):
            continue

        if input_path.name.endswith(".nii.gz"):
            output_name = input_path.name.replace(".nii.gz", "_defaced.nii.gz")
        else:
            output_name = input_path.name.replace(".nii", "_defaced.nii")

        output_path = input_path.with_name(output_name)
        if output_path.is_file():
            records.append(
                {
                    "subject": input_path.parts[-4] if len(input_path.parts) >= 4 else "",
                    "input_file": str(input_path),
                    "output_file": str(output_path),
                    "tool": "existing",
                    "status": "skipped",
                    "message": "defaced output already exists",
                }
            )
            stats.n_defacing_skipped += 1
            continue

        tool, success, message = deface_volume(input_path, output_path)
        status = "success" if success else "failed"
        records.append(
            {
                "subject": input_path.parts[-4] if len(input_path.parts) >= 4 else "",
                "input_file": str(input_path),
                "output_file": str(output_path),
                "tool": tool,
                "status": status,
                "message": message,
            }
        )
        if success:
            stats.n_defaced += 1
            LOGGER.info("Defaced %s -> %s", input_path.name, output_path.name)
        else:
            stats.n_defacing_failed += 1
            LOGGER.warning("Defacing failed for %s: %s", input_path, message)

    return pd.DataFrame(records)
