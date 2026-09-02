"""Diffusion (DWI / ADC) companion-file validation."""

from __future__ import annotations

import logging
import math
import re
from pathlib import Path

from neuro_pipeline.validation.models import DWIValidationResult, ValidationStatus

LOGGER = logging.getLogger(__name__)

_BVEC_NORM_TOL = 0.05

# Names that indicate raw / TRACE DWI needing gradient tables.
_DWI_RAW_HINTS = (
    "dwi",
    "dti",
    "diff",
    "ep2d_diff",
    "tensor",
    "trace",  # TRACE acquisitions (not TRACEW maps — see classifier)
)

_ADC_PATTERNS = (
    re.compile(r"\badc\b", re.I),
    re.compile(r"apparent[_\s-]?diffusion[_\s-]?coefficient", re.I),
)


class DiffusionValidator:
    """Validate DWI / ADC NIfTI bundles under an output directory.

    Rules
    -----
    * Raw/TRACE DWI → require ``.nii(.gz)`` + ``.bval`` + ``.bvec``
    * ADC maps → require only ``.nii(.gz)`` (no gradients expected)
    """

    def __init__(self, output_directory: Path | str) -> None:
        self.output_directory = Path(output_directory)

    def find_dwi_niftis(self) -> list[Path]:
        """Locate candidate diffusion-related NIfTI files."""
        root = self.output_directory
        if not root.exists():
            return []
        candidates: list[Path] = []
        for path in list(root.rglob("*.nii")) + list(root.rglob("*.nii.gz")):
            label = _label(path)
            if is_adc_map(label) or is_raw_dwi(label):
                candidates.append(path)
            elif _sidecar(path, ".bval").exists():
                candidates.append(path)
        return sorted({p.resolve(): p for p in candidates}.values(), key=lambda p: str(p).lower())

    def validate_all(self) -> list[DWIValidationResult]:
        return [self.validate_one(path) for path in self.find_dwi_niftis()]

    def validate_one(self, nifti_path: Path) -> DWIValidationResult:
        """Validate sidecars / gradients for one diffusion-related NIfTI."""
        label = _label(nifti_path)
        bval = _sidecar(nifti_path, ".bval")
        bvec = _sidecar(nifti_path, ".bvec")
        json_path = _sidecar(nifti_path, ".json")

        has_bval = bval.exists()
        has_bvec = bvec.exists()
        has_json = json_path.exists()

        if is_adc_map(label):
            return DWIValidationResult(
                nifti_path=nifti_path,
                status=ValidationStatus.PASS,
                message="ADC map without gradients (expected)",
                has_bval=has_bval,
                has_bvec=has_bvec,
                has_json=has_json,
                kind="adc",
            )

        # Raw / TRACE DWI (and any other gradient-dependent series)
        if not has_bvec:
            return DWIValidationResult(
                nifti_path=nifti_path,
                status=ValidationStatus.FAIL,
                message="Missing bvec file",
                has_bval=has_bval,
                has_bvec=False,
                has_json=has_json,
                kind="dwi",
            )
        if not has_bval:
            return DWIValidationResult(
                nifti_path=nifti_path,
                status=ValidationStatus.FAIL,
                message="Missing bval file",
                has_bval=False,
                has_bvec=has_bvec,
                has_json=has_json,
                kind="dwi",
            )

        try:
            n_volumes = _nifti_volumes(nifti_path)
            bvals = _read_bval(bval)
            bvecs = _read_bvec(bvec)

            if len(bvals) == 0:
                return DWIValidationResult(
                    nifti_path=nifti_path,
                    status=ValidationStatus.FAIL,
                    message="bval is empty",
                    n_volumes=n_volumes,
                    n_gradients=0,
                    has_bval=True,
                    has_bvec=True,
                    has_json=has_json,
                    kind="dwi",
                )

            n_gradients = len(bvecs) if bvecs else len(bvals)
            issues_fail: list[str] = []
            issues_warn: list[str] = []

            if n_volumes is not None and n_gradients != n_volumes:
                issues_fail.append(
                    f"gradient count ({n_gradients}) != NIfTI volumes ({n_volumes})"
                )

            bad_norms = _count_bad_bvec_norms(bvecs, bvals, tol=_BVEC_NORM_TOL)
            if bad_norms:
                issues_warn.append(
                    f"Potential bvec normalization issue ({bad_norms} direction(s))"
                )

            if issues_fail:
                return DWIValidationResult(
                    nifti_path=nifti_path,
                    status=ValidationStatus.FAIL,
                    message="; ".join(issues_fail),
                    n_volumes=n_volumes,
                    n_gradients=n_gradients,
                    has_bval=True,
                    has_bvec=True,
                    has_json=has_json,
                    kind="dwi",
                )

            if issues_warn:
                return DWIValidationResult(
                    nifti_path=nifti_path,
                    status=ValidationStatus.WARNING,
                    message="; ".join(issues_warn),
                    n_volumes=n_volumes,
                    n_gradients=n_gradients,
                    has_bval=True,
                    has_bvec=True,
                    has_json=has_json,
                    kind="dwi",
                )

            return DWIValidationResult(
                nifti_path=nifti_path,
                status=ValidationStatus.PASS,
                message=f"Valid DWI acquisition: {n_volumes} volumes, {n_gradients} gradients",
                n_volumes=n_volumes,
                n_gradients=n_gradients,
                has_bval=True,
                has_bvec=True,
                has_json=has_json,
                kind="dwi",
            )
        except Exception as exc:  # noqa: BLE001
            LOGGER.debug("DWI validation error for %s: %s", nifti_path, exc)
            return DWIValidationResult(
                nifti_path=nifti_path,
                status=ValidationStatus.FAIL,
                message=f"DWI validation error: {exc}",
                has_bval=has_bval,
                has_bvec=has_bvec,
                has_json=has_json,
                kind="dwi",
            )


