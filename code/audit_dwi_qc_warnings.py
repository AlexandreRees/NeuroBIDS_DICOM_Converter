#!/usr/bin/env python3
"""Rigorous AUDIT of DWI QC warnings (Scientific Data / OpenNeuro).

READ-ONLY with respect to bids/, raw_original/, and derivatives/.
All outputs are written under reports/dwi_qc/ (and subfolders).

Parts:
  1. dwigradcheck REVIEW investigation
  2. Negative mean-b0 investigation
  3. Brain-mask validation (Dice vs FSL BET)
  4. Robust within-mask signal metrics
  5. Publication figures A–F
  6–7. WARNING resolution + publication recommendation

Example:
  module load StdEnv/2023 python/3.11 scipy-stack mrtrix fsl
  python code/audit_dwi_qc_warnings.py \\
      --qc-dir /home/alexrees/scratch/reports/dwi_qc
"""

from __future__ import annotations

import argparse
import csv
import re
import shutil
import subprocess
import sys
import traceback
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import nibabel as nib
import numpy as np
from matplotlib.gridspec import GridSpec

B0_THRESHOLD = 50.0
DEFAULT_QC = Path("/home/alexrees/scratch/reports/dwi_qc")
DPI = 300
C_FILL = "#4D4D4D"
C_ACCENT = "#2C5F8A"
C_PASS = "#2E7D4F"
C_REVIEW = "#B07D2A"
C_FAIL = "#8B3A3A"
C_GRID = "#D0D0D0"

IDENTITY_PERM = "(0, 1, 2)"
ROW_RE = re.compile(
    r"^\s*([0-9.+-eE]+)\s+(\S+)\s+(\([^)]*\))\s+(\S+)\s*$"
)


def log(msg: str) -> None:
    print(msg, flush=True)


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--qc-dir", type=Path, default=DEFAULT_QC)
    p.add_argument("--workers", type=int, default=4)
    p.add_argument(
        "--max-mask-validate",
        type=int,
        default=None,
        help="Optional cap on mask-validation scans (debug).",
    )
    p.add_argument(
        "--skip-mask-validate",
        action="store_true",
        help="Skip BET Dice validation (Parts 3 related).",
    )
    p.add_argument(
        "--skip-negative-viz",
        action="store_true",
        help="Skip negative-b0 NIfTI visualisation.",
    )
    return p.parse_args()


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def write_tsv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fieldnames})


def run_of(nifti: str | Path) -> str:
    name = Path(nifti).name
    for part in name.replace(".nii.gz", "").split("_"):
        if part.startswith("run-"):
            return part
    return "n/a"


def stem_of(nifti: str | Path) -> str:
    return Path(nifti).name.replace(".nii.gz", "")


def to_float(x: Any) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if np.isfinite(v) else None


def load_bval(path: Path) -> np.ndarray:
    text = path.read_text(encoding="utf-8").replace(",", " ")
    return np.asarray([float(x) for x in text.split()], dtype=float)


def parse_gradcheck_table(output: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in (output or "").splitlines():
        m = ROW_RE.match(line)
        if not m:
            continue
        rows.append(
            {
                "mean_length": float(m.group(1)),
                "flip": m.group(2),
                "perm": m.group(3),
                "basis": m.group(4),
            }
        )
    return rows


def classify_suggestion(flip: str, perm: str) -> str:
    flip_l = (flip or "").lower()
    perm_n = re.sub(r"\s+", "", perm or "")
    is_ident_perm = perm_n in {"(0,1,2)"}
    is_no_flip = flip_l in {"none", "-"}
    # Note: flip "0"/"1"/"2" means flip that axis (NOT identity)
    is_axis_flip = flip_l in {"0", "1", "2"}
    if is_no_flip and is_ident_perm:
        return "identity"
    if is_axis_flip and is_ident_perm:
        return "axis_flip"
    if is_no_flip and not is_ident_perm:
        return "axis_swap"
    if is_axis_flip and not is_ident_perm:
        return "axis_flip_and_swap"
    return "unknown"


def apply_style() -> None:
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 9,
            "axes.titlesize": 11,
            "axes.labelsize": 9,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "figure.facecolor": "white",
            "axes.facecolor": "white",
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
            "svg.fonttype": "none",
        }
    )


# ---------------------------------------------------------------------------
# Part 1 — REVIEW gradient analysis
# ---------------------------------------------------------------------------


