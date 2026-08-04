"""Shared helpers for DWI technical validation (BIDS is read-only)."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import nibabel as nib
import numpy as np
import pandas as pd

B0_THRESHOLD = 50.0
DEFAULT_BIDS = Path("/home/alexrees/scratch/bids")
DEFAULT_QC = Path("/home/alexrees/scratch/reports/dwi_qc")

FONT_FAMILY = "DejaVu Sans"
C_FILL = "#4D4D4D"
C_EDGE = "#1A1A1A"
C_ACCENT = "#2C5F8A"
C_PASS = "#2E7D4F"
C_REVIEW = "#B07D2A"
C_FAIL = "#8B3A3A"
C_NA = "#6E6E6E"
C_GRID = "#D0D0D0"
C_PROTOCOLS = ["#2C5F8A", "#B07D2A", "#2E7D4F", "#8B3A3A", "#5B4B8A", "#3A6B5B"]

ENTITY_RE = re.compile(
    r"(?P<subject>sub-[^_/]+)"
    r"(?:_(?P<session>ses-[^_/]+))?"
    r"(?:_.*)?_dwi\.nii\.gz$"
)
RUN_RE = re.compile(r"_run-(\d+)_")


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def log(msg: str) -> None:
    print(msg, flush=True)


def apply_style() -> None:
    plt.rcParams.update(
        {
            "font.family": FONT_FAMILY,
            "font.size": 9,
            "axes.titlesize": 11,
            "axes.labelsize": 9,
            "xtick.labelsize": 8,
            "ytick.labelsize": 8,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.facecolor": "white",
            "figure.facecolor": "white",
            "savefig.facecolor": "white",
            "axes.grid": False,
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
            "svg.fonttype": "none",
        }
    )


def save_figure(fig: plt.Figure, path: Path, dpi: int = 300) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    stem = path.with_suffix("")
    for ext in (".png", ".pdf", ".svg"):
        fig.savefig(stem.with_suffix(ext), dpi=dpi, bbox_inches="tight")
    plt.close(fig)


def write_tsv(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, sep="\t", index=False)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")


def parse_entities(nifti: Path) -> tuple[str, str, str]:
    match = ENTITY_RE.search(nifti.name)
    if match:
        subject = match.group("subject")
        session = match.group("session") or "n/a"
    else:
        parts = nifti.parts
        subject = next((p for p in parts if p.startswith("sub-")), "unknown")
        session = next((p for p in parts if p.startswith("ses-")), "n/a")
    run_m = RUN_RE.search(nifti.name)
    run = f"run-{run_m.group(1)}" if run_m else "n/a"
    return subject, session, run


def scan_id_from_nifti(nifti: Path | str) -> str:
    return Path(nifti).name.replace(".nii.gz", "")


def sidecar_paths(nifti: Path) -> tuple[Path, Path, Path]:
    stem = nifti.name[: -len(".nii.gz")]
    parent = nifti.parent
    return parent / f"{stem}.bval", parent / f"{stem}.bvec", parent / f"{stem}.json"


def load_bval(path: Path) -> np.ndarray:
    return np.loadtxt(path).astype(float).ravel()


def load_bvec(path: Path) -> np.ndarray:
    arr = np.loadtxt(path).astype(float)
    if arr.ndim == 1:
        arr = arr.reshape(1, -1)
    if arr.shape[0] == 3:
        return arr
    if arr.shape[1] == 3:
        return arr.T
    return arr


def load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def nifti_n_volumes(img: nib.spatialimages.SpatialImage) -> int:
    shape = img.shape
    return int(shape[3]) if len(shape) >= 4 else 1


def round_bvals(bvals: np.ndarray, tol: float = 50.0) -> np.ndarray:
    """Round b-values onto a common shell grid (0 / 1000 / 2000 …)."""
    out = np.zeros_like(bvals)
    for i, b in enumerate(bvals):
        if b < tol:
            out[i] = 0.0
        else:
            out[i] = float(np.round(b / 100.0) * 100.0)
    return out


def unique_bval_string(bvals: np.ndarray) -> str:
    rounded = round_bvals(bvals)
    uniq = sorted(int(v) for v in np.unique(np.rint(rounded).astype(int)))
    return ",".join(str(v) for v in uniq)


def orientation_code(affine: np.ndarray) -> str:
    try:
        ornt = nib.orientations.io_orientation(affine)
        axcodes = nib.orientations.ornt2axcodes(ornt)
        return "".join(axcodes)
    except Exception:  # noqa: BLE001
        return "unknown"


def fov_mm(shape: tuple[int, ...], zooms: tuple[float, ...]) -> tuple[float, float, float]:
    return tuple(float(shape[i] * zooms[i]) for i in range(3))  # type: ignore[return-value]


def voxel_volume_mm3(zooms: tuple[float, ...]) -> float:
    return float(zooms[0] * zooms[1] * zooms[2])


def ensure_scan_columns(df: pd.DataFrame, inventory: pd.DataFrame) -> pd.DataFrame:
    """Attach scan_id / nifti from inventory by row order when missing."""
    out = df.copy()
    if "nifti" not in out.columns and len(out) == len(inventory):
        out["nifti"] = inventory["nifti"].values
    if "scan_id" not in out.columns:
        if "nifti" in out.columns:
            out["scan_id"] = out["nifti"].map(lambda p: scan_id_from_nifti(p))
        elif len(out) == len(inventory):
            out["scan_id"] = inventory["nifti"].map(lambda p: scan_id_from_nifti(p))
    return out


def read_existing_tsv(path: Path) -> pd.DataFrame | None:
    if not path.is_file():
        return None
    return pd.read_csv(path, sep="\t")
