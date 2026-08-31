#!/usr/bin/env python3
"""Build Figure_DWI_protocols from release_dataset BIDS diffusion files only.

Read-only: does not modify NIfTI, JSON, bval, or bvec files.
"""
from __future__ import annotations

import csv
import gzip
import json
import pickle
import struct
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.lines import Line2D
from matplotlib.patches import Circle

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
RELEASE = Path("/lustre07/scratch/alexrees/release_dataset")
PAPER = Path("/lustre07/scratch/alexrees/paper")
FIG_PNG = PAPER / "figures" / "Figure_DWI_protocols.png"
FIG_PDF = PAPER / "figures" / "Figure_DWI_protocols.pdf"
TSV_PATH = Path("/lustre07/scratch/alexrees/metadata") / "dwi_protocol_summary.tsv"
QC_PATH = RELEASE / "docs" / "quality_control" / "dwi" / "figure_dwi_protocols_qc.txt"
CAPTION_PATH = PAPER / "figures" / "Figure_DWI_protocols_caption.tex"
CACHE_PATH = PAPER / "metadata" / "dwi_figure_schemes.pkl"

# b-values below this (s/mm^2) are treated as b=0.
# Scanner-reported shells are then snapped to the nearest 100 s/mm^2 when
# they fall within BVAL_TOL of that grid (documented grouping tolerance).
B0_THRESH = 50.0
BVAL_TOL = 50.0
BVAL_GRID = 100.0

# Angular merge for "unique directions" (degrees). Exact gSlider repeats
# collapse at 0 deg; this tolerance only absorbs numerical noise.
DIR_MERGE_DEG = 1.0
# Majority schemes shown in the figure; rarer variants remain in the TSV.
PRINCIPAL_MIN_MAGNITUDE = 20

# Wong / IBM-ish colorblind-safe palette (no rainbow).
COL_B1000 = "#0072B2"
COL_B2000 = "#D55E00"
COL_B0 = "#6B7280"
COL_OTHER = "#009E73"
COL_INK = "#374151"
COL_RULE = "#9CA3AF"


def canonical_b(b: float) -> int:
    """Map a raw b-value to 0 or a 100 s/mm^2 grid using BVAL_TOL."""
    if b < B0_THRESH:
        return 0
    snapped = int(round(b / BVAL_GRID) * BVAL_GRID)
    if abs(b - snapped) <= BVAL_TOL:
        return snapped
    return int(round(b))


def find_dwi_niis() -> list[Path]:
    out = subprocess.check_output(
        [
            "find",
            str(RELEASE),
            "-path",
            "*/derivatives/*",
            "-prune",
            "-o",
            "-path",
            "*/sub-*/ses-*/dwi/*_dwi.nii.gz",
            "-print",
        ],
        text=True,
    )
    paths = [Path(line) for line in out.splitlines() if line.strip()]
    paths.sort()
    return paths


def sidecar(path: Path, ext: str) -> Path:
    return Path(str(path).replace(".nii.gz", ext))


def read_nifti_shape_zooms(path: Path) -> tuple[tuple[int, ...] | None, tuple[float, ...] | None, str]:
    """Read NIfTI-1 dim/pixdim from the gzip header without loading the image."""
    try:
        with gzip.open(path, "rb") as handle:
            hdr = handle.read(352)
        if len(hdr) < 352:
            return None, None, "truncated_header"
        sizeof = struct.unpack("<i", hdr[0:4])[0]
        endian = "<" if sizeof == 348 else ">"
        if struct.unpack(endian + "i", hdr[0:4])[0] != 348:
            return None, None, "unrecognised_nifti_header"
        dim = struct.unpack(endian + "8h", hdr[40:56])
        pixdim = struct.unpack(endian + "8f", hdr[76:108])
        ndim = int(dim[0])
        if ndim < 1 or ndim > 7:
            return None, None, f"invalid_ndim={ndim}"
        shape = tuple(int(dim[i]) for i in range(1, ndim + 1))
        zooms = tuple(float(pixdim[i]) for i in range(1, ndim + 1))
        return shape, zooms, "ok"
    except Exception as exc:  # noqa: BLE001 — QC must record any header failure
        return None, None, f"header_read_error:{exc}"


def load_bval(path: Path) -> np.ndarray | None:
    if not path.exists():
        return None
    try:
        vals = np.loadtxt(path, dtype=float)
    except Exception:  # noqa: BLE001
        return None
    return np.atleast_1d(vals).astype(float).ravel()


def load_bvec(path: Path) -> np.ndarray | None:
    if not path.exists():
        return None
    try:
        arr = np.loadtxt(path, dtype=float)
    except Exception:  # noqa: BLE001
        return None
    arr = np.atleast_2d(arr)
    if arr.shape[0] == 3:
        return arr
    if arr.shape[1] == 3:
        return arr.T
    return arr