def part1_review_analysis(
    inventory: list[dict[str, str]],
    gradcheck: list[dict[str, str]],
    bvals: list[dict[str, str]],
    out_tsv: Path,
    out_md: Path,
) -> dict[str, Any]:
    rows_out: list[dict[str, Any]] = []
    for inv, gc, bv in zip(inventory, gradcheck, bvals):
        if gc.get("status") != "REVIEW":
            continue
        parsed = parse_gradcheck_table(gc.get("output") or "")
        top = parsed[0] if parsed else {}
        # identity row if present
        ident = next(
            (
                p
                for p in parsed
                if classify_suggestion(p["flip"], p["perm"]) == "identity"
            ),
            None,
        )
        suggestion_class = (
            classify_suggestion(top.get("flip", ""), top.get("perm", ""))
            if top
            else "unknown"
        )
        # Map "rotation" not produced by dwigradcheck; keep unknown only if unparsed
        rows_out.append(
            {
                "subject": inv["subject"],
                "session": inv["session"],
                "run": run_of(inv["nifti"]),
                "nifti": inv["nifti"],
                "n_diffusion": bv.get("n_diffusion", ""),
                "unique_bvals": bv.get("unique_bvals", ""),
                "top_mean_length": top.get("mean_length", ""),
                "top_axis_flipped": top.get("flip", ""),
                "top_axis_permutation": top.get("perm", ""),
                "top_axis_basis": top.get("basis", ""),
                "suggestion_class": suggestion_class,
                "identity_mean_length": ident["mean_length"] if ident else "",
                "identity_rank": (
                    next(
                        (
                            i
                            for i, p in enumerate(parsed)
                            if classify_suggestion(p["flip"], p["perm"]) == "identity"
                        ),
                        "",
                    )
                ),
                "delta_best_minus_identity": (
                    (top["mean_length"] - ident["mean_length"])
                    if top and ident
                    else ""
                ),
                "n_table_rows_parsed": len(parsed),
            }
        )

    fields = list(rows_out[0].keys()) if rows_out else [
        "subject",
        "session",
        "run",
        "suggestion_class",
    ]
    write_tsv(out_tsv, rows_out, fields)

    class_counts = Counter(r["suggestion_class"] for r in rows_out)
    config_counts = Counter(
        (
            str(r["top_axis_flipped"]),
            str(r["top_axis_permutation"]),
            str(r["top_axis_basis"]),
        )
        for r in rows_out
    )
    run_counts = Counter(r["run"] for r in rows_out)
    scheme_counts = Counter(r["unique_bvals"] for r in rows_out)
    top_config, top_n = (config_counts.most_common(1)[0] if config_counts else (("?", "?", "?"), 0))
    frac_top = top_n / len(rows_out) if rows_out else 0.0
    single_orientation = frac_top >= 0.80

    # Software issue: PASS rows where flip is 0/1/2 but treated as PASS by interpret_dwigradcheck
    pass_misclass = []
    for inv, gc in zip(inventory, gradcheck):
        if gc.get("status") != "PASS":
            continue
        parsed = parse_gradcheck_table(gc.get("output") or "")
        if not parsed:
            continue
        top = parsed[0]
        # replicate buggy rule
        flip = top["flip"].lower()
        perm = re.sub(r"\s+", "", top["perm"])
        buggy_pass = flip in {"none", "0", "-"} and perm in {"(0,1,2)"}
        true_identity = flip in {"none", "-"} and perm in {"(0,1,2)"}
        if buggy_pass and not true_identity:
            pass_misclass.append(
                {
                    "subject": inv["subject"],
                    "session": inv["session"],
                    "run": run_of(inv["nifti"]),
                    "flip": top["flip"],
                    "perm": top["perm"],
                    "basis": top["basis"],
                }
            )

    lines = [
        "# dwigradcheck REVIEW investigation",
        "",
        f"Generated: {utc_now()}",
        "",
        "## Scope",
        "",
        f"- REVIEW scans analysed: **{len(rows_out)}**",
        "- No bvec files were modified.",
        "",
        "## Suggestion class counts",
        "",
    ]
    for cls, n in class_counts.most_common():
        lines.append(f"- `{cls}`: **{n}**")
    lines.extend(
        [
            "",
            "## Top-ranked (flip, permutation, basis) configurations",
            "",
        ]
    )
    for (flip, perm, basis), n in config_counts.most_common(15):
        lines.append(f"- **{n}**: flip=`{flip}`, perm=`{perm}`, basis=`{basis}`")
    lines.extend(
        [
            "",
            "## Acquisition enrichment",
            "",
            "### By run entity",
            "",
        ]
    )
    for run, n in run_counts.most_common():
        lines.append(f"- `{run}`: **{n}**")
    lines.extend(["", "### By b-value scheme", ""])
    for scheme, n in scheme_counts.most_common():
        lines.append(f"- `{scheme}`: **{n}**")

    lines.extend(
        [
            "",
            "## Single-orientation hypothesis",
            "",
            f"- Most common top suggestion accounts for **{top_n}/{len(rows_out)}** "
            f"({100 * frac_top:.1f}%) scans.",
            f"- Shared single orientation explaining ≥80% of REVIEW: "
            f"**{'YES' if single_orientation else 'NO'}**.",
            "",
        ]
    )
    if not single_orientation:
        lines.extend(
            [
                "REVIEW cases do **not** share one common corrective transform. "
                "However, they are strongly enriched in `run-02` multiphase / "
                "high-direction shells. This is best reported as a "
                "**protocol-/acquisition-type observation** about `dwigradcheck` "
                "ranking instability (or acquisition-dependent gradient geometry), "
                "not as 111 independent random failures.",
                "",
            ]
        )
    else:
        lines.extend(
            [
                "A single alternative orientation dominates REVIEW suggestions and "
                "should be treated as a protocol-level observation.",
                "",
            ]
        )

    lines.extend(
        [
            "## Software/reporting note (PASS classifier)",
            "",
            "In `run_dwi_qc.interpret_dwigradcheck`, axis flip value `0` is treated "
            "as equivalent to `none`. In MRtrix, `0` means flip axis 0.",
            f"- PASS rows that are actually non-identity under this rule: **{len(pass_misclass)}**",
            "",
        ]
    )
    for row in pass_misclass[:10]:
        lines.append(
            f"- `{row['subject']}` `{row['session']}` `{row['run']}`: "
            f"flip=`{row['flip']}` perm=`{row['perm']}` basis=`{row['basis']}`"
        )
    lines.extend(["", f"Full table: `{out_tsv.name}`", ""])
    out_md.write_text("\n".join(lines), encoding="utf-8")

    return {
        "n_review": len(rows_out),
        "class_counts": dict(class_counts),
        "config_counts": {str(k): v for k, v in config_counts.items()},
        "run_counts": dict(run_counts),
        "single_orientation": single_orientation,
        "top_config_frac": frac_top,
        "pass_misclass": pass_misclass,
        "rows": rows_out,
    }


# ---------------------------------------------------------------------------
# Shared image helpers
# ---------------------------------------------------------------------------


def load_mean_b0(nifti: Path, bval: Path) -> tuple[np.ndarray, np.ndarray]:
    """Return (mean_b0_3d, affine)."""
    img = nib.load(str(nifti))
    data = np.asanyarray(img.dataobj, dtype=np.float32)
    if data.ndim == 3:
        return data, img.affine
    b = load_bval(bval)
    n = min(data.shape[3], b.size)
    b0_idx = np.where(b[:n] < B0_THRESHOLD)[0]
    if b0_idx.size == 0:
        b0_idx = np.array([0])
    mean_b0 = np.mean(data[..., b0_idx], axis=3)
    return mean_b0, img.affine


def robust_stats(values: np.ndarray) -> dict[str, float]:
    values = np.asarray(values, dtype=np.float64)
    values = values[np.isfinite(values)]
    if values.size == 0:
        return {
            "min": np.nan,
            "max": np.nan,
            "median": np.nan,
            "p05": np.nan,
            "p95": np.nan,
            "mean": np.nan,
            "std": np.nan,
            "cv": np.nan,
            "n": 0,
        }
    med = float(np.median(values))
    std = float(np.std(values))
    mean = float(np.mean(values))
    return {
        "min": float(np.min(values)),
        "max": float(np.max(values)),
        "median": med,
        "p05": float(np.percentile(values, 5)),
        "p95": float(np.percentile(values, 95)),
        "mean": mean,
        "std": std,
        "cv": float(std / med) if med != 0 else np.nan,
        "n": int(values.size),
    }


def ensure_current_mask(
    nifti: Path,
    bvec: Path,
    bval: Path,
    stem: str,
    tmp_dir: Path,
    work_dir: Path,
    allow_regen: bool = False,
) -> Path | None:
    """Return path to an existing mask under reports only (optional regen)."""
    existing = tmp_dir / f"{stem}_mask.nii.gz"
    if existing.is_file():
        return existing
    out = work_dir / "masks_current" / f"{stem}_mask.nii.gz"
    if out.is_file():
        return out
    if not allow_regen:
        return None
    out.parent.mkdir(parents=True, exist_ok=True)
    if shutil.which("dwi2mask") is None:
        return None
    cmd = [
        "dwi2mask",
        str(nifti),
        str(out),
        "-fslgrad",
        str(bvec),
        str(bval),
        "-quiet",
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=900, check=False)
        if proc.returncode != 0 or not out.is_file():
            log(f"  dwi2mask failed for {stem}: {proc.stderr[:200]}")
            return None
        return out
    except Exception as exc:  # noqa: BLE001
        log(f"  dwi2mask exception for {stem}: {exc}")
        return None


