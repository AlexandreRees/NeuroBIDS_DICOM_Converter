#!/usr/bin/env python3
"""Generate a publication-quality multi-panel DWI QC figure (read-only).

Reads existing reports under reports/dwi_qc/ and writes only under
reports/dwi_qc/publication/. Never modifies BIDS or derivatives.

Example:
  python code/generate_dwi_qc_figure.py
  python code/generate_dwi_qc_figure.py \\
      --qc-dir /home/alexrees/scratch/reports/dwi_qc
"""

from __future__ import annotations

import argparse
import csv
import math
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.gridspec import GridSpec

DEFAULT_QC = Path("/home/alexrees/scratch/reports/dwi_qc")
DPI = 300
FONT_FAMILY = "DejaVu Sans"
# Scientific Data / Nature-like greyscale + one restrained accent
C_FILL = "#4D4D4D"
C_EDGE = "#1A1A1A"
C_ACCENT = "#2C5F8A"
C_PASS = "#2E7D4F"
C_REVIEW = "#B07D2A"
C_FAIL = "#8B3A3A"
C_GRID = "#D0D0D0"


@dataclass
class AuditState:
    files_used: list[str] = field(default_factory=list)
    missing_inputs: list[str] = field(default_factory=list)
    panels_generated: list[str] = field(default_factory=list)
    panels_skipped: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    n_scans: int = 0
    extras: dict[str, Any] = field(default_factory=dict)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--qc-dir", type=Path, default=DEFAULT_QC)
    p.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="Default: <qc-dir>/publication",
    )
    return p.parse_args()


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(out):
        return None
    return out


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


def load_optional(qc_dir: Path, name: str, state: AuditState) -> list[dict[str, str]] | None:
    path = qc_dir / name
    if not path.is_file():
        state.missing_inputs.append(name)
        return None
    try:
        rows = read_tsv(path)
    except Exception as exc:  # noqa: BLE001
        state.warnings.append(f"Failed to read {name}: {exc}")
        state.missing_inputs.append(name)
        return None
    if not rows:
        state.warnings.append(f"{name} is empty")
        state.missing_inputs.append(name)
        return None
    state.files_used.append(name)
    return rows


def median_iqr(values: np.ndarray) -> tuple[float, float, float]:
    q1, med, q3 = np.percentile(values, [25, 50, 75])
    return float(med), float(q1), float(q3)


def single_violin(ax: plt.Axes, arr: np.ndarray, ylabel: str) -> tuple[float, float, float]:
    """Draw one violin with median/IQR on its own axis (independent scale)."""
    arr = np.asarray(arr, dtype=float)
    arr = arr[np.isfinite(arr)]
    if arr.size == 0:
        ax.text(0.5, 0.5, "No data", ha="center", va="center", transform=ax.transAxes)
        ax.set_axis_off()
        return float("nan"), float("nan"), float("nan")
    try:
        parts = ax.violinplot(
            [arr],
            positions=[0],
            widths=0.85,
            showmeans=False,
            showmedians=False,
            showextrema=False,
        )
        for body in parts["bodies"]:
            body.set_facecolor(C_FILL)
            body.set_edgecolor(C_EDGE)
            body.set_alpha(0.55)
            body.set_linewidth(0.8)
    except Exception:  # noqa: BLE001
        bp = ax.boxplot(
            [arr],
            positions=[0],
            widths=0.55,
            patch_artist=True,
            showfliers=False,
        )
        for box in bp["boxes"]:
            box.set(facecolor=C_FILL, alpha=0.45, edgecolor=C_EDGE)
        for key in ("whiskers", "caps", "medians"):
            for line in bp[key]:
                line.set_color(C_EDGE)
    med, q1, q3 = median_iqr(arr)
    ax.hlines(med, -0.2, 0.2, colors=C_ACCENT, linewidth=1.8, zorder=5)
    ax.vlines(0, q1, q3, colors=C_ACCENT, linewidth=1.3, zorder=4)
    ax.set_xticks([])
    ax.set_ylabel(ylabel)
    ax.yaxis.grid(True, color=C_GRID, linewidth=0.5, linestyle="-", alpha=0.8)
    ax.set_axisbelow(True)
    return med, q1, q3