def is_adc_map(name: str) -> bool:
    """Return True when the filename/series label denotes an ADC map."""
    text = name.replace("-", " ").replace("_", " ")
    if any(pat.search(name) or pat.search(text) for pat in _ADC_PATTERNS):
        return True
    # Common Siemens token without word boundaries (…_ADC, ADC.nii.gz)
    lowered = name.lower()
    return "adc" in lowered


def is_raw_dwi(name: str) -> bool:
    """Return True for raw/TRACE DWI that should have gradient tables."""
    if is_adc_map(name):
        return False
    lowered = name.lower()
    # Siemens derived TRACEW / FA / MD maps do not need bval/bvec.
    if any(tag in lowered for tag in ("tracew", "_fa", "_md", "colfa", "fa.")):
        return False
    return any(h in lowered for h in _DWI_RAW_HINTS)


def _label(path: Path) -> str:
    return _stem(path)


def _stem(path: Path) -> str:
    name = path.name
    if name.endswith(".nii.gz"):
        return name[: -len(".nii.gz")]
    if name.endswith(".nii"):
        return name[: -len(".nii")]
    return path.stem


def _sidecar(nifti_path: Path, suffix: str) -> Path:
    return nifti_path.parent / f"{_stem(nifti_path)}{suffix}"


def _nifti_volumes(path: Path) -> int | None:
    import nibabel as nib

    img = nib.load(str(path))
    shape = img.shape
    if len(shape) < 4:
        return 1
    return int(shape[3])


def _read_bval(path: Path) -> list[float]:
    text = path.read_text(encoding="utf-8", errors="replace").strip()
    if not text:
        return []
    return [float(x) for x in text.replace(",", " ").split()]


def _read_bvec(path: Path) -> list[tuple[float, float, float]]:
    lines = [
        line.strip()
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines()
        if line.strip()
    ]
    if not lines:
        return []
    rows = [[float(x) for x in line.replace(",", " ").split()] for line in lines]
    if len(rows) == 3:
        n = len(rows[0])
        return [(rows[0][i], rows[1][i], rows[2][i]) for i in range(n)]
    if all(len(r) == 3 for r in rows):
        return [(r[0], r[1], r[2]) for r in rows]
    raise ValueError(f"Unrecognized bvec layout in {path}")


def _count_bad_bvec_norms(
    bvecs: list[tuple[float, float, float]],
    bvals: list[float],
    *,
    tol: float = _BVEC_NORM_TOL,
) -> int:
    """Count non-b0 vectors whose Euclidean norm is not ~1."""
    bad = 0
    for i, vec in enumerate(bvecs):
        b = bvals[i] if i < len(bvals) else None
        # Ignore b0 / zero-b entries entirely.
        if b is not None and abs(b) < 1e-6:
            continue
        if b is None:
            # No matching bval → still check norm if vector looks non-zero
            pass
        norm = math.sqrt(vec[0] ** 2 + vec[1] ** 2 + vec[2] ** 2)
        if not math.isfinite(norm) or abs(norm - 1.0) > tol:
            bad += 1
    return bad