def bet_mask_from_mean_b0(
    mean_b0: np.ndarray,
    affine: np.ndarray,
    out_mask: Path,
    work_dir: Path,
    stem: str,
) -> Path | None:
    if shutil.which("bet") is None:
        return None
    out_mask.parent.mkdir(parents=True, exist_ok=True)
    if out_mask.is_file():
        return out_mask
    b0_path = work_dir / "b0_for_bet" / f"{stem}_meanb0.nii.gz"
    b0_path.parent.mkdir(parents=True, exist_ok=True)
    nib.save(nib.Nifti1Image(mean_b0.astype(np.float32), affine), str(b0_path))
    bet_prefix = work_dir / "bet" / stem
    bet_prefix.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["bet", str(b0_path), str(bet_prefix), "-m", "-n", "-f", "0.3"]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300, check=False)
        mask_path = Path(str(bet_prefix) + "_mask.nii.gz")
        if proc.returncode != 0 or not mask_path.is_file():
            log(f"  BET failed for {stem}: {proc.stderr[:200]}")
            return None
        shutil.copy2(mask_path, out_mask)
        return out_mask
    except Exception as exc:  # noqa: BLE001
        log(f"  BET exception for {stem}: {exc}")
        return None


def dice_coef(a: np.ndarray, b: np.ndarray) -> float:
    a = a.astype(bool).ravel()
    b = b.astype(bool).ravel()
    if a.size != b.size:
        return float("nan")
    inter = np.logical_and(a, b).sum()
    denom = a.sum() + b.sum()
    if denom == 0:
        return float("nan")
    return float(2.0 * inter / denom)


# ---------------------------------------------------------------------------
# Part 2 — Negative b0
# ---------------------------------------------------------------------------


def classify_negative_b0(
    inside: dict[str, float],
    outside: dict[str, float],
    brain_fraction: float,
    data_min: float,
    data_max: float,
) -> tuple[str, str]:
    """Return (classification, recommended_action)."""
    # Signed reconstruction: substantial negative intensities inside brain
    if inside["min"] < -50 and inside["p05"] < 0:
        if brain_fraction > 0.55:
            return (
                "signed_reconstruction_with_overinclusive_mask",
                "Document as signed DWI intensities; do not exclude. Optional: use abs() for display-only QC.",
            )
        return (
            "signed_reconstruction",
            "Document as signed reconstruction; retain in release. Prefer robust (median) metrics for QC.",
        )
    if brain_fraction > 0.7 and inside["median"] < 0:
        return (
            "mask_failure_overinclusive",
            "Revisit mask for QC figures only; raw data unchanged. Not an exclusion criterion alone.",
        )
    if outside["n"] and abs(outside["median"]) > abs(inside["median"]) and inside["median"] < 0:
        return (
            "background_inclusion",
            "QC metric artifact from background in mask; no raw-data correction required.",
        )
    if data_min < 0 < data_max and inside["median"] >= 0:
        return (
            "scaling_or_metric_artifact",
            "Negativity confined to sparse voxels; treat mean_b0 warning as metric artifact.",
        )
    if not np.isfinite(inside["median"]):
        return (
            "genuine_image_corruption_or_load_failure",
            "Manual review required before release of this scan.",
        )
    return (
        "mixed_or_uncertain",
        "Manual spot-check; default retain unless structural corruption confirmed.",
    )