def panel_a(
    ax_bval: plt.Axes,
    ax_dir: plt.Axes,
    inventory: list[dict[str, str]] | None,
    bvals: list[dict[str, str]] | None,
    state: AuditState,
) -> bool:
    if not inventory and not bvals:
        return False
    n_scans = len(inventory) if inventory else (len(bvals) or 0)
    state.n_scans = max(state.n_scans, n_scans)
    subjects = sorted({r["subject"] for r in (inventory or bvals or []) if r.get("subject")})
    sessions = {
        (r.get("subject"), r.get("session"))
        for r in (inventory or bvals or [])
        if r.get("subject")
    }
    n_subj = len(subjects)
    n_sess = len(sessions)

    # b-value histogram: expand unique_bvals lists if present
    b_samples: list[float] = []
    n_b0_list: list[float] = []
    n_dir_list: list[float] = []
    if bvals:
        for row in bvals:
            scheme = (row.get("unique_bvals") or "").strip()
            for token in scheme.split(","):
                token = token.strip()
                if not token:
                    continue
                val = to_float(token)
                if val is not None:
                    b_samples.append(val)
            nb0 = to_float(row.get("n_b0"))
            nd = to_float(row.get("n_diffusion"))
            if nb0 is not None:
                n_b0_list.append(nb0)
            if nd is not None:
                n_dir_list.append(nd)

    if b_samples:
        uniq = sorted(set(b_samples))
        # discrete histogram of scheme membership counts per distinct b
        counts = [b_samples.count(u) for u in uniq]
        ax_bval.bar(
            [str(int(u)) if u == int(u) else str(u) for u in uniq],
            counts,
            color=C_FILL,
            edgecolor=C_EDGE,
            linewidth=0.6,
            width=0.72,
        )
        ax_bval.set_xlabel(r"b-value (s/mm$^2$)")
        ax_bval.set_ylabel("Scan mentions")
        ax_bval.set_title("b-value shells", loc="left", fontweight="semibold")
        ax_bval.yaxis.grid(True, color=C_GRID, linewidth=0.5)
        ax_bval.set_axisbelow(True)
    else:
        ax_bval.text(0.5, 0.5, "b-value summary unavailable", ha="center", va="center", transform=ax_bval.transAxes)
        ax_bval.set_axis_off()

    if n_dir_list:
        # histogram of diffusion directions
        vals = np.asarray(n_dir_list, dtype=float)
        uniq_d, freq = np.unique(vals, return_counts=True)
        ax_dir.bar(
            [str(int(u)) for u in uniq_d],
            freq,
            color=C_ACCENT,
            edgecolor=C_EDGE,
            linewidth=0.6,
            width=0.72,
            alpha=0.9,
        )
        ax_dir.set_xlabel("Diffusion-weighted directions")
        ax_dir.set_ylabel("Number of scans")
        ax_dir.set_title("Directions per acquisition", loc="left", fontweight="semibold")
        ax_dir.yaxis.grid(True, color=C_GRID, linewidth=0.5)
        ax_dir.set_axisbelow(True)
        if len(uniq_d) > 8:
            ax_dir.tick_params(axis="x", labelrotation=45)
    else:
        ax_dir.text(0.5, 0.5, "direction counts unavailable", ha="center", va="center", transform=ax_dir.transAxes)
        ax_dir.set_axis_off()

    mean_dir = float(np.mean(n_dir_list)) if n_dir_list else float("nan")
    med_dir = float(np.median(n_dir_list)) if n_dir_list else float("nan")
    mean_b0 = float(np.mean(n_b0_list)) if n_b0_list else float("nan")
    stats = (
        f"N subjects = {n_subj}   |   N sessions = {n_sess}   |   N DWI scans = {n_scans}\n"
        f"Mean directions = {mean_dir:.1f}   |   Median directions = {med_dir:.1f}   |   "
        f"Mean b0 volumes = {mean_b0:.1f}"
    )
    state.extras["panel_a_stats"] = {
        "n_subjects": n_subj,
        "n_sessions": n_sess,
        "n_scans": n_scans,
        "mean_directions": mean_dir,
        "median_directions": med_dir,
        "mean_b0": mean_b0,
    }
    # Stash cohort stats for the figure header.
    ax_bval.figure._panel_a_stats = stats  # type: ignore[attr-defined]
    state.extras["panel_a_stats_text"] = stats
    return True