def unique_directions(vecs: np.ndarray, deg: float = DIR_MERGE_DEG) -> np.ndarray:
    """Return unique unit directions, merging those within `deg` (and antipodes)."""
    if vecs.size == 0:
        return np.zeros((0, 3))
    v = np.asarray(vecs, dtype=float)
    nrm = np.linalg.norm(v, axis=1)
    keep = nrm > 1e-8
    v = v[keep]
    if v.size == 0:
        return np.zeros((0, 3))
    v = v / np.linalg.norm(v, axis=1, keepdims=True)
    # Fold to z >= 0 so antipodal pairs count once (DWI).
    flip = v[:, 2] < 0
    v[flip] *= -1
    uniq: list[np.ndarray] = []
    cos_thr = float(np.cos(np.deg2rad(deg)))
    for row in v:
        if not uniq:
            uniq.append(row)
            continue
        dots = np.abs(np.asarray(uniq) @ row)
        if float(dots.max()) < cos_thr:
            uniq.append(row)
    return np.asarray(uniq)


def lambert_azimuthal_equal_area(v: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Upper-hemisphere Lambert azimuthal equal-area projection (Schmidt net)."""
    x, y, z = v[:, 0], v[:, 1], v[:, 2]
    z = np.clip(z, -1.0 + 1e-12, 1.0)
    rho = np.sqrt(2.0 * (1.0 - z))
    phi = np.arctan2(y, x)
    return rho * np.cos(phi), rho * np.sin(phi)


def voxel_string(zooms: tuple[float, ...] | None) -> str:
    if not zooms or len(zooms) < 3:
        return "n/a"
    return f"{zooms[0]:.2f}x{zooms[1]:.2f}x{zooms[2]:.2f}"


def pe_label(pe: str | None) -> str:
    mapping = {"j-": "AP", "j": "PA", "i-": "RL", "i": "LR", "k-": "SI", "k": "IS"}
    if not pe:
        return "n/a"
    return mapping.get(pe, pe)


def wrap_label(text: str, width: int = 34) -> str:
    if len(text) <= width:
        return text
    parts = text.split("_")
    lines: list[str] = []
    cur = ""
    for part in parts:
        trial = part if not cur else cur + "_" + part
        if len(trial) <= width:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = part
    if cur:
        lines.append(cur)
    return "\n".join(lines) if lines else text


def tex_tt(text: str) -> str:
    return r"\texttt{" + text.replace("_", r"\_").replace("%", r"\%") + "}"


def process_one(path: Path) -> tuple[dict, list[str]]:
    qc_lines: list[str] = []
    rec: dict = {
        "path": str(path),
        "relpath": str(path.relative_to(RELEASE)),
        "subject": path.parts[-4],
        "session": path.parts[-3],
        "filename": path.name,
        "is_phase": "part-phase" in path.name,
    }
    json_path = sidecar(path, ".json")
    bval_path = sidecar(path, ".bval")
    bvec_path = sidecar(path, ".bvec")
    rec["json_exists"] = json_path.exists()
    rec["bval_exists"] = bval_path.exists()
    rec["bvec_exists"] = bvec_path.exists()

    meta: dict = {}
    if json_path.exists():
        try:
            meta = json.loads(json_path.read_text())
        except Exception as exc:  # noqa: BLE001
            rec["json_error"] = str(exc)
            qc_lines.append(f"MALFORMED_JSON\t{rec['relpath']}\t{exc}")
    else:
        qc_lines.append(f"MISSING_JSON\t{rec['relpath']}")

    rec["SeriesDescription"] = meta.get("SeriesDescription") or ""
    rec["ProtocolName"] = meta.get("ProtocolName") or ""
    rec["SequenceName"] = meta.get("SequenceName") or ""
    rec["PhaseEncodingDirection"] = meta.get("PhaseEncodingDirection") or ""
    rec["EffectiveEchoSpacing"] = meta.get("EffectiveEchoSpacing")
    rec["TotalReadoutTime"] = meta.get("TotalReadoutTime")
    rec["RepetitionTime"] = meta.get("RepetitionTime")
    rec["EchoTime"] = meta.get("EchoTime")
    rec["SliceThickness"] = meta.get("SliceThickness")
    rec["PixelSpacing"] = meta.get("PixelSpacing")

    shape, zooms, hdr_status = read_nifti_shape_zooms(path)
    rec["nifti_header_status"] = hdr_status
    rec["nifti_shape"] = shape
    rec["nifti_zooms"] = zooms
    rec["n_vol_nifti"] = (
        int(shape[3]) if shape and len(shape) >= 4 else (1 if shape else None)
    )
    rec["voxel_mm"] = voxel_string(zooms)
    if hdr_status != "ok":
        qc_lines.append(f"NIFTI_HEADER\t{rec['relpath']}\t{hdr_status}")

    bval = load_bval(bval_path)
    bvec = load_bvec(bvec_path)
    rec["n_bval"] = None if bval is None else int(bval.size)
    rec["bvec_shape"] = None if bvec is None else f"{bvec.shape[0]}x{bvec.shape[1]}"

    issues: list[str] = []
    if bval is None:
        issues.append("missing_or_unreadable_bval")
        qc_lines.append(f"MISSING_BVAL\t{rec['relpath']}")
    if bvec is None:
        issues.append("missing_or_unreadable_bvec")
        qc_lines.append(f"MISSING_BVEC\t{rec['relpath']}")
    if bval is not None and rec["n_vol_nifti"] is not None and int(bval.size) != rec["n_vol_nifti"]:
        issues.append(
            f"bval_len={int(bval.size)}_ne_nifti_t={rec['n_vol_nifti']}"
        )
        qc_lines.append(
            f"BVAL_LENGTH_MISMATCH\t{rec['relpath']}\tbval={int(bval.size)}\tnifti_t={rec['n_vol_nifti']}"
        )
    if bvec is not None:
        if bvec.shape[0] != 3:
            issues.append(f"bvec_rows={bvec.shape[0]}_expected_3")
            qc_lines.append(f"BVEC_SHAPE\t{rec['relpath']}\t{bvec.shape}")
        elif bval is not None and bvec.shape[1] != bval.size:
            issues.append(
                f"bvec_cols={bvec.shape[1]}_ne_bval={bval.size}"
            )
            qc_lines.append(
                f"BVEC_LENGTH_MISMATCH\t{rec['relpath']}\tbvec_cols={bvec.shape[1]}\tbval={bval.size}"
            )

    if bval is not None:
        canon = np.array([canonical_b(float(x)) for x in bval], dtype=int)
        rec["b_hist"] = dict(sorted(Counter(canon.tolist()).items()))
        rec["n_b0"] = int((canon == 0).sum())
        rec["n_dw"] = int((canon > 0).sum())
        rec["raw_b_unique"] = sorted({float(x) for x in bval})
    else:
        rec["b_hist"] = {}
        rec["n_b0"] = None
        rec["n_dw"] = None
        rec["raw_b_unique"] = []

    rec["shell_unique_dirs"] = {}
    rec["repeat_factor"] = None
    if bval is not None and bvec is not None and bvec.shape[0] == 3 and bvec.shape[1] == bval.size:
        canon = np.array([canonical_b(float(x)) for x in bval], dtype=int)
        vecs = bvec.T
        repeats: list[int] = []
        for shell in sorted(set(canon.tolist()) - {0}):
            sel = vecs[canon == shell]
            uniq = unique_directions(sel)
            rec["shell_unique_dirs"][shell] = int(len(uniq))
            if len(uniq) > 0:
                repeats.append(int(round(len(sel) / len(uniq))))
        if rec["n_b0"]:
            uniq0 = unique_directions(vecs[canon == 0])
            rec["n_b0_unique_encodings"] = int(len(uniq0))
        if repeats:
            rec["repeat_factor"] = int(Counter(repeats).most_common(1)[0][0])

    rec["issues"] = issues
    rec["qc_ok"] = len(issues) == 0
    if not rec["qc_ok"]:
        qc_lines.append(f"SERIES_ISSUES\t{rec['relpath']}\t{';'.join(issues)}")
    return rec, qc_lines


def enumerate_series(paths: list[Path]) -> tuple[list[dict], list[str]]:
    records: list[dict] = []
    qc_lines: list[str] = []
    n = len(paths)
    print(f"Reading sidecars and NIfTI headers for {n} DWI series...", flush=True)
    for done, path in enumerate(paths, start=1):
        rec, rec_qc = process_one(path)
        records.append(rec)
        qc_lines.extend(rec_qc)
        if done % 50 == 0 or done == n or done <= 3:
            print(f"  {done}/{n}", flush=True)
    return records, qc_lines


def scheme_key(rec: dict) -> tuple:
    label = rec["SeriesDescription"] or rec["ProtocolName"] or "UNKNOWN"
    b_hist = tuple(sorted((int(k), int(v)) for k, v in rec["b_hist"].items()))
    dirs = tuple(sorted((int(k), int(v)) for k, v in rec["shell_unique_dirs"].items()))
    return (
        label,
        rec["ProtocolName"],
        rec["SequenceName"],
        rec["PhaseEncodingDirection"],
        rec["voxel_mm"],
        rec["n_vol_nifti"],
        b_hist,
        dirs,
    )


def classify_scheme(rec: dict) -> str:
    desc = (rec["SeriesDescription"] or "").upper()
    n_dw = rec["n_dw"] or 0
    n_b0 = rec["n_b0"] or 0
    n_shells = len([k for k in rec["b_hist"] if k > 0])
    if "TRACEW" in desc:
        return "trace_weighted"
    if n_dw == 0 and n_b0 > 0:
        return "b0_reference"
    if n_shells >= 2:
        return "multi_shell"
    if n_shells == 1:
        return "single_shell"
    return "other"


def group_schemes(records: list[dict]) -> list[dict]:
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for rec in records:
        groups[scheme_key(rec)].append(rec)

    schemes: list[dict] = []
    for key, members in groups.items():
        mag = [m for m in members if not m["is_phase"]]
        pha = [m for m in members if m["is_phase"]]
        ref = mag[0] if mag else members[0]
        sessions = {(m["subject"], m["session"]) for m in members}
        subjects = {m["subject"] for m in members}
        shells = sorted(int(k) for k in ref["b_hist"] if int(k) > 0)
        schemes.append(
            {
                "scheme_id": "",
                "series_description": ref["SeriesDescription"] or "UNKNOWN",
                "protocol_name": ref["ProtocolName"],
                "sequence_name": ref["SequenceName"],
                "phase_encoding_direction": ref["PhaseEncodingDirection"],
                "pe_label": pe_label(ref["PhaseEncodingDirection"]),
                "voxel_size_mm": ref["voxel_mm"],
                "slice_thickness_json_mm": ref["SliceThickness"],
                "repetition_time_s": ref["RepetitionTime"],
                "echo_time_s": ref["EchoTime"],
                "effective_echo_spacing_s": ref["EffectiveEchoSpacing"],
                "total_readout_time_s": ref["TotalReadoutTime"],
                "n_volumes": ref["n_vol_nifti"],
                "n_b0": ref["n_b0"],
                "n_b0_unique_encodings": ref.get("n_b0_unique_encodings"),
                "n_dw": ref["n_dw"],
                "b_hist": ref["b_hist"],
                "shells": shells,
                "n_dirs_per_shell_unique": dict(ref["shell_unique_dirs"]),
                "repeat_factor": ref["repeat_factor"],
                "scheme_type": classify_scheme(ref),
                "n_series": len(members),
                "n_magnitude": len(mag),
                "n_part_phase": len(pha),
                "n_sessions": len(sessions),
                "n_subjects": len(subjects),
                "n_series_with_issues": sum(1 for m in members if not m["qc_ok"]),
                "representative_file": ref["relpath"],
                "key": key,
            }
        )
    # Stable, interpretable order: DW schemes first, then b0, then trace.
    type_order = {"multi_shell": 0, "single_shell": 1, "b0_reference": 2, "trace_weighted": 3, "other": 4}
    schemes.sort(
        key=lambda s: (
            type_order.get(s["scheme_type"], 9),
            -s["n_dw"] if s["n_dw"] else 0,
            s["series_description"],
            s["pe_label"],
        )
    )
    for i, sch in enumerate(schemes, start=1):
        sch["scheme_id"] = f"S{i:02d}"
    return schemes


def write_tsv(schemes: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "scheme_id",
        "series_description",
        "protocol_name",
        "sequence_name",
        "scheme_type",
        "phase_encoding_direction",
        "pe_label",
        "voxel_size_mm",
        "slice_thickness_json_mm",
        "repetition_time_s",
        "echo_time_s",
        "effective_echo_spacing_s",
        "total_readout_time_s",
        "n_volumes",
        "n_b0",
        "n_b0_unique_encodings",
        "n_dw",
        "shells_s_mm2",
        "n_vols_per_shell",
        "n_unique_dirs_per_shell",
        "repeat_factor",
        "n_series",
        "n_magnitude",
        "n_part_phase",
        "n_sessions",
        "n_subjects",
        "n_series_with_issues",
        "is_principal",
        "representative_file",
    ]
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t")
        writer.writeheader()
        for sch in schemes:
            hist = sch["b_hist"]
            writer.writerow(
                {
                    "scheme_id": sch["scheme_id"],
                    "series_description": sch["series_description"],
                    "protocol_name": sch["protocol_name"],
                    "sequence_name": sch["sequence_name"],
                    "scheme_type": sch["scheme_type"],
                    "phase_encoding_direction": sch["phase_encoding_direction"],
                    "pe_label": sch["pe_label"],
                    "voxel_size_mm": sch["voxel_size_mm"],
                    "slice_thickness_json_mm": sch["slice_thickness_json_mm"],
                    "repetition_time_s": sch["repetition_time_s"],
                    "echo_time_s": sch["echo_time_s"],
                    "effective_echo_spacing_s": sch["effective_echo_spacing_s"],
                    "total_readout_time_s": sch["total_readout_time_s"],
                    "n_volumes": sch["n_volumes"],
                    "n_b0": sch["n_b0"],
                    "n_b0_unique_encodings": sch["n_b0_unique_encodings"],
                    "n_dw": sch["n_dw"],
                    "shells_s_mm2": ",".join(str(s) for s in sch["shells"]) if sch["shells"] else "",
                    "n_vols_per_shell": ";".join(
                        f"b={k}:{v}" for k, v in sorted(hist.items())
                    ),
                    "n_unique_dirs_per_shell": ";".join(
                        f"b={k}:{v}" for k, v in sorted(sch["n_dirs_per_shell_unique"].items())
                    ),
                    "repeat_factor": sch["repeat_factor"],
                    "n_series": sch["n_series"],
                    "n_magnitude": sch["n_magnitude"],
                    "n_part_phase": sch["n_part_phase"],
                    "n_sessions": sch["n_sessions"],
                    "n_subjects": sch["n_subjects"],
                    "n_series_with_issues": sch["n_series_with_issues"],
                    "is_principal": "yes" if is_principal(sch) else "no",
                    "representative_file": sch["representative_file"],
                }
            )


def shell_color(b: int) -> str:
    if b == 0:
        return COL_B0
    if b == 1000:
        return COL_B1000
    if b == 2000:
        return COL_B2000
    return COL_OTHER


def is_principal(scheme: dict) -> bool:
    return int(scheme.get("n_magnitude") or 0) >= PRINCIPAL_MIN_MAGNITUDE


def representative_bvecs(scheme: dict) -> dict[int, np.ndarray]:
    """Unique DW directions per shell from the representative series."""
    ref_path = RELEASE / scheme["representative_file"]
    bval = load_bval(sidecar(ref_path, ".bval"))
    bvec = load_bvec(sidecar(ref_path, ".bvec"))
    if bval is None or bvec is None or bvec.shape[0] != 3:
        return {}
    canon = np.array([canonical_b(float(x)) for x in bval], dtype=int)
    vecs = bvec.T
    out: dict[int, np.ndarray] = {}
    for shell in sorted(set(canon.tolist()) - {0}):
        out[shell] = unique_directions(vecs[canon == shell])
    return out


def draw_sphere(ax, dirs_by_shell: dict[int, np.ndarray], subtitle: str) -> None:
    ax.set_aspect("equal")
    ax.set_xlim(-1.55, 1.55)
    ax.set_ylim(-1.55, 1.55)
    ax.axis("off")
    rim = Circle((0, 0), np.sqrt(2.0), fill=False, lw=0.8, ec=COL_INK, zorder=2)
    ax.add_patch(rim)
    mid = Circle((0, 0), 1.0, fill=False, lw=0.4, ec=COL_RULE, ls="--", zorder=1)
    ax.add_patch(mid)
    ax.axhline(0, color=COL_RULE, lw=0.4, zorder=1)
    ax.axvline(0, color=COL_RULE, lw=0.4, zorder=1)
    ax.scatter([0], [0], s=8, c=COL_INK, zorder=3, linewidths=0)
    for shell, vecs in sorted(dirs_by_shell.items()):
        if vecs.size == 0:
            continue
        xs, ys = lambert_azimuthal_equal_area(vecs)
        ax.scatter(
            xs,
            ys,
            s=14 if len(vecs) < 40 else 9,
            c=shell_color(shell),
            alpha=0.9,
            linewidths=0.2,
            edgecolors="white",
            zorder=4,
            label=rf"$b={shell}$ ($n={len(vecs)}$)",
        )
    ax.set_title(subtitle, fontsize=7.5, color=COL_INK, pad=4)
    if dirs_by_shell:
        ax.legend(
            loc="lower center",
            bbox_to_anchor=(0.5, -0.18),
            ncol=min(3, len(dirs_by_shell)),
            fontsize=6.5,
            frameon=False,
            handletextpad=0.3,
            columnspacing=0.8,
        )


def plot_figure(schemes: list[dict]) -> None:
    principal = [s for s in schemes if is_principal(s)]
    dw_schemes = [s for s in principal if s["scheme_type"] in {"multi_shell", "single_shell"}]
    b0_principal = [s for s in principal if s["scheme_type"] == "b0_reference"]
    n_variant_series = sum(s["n_series"] for s in schemes if not is_principal(s))
    n_variant_schemes = sum(1 for s in schemes if not is_principal(s))

    plt.rcParams.update(
        {
            "font.family": "serif",
            "font.serif": ["DejaVu Serif", "Times New Roman", "Times"],
            "font.size": 8,
            "axes.linewidth": 0.6,
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
            "figure.facecolor": "white",
            "axes.facecolor": "white",
            "savefig.facecolor": "white",
            "text.color": COL_INK,
            "axes.labelcolor": COL_INK,
            "xtick.color": COL_INK,
            "ytick.color": COL_INK,
        }
    )

    fig = plt.figure(figsize=(7.4, 3.95), dpi=300)
    n_a = max(1, len(dw_schemes))
    axes_a = []
    width_a = 0.245
    gap_a = 0.025
    left0 = 0.03
    for i in range(n_a):
        left = left0 + i * (width_a + gap_a)
        axes_a.append(fig.add_axes([left, 0.22, width_a, 0.62]))

    ax_b = fig.add_axes([0.56, 0.22, 0.42, 0.62])

    fig.text(0.02, 0.93, "A", fontsize=12, fontweight="bold", color=COL_INK)
    fig.text(
        0.05,
        0.93,
        "Q-space sampling",
        fontsize=8.5,
        color=COL_INK,
        va="center",
    )
    fig.text(0.55, 0.93, "B", fontsize=12, fontweight="bold", color=COL_INK)
    fig.text(
        0.58,
        0.93,
        "Acquisition overview",
        fontsize=8.5,
        color=COL_INK,
        va="center",
    )

    if not dw_schemes:
        axes_a[0].axis("off")
        axes_a[0].text(0.5, 0.5, "No diffusion-weighted schemes found", ha="center")
    else:
        for ax, sch in zip(axes_a, dw_schemes):
            dirs = representative_bvecs(sch)
            n_unique = sum(len(v) for v in dirs.values())
            title = f"{wrap_label(sch['series_description'], 24)}\n{n_unique} unique directions"
            draw_sphere(ax, dirs, title)

    b0_note = ""
    if b0_principal:
        names = "; ".join(
            f"{s['series_description']} ({s['pe_label']}, {s['n_b0']} $b=0$)"
            for s in b0_principal
        )
        b0_note = f" $b=0$ reverse-PE references not shown as shells: {names}."
    fig.text(
        0.03,
        0.02,
        "Lambert azimuthal equal-area (upper hemisphere; antipodes folded). "
        "Points are unique non-zero directions from a representative .bvec."
        + b0_note,
        fontsize=5.8,
        color=COL_INK,
        wrap=True,
    )

    n = len(principal)
    y_pos = np.arange(n)[::-1]
    ax_b.set_xlim(-180, 3600)
    ax_b.set_ylim(-0.85, n - 0.05)
    ax_b.set_yticks(y_pos)
    ax_b.set_yticklabels([f"{s['pe_label']}" for s in principal], fontsize=7)
    ax_b.tick_params(axis="y", length=0, pad=3)
    ax_b.set_xticks([0, 1000, 2000])
    ax_b.set_xticklabels([r"$b=0$", r"$b=1000$", r"$b=2000$"], fontsize=7)
    ax_b.set_xlabel(r"$b$ (s/mm$^2$)", fontsize=7.5, labelpad=3)
    for spine in ("top", "right", "left"):
        ax_b.spines[spine].set_visible(False)
    ax_b.spines["bottom"].set_color(COL_RULE)
    ax_b.grid(axis="x", color="#E5E7EB", lw=0.5, zorder=0)
    ax_b.set_axisbelow(True)

    size_scale = 16.0
    for yi, sch in zip(y_pos, principal):
        nb0 = sch["n_b0"] or 0
        if nb0:
            ax_b.scatter(
                [0], [yi],
                s=max(32, size_scale * np.sqrt(nb0)),
                c=COL_B0, zorder=3, linewidths=0.35, edgecolors="white",
            )
            ax_b.annotate(
                str(nb0), (0, yi), textcoords="offset points", xytext=(0, 8),
                ha="center", va="bottom", fontsize=6.0, color=COL_B0,
            )
        if sch["scheme_type"] == "trace_weighted":
            nvol = sch["b_hist"].get(1000, 1)
            ax_b.scatter(
                [1000], [yi],
                s=44, c=COL_B1000, marker="D", zorder=3,
                linewidths=0.35, edgecolors="white",
            )
            ax_b.text(1000, yi + 0.28, f"{nvol} vol (trace)", va="bottom", ha="center",
                      fontsize=6.0, color=COL_B1000)
        else:
            for shell, ndir in sorted(sch["n_dirs_per_shell_unique"].items()):
                if shell not in (1000, 2000) or ndir <= 0:
                    continue
                ax_b.scatter(
                    [shell], [yi],
                    s=max(40, size_scale * np.sqrt(ndir) * 3.4),
                    c=shell_color(shell), zorder=3, linewidths=0.35, edgecolors="white",
                )
                extra = f"{ndir}"
                if sch["repeat_factor"] and sch["repeat_factor"] > 1:
                    extra += f"×{sch['repeat_factor']}"
                ax_b.annotate(
                    extra, (shell, yi), textcoords="offset points", xytext=(0, 8),
                    ha="center", va="bottom", fontsize=6.0, color=shell_color(shell),
                )
        voxel = sch["voxel_size_mm"].replace("x", "×")
        ax_b.text(
            2180,
            yi,
            f"{wrap_label(sch['series_description'], 28)}\n"
            f"{voxel} mm · n={sch['n_magnitude']}",
            va="center",
            ha="left",
            fontsize=5.9,
            color=COL_INK,
            linespacing=1.05,
            clip_on=False,
        )

    ax_b.text(
        0.0, 1.03,
        "Numbers above markers: $b=0$ volumes, or unique DW directions (× stored repeats).",
        transform=ax_b.transAxes, fontsize=5.8, color=COL_INK, va="bottom",
    )
    if n_variant_schemes:
        ax_b.text(
            0.0, -0.22,
            f"{n_variant_schemes} less frequent variants ({n_variant_series} series) "
            "are listed in dwi_protocol_summary.tsv.",
            transform=ax_b.transAxes, fontsize=5.6, color=COL_INK, va="top",
        )

    legend_elems = [
        Line2D([0], [0], marker="o", color="none", markerfacecolor=COL_B0,
               markersize=6, label=r"$b=0$ volumes"),
        Line2D([0], [0], marker="o", color="none", markerfacecolor=COL_B1000,
               markersize=7, label=r"$b=1000$ dirs"),
        Line2D([0], [0], marker="o", color="none", markerfacecolor=COL_B2000,
               markersize=7, label=r"$b=2000$ dirs"),
        Line2D([0], [0], marker="D", color="none", markerfacecolor=COL_B1000,
               markersize=6, label="trace-weighted"),
    ]
    ax_b.legend(
        handles=legend_elems, loc="lower left", bbox_to_anchor=(0.0, -0.38),
        ncol=2, fontsize=5.8, frameon=False, handletextpad=0.35, columnspacing=0.9,
    )

    FIG_PNG.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(FIG_PNG, dpi=300, bbox_inches="tight", pad_inches=0.06)
    fig.savefig(FIG_PDF, bbox_inches="tight", pad_inches=0.06)
    plt.close(fig)


def write_qc(
    path: Path,
    records: list[dict],
    schemes: list[dict],
    qc_lines: list[str],
) -> str:
    n_series = len(records)
    n_mag = sum(1 for r in records if not r["is_phase"])
    n_phase = sum(1 for r in records if r["is_phase"])
    sessions = {(r["subject"], r["session"]) for r in records}
    n_malformed = sum(1 for r in records if not r["qc_ok"])
    b_sets = sorted(
        {
            tuple(sorted((int(k), int(v)) for k, v in r["b_hist"].items()))
            for r in records
            if r["b_hist"]
        }
    )

    lines = [
        "Figure_DWI_protocols quality-control log",
        "Source: release_dataset BIDS dwi/ (NIfTI + JSON + bval + bvec).",
        "No DWI, JSON, bval, or bvec files were modified.",
        "",
        f"Total DWI NIfTI series: {n_series} (magnitude={n_mag}, part-phase={n_phase})",
        f"Sessions containing DWI: {len(sessions)}",
        f"Subjects containing DWI: {len({r['subject'] for r in records})}",
        f"Unique acquisition schemes: {len(schemes)}",
        f"Series with malformed/missing gradient tables or length mismatches: {n_malformed}",
        "",
        f"b-value grouping: volumes with b < {B0_THRESH:.0f} s/mm^2 counted as b=0;",
        f"  remaining values snapped to a {BVAL_GRID:.0f} s/mm^2 grid if within {BVAL_TOL:.0f} s/mm^2.",
        f"Unique directions: unit vectors merged within {DIR_MERGE_DEG:.1f} deg; antipodes folded.",
        "",
        "Unique canonical b-value histograms (b: n_volumes):",
    ]
    for hist in b_sets:
        lines.append("  " + ", ".join(f"b={b}:{n}" for b, n in hist))
    lines.append("")
    lines.append("Protocol-level schemes:")
    for sch in schemes:
        dirs = ", ".join(
            f"b={b}:{n} unique dirs" for b, n in sorted(sch["n_dirs_per_shell_unique"].items())
        ) or "no DW directions"
        lines.append(
            f"  {sch['scheme_id']}  {sch['series_description']}  type={sch['scheme_type']}  "
            f"PE={sch['pe_label']}  voxel={sch['voxel_size_mm']} mm  "
            f"n_vol={sch['n_volumes']}  n_b0={sch['n_b0']}  {dirs}  "
            f"repeat={sch['repeat_factor']}  n_series={sch['n_series']}  "
            f"n_sessions={sch['n_sessions']}  issues={sch['n_series_with_issues']}"
        )
    lines.append("")
    lines.append("Per-series QC flags:")
    if qc_lines:
        lines.extend(qc_lines)
    else:
        lines.append("  none")
    text = "\n".join(lines) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return text


def write_caption(schemes: list[dict], n_series: int, n_sessions: int) -> None:
    principal = [s for s in schemes if is_principal(s)]
    dw = [s for s in principal if s["scheme_type"] in {"multi_shell", "single_shell"}]
    b0 = [s for s in principal if s["scheme_type"] == "b0_reference"]
    a_bits = []
    for s in dw:
        dirs = ", ".join(
            rf"$b={b}$ ($n={n}$ unique directions)"
            for b, n in sorted(s["n_dirs_per_shell_unique"].items())
        )
        a_bits.append(f"{tex_tt(s['series_description'])} [{s['pe_label']}: {dirs}]")
    b0_txt = ""
    if b0:
        b0_txt = (
            " Reverse-phase-encoding $b=0$ series ("
            + "; ".join(f"{tex_tt(s['series_description'])} [{s['pe_label']}]" for s in b0)
            + ") are reference images and are not plotted as diffusion shells."
        )
    n_var = sum(1 for s in schemes if not is_principal(s))
    caption = (
        r"Diffusion MRI acquisition schemes in the released BIDS dataset. "
        r"(A)~Angular distribution of unique non-zero diffusion-encoding directions "
        r"from representative \texttt{.bvec} files, shown as a Lambert azimuthal "
        r"equal-area projection of the upper hemisphere (antipodal directions folded). "
        + "; ".join(a_bits)
        + "."
        + b0_txt
        + r" (B)~Protocol-level summary of $b$-value shells, unique angular samples "
        r"per shell, $b=0$ volume counts, voxel size, phase-encoding direction, and "
        r"number of magnitude series for schemes represented in $\geq$"
        + str(PRINCIPAL_MIN_MAGNITUDE)
        + r" series. The figure is derived from "
        + str(n_series)
        + r" released DWI NIfTI files in "
        + str(n_sessions)
        + r" sessions and shows unique acquisition schemes rather than every "
        r"individual series. Where a gradient table stores repeated encodings of the "
        r"same direction, panel~A plots unique directions and panel~B reports the "
        r"observed repeat factor. "
        + str(n_var)
        + r" less frequent variants (truncated shells, alternate voxel size, missing "
        r"phase-encoding metadata, or shim/PE differences) are tabulated in "
        r"\texttt{dwi\_protocol\_summary.tsv}."
    )
    CAPTION_PATH.write_text(
        "\\begin{figure}[htbp]\n"
        "\\centering\n"
        "\\includegraphics[width=\\linewidth]{figures/Figure_DWI_protocols.pdf}\n"
        "\\caption{" + caption + "}\n"
        "\\label{fig:dwi_protocols}\n"
        "\\end{figure}\n"
    )


def print_audit(records: list[dict], schemes: list[dict], n_malformed: int) -> None:
    sessions = {(r["subject"], r["session"]) for r in records}
    print("=== DWI protocol figure audit ===")
    print(f"total DWI series: {len(records)}")
    print(f"  magnitude: {sum(1 for r in records if not r['is_phase'])}")
    print(f"  part-phase: {sum(1 for r in records if r['is_phase'])}")
    print(f"sessions containing DWI: {len(sessions)}")
    print(f"unique acquisition schemes: {len(schemes)}")
    print("unique b-value sets (canonical b: n_volumes):")
    seen = sorted(
        {
            tuple(sorted((int(k), int(v)) for k, v in r["b_hist"].items()))
            for r in records
            if r["b_hist"]
        }
    )
    for hist in seen:
        print("  " + ", ".join(f"b={b}:{n}" for b, n in hist))
    print("directions per shell (unique) and b=0 counts by scheme:")
    for sch in schemes:
        dirs = ", ".join(
            f"b={b}:{n}" for b, n in sorted(sch["n_dirs_per_shell_unique"].items())
        ) or "—"
        print(
            f"  {sch['scheme_id']} {sch['series_description']} [{sch['pe_label']}] "
            f"type={sch['scheme_type']}  dirs={dirs}  n_b0={sch['n_b0']}  "
            f"repeat={sch['repeat_factor']}  n_series={sch['n_series']}"
        )
    print(f"malformed/missing gradient tables or length mismatches: {n_malformed}")
    print(f"wrote {FIG_PNG}")
    print(f"wrote {FIG_PDF}")
    print(f"wrote {TSV_PATH}")
    print(f"wrote {QC_PATH}")
    print(f"wrote {CAPTION_PATH}")


def main() -> None:
    plot_only = "--plot-only" in sys.argv
    if plot_only and CACHE_PATH.exists():
        bundle = pickle.loads(CACHE_PATH.read_bytes())
        schemes = bundle["schemes"]
        print("Loaded cached schemes; redrawing figure...", flush=True)
        write_caption(schemes, bundle["n_series"], bundle["n_sessions"])
        plot_figure(schemes)
        print(f"wrote {FIG_PNG}")
        print(f"wrote {FIG_PDF}")
        return

    print("Finding DWI NIfTIs in release_dataset...", flush=True)
    paths = find_dwi_niis()
    print(f"Found {len(paths)} files", flush=True)
    records, qc_lines = enumerate_series(paths)
    schemes = group_schemes(records)
    write_tsv(schemes, TSV_PATH)
    paper_tsv = PAPER / "metadata" / "dwi_protocol_summary.tsv"
    paper_tsv.parent.mkdir(parents=True, exist_ok=True)
    paper_tsv.write_text(TSV_PATH.read_text())
    n_malformed = sum(1 for r in records if not r["qc_ok"])
    write_qc(QC_PATH, records, schemes, qc_lines)
    sessions = {(r["subject"], r["session"]) for r in records}
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_bytes(
        pickle.dumps(
            {
                "schemes": schemes,
                "n_series": len(records),
                "n_sessions": len(sessions),
                "n_malformed": n_malformed,
            }
        )
    )
    write_caption(schemes, len(records), len(sessions))
    plot_figure(schemes)
    print_audit(records, schemes, n_malformed)


if __name__ == "__main__":
    main()
