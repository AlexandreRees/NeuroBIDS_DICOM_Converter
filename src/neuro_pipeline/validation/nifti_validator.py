"""NIfTI structural validation using nibabel."""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np

from neuro_pipeline.validation.models import ValidationResult, ValidationStatus

LOGGER = logging.getLogger(__name__)

# Soft limits used for WARNING / FAIL heuristics (modality-agnostic).
_MIN_VOXEL_MM = 1e-4
_MAX_VOXEL_MM = 50.0
_MIN_DIM = 1


class NiftiValidator:
    """Validate NIfTI files written under an output directory."""

    def __init__(self, output_directory: Path | str) -> None:
        self.output_directory = Path(output_directory)

    def iter_nifti_files(self) -> list[Path]:
        """Return all ``*.nii`` / ``*.nii.gz`` files under the output tree."""
        root = self.output_directory
        if not root.exists():
            return []
        files = list(root.rglob("*.nii")) + list(root.rglob("*.nii.gz"))
        # Avoid double-counting when *.nii glob also hits .nii.gz on some systems
        unique: dict[Path, Path] = {}
        for path in files:
            unique[path.resolve()] = path
        return sorted(unique.values(), key=lambda p: str(p).lower())

    def validate_all(self) -> list[ValidationResult]:
        """Validate every NIfTI file found recursively."""
        results: list[ValidationResult] = []
        for path in self.iter_nifti_files():
            results.append(self.validate_one(path))
        return results

    def validate_one(self, path: Path) -> ValidationResult:
        """Validate a single NIfTI file without modifying it."""
        try:
            import nibabel as nib
        except ImportError as exc:  # pragma: no cover - dependency declared
            return ValidationResult(
                path=path,
                status=ValidationStatus.FAIL,
                message=f"nibabel is required for NIfTI validation: {exc}",
            )

        try:
            img = nib.load(str(path))
            header = img.header
            affine = np.asarray(img.affine, dtype=float)
            shape = tuple(int(x) for x in img.shape)
            # Only spatial voxel sizes (ignore 4th+/time dimension spacing).
            spatial_zooms = tuple(float(z) for z in header.get_zooms()[:3])
            datatype = str(header.get_data_dtype())
            try:
                orientation = "".join(nib.aff2axcodes(affine))
            except Exception:  # noqa: BLE001
                orientation = "unknown"

            affine_list = affine.tolist()
            issues: list[str] = []
            status = ValidationStatus.PASS

            spatial_shape = shape[:3] if len(shape) >= 3 else shape
            if any(d < _MIN_DIM for d in spatial_shape):
                issues.append("empty or invalid dimension")
                status = ValidationStatus.FAIL

            if len(spatial_zooms) < 3 or any(
                not np.isfinite(z) or z <= 0 for z in spatial_zooms
            ):
                issues.append("impossible voxel size (<=0 or non-finite)")
                status = ValidationStatus.FAIL
            elif any(z < _MIN_VOXEL_MM or z > _MAX_VOXEL_MM for z in spatial_zooms):
                issues.append(
                    f"unusual voxel size {spatial_zooms} "
                    f"(outside {_MIN_VOXEL_MM}–{_MAX_VOXEL_MM} mm)"
                )
                if status != ValidationStatus.FAIL:
                    status = ValidationStatus.WARNING

            if affine.shape != (4, 4) or not np.isfinite(affine).all():
                issues.append("invalid affine matrix")
                status = ValidationStatus.FAIL
            elif abs(float(np.linalg.det(affine[:3, :3]))) < 1e-12:
                issues.append("degenerate affine (near-zero determinant)")
                status = ValidationStatus.FAIL

            # Cheap integrity probe without writing
            try:
                dataobj = img.dataobj
                # Touch a corner voxel to surface truncated/compressed corruptions
                _ = dataobj[tuple(0 for _ in shape)]
            except Exception as exc:  # noqa: BLE001
                issues.append(f"corrupted or unreadable image data: {exc}")
                status = ValidationStatus.FAIL

            if status == ValidationStatus.PASS:
                message = (
                    f"OK: dims={shape}, voxel={tuple(round(z, 4) for z in spatial_zooms)}, "
                    f"orient={orientation}, dtype={datatype}"
                )
            else:
                message = "; ".join(issues)

            return ValidationResult(
                path=path,
                status=status,
                message=message,
                dimensions=shape,
                voxel_size=spatial_zooms,
                datatype=datatype,
                orientation=orientation,
                affine=affine_list,
            )
        except Exception as exc:  # noqa: BLE001
            LOGGER.debug("NIfTI validation failed for %s: %s", path, exc)
            return ValidationResult(
                path=path,
                status=ValidationStatus.FAIL,
                message=f"corrupted NIfTI / unreadable header: {exc}",
            )