def panel_b(ax: plt.Axes, gradcheck: list[dict[str, str]] | None, state: AuditState) -> bool:
    if not gradcheck:
        return False
    status_counts = {"PASS": 0, "REVIEW": 0, "FAIL": 0, "OTHER": 0}
    for row in gradcheck:
        st = (row.get("status") or "").strip().upper()
        if st in status_counts:
            status_counts[st] += 1
        else:
            status_counts["OTHER"] += 1
    n_checked = sum(status_counts.values())
    state.extras["gradcheck"] = dict(status_counts)
    state.extras["gradcheck"]["n_checked"] = n_checked

    labels = ["PASS", "REVIEW", "FAIL"]
    values = [status_counts[k] for k in labels]
    colors = [C_PASS, C_REVIEW, C_FAIL]
    if status_counts["OTHER"]:
        labels.append("OTHER")
        values.append(status_counts["OTHER"])
        colors.append(C_FILL)

    bars = ax.bar(labels, values, color=colors, edgecolor=C_EDGE, linewidth=0.7, width=0.65)
    for bar, val in zip(bars, values):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height(),
            str(val),
            ha="center",
            va="bottom",
            fontsize=9,
            fontweight="semibold",
        )
    ax.set_ylabel("Number of scans")
    ax.set_title(
        f"Gradient verification (dwigradcheck) — {n_checked} scans checked",
        loc="left",
        fontweight="semibold",
    )
    ax.set_ylim(0, max(values) * 1.18 if max(values) else 1)
    ax.yaxis.grid(True, color=C_GRID, linewidth=0.5)
    ax.set_axisbelow(True)

    if status_counts["PASS"] == n_checked and n_checked > 0:
        msg = "All gradient tables were internally consistent."
        ax.text(
            0.5,
            0.92,
            msg,
            transform=ax.transAxes,
            ha="center",
            va="top",
            fontsize=9,
            fontstyle="italic",
            color=C_PASS,
        )
        state.extras["gradcheck_all_pass"] = True
    else:
        state.extras["gradcheck_all_pass"] = False
        note = (
            f"{status_counts['PASS']} passed; "
            f"{status_counts['REVIEW']} suggested a possible orientation correction "
            f"(not applied); {status_counts['FAIL']} failed."
        )
        ax.text(0.5, -0.18, note, transform=ax.transAxes, ha="center", va="top", fontsize=7.5, color="#333333")
    return True


def panel_c(axes: list[plt.Axes], masks: list[dict[str, str]] | None, state: AuditState) -> bool:
    if not masks:
        return False
    volumes = np.array([to_float(r.get("mask_voxels")) for r in masks], dtype=float)
    fractions = np.array([to_float(r.get("brain_fraction")) for r in masks], dtype=float)
    volumes = volumes[np.isfinite(volumes)]
    fractions = fractions[np.isfinite(fractions)]
    if volumes.size == 0 and fractions.size == 0:
        return False

    # Ensure two axes
    while len(axes) < 2:
        axes.append(axes[0])
    ax0, ax1 = axes[0], axes[1]
    notes = []
    if volumes.size:
        med, q1, q3 = single_violin(ax0, volumes / 1e5, "Mask volume (×10⁵ voxels)")
        notes.append(f"Vol median={med:.2f} (IQR {q1:.2f}–{q3:.2f})")
        ax0.set_title("Mask volume", fontsize=9)
    else:
        ax0.set_axis_off()
    if fractions.size:
        med, q1, q3 = single_violin(ax1, fractions, "Brain fraction")
        notes.append(f"BF median={med:.3f} (IQR {q1:.3f}–{q3:.3f})")
        ax1.set_title("Brain fraction", fontsize=9)
    else:
        ax1.set_axis_off()
    state.extras["mask_n"] = int(max(volumes.size, fractions.size))
    state.extras["mask_notes"] = notes
    return True