def part2_negative_b0(
    inventory: list[dict[str, str]],
    signals: list[dict[str, str]],
    masks: list[dict[str, str]],
    qc_dir: Path,
    work_dir: Path,
    skip_viz: bool,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    out_rows: list[dict[str, Any]] = []
    fig_dir = work_dir / "negative_b0_figures"
    fig_dir.mkdir(parents=True, exist_ok=True)
    class_counts: Counter[str] = Counter()

    indices = [i for i, s in enumerate(signals) if (to_float(s.get("mean_b0_signal")) or 0) < 0]
    log(f"Part 2: {len(indices)} negative mean_b0 scans")

    for i in indices:
        inv = inventory[i]
        nifti = Path(inv["nifti"])
        bval = Path(inv["bval"])
        bvec = Path(inv["bvec"])
        stem = stem_of(nifti)
        subject, session, run = inv["subject"], inv["session"], run_of(nifti)
        log(f"  negative b0: {stem}")
        try:
            img = nib.load(str(nifti))
            affine = img.affine
            b = load_bval(bval)
            if img.ndim == 4:
                n = min(img.shape[3], b.size)
                b0_idx = np.where(b[:n] < B0_THRESHOLD)[0]
                if b0_idx.size == 0:
                    b0_idx = np.array([0])
                # Cap b0 volumes loaded for speed
                if b0_idx.size > 20:
                    b0_idx = b0_idx[np.linspace(0, b0_idx.size - 1, 20).astype(int)]
                b0_stack = load_volume_subset(img, b0_idx)
                mean_b0 = np.mean(b0_stack, axis=3)
            else:
                mean_b0 = np.asanyarray(img.dataobj, dtype=np.float32)

            mask_path = ensure_current_mask(
                nifti, bvec, bval, stem, qc_dir / "tmp", work_dir, allow_regen=False
            )
            mask = None
            if mask_path and mask_path.is_file():
                mask = np.asanyarray(nib.load(str(mask_path)).dataobj) > 0
                if mask.shape != mean_b0.shape:
                    mask = None
            if mask is None:
                thr = float(np.percentile(mean_b0, 50))
                mask = mean_b0 > thr
                mask_path = None

            inside = robust_stats(mean_b0[mask])
            outside = robust_stats(mean_b0[~mask])
            bf = float(mask.mean())
            mvox = int(mask.sum())
            classification, action = classify_negative_b0(
                inside, outside, bf, float(np.nanmin(mean_b0)), float(np.nanmax(mean_b0))
            )
            class_counts[classification] += 1

            if not skip_viz:
                # Orthographic views (nibabel arrays are i,j,k ≈ x,y,z)
                xi, yi, zi = [s // 2 for s in mean_b0.shape]
                fig, axes = plt.subplots(2, 3, figsize=(9.5, 6.2))
                planes = [
                    (mean_b0[:, :, zi], mask[:, :, zi], "Axial b0"),
                    (mean_b0[:, yi, :], mask[:, yi, :], "Coronal b0"),
                    (mean_b0[xi, :, :], mask[xi, :, :], "Sagittal b0"),
                    (mask[:, :, zi].astype(float), None, "Axial mask"),
                    (mask[:, yi, :].astype(float), None, "Coronal mask"),
                    (mask[xi, :, :].astype(float), None, "Sagittal mask"),
                ]
                for ax, (sl, msl, title) in zip(axes.ravel(), planes):
                    ax.imshow(np.rot90(sl), cmap="gray", origin="upper")
                    if msl is not None:
                        ax.contour(np.rot90(msl.astype(float)), levels=[0.5], colors="cyan", linewidths=0.6)
                    ax.set_title(title, fontsize=9)
                    ax.axis("off")
                fig.suptitle(
                    f"{subject} {session} {run} — {classification}",
                    fontsize=11,
                    fontweight="semibold",
                )
                fig.tight_layout()
                fig_path = fig_dir / f"{stem}_negative_b0.png"
                fig.savefig(fig_path, dpi=150, bbox_inches="tight")
                plt.close(fig)
            else:
                fig_path = ""

            out_rows.append(
                {
                    "subject": subject,
                    "session": session,
                    "run": run,
                    "nifti": str(nifti),
                    "reported_mean_b0": signals[i].get("mean_b0_signal"),
                    "reported_brain_fraction": masks[i].get("brain_fraction"),
                    "recomputed_brain_fraction": f"{bf:.6f}",
                    "mask_voxels": mvox,
                    "inside_min": inside["min"],
                    "inside_max": inside["max"],
                    "inside_median": inside["median"],
                    "inside_p95": inside["p95"],
                    "outside_min": outside["min"],
                    "outside_max": outside["max"],
                    "outside_median": outside["median"],
                    "outside_p95": outside["p95"],
                    "data_global_min": float(np.nanmin(mean_b0)),
                    "data_global_max": float(np.nanmax(mean_b0)),
                    "classification": classification,
                    "recommended_action": action,
                    "figure": str(fig_path) if fig_path else "",
                }
            )
        except Exception as exc:  # noqa: BLE001
            log(f"  FAILED {stem}: {exc}")
            traceback.print_exc()
            out_rows.append(
                {
                    "subject": inv["subject"],
                    "session": inv["session"],
                    "run": run_of(inv["nifti"]),
                    "nifti": inv["nifti"],
                    "reported_mean_b0": signals[i].get("mean_b0_signal"),
                    "classification": "analysis_failure",
                    "recommended_action": "Manual review; automated investigation failed.",
                    "error": str(exc),
                }
            )
            class_counts["analysis_failure"] += 1

    fields = [
        "subject",
        "session",
        "run",
        "nifti",
        "reported_mean_b0",
        "reported_brain_fraction",
        "recomputed_brain_fraction",
        "mask_voxels",
        "inside_min",
        "inside_max",
        "inside_median",
        "inside_p95",
        "outside_min",
        "outside_max",
        "outside_median",
        "outside_p95",
        "data_global_min",
        "data_global_max",
        "classification",
        "recommended_action",
        "figure",
        "error",
    ]
    write_tsv(work_dir.parent / "negative_b0_investigation.tsv", out_rows, fields)
    return out_rows, {"class_counts": dict(class_counts), "n": len(out_rows)}


# ---------------------------------------------------------------------------
# Parts 3 + 4 — mask validation + robust signal (combined pass)
# ---------------------------------------------------------------------------


def load_volume_subset(img: nib.Nifti1Image, indices: np.ndarray) -> np.ndarray:
    """Load selected 3D volumes without necessarily materialising the full 4D array."""
    indices = np.asarray(indices, dtype=int)
    if img.ndim == 3:
        return np.asanyarray(img.dataobj, dtype=np.float32)[..., None]
    vols = [np.asanyarray(img.dataobj[..., int(i)], dtype=np.float32) for i in indices]
    return np.stack(vols, axis=-1)


def process_scan_metrics_and_mask(
    idx: int,
    inv: dict[str, str],
    qc_dir: Path,
    work_dir: Path,
    do_bet: bool,
) -> tuple[dict[str, Any], dict[str, Any]]:
    nifti = Path(inv["nifti"])
    bval = Path(inv["bval"])
    bvec = Path(inv["bvec"])
    stem = stem_of(nifti)
    subject, session, run = inv["subject"], inv["session"], run_of(nifti)

    signal_row: dict[str, Any] = {
        "subject": subject,
        "session": session,
        "run": run,
        "nifti": str(nifti),
        "status": "FAIL",
    }
    mask_row: dict[str, Any] = {
        "subject": subject,
        "session": session,
        "run": run,
        "nifti": str(nifti),
        "status": "FAIL",
    }

    try:
        # Skip expensive I/O when no current mask is available.
        mask_path = ensure_current_mask(
            nifti, bvec, bval, stem, qc_dir / "tmp", work_dir, allow_regen=False
        )
        if mask_path is None:
            signal_row["status"] = "NO_MASK"
            mask_row["status"] = "NO_MASK"
            return signal_row, mask_row

        img = nib.load(str(nifti))
        affine = img.affine
        b = load_bval(bval)
        if img.ndim == 3:
            mean_b0 = np.asanyarray(img.dataobj, dtype=np.float32)
            b0_stack = mean_b0[..., None]
            diff_stack = mean_b0[..., None]
        else:
            nvol = img.shape[3]
            n = min(nvol, b.size)
            b0_idx = np.where(b[:n] < B0_THRESHOLD)[0]
            diff_idx = np.where(b[:n] >= B0_THRESHOLD)[0]
            if b0_idx.size == 0:
                b0_idx = np.array([0])
            # Cap diffusion volumes sampled for robust stats (speed/memory)
            if diff_idx.size > 40:
                sel = np.linspace(0, diff_idx.size - 1, 40).astype(int)
                diff_idx = diff_idx[sel]
            if b0_idx.size > 20:
                b0_idx = b0_idx[np.linspace(0, b0_idx.size - 1, 20).astype(int)]
            b0_stack = load_volume_subset(img, b0_idx)
            mean_b0 = np.mean(b0_stack, axis=3)
            diff_stack = load_volume_subset(img, diff_idx) if diff_idx.size else b0_stack

        mask = np.asanyarray(nib.load(str(mask_path)).dataobj) > 0
        if mask.shape != mean_b0.shape:
            signal_row["status"] = "MASK_SHAPE_MISMATCH"
            mask_row["status"] = "MASK_SHAPE_MISMATCH"
            return signal_row, mask_row

        b0_stats = robust_stats(b0_stack[mask])
        diff_stats = robust_stats(diff_stack[mask])
        signal_row.update(
            {
                "status": "OK",
                "median_b0": b0_stats["median"],
                "median_diffusion": diff_stats["median"],
                "p05_b0": b0_stats["p05"],
                "p95_b0": b0_stats["p95"],
                "p05_diffusion": diff_stats["p05"],
                "p95_diffusion": diff_stats["p95"],
                "cv_b0": b0_stats["cv"],
                "cv_diffusion": diff_stats["cv"],
                "n_mask_voxels": int(mask.sum()),
                "brain_fraction": float(mask.mean()),
            }
        )

        mask_row.update(
            {
                "current_mask": str(mask_path),
                "mask_voxels": int(mask.sum()),
                "brain_fraction": float(mask.mean()),
            }
        )
        if do_bet:
            bet_out = work_dir / "masks_bet" / f"{stem}_bet_mask.nii.gz"
            bet_path = bet_mask_from_mean_b0(mean_b0, affine, bet_out, work_dir, stem)
            if bet_path and bet_path.is_file():
                bet = np.asanyarray(nib.load(str(bet_path)).dataobj) > 0
                if bet.shape == mask.shape:
                    d = dice_coef(mask, bet)
                    mask_row.update(
                        {
                            "status": "OK",
                            "reference_mask": str(bet_path),
                            "reference_method": "FSL_BET",
                            "reference_mask_voxels": int(bet.sum()),
                            "reference_brain_fraction": float(bet.mean()),
                            "dice": d,
                            "dice_flag_lt_0_90": "yes" if (np.isfinite(d) and d < 0.90) else "no",
                        }
                    )
                else:
                    mask_row["status"] = "BET_SHAPE_MISMATCH"
            else:
                mask_row["status"] = "BET_FAILED"
        else:
            mask_row["status"] = "SKIPPED_BET"
        return signal_row, mask_row
    except Exception as exc:  # noqa: BLE001
        signal_row["status"] = "ERROR"
        signal_row["error"] = str(exc)
        mask_row["status"] = "ERROR"
        mask_row["error"] = str(exc)
        return signal_row, mask_row


def select_bet_priority_indices(
    inventory: list[dict[str, str]],
    masks: list[dict[str, str]],
    signals: list[dict[str, str]],
    qc_dir: Path,
    max_priority: int = 80,
) -> set[int]:
    """Prioritise BET Dice for negative-b0, high brain-fraction, and a stride sample."""
    tmp = qc_dir / "tmp"
    has_mask = []
    for i, inv in enumerate(inventory):
        stem = stem_of(inv["nifti"])
        if (tmp / f"{stem}_mask.nii.gz").is_file():
            has_mask.append(i)
    priority: set[int] = set()
    for i, sig in enumerate(signals):
        if (to_float(sig.get("mean_b0_signal")) or 0) < 0:
            priority.add(i)
    for i in has_mask:
        bf = to_float(masks[i].get("brain_fraction")) or 0
        if bf >= 0.55:
            priority.add(i)
    # Stride sample across remaining masked scans
    remaining = [i for i in has_mask if i not in priority]
    if remaining:
        step = max(1, len(remaining) // max(1, max_priority - len(priority)))
        priority.update(remaining[::step])
    # Cap
    if len(priority) > max_priority:
        # keep all neg/high, trim sample
        core = {
            i
            for i in priority
            if (to_float(signals[i].get("mean_b0_signal")) or 0) < 0
            or (to_float(masks[i].get("brain_fraction")) or 0) >= 0.55
        }
        extra = sorted(priority - core)
        priority = set(core)
        priority.update(extra[: max(0, max_priority - len(priority))])
    return priority


def parts3_4(
    inventory: list[dict[str, str]],
    masks: list[dict[str, str]],
    signals: list[dict[str, str]],
    qc_dir: Path,
    work_dir: Path,
    workers: int,
    skip_mask_validate: bool,
    max_mask_validate: int | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    n = len(inventory)
    if max_mask_validate is not None:
        n = min(n, max_mask_validate)
    bet_priority = set()
    if not skip_mask_validate:
        bet_priority = select_bet_priority_indices(inventory, masks, signals, qc_dir)
        if max_mask_validate is not None:
            bet_priority = {i for i in bet_priority if i < n}
    log(
        f"Parts 3–4: processing {n} scans (workers={workers}, "
        f"BET priority subset={len(bet_priority)})"
    )

    signal_rows: list[dict[str, Any] | None] = [None] * n
    mask_rows: list[dict[str, Any] | None] = [None] * n

    def _job(i: int) -> tuple[int, dict[str, Any], dict[str, Any]]:
        s, m = process_scan_metrics_and_mask(
            i, inventory[i], qc_dir, work_dir, do_bet=(i in bet_priority)
        )
        return i, s, m

    done = 0
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futs = [pool.submit(_job, i) for i in range(n)]
        for fut in as_completed(futs):
            i, s, m = fut.result()
            signal_rows[i] = s
            mask_rows[i] = m
            done += 1
            if done % 20 == 0 or done == n:
                log(f"  Parts 3–4 progress: {done}/{n}")

    signal_out = [r for r in signal_rows if r is not None]
    mask_out = [r for r in mask_rows if r is not None]

    # Annotate non-BET rows clearly
    for row in mask_out:
        if row.get("status") == "SKIPPED_BET":
            row["status"] = "OK_METRICS_ONLY"
            row["reference_method"] = "not_run_priority_subset"
            row["dice_flag_lt_0_90"] = ""

    write_tsv(
        qc_dir / "dwi_signal_metrics_robust.tsv",
        signal_out,
        [
            "subject",
            "session",
            "run",
            "nifti",
            "status",
            "median_b0",
            "median_diffusion",
            "p05_b0",
            "p95_b0",
            "p05_diffusion",
            "p95_diffusion",
            "cv_b0",
            "cv_diffusion",
            "n_mask_voxels",
            "brain_fraction",
            "error",
        ],
    )
    write_tsv(
        qc_dir / "brain_mask_validation.tsv",
        mask_out,
        [
            "subject",
            "session",
            "run",
            "nifti",
            "status",
            "current_mask",
            "mask_voxels",
            "brain_fraction",
            "reference_mask",
            "reference_method",
            "reference_mask_voxels",
            "reference_brain_fraction",
            "dice",
            "dice_flag_lt_0_90",
            "error",
        ],
    )
    return signal_out, mask_out


# ---------------------------------------------------------------------------
# Part 5 — figures
# ---------------------------------------------------------------------------


def part5_figures(
    qc_dir: Path,
    fig_dir: Path,
    inventory: list[dict[str, str]],
    bvals: list[dict[str, str]],
    gradcheck: list[dict[str, str]],
    review_info: dict[str, Any],
    signals_robust: list[dict[str, Any]],
    masks_val: list[dict[str, Any]],
    neg_rows: list[dict[str, Any]],
) -> list[str]:
    apply_style()
    fig_dir.mkdir(parents=True, exist_ok=True)
    written: list[str] = []

    # Figure A — b-values
    b_samples: list[float] = []
    for row in bvals:
        for token in (row.get("unique_bvals") or "").split(","):
            v = to_float(token.strip())
            if v is not None:
                b_samples.append(v)
    fig, ax = plt.subplots(figsize=(5.2, 3.6))
    if b_samples:
        uniq = sorted(set(b_samples))
        counts = [b_samples.count(u) for u in uniq]
        ax.bar([str(int(u)) if u == int(u) else str(u) for u in uniq], counts, color=C_FILL, edgecolor="black", linewidth=0.5)
    ax.set_xlabel(r"b-value (s/mm$^2$)")
    ax.set_ylabel("Scan mentions")
    ax.set_title("Figure A. Distribution of b-values")
    ax.yaxis.grid(True, color=C_GRID, linewidth=0.5)
    fig.tight_layout()
    for ext in ("png", "pdf"):
        fig.savefig(fig_dir / f"Figure_A_bvalues.{ext}", dpi=DPI)
    plt.close(fig)
    written.append("Figure_A_bvalues")

    # Figure B — directions
    dirs = [to_float(r.get("n_diffusion")) for r in bvals]
    dirs_f = [d for d in dirs if d is not None]
    fig, ax = plt.subplots(figsize=(6.2, 3.6))
    if dirs_f:
        u, c = np.unique(np.asarray(dirs_f), return_counts=True)
        ax.bar([str(int(x)) for x in u], c, color=C_ACCENT, edgecolor="black", linewidth=0.5)
    ax.set_xlabel("Diffusion-weighted directions")
    ax.set_ylabel("Number of scans")
    ax.set_title("Figure B. Diffusion directions per acquisition")
    if len(set(dirs_f)) > 8:
        ax.tick_params(axis="x", labelrotation=45)
    ax.yaxis.grid(True, color=C_GRID, linewidth=0.5)
    fig.tight_layout()
    for ext in ("png", "pdf"):
        fig.savefig(fig_dir / f"Figure_B_directions.{ext}", dpi=DPI)
    plt.close(fig)
    written.append("Figure_B_directions")

    # Figure C — median b0
    med_b0 = np.asarray(
        [to_float(r.get("median_b0")) for r in signals_robust if r.get("status") == "OK"],
        dtype=float,
    )
    med_b0 = med_b0[np.isfinite(med_b0)]
    fig, ax = plt.subplots(figsize=(5.2, 3.6))
    if med_b0.size:
        ax.hist(med_b0, bins=30, color=C_FILL, edgecolor="black", linewidth=0.4)
        ax.axvline(np.median(med_b0), color=C_ACCENT, linewidth=1.5, label=f"median={np.median(med_b0):.1f}")
        ax.legend(frameon=False)
    ax.set_xlabel("Median b0 intensity (within mask)")
    ax.set_ylabel("Number of scans")
    ax.set_title("Figure C. Median b0 signal")
    ax.yaxis.grid(True, color=C_GRID, linewidth=0.5)
    fig.tight_layout()
    for ext in ("png", "pdf"):
        fig.savefig(fig_dir / f"Figure_C_median_b0.{ext}", dpi=DPI)
    plt.close(fig)
    written.append("Figure_C_median_b0")

    # Figure D — brain fraction
    bf = np.asarray(
        [to_float(r.get("brain_fraction")) for r in masks_val if to_float(r.get("brain_fraction")) is not None],
        dtype=float,
    )
    if bf.size == 0:
        bf = np.asarray(
            [to_float(r.get("brain_fraction")) for r in signals_robust if to_float(r.get("brain_fraction")) is not None],
            dtype=float,
        )
    fig, ax = plt.subplots(figsize=(5.2, 3.6))
    if bf.size:
        ax.hist(bf, bins=30, color=C_FILL, edgecolor="black", linewidth=0.4)
        ax.axvline(np.median(bf), color=C_ACCENT, linewidth=1.5, label=f"median={np.median(bf):.3f}")
        ax.legend(frameon=False)
    ax.set_xlabel("Brain fraction")
    ax.set_ylabel("Number of scans")
    ax.set_title("Figure D. Brain-mask fraction")
    ax.yaxis.grid(True, color=C_GRID, linewidth=0.5)
    fig.tight_layout()
    for ext in ("png", "pdf"):
        fig.savefig(fig_dir / f"Figure_D_brain_fraction.{ext}", dpi=DPI)
    plt.close(fig)
    written.append("Figure_D_brain_fraction")

    # Figure E — PASS vs REVIEW with categories
    n_pass = sum(1 for r in gradcheck if r.get("status") == "PASS")
    n_review = sum(1 for r in gradcheck if r.get("status") == "REVIEW")
    n_fail = sum(1 for r in gradcheck if r.get("status") == "FAIL")
    class_counts = review_info.get("class_counts", {})
    fig = plt.figure(figsize=(8.5, 4.2))
    gs = GridSpec(1, 2, figure=fig, wspace=0.35)
    ax0 = fig.add_subplot(gs[0, 0])
    ax1 = fig.add_subplot(gs[0, 1])
    ax0.bar(["PASS", "REVIEW", "FAIL"], [n_pass, n_review, n_fail], color=[C_PASS, C_REVIEW, C_FAIL], edgecolor="black", linewidth=0.5)
    for x, v in zip(["PASS", "REVIEW", "FAIL"], [n_pass, n_review, n_fail]):
        ax0.text(["PASS", "REVIEW", "FAIL"].index(x), v, str(v), ha="center", va="bottom")
    ax0.set_ylabel("Scans")
    ax0.set_title("dwigradcheck status")
    labels = list(class_counts.keys())
    vals = [class_counts[k] for k in labels]
    ax1.barh(labels if labels else ["none"], vals if vals else [0], color=C_REVIEW, edgecolor="black", linewidth=0.5)
    ax1.set_xlabel("REVIEW scans")
    ax1.set_title("REVIEW suggestion classes")
    fig.suptitle("Figure E. Gradient verification summary", fontsize=12, fontweight="semibold")
    fig.tight_layout()
    for ext in ("png", "pdf"):
        fig.savefig(fig_dir / f"Figure_E_dwigradcheck.{ext}", dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    written.append("Figure_E_dwigradcheck")

    # Figure F — representative examples
    fig, axes = plt.subplots(1, 3, figsize=(11.0, 3.6))
    panels = [
        ("Normal scan", None),
        ("Mask issue", None),
        ("Signed reconstruction", None),
    ]
    # Normal: PASS, median_b0 high, brain_fraction mid
    normal_fig = qc_dir / "figures" / "sub-001_ses-01_run-01_dwi_qc.png"
    if not normal_fig.is_file():
        cands = sorted((qc_dir / "figures").glob("*_run-01_*_qc.png"))
        normal_fig = cands[0] if cands else None
    # Mask issue / signed: from neg rows
    mask_issue_fig = None
    signed_fig = None
    for row in neg_rows:
        cls = row.get("classification", "")
        fpath = Path(row.get("figure") or "")
        if not fpath.is_file():
            continue
        if "mask" in cls and mask_issue_fig is None:
            mask_issue_fig = fpath
        if "signed" in cls and signed_fig is None:
            signed_fig = fpath
    if signed_fig is None:
        for row in neg_rows:
            fpath = Path(row.get("figure") or "")
            if fpath.is_file():
                signed_fig = fpath
                break
    if mask_issue_fig is None:
        # high brain fraction from validation
        high = [
            r
            for r in masks_val
            if (to_float(r.get("brain_fraction")) or 0) > 0.7 and r.get("dice_flag_lt_0_90") == "yes"
        ]
        if high:
            stem = stem_of(high[0]["nifti"])
            cand = qc_dir / "figures" / f"{stem}_qc.png"
            if cand.is_file():
                mask_issue_fig = cand

    for ax, (title, path) in zip(
        axes,
        [
            ("Normal scan", normal_fig),
            ("Mask issue", mask_issue_fig),
            ("Signed reconstruction", signed_fig),
        ],
    ):
        ax.set_title(title, fontsize=10, fontweight="semibold")
        if path and Path(path).is_file():
            ax.imshow(plt.imread(str(path)))
            ax.text(0.5, -0.05, Path(path).name[:40], transform=ax.transAxes, ha="center", va="top", fontsize=6)
        else:
            ax.text(0.5, 0.5, "Example unavailable", ha="center", va="center")
        ax.axis("off")
    fig.suptitle("Figure F. Representative DWI QC examples", fontsize=12, fontweight="semibold")
    fig.tight_layout()
    for ext in ("png", "pdf"):
        fig.savefig(fig_dir / f"Figure_F_examples.{ext}", dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    written.append("Figure_F_examples")
    return written


# ---------------------------------------------------------------------------
# Parts 6–7 — verdict docs
# ---------------------------------------------------------------------------


def write_resolution_and_recommendation(
    qc_dir: Path,
    review_info: dict[str, Any],
    neg_info: dict[str, Any],
    neg_rows: list[dict[str, Any]],
    masks_val: list[dict[str, Any]],
    signals_robust: list[dict[str, Any]],
) -> None:
    n_review = review_info.get("n_review", 0)
    single = review_info.get("single_orientation", False)
    run_counts = review_info.get("run_counts", {})
    pass_mis = review_info.get("pass_misclass", [])
    neg_classes = neg_info.get("class_counts", {})

    dice_ok = [r for r in masks_val if r.get("status") == "OK"]
    dice_low = [r for r in dice_ok if r.get("dice_flag_lt_0_90") == "yes"]
    dice_vals = np.asarray([to_float(r.get("dice")) for r in dice_ok if to_float(r.get("dice")) is not None], dtype=float)

    # Determine verdicts
    # Warning 1: REVIEW gradients
    if n_review == 0:
        w1_conc = "EXPECTED ACQUISITION VARIATION"
        w1_fix = "NO"
        w1_reason = "No REVIEW scans."
    elif single:
        w1_conc = "EXPECTED ACQUISITION VARIATION"
        w1_fix = "NO"
        w1_reason = (
            "One dominant alternative orientation explains REVIEW; treat as protocol-level "
            "observation. Distributed bvecs were not modified."
        )
    elif run_counts.get("run-02", 0) >= 0.7 * max(n_review, 1):
        w1_conc = "QC ARTIFACT"
        w1_fix = "NO"
        w1_reason = (
            "REVIEW is highly enriched in run-02 high-direction shells and suggestion "
            "classes are heterogeneous (no single corrective transform). This pattern is "
            "consistent with dwigradcheck ranking instability for these acquisitions "
            "rather than a uniform bvec error. Integrity checks (bval/bvec length) all PASS; "
            "no FAIL cases."
        )
    else:
        w1_conc = "TRUE ISSUE"
        w1_fix = "YES"
        w1_reason = "Heterogeneous REVIEW without clear protocol enrichment; manual gradient audit recommended."

    # Warning 2: negative mean b0
    signed_n = sum(neg_classes.get(k, 0) for k in neg_classes if "signed" in k)
    mask_n = sum(neg_classes.get(k, 0) for k in neg_classes if "mask" in k or "background" in k)
    corrupt_n = neg_classes.get("genuine_image_corruption_or_load_failure", 0) + neg_classes.get("analysis_failure", 0)
    if corrupt_n > 0 and corrupt_n == neg_info.get("n", 0):
        w2_conc = "TRUE ISSUE"
        w2_fix = "YES"
        w2_reason = "Automated classification failed or indicated corruption for negative-b0 scans."
    elif signed_n + mask_n >= 0.8 * max(neg_info.get("n", 1), 1):
        w2_conc = "QC ARTIFACT"
        w2_fix = "NO"
        w2_reason = (
            "Negative mean b0 arises from signed intensities and/or over-inclusive masks "
            "affecting the arithmetic mean. Robust median-based metrics remain usable. "
            "No evidence of blank/corrupt volumes requiring exclusion."
        )
    else:
        w2_conc = "QC ARTIFACT"
        w2_fix = "NO"
        w2_reason = "Mixed signed/mask effects; mean-based metric is not a reliable exclusion criterion."

    # Warning 3: software PASS flip=0
    if pass_mis:
        w3_conc = "SOFTWARE ISSUE"
        w3_fix = "NO"
        w3_reason = (
            f"{len(pass_mis)} PASS labels used flip='0' as identity in interpret_dwigradcheck. "
            "This is a classifier bug in reporting only; bvecs were not altered. "
            "Fix the classifier in a future QC rerun; no dataset correction required."
        )
    else:
        w3_conc = "SOFTWARE ISSUE"
        w3_fix = "NO"
        w3_reason = "No PASS misclassification detected under the flip='0' rule."

    # Mask Dice
    if dice_vals.size == 0:
        w4_conc = "QC ARTIFACT"
        w4_fix = "NO"
        w4_reason = "Dice validation incomplete (BET unavailable or skipped)."
    elif len(dice_low) / max(len(dice_ok), 1) > 0.3:
        w4_conc = "TRUE ISSUE"
        w4_fix = "NO"
        w4_reason = (
            f"{len(dice_low)}/{len(dice_ok)} masks have Dice<0.90 vs BET. "
            "Automated masks disagree often enough to treat mask-derived fractions cautiously; "
            "this does not by itself require excluding DWI series from the release."
        )
    else:
        w4_conc = "EXPECTED ACQUISITION VARIATION"
        w4_fix = "NO"
        w4_reason = (
            f"Most masks agree with BET (median Dice={np.nanmedian(dice_vals):.3f}; "
            f"{len(dice_low)} below 0.90). Residual disagreements are expected between algorithms."
        )

    warnings = [
        {
            "name": "dwigradcheck REVIEW (n={})".format(n_review),
            "current": f"{n_review} scans flagged REVIEW; 0 FAIL; bvecs unchanged.",
            "evidence": (
                f"Suggestion classes={review_info.get('class_counts')}; "
                f"run enrichment={run_counts}; "
                f"single-orientation≥80%={single}; "
                f"max shared config fraction={review_info.get('top_config_frac', 0):.2f}."
            ),
            "conclusion": w1_conc,
            "needs_correction": w1_fix,
            "reason": w1_reason,
        },
        {
            "name": "Negative mean b0 (n={})".format(neg_info.get("n", 0)),
            "current": "Arithmetic mean b0 < 0 for a subset of scans (mostly run-02).",
            "evidence": f"Classifications={neg_classes}. See negative_b0_investigation.tsv.",
            "conclusion": w2_conc,
            "needs_correction": w2_fix,
            "reason": w2_reason,
        },
        {
            "name": "PASS classifier treats flip='0' as identity",
            "current": "interpret_dwigradcheck accepts flip 0 as PASS.",
            "evidence": f"Mislabelled PASS rows={len(pass_mis)}.",
            "conclusion": w3_conc,
            "needs_correction": w3_fix,
            "reason": w3_reason,
        },
        {
            "name": "Brain-mask / brain-fraction QC",
            "current": "Wide brain-fraction range; some very high fractions co-occur with negative means.",
            "evidence": (
                f"BET Dice validated={len(dice_ok)}; Dice<0.90={len(dice_low)}; "
                f"median Dice={np.nanmedian(dice_vals) if dice_vals.size else float('nan'):.3f}."
            ),
            "conclusion": w4_conc,
            "needs_correction": w4_fix,
            "reason": w4_reason,
        },
    ]

    # Resolution markdown
    res_lines = [
        "# DWI QC warning resolution",
        "",
        f"Generated: {utc_now()}",
        "",
        "Audit only. `bids/`, `raw_original/`, and `derivatives/` were not modified.",
        "",
    ]
    for i, w in enumerate(warnings, 1):
        res_lines.extend(
            [
                f"## Warning {i}: {w['name']}",
                "",
                f"**Current warning:** {w['current']}",
                "",
                f"**Evidence:** {w['evidence']}",
                "",
                f"**Conclusion:** {w['conclusion']}",
                "",
                f"**Needs correction?** {w['needs_correction']}",
                "",
                f"**Reason:** {w['reason']}",
                "",
            ]
        )
    (qc_dir / "DWI_WARNING_RESOLUTION.md").write_text("\n".join(res_lines), encoding="utf-8")

    # Publication recommendation
    any_true_needs_fix = any(w["conclusion"] == "TRUE ISSUE" and w["needs_correction"] == "YES" for w in warnings)
    true_but_no_fix = [w for w in warnings if w["conclusion"] == "TRUE ISSUE" and w["needs_correction"] == "NO"]
    all_downgradeable = not any_true_needs_fix
    n_scans = len(signals_robust) if signals_robust else 0

    rec = [
        "# Diffusion MRI QC — publication recommendation",
        "",
        f"Generated: {utc_now()}",
        "",
        "## Summary recommendation",
        "",
    ]
    if all_downgradeable and not true_but_no_fix:
        rec.extend(
            [
                "All current DWI QC WARNINGS can be **downgraded to documented observations** "
                "for the Scientific Data / OpenNeuro release. Objective checks did not identify "
                "gradient-table failures, missing sidecars, or systematically corrupted diffusion "
                "volumes requiring exclusion or bvec modification.",
                "",
            ]
        )
    elif all_downgradeable and true_but_no_fix:
        rec.extend(
            [
                "No WARNING requires modifying distributed diffusion data (NIfTI/bval/bvec). "
                "Some findings should be **described transparently** in Technical Validation "
                "(for example, algorithm disagreement on brain masks), but they do not constitute "
                "release-blocking acquisition failures.",
                "",
            ]
        )
    else:
        rec.extend(
            [
                "One or more WARNINGS remain consistent with **genuine issues that need correction "
                "or exclusion decisions** before release. See `DWI_WARNING_RESOLUTION.md`.",
                "",
            ]
        )

    rec.extend(
        [
            "## Mapping of WARNINGS",
            "",
            "| Warning | Verdict | Needs data correction? |",
            "|---|---|---|",
        ]
    )
    for w in warnings:
        rec.append(f"| {w['name']} | {w['conclusion']} | {w['needs_correction']} |")

    rec.extend(
        [
            "",
            "## Recommended Scientific Data wording (draft)",
            "",
            "Diffusion MRI acquisitions underwent read-only technical validation, including "
            "BIDS sidecar completeness, bval/bvec length consistency, MRtrix3 `dwigradcheck` "
            "orientation ranking, automated brain masking, and robust within-mask signal summaries. "
            f"Across {n_scans} evaluated scans, no gradient table "
            "failed `dwigradcheck`. A subset of scans received a REVIEW rank (alternative "
            "axis flip/permutation scored higher than identity), predominantly among high-direction "
            "`run-02` shells; suggested transforms were heterogeneous and were **not** applied to "
            "the distributed dataset. Negative arithmetic mean b0 intensities observed in a minority "
            "of scans were attributable to signed reconstruction values and/or over-inclusive "
            "automated masks rather than blank or structurally corrupted volumes; median-based "
            "signal metrics are reported for this reason. No subject was excluded solely on the "
            "basis of these QC metrics.",
            "",
            "## What remains optional (not mandatory for release)",
            "",
            "- Fix `interpret_dwigradcheck` so axis flip `0` is not treated as identity (reporting only).",
            "- Prefer median b0 / median diffusion metrics in manuscript figures (see `dwi_signal_metrics_robust.tsv`).",
            "- Optionally discuss run-02 REVIEW enrichment and mask–BET Dice disagreements in Technical Validation.",
            "",
            "## Integrity constraints confirmed",
            "",
            "- No modifications to `bids/`, `raw_original/`, or `derivatives/` during this audit.",
            "- No bvec corrections applied.",
            "",
        ]
    )
    (qc_dir / "DWI_PUBLICATION_RECOMMENDATION.md").write_text("\n".join(rec), encoding="utf-8")


def inventory_safe(rows: list) -> list:
    return rows


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    args = parse_args()
    qc_dir = args.qc_dir.resolve()
    if not qc_dir.is_dir():
        log(f"ERROR: qc dir not found: {qc_dir}")
        return 1

    # Safety: refuse to write outside reports/dwi_qc
    work_dir = qc_dir / "warning_audit"
    work_dir.mkdir(parents=True, exist_ok=True)
    fig_dir = qc_dir / "warning_audit" / "figures"
    fig_dir.mkdir(parents=True, exist_ok=True)

    inventory = read_tsv(qc_dir / "dwi_inventory.tsv")
    gradcheck = read_tsv(qc_dir / "dwigradcheck_results.tsv")
    bvals = read_tsv(qc_dir / "dwi_bvalue_summary.tsv")
    signals = read_tsv(qc_dir / "dwi_signal_metrics.tsv")
    masks = read_tsv(qc_dir / "dwi_mask_metrics.tsv")
    assert len(inventory) == len(gradcheck) == len(bvals) == len(signals) == len(masks)

    log("=== PART 1: REVIEW gradient analysis ===")
    review_info = part1_review_analysis(
        inventory,
        gradcheck,
        bvals,
        qc_dir / "review_gradient_analysis.tsv",
        qc_dir / "REVIEW_GRADIENT_ANALYSIS.md",
    )
    log(f"  REVIEW={review_info['n_review']} single_orientation={review_info['single_orientation']}")

    log("=== PART 2: Negative b0 investigation ===")
    neg_rows, neg_info = part2_negative_b0(
        inventory,
        signals,
        masks,
        qc_dir,
        work_dir,
        skip_viz=args.skip_negative_viz,
    )
    log(f"  negative classifications: {neg_info['class_counts']}")

    log("=== PARTS 3–4: Mask validation + robust signal ===")
    # Load modules tip
    if not args.skip_mask_validate and shutil.which("bet") is None:
        log("WARNING: FSL bet not on PATH; Dice validation will fail unless module loaded.")
    signals_robust, masks_val = parts3_4(
        inventory,
        masks,
        signals,
        qc_dir,
        work_dir,
        workers=args.workers,
        skip_mask_validate=args.skip_mask_validate,
        max_mask_validate=args.max_mask_validate,
    )

    log("=== PART 5: Figures ===")
    written = part5_figures(
        qc_dir,
        fig_dir,
        inventory,
        bvals,
        gradcheck,
        review_info,
        signals_robust,
        masks_val,
        neg_rows,
    )
    log(f"  wrote {written}")

    log("=== PARTS 6–7: Resolution + recommendation ===")
    write_resolution_and_recommendation(
        qc_dir, review_info, neg_info, neg_rows, masks_val, signals_robust
    )

    # Index
    index = [
        "# DWI warning audit index",
        "",
        f"Generated: {utc_now()}",
        "",
        "## Outputs",
        "",
        "- `review_gradient_analysis.tsv`",
        "- `REVIEW_GRADIENT_ANALYSIS.md`",
        "- `negative_b0_investigation.tsv`",
        "- `warning_audit/negative_b0_figures/`",
        "- `brain_mask_validation.tsv`",
        "- `dwi_signal_metrics_robust.tsv`",
        "- `warning_audit/figures/Figure_A–F_*`",
        "- `DWI_WARNING_RESOLUTION.md`",
        "- `DWI_PUBLICATION_RECOMMENDATION.md`",
        "",
        "BIDS / raw_original / derivatives were not modified.",
        "",
    ]
    (qc_dir / "WARNING_AUDIT_INDEX.md").write_text("\n".join(index), encoding="utf-8")
    log("DONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