def panel_d(axes: list[plt.Axes], signals: list[dict[str, str]] | None, state: AuditState) -> bool:
    if not signals:
        return False
    series: list[tuple[str, np.ndarray]] = []
    # Preferred publication metrics (independent scales).
    for key, label in (
        ("mean_b0_signal", "Mean b0"),
        ("median_signal", "Median intensity"),
    ):
        if key not in signals[0]:
            continue
        arr = np.array([to_float(r.get(key)) for r in signals], dtype=float)
        arr = arr[np.isfinite(arr)]
        if arr.size:
            series.append((label, arr))

    if "mean_b0_signal" in signals[0] and "std_signal" in signals[0]:
        snr = []
        for row in signals:
            mb0 = to_float(row.get("mean_b0_signal"))
            std = to_float(row.get("std_signal"))
            if mb0 is None or std is None or std <= 0:
                continue
            snr.append(mb0 / std)
        if snr:
            series.append(("Estimated SNR", np.asarray(snr, dtype=float)))
            state.extras["snr_proxy"] = True
            state.warnings.append(
                "Estimated SNR defined as mean_b0_signal / std_signal (proxy; not thermal SNR)."
            )

    # Fallback if SNR unavailable
    if len(series) < 3 and "mean_signal" in signals[0]:
        arr = np.array([to_float(r.get("mean_signal")) for r in signals], dtype=float)
        arr = arr[np.isfinite(arr)]
        if arr.size:
            series.append(("Mean intensity", arr))

    if not series:
        return False

    n = min(len(series), len(axes))
    for i in range(n):
        label, arr = series[i]
        single_violin(axes[i], arr, label)
        axes[i].set_title(label, fontsize=9)
    for j in range(n, len(axes)):
        axes[j].set_axis_off()

    if "mean_b0_signal" in signals[0]:
        mb0 = np.array([to_float(r.get("mean_b0_signal")) for r in signals], dtype=float)
        n_neg = int(np.sum(np.isfinite(mb0) & (mb0 < 0)))
        if n_neg:
            state.warnings.append(
                f"{n_neg}/{len(signals)} scans have negative mean b0 intensity "
                f"(often signed / poorly masked volumes; retained in distributions)."
            )
    state.extras["signal_n"] = len(signals)
    return True


def pick_representative_pair(
    fig_dir: Path, tmp_dir: Path, inventory: list[dict[str, str]] | None
) -> tuple[Path | None, Path | None]:
    """Prefer a QC snapshot that also has a temporary mask on disk."""
    if not fig_dir.is_dir():
        return None, None
    pngs = sorted(fig_dir.glob("*_dwi_qc.png"))
    if not pngs:
        return None, None

    def mask_for(snap: Path) -> Path | None:
        stem = snap.name.replace("_qc.png", "")
        cand = tmp_dir / f"{stem}_mask.nii.gz"
        return cand if cand.is_file() else None

    preferred_names = [
        "sub-001_ses-01_run-01_dwi_qc.png",
        "sub-001_ses-01_run-05_dwi_qc.png",
        "sub-002_ses-01_run-01_dwi_qc.png",
    ]
    for name in preferred_names:
        snap = fig_dir / name
        if snap.is_file():
            m = mask_for(snap)
            if m is not None:
                return snap, m

    # Any run-01 with both
    for snap in pngs:
        if "run-01" not in snap.name:
            continue
        m = mask_for(snap)
        if m is not None:
            return snap, m

    # Any pair
    for snap in pngs:
        m = mask_for(snap)
        if m is not None:
            return snap, m

    # Snapshot only
    for name in preferred_names:
        snap = fig_dir / name
        if snap.is_file():
            return snap, None
    return pngs[0], None


def make_examples_figure(
    out_dir: Path,
    fig_dir: Path,
    inventory: list[dict[str, str]] | None,
    tmp_dir: Path,
    state: AuditState,
) -> Path | None:
    """Compose bonus figure from existing QC snapshot (+ mask if tmp available)."""
    snap, mask_path = pick_representative_pair(fig_dir, tmp_dir, inventory)
    if snap is None:
        state.warnings.append("No representative QC PNGs found; skipped Figure_DWI_examples.")
        return None

    try:
        img = plt.imread(snap)
    except Exception as exc:  # noqa: BLE001
        state.warnings.append(f"Could not read example snapshot {snap.name}: {exc}")
        return None

    n_panels = 1 + int(mask_path is not None and mask_path.is_file())
    fig, axes = plt.subplots(1, n_panels, figsize=(3.4 * n_panels, 3.2), squeeze=False)
    ax0 = axes[0, 0]
    ax0.imshow(img)
    ax0.set_title("b0 / diffusion snapshot", fontsize=10, fontweight="semibold")
    ax0.axis("off")
    ax0.text(
        0.5,
        -0.04,
        snap.name.replace("_dwi_qc.png", ""),
        transform=ax0.transAxes,
        ha="center",
        va="top",
        fontsize=8,
        color="#333333",
    )

    if mask_path is not None and mask_path.is_file():
        try:
            import nibabel as nib

            mask = np.asanyarray(nib.load(str(mask_path)).dataobj)
            if mask.ndim == 3:
                z = mask.shape[2] // 2
                sl = mask[:, :, z]
            else:
                sl = np.squeeze(mask)
            ax1 = axes[0, 1]
            ax1.imshow(np.rot90(sl), cmap="gray", origin="upper")
            ax1.set_title("Brain mask (central axial)", fontsize=10, fontweight="semibold")
            ax1.axis("off")
            state.files_used.append(f"tmp/{mask_path.name}")
        except Exception as exc:  # noqa: BLE001
            state.warnings.append(f"Mask overlay skipped: {exc}")

    state.files_used.append(f"figures/{snap.name}")
    fig.suptitle("Representative diffusion MRI QC example", fontsize=12, fontweight="semibold", y=1.02)
    fig.tight_layout()
    out = out_dir / "Figure_DWI_examples.png"
    fig.savefig(out, dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    state.extras["examples_figure"] = out.name
    return out


def write_legend(path: Path, state: AuditState) -> None:
    grad = state.extras.get("gradcheck", {})
    all_pass = state.extras.get("gradcheck_all_pass")
    if all_pass:
        panel_b_text = (
            "(B) Summary of diffusion gradient verification using MRtrix3 "
            "`dwigradcheck`. All gradient tables were internally consistent."
        )
    elif grad:
        panel_b_text = (
            "(B) Summary of diffusion gradient verification using MRtrix3 "
            f"`dwigradcheck` across {grad.get('n_checked', 'N')} scans "
            f"({grad.get('PASS', 0)} pass, {grad.get('REVIEW', 0)} review, "
            f"{grad.get('FAIL', 0)} fail). Suggested orientation corrections "
            "were recorded but not applied to the distributed dataset."
        )
    else:
        panel_b_text = (
            "(B) Gradient verification panel was omitted because "
            "`dwigradcheck_results.tsv` was unavailable."
        )

    snr_note = ""
    if state.extras.get("snr_proxy"):
        snr_note = (
            " Estimated SNR is a proxy defined as mean b0 intensity divided by "
            "within-mask signal standard deviation."
        )

    lines = [
        "Figure X.",
        "Diffusion MRI quality assessment.",
        "",
        "(A) Distribution of diffusion acquisition parameters including b-values "
        "and the number of diffusion-weighted directions across all scans, with "
        "cohort counts (subjects, sessions, DWI acquisitions) and summary "
        "direction / b0 statistics.",
        "",
        panel_b_text,
        "",
        "(C) Distribution of automated brain-mask metrics (mask volume and brain "
        "fraction) across the cohort. Horizontal marks indicate the median; "
        "vertical marks indicate the interquartile range.",
        "",
        "(D) Distribution of signal-quality metrics derived from the raw "
        f"diffusion-weighted images within the brain mask.{snr_note}",
        "",
        "No subject was excluded based solely on these quality-control metrics.",
        "",
        f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def write_summary(path: Path, state: AuditState, status: str) -> None:
    lines = [
        "# DWI publication figure — summary",
        "",
        f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}",
        "",
        f"## Status: **{status}**",
        "",
        "## Files used",
        "",
    ]
    if state.files_used:
        for name in state.files_used:
            lines.append(f"- `{name}`")
    else:
        lines.append("- (none)")
    lines.extend(["", "## Number of scans summarized", "", f"- **{state.n_scans}**", ""])
    lines.extend(["## Missing inputs", ""])
    if state.missing_inputs:
        for name in state.missing_inputs:
            lines.append(f"- `{name}`")
    else:
        lines.append("- None")
    lines.extend(["", "## Panels generated", ""])
    for p in state.panels_generated:
        lines.append(f"- {p}")
    if state.panels_skipped:
        lines.extend(["", "## Panels skipped", ""])
        for p in state.panels_skipped:
            lines.append(f"- {p}")
    lines.extend(["", "## Warnings", ""])
    if state.warnings:
        for w in state.warnings:
            lines.append(f"- {w}")
    else:
        lines.append("- None")
    if state.extras.get("examples_figure"):
        lines.extend(
            [
                "",
                "## Bonus",
                "",
                f"- `{state.extras['examples_figure']}`",
            ]
        )
    lines.extend(
        [
            "",
            "## Final publication status",
            "",
            status,
            "",
            "Read-only: BIDS and derivatives were not modified.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    args = parse_args()
    qc_dir = args.qc_dir.resolve()
    out_dir = (args.out_dir or (qc_dir / "publication")).resolve()
    # Safety: only write under publication/
    if "publication" not in out_dir.parts:
        print("ERROR: output must be under a publication/ directory", file=sys.stderr)
        return 1
    if not qc_dir.is_dir():
        print(f"ERROR: QC directory not found: {qc_dir}", file=sys.stderr)
        return 1

    out_dir.mkdir(parents=True, exist_ok=True)
    apply_style()
    state = AuditState()

    inventory = load_optional(qc_dir, "dwi_inventory.tsv", state)
    consistency = load_optional(qc_dir, "dwi_gradient_consistency.tsv", state)
    bvals = load_optional(qc_dir, "dwi_bvalue_summary.tsv", state)
    gradcheck = load_optional(qc_dir, "dwigradcheck_results.tsv", state)
    masks = load_optional(qc_dir, "dwi_mask_metrics.tsv", state)
    signals = load_optional(qc_dir, "dwi_signal_metrics.tsv", state)

    # Discover any additional QC TSVs
    known = {
        "dwi_inventory.tsv",
        "dwi_gradient_consistency.tsv",
        "dwi_bvalue_summary.tsv",
        "dwigradcheck_results.tsv",
        "dwi_mask_metrics.tsv",
        "dwi_signal_metrics.tsv",
    }
    for extra in sorted(qc_dir.glob("*.tsv")):
        if extra.name not in known:
            state.warnings.append(f"Additional QC TSV present but unused in figure: {extra.name}")

    if consistency:
        n_fail = sum(1 for r in consistency if (r.get("status") or "").upper() != "PASS")
        if n_fail:
            state.warnings.append(f"{n_fail} gradient-consistency rows are not PASS.")
        else:
            state.extras["consistency_all_pass"] = True

    # Layout: A top (2), B middle full width, C/D bottom with nested violins
    fig = plt.figure(figsize=(11.2, 10.0))
    gs = GridSpec(
        3,
        2,
        figure=fig,
        height_ratios=[1.05, 0.95, 1.2],
        hspace=0.45,
        wspace=0.30,
        left=0.07,
        right=0.98,
        top=0.88,
        bottom=0.06,
    )
    ax_a1 = fig.add_subplot(gs[0, 0])
    ax_a2 = fig.add_subplot(gs[0, 1])
    ax_b = fig.add_subplot(gs[1, :])

    gs_c = gs[2, 0].subgridspec(1, 2, wspace=0.45)
    gs_d = gs[2, 1].subgridspec(1, 3, wspace=0.45)
    ax_c_list = [fig.add_subplot(gs_c[0, 0]), fig.add_subplot(gs_c[0, 1])]
    ax_d_list = [fig.add_subplot(gs_d[0, i]) for i in range(3)]

    def letter(ax: plt.Axes, lab: str, x: float = -0.08) -> None:
        ax.text(
            x,
            1.12,
            lab,
            transform=ax.transAxes,
            fontsize=14,
            fontweight="bold",
            va="bottom",
            ha="right",
        )

    stats_text = None
    if panel_a(ax_a1, ax_a2, inventory, bvals, state):
        state.panels_generated.append("A (acquisition overview)")
        letter(ax_a1, "A")
        stats_text = state.extras.get("panel_a_stats_text")
    else:
        state.panels_skipped.append("A (acquisition overview)")
        ax_a1.set_axis_off()
        ax_a2.set_axis_off()
        ax_a1.text(
            0.5,
            0.5,
            "Panel A skipped — missing inputs",
            ha="center",
            va="center",
            transform=ax_a1.transAxes,
        )

    if panel_b(ax_b, gradcheck, state):
        state.panels_generated.append("B (gradient quality)")
        letter(ax_b, "B", x=-0.03)
    else:
        state.panels_skipped.append("B (gradient quality)")
        ax_b.set_axis_off()
        ax_b.text(
            0.5,
            0.5,
            "Panel B skipped — dwigradcheck_results.tsv unavailable",
            ha="center",
            va="center",
            transform=ax_b.transAxes,
        )

    if panel_c(ax_c_list, masks, state):
        state.panels_generated.append("C (brain mask QC)")
        letter(ax_c_list[0], "C")
        # panel title above the pair
        ax_c_list[0].annotate(
            "Brain-mask QC",
            xy=(1.0, 1.18),
            xycoords="axes fraction",
            ha="center",
            fontsize=11,
            fontweight="semibold",
        )
    else:
        state.panels_skipped.append("C (brain mask QC)")
        for ax in ax_c_list:
            ax.set_axis_off()
        ax_c_list[0].text(
            0.5,
            0.5,
            "Panel C skipped",
            ha="center",
            va="center",
            transform=ax_c_list[0].transAxes,
        )

    if panel_d(ax_d_list, signals, state):
        state.panels_generated.append("D (signal quality)")
        letter(ax_d_list[0], "D")
        ax_d_list[0].annotate(
            "Signal quality",
            xy=(1.55, 1.18),
            xycoords="axes fraction",
            ha="center",
            fontsize=11,
            fontweight="semibold",
        )
    else:
        state.panels_skipped.append("D (signal quality)")
        for ax in ax_d_list:
            ax.set_axis_off()
        ax_d_list[0].text(
            0.5,
            0.5,
            "Panel D skipped",
            ha="center",
            va="center",
            transform=ax_d_list[0].transAxes,
        )

    if stats_text:
        fig.text(0.5, 0.915, stats_text, ha="center", va="top", fontsize=8.5, color="#222222")

    fig.suptitle(
        "Diffusion MRI quality assessment",
        fontsize=14,
        fontweight="bold",
        y=0.98,
    )

    # Save main figure
    base = out_dir / "Figure_DWI_QC"
    for ext in ("png", "pdf", "svg"):
        fig.savefig(base.with_suffix(f".{ext}"), dpi=DPI, bbox_inches="tight")
    plt.close(fig)

    write_legend(out_dir / "FIGURE_DWI_QC_LEGEND.md", state)

    # Bonus examples figure (read-only from figures/ and optional tmp masks)
    make_examples_figure(
        out_dir=out_dir,
        fig_dir=qc_dir / "figures",
        inventory=inventory,
        tmp_dir=qc_dir / "tmp",
        state=state,
    )

    # Publication status
    core_panels = {"A (acquisition overview)", "B (gradient quality)", "C (brain mask QC)", "D (signal quality)"}
    generated = set(state.panels_generated)
    if not generated:
        status = "WARNING"
        state.warnings.append("No panels could be generated.")
    elif core_panels.issubset(generated) and state.n_scans > 0:
        # WARNING if substantive QC anomalies exist
        if state.extras.get("gradcheck", {}).get("FAIL", 0) > 0:
            status = "WARNING"
        elif state.extras.get("gradcheck", {}).get("REVIEW", 0) > 0:
            status = "WARNING"
            state.warnings.append(
                "Gradient REVIEW counts present: orientation suggestions recorded; "
                "no corrections applied."
            )
        elif state.missing_inputs:
            status = "WARNING"
        else:
            status = "PASS"
    else:
        status = "WARNING"
        state.warnings.append("One or more core panels were skipped.")

    write_summary(out_dir / "DWI_PUBLICATION_SUMMARY.md", state, status)
    print(f"Wrote figure to {base}.{{png,pdf,svg}}")
    print(f"Publication status: {status}")
    print(f"Summary: {out_dir / 'DWI_PUBLICATION_SUMMARY.md'}")
    return 0 if status in {"PASS", "WARNING"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
