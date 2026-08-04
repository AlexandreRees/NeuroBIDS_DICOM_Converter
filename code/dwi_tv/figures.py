"""Publication figures for DWI technical validation."""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import nibabel as nib
import numpy as np
import pandas as pd
from mpl_toolkits.mplot3d import Axes3D  # noqa: F401

from .common import (
    B0_THRESHOLD,
    C_ACCENT,
    C_EDGE,
    C_FAIL,
    C_FILL,
    C_NA,
    C_PASS,
    C_PROTOCOLS,
    C_REVIEW,
    apply_style,
    load_bval,
    save_figure,
)
from .sections import unique_directions_from_bvec


def _hist_box(ax_hist, ax_box, values: np.ndarray, color: str, xlabel: str) -> None:
    values = np.asarray(values, dtype=float)
    values = values[np.isfinite(values)]
    if values.size == 0:
        ax_hist.text(0.5, 0.5, "No data", ha="center", va="center", transform=ax_hist.transAxes)
        ax_box.axis("off")
        return
    ax_hist.hist(values, bins=30, color=color, edgecolor=C_EDGE, alpha=0.85)
    ax_hist.set_xlabel(xlabel)
    ax_hist.set_ylabel("Scans")
    ax_box.boxplot(
        values,
        vert=True,
        widths=0.55,
        patch_artist=True,
        boxprops=dict(facecolor=color, alpha=0.55, edgecolor=C_EDGE),
        medianprops=dict(color=C_EDGE, linewidth=1.5),
        whiskerprops=dict(color=C_EDGE),
        capprops=dict(color=C_EDGE),
        flierprops=dict(marker="o", markersize=3, alpha=0.4),
    )
    ax_box.set_xticks([])
    ax_box.set_ylabel(xlabel)


def figure_protocols(proto: pd.DataFrame, out_stem: Path) -> None:
    apply_style()
    fig, axes = plt.subplots(1, 2, figsize=(10, 4.2))
    labels = proto["protocol_id"].tolist()
    counts = proto["n_scans"].tolist()
    colors = [C_PROTOCOLS[i % len(C_PROTOCOLS)] for i in range(len(labels))]
    axes[0].bar(labels, counts, color=colors, edgecolor=C_EDGE)
    axes[0].set_ylabel("Number of scans")
    axes[0].set_title("Acquisition protocols")
    axes[0].tick_params(axis="x", rotation=20)

    # Composition: b-value scheme text
    schemes = proto["unique_bvals"].astype(str) + "\n" + proto["n_diffusion_directions"].astype(str) + " dir"
    axes[1].barh(labels[::-1], counts[::-1], color=colors[::-1], edgecolor=C_EDGE)
    for i, (lab, n, sch) in enumerate(zip(labels[::-1], counts[::-1], schemes[::-1])):
        axes[1].text(n + max(counts) * 0.01, i, f"{sch} (n={n})", va="center", fontsize=8)
    axes[1].set_xlabel("Number of scans")
    axes[1].set_title("Protocol composition")
    fig.tight_layout()
    save_figure(fig, out_stem.with_suffix(".png"))


def figure_bvalue_distribution(acq: pd.DataFrame, out_stem: Path) -> None:
    apply_style()
    fig, axes = plt.subplots(1, 2, figsize=(10, 4))
    counts = acq["unique_bvals"].value_counts()
    axes[0].bar(counts.index.astype(str), counts.values, color=C_ACCENT, edgecolor=C_EDGE)
    axes[0].set_xlabel("Unique b-value scheme")
    axes[0].set_ylabel("Scans")
    axes[0].set_title("Distribution of unique b-values")
    axes[0].tick_params(axis="x", rotation=15)

    # Flatten all unique shells across scans for histogram of shell usage
    shells = []
    for s in acq["unique_bvals"].dropna():
        for part in str(s).split(","):
            if part.strip():
                shells.append(int(float(part)))
    if shells:
        uniq, freq = np.unique(shells, return_counts=True)
        axes[1].bar([str(u) for u in uniq], freq, color=C_FILL, edgecolor=C_EDGE)
    axes[1].set_xlabel("b-value (s/mm²)")
    axes[1].set_ylabel("Protocol inclusions (scan×shell)")
    axes[1].set_title("b-value shell usage")
    fig.tight_layout()
    save_figure(fig, out_stem.with_suffix(".png"))


def figure_directions(acq: pd.DataFrame, out_stem: Path) -> None:
    apply_style()
    fig, axes = plt.subplots(1, 2, figsize=(10, 4))
    vals = acq["n_diffusion_directions"].dropna().astype(int)
    counts = vals.value_counts().sort_index()
    axes[0].bar(counts.index.astype(str), counts.values, color=C_ACCENT, edgecolor=C_EDGE)
    axes[0].set_xlabel("Number of diffusion directions")
    axes[0].set_ylabel("Scans")
    axes[0].set_title("Distribution of gradient directions")
    axes[0].tick_params(axis="x", rotation=45)
    axes[1].hist(vals.values, bins=min(30, max(5, vals.nunique())), color=C_FILL, edgecolor=C_EDGE)
    axes[1].set_xlabel("Number of diffusion directions")
    axes[1].set_ylabel("Scans")
    axes[1].set_title("Histogram of directions")
    fig.tight_layout()
    save_figure(fig, out_stem.with_suffix(".png"))


def figure_protocol_composition(acq: pd.DataFrame, out_stem: Path) -> None:
    apply_style()
    fig, ax = plt.subplots(figsize=(7, 4.5))
    ct = pd.crosstab(acq["protocol_id"], acq["unique_bvals"])
    ct.plot(kind="bar", stacked=True, ax=ax, edgecolor=C_EDGE, colormap="tab20")
    ax.set_ylabel("Scans")
    ax.set_xlabel("")
    ax.set_title("Protocol composition by b-value scheme")
    ax.legend(title="b-values", fontsize=7)
    fig.tight_layout()
    save_figure(fig, out_stem.with_suffix(".png"))


def figure_gradient_qc_summary(grad: pd.DataFrame, out_stem: Path) -> None:
    apply_style()
    fig, axes = plt.subplots(1, 2, figsize=(10, 4))
    status_counts = grad["status"].value_counts().reindex(["PASS", "REVIEW", "FAIL"]).fillna(0)
    colors = [C_PASS, C_REVIEW, C_FAIL]
    axes[0].bar(status_counts.index.astype(str), status_counts.values, color=colors, edgecolor=C_EDGE)
    axes[0].set_ylabel("Scans")
    axes[0].set_title("dwigradcheck status")
    for i, v in enumerate(status_counts.values):
        axes[0].text(i, v + max(status_counts.values) * 0.01, str(int(v)), ha="center", fontsize=9)

    rev = grad[grad["status"] == "REVIEW"]["review_class"].value_counts()
    if len(rev):
        axes[1].bar(rev.index.astype(str), rev.values, color=C_REVIEW, edgecolor=C_EDGE)
        axes[1].tick_params(axis="x", rotation=25)
    else:
        axes[1].text(0.5, 0.5, "No REVIEW cases", ha="center", va="center", transform=axes[1].transAxes)
    axes[1].set_ylabel("Scans")
    axes[1].set_title("REVIEW classification")
    fig.tight_layout()
    save_figure(fig, out_stem.with_suffix(".png"))


def figure_gradient_sphere(
    dirs: np.ndarray,
    title: str,
    out_stem: Path,
) -> None:
    apply_style()
    fig = plt.figure(figsize=(5.5, 5.2))
    ax = fig.add_subplot(111, projection="3d")
    if dirs.size == 0:
        ax.text2D(0.5, 0.5, "No directions", transform=ax.transAxes, ha="center")
    else:
        # Unit sphere wireframe
        u = np.linspace(0, 2 * np.pi, 40)
        v = np.linspace(0, np.pi, 20)
        x = np.outer(np.cos(u), np.sin(v))
        y = np.outer(np.sin(u), np.sin(v))
        z = np.outer(np.ones_like(u), np.cos(v))
        ax.plot_wireframe(x, y, z, color="#CCCCCC", linewidth=0.3, alpha=0.5)
        ax.scatter(dirs[:, 0], dirs[:, 1], dirs[:, 2], s=12, c=C_ACCENT, depthshade=True, alpha=0.85)
        # Antipodes lightly
        ax.scatter(-dirs[:, 0], -dirs[:, 1], -dirs[:, 2], s=6, c=C_FILL, alpha=0.35)
    ax.set_title(title, fontsize=11)
    ax.set_box_aspect((1, 1, 1))
    ax.set_xlabel("x")
    ax.set_ylabel("y")
    ax.set_zlabel("z")
    fig.tight_layout()
    save_figure(fig, out_stem.with_suffix(".png"))


def figure_brainmask(mask_qc: pd.DataFrame, out_stem: Path) -> None:
    apply_style()
    fig, axes = plt.subplots(2, 2, figsize=(9.5, 7.5))
    bf = mask_qc["brain_fraction"].to_numpy(dtype=float)
    bv = mask_qc["brain_volume_mm3"].to_numpy(dtype=float) / 1000.0  # mL
    _hist_box(axes[0, 0], axes[0, 1], bf, C_ACCENT, "Brain fraction")
    axes[0, 0].set_title("Brain fraction — histogram")
    axes[0, 1].set_title("Brain fraction — boxplot")
    _hist_box(axes[1, 0], axes[1, 1], bv, C_FILL, "Brain volume (mL)")
    axes[1, 0].set_title("Brain volume — histogram")
    axes[1, 1].set_title("Brain volume — boxplot")
    fig.tight_layout()
    save_figure(fig, out_stem.with_suffix(".png"))


def figure_signal(signal_qc: pd.DataFrame, out_stem: Path) -> None:
    apply_style()
    fig, axes = plt.subplots(2, 3, figsize=(11.5, 7))
    panels = [
        (axes[0, 0], "median_b0_signal", "Median b0 signal", C_ACCENT),
        (axes[0, 1], "median_diffusion_signal", "Median diffusion signal", C_FILL),
        (axes[0, 2], "b0_SNR", "b0 SNR (robust)", C_PASS),
        (axes[1, 0], "CNR", "CNR (robust)", C_REVIEW),
        (axes[1, 1], "cv_b0", "CV (b0)", C_FAIL),
        (axes[1, 2], "background_signal", "Background signal", C_NA),
    ]
    for ax, col, title, color in panels:
        vals = signal_qc[col].to_numpy(dtype=float) if col in signal_qc.columns else np.array([])
        vals = vals[np.isfinite(vals)]
        if vals.size:
            ax.hist(vals, bins=30, color=color, edgecolor=C_EDGE, alpha=0.85)
            med = float(np.median(vals))
            ax.axvline(med, color=C_EDGE, linestyle="--", linewidth=1, label=f"median={med:.2g}")
            ax.legend(fontsize=7)
        else:
            ax.text(0.5, 0.5, "No data", ha="center", va="center", transform=ax.transAxes)
        ax.set_title(title)
        ax.set_xlabel(title)
        ax.set_ylabel("Scans")
    fig.tight_layout()
    save_figure(fig, out_stem.with_suffix(".png"))


def figure_summary_table_image(rows: list[tuple[str, str]], out_stem: Path) -> None:
    apply_style()
    fig, ax = plt.subplots(figsize=(8.5, 5.5))
    ax.axis("off")
    cell = [[a, b] for a, b in rows]
    table = ax.table(
        cellText=cell,
        colLabels=["QC item", "Status"],
        loc="center",
        cellLoc="left",
    )
    table.auto_set_font_size(False)
    table.set_fontsize(10)
    table.scale(1.2, 1.45)
    for (r, c), cell_obj in table.get_celld().items():
        cell_obj.set_edgecolor("#CCCCCC")
        if r == 0:
            cell_obj.set_facecolor("#F0F0F0")
            cell_obj.set_text_props(weight="bold")
        elif c == 1:
            txt = cell[r - 1][1]
            if "PASS" in txt and "N.A" not in txt:
                cell_obj.set_text_props(color=C_PASS, weight="bold")
            elif "FAIL" in txt:
                cell_obj.set_text_props(color=C_FAIL, weight="bold")
            elif "N.A" in txt or "WARNING" in txt:
                cell_obj.set_text_props(color=C_REVIEW, weight="bold")
    ax.set_title("Technical validation summary", fontsize=13, pad=12)
    fig.tight_layout()
    save_figure(fig, out_stem.with_suffix(".png"))


def _ortho_slices(vol: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    x, y, z = [s // 2 for s in vol.shape]
    axial = np.rot90(vol[:, :, z])
    coronal = np.rot90(vol[:, y, :])
    sagittal = np.rot90(vol[x, :, :])
    return axial, coronal, sagittal


def _overlay(base: np.ndarray, mask_sl: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    base = np.asarray(base, dtype=float)
    finite = base[np.isfinite(base)]
    if finite.size:
        lo, hi = np.percentile(finite, [1, 99])
        if hi <= lo:
            hi = lo + 1
        norm = np.clip((base - lo) / (hi - lo), 0, 1)
    else:
        norm = np.zeros_like(base, dtype=float)
    return norm, mask_sl.astype(bool)


def make_visual_example(
    nifti: Path,
    bval: Path,
    mask_path: Path | None,
    out_path: Path,
) -> bool:
    apply_style()
    img = nib.load(str(nifti))
    dataobj = img.dataobj
    bvals = load_bval(bval)
    b0_idx = np.where(bvals < B0_THRESHOLD)[0]
    b1000 = np.where((bvals >= 800) & (bvals < 1200))[0]
    if b0_idx.size == 0:
        return False
    max_b = float(np.max(bvals))
    high_idx = np.where(np.abs(bvals - max_b) < 50)[0]
    picks = [
        ("b0", int(b0_idx[0])),
        ("b≈1000", int(b1000[0]) if b1000.size else int(np.where(bvals >= B0_THRESHOLD)[0][0])),
        (f"b≈{int(round(max_b))}", int(high_idx[0]) if high_idx.size else int(bvals.argmax())),
    ]
    mask = None
    if mask_path is not None and mask_path.is_file():
        mask = np.asanyarray(nib.load(str(mask_path)).dataobj) > 0

    fig, axes = plt.subplots(3, 3, figsize=(9, 9))
    view_names = ["Axial", "Coronal", "Sagittal"]
    for col, (label, idx) in enumerate(picks):
        vol = np.asanyarray(dataobj[..., idx], dtype=np.float32)
        slices = _ortho_slices(vol)
        mask_slices = _ortho_slices(mask.astype(float)) if mask is not None else (None, None, None)
        for row, (sl, msl, vname) in enumerate(zip(slices, mask_slices, view_names)):
            ax = axes[row, col]
            norm, mbool = _overlay(sl, msl if msl is not None else np.zeros_like(sl))
            ax.imshow(norm, cmap="gray", origin="upper")
            if msl is not None and mbool.any():
                ax.contour(mbool, levels=[0.5], colors=["#E0B000"], linewidths=0.6)
            ax.set_xticks([])
            ax.set_yticks([])
            if row == 0:
                ax.set_title(label, fontsize=10)
            if col == 0:
                ax.set_ylabel(vname, fontsize=10)
    fig.suptitle(nifti.name.replace(".nii.gz", ""), fontsize=11)
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return True


def figure_visual_montage(example_paths: list[Path], out_stem: Path, n: int = 6) -> None:
    apply_style()
    paths = [p for p in example_paths if p.is_file()][:n]
    if not paths:
        return
    from PIL import Image

    imgs = [Image.open(p).convert("RGB") for p in paths]
    # Resize to common width
    w = min(im.width for im in imgs)
    resized = []
    for im in imgs:
        h = int(im.height * (w / im.width))
        resized.append(im.resize((w, h)))
    cols = 2 if len(resized) > 1 else 1
    rows = int(np.ceil(len(resized) / cols))
    cell_h = max(im.height for im in resized)
    canvas = Image.new("RGB", (cols * w, rows * cell_h), (255, 255, 255))
    for i, im in enumerate(resized):
        r, c = divmod(i, cols)
        canvas.paste(im, (c * w, r * cell_h))
    out_stem.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out_stem.with_suffix(".png"))
    # Also PDF/SVG via matplotlib wrapper
    fig, ax = plt.subplots(figsize=(10, 5 * rows / max(cols, 1)))
    ax.imshow(np.asarray(canvas))
    ax.axis("off")
    ax.set_title("Representative visual QC", fontsize=12)
    save_figure(fig, out_stem.with_suffix(".png"))


def build_protocol_spheres(acq: pd.DataFrame, out_dir: Path, max_protocols: int = 8) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    proto_order = (
        acq.groupby("protocol_id").size().sort_values(ascending=False).index.tolist()
    )
    for i, pid in enumerate(proto_order[:max_protocols]):
        g = acq[acq["protocol_id"] == pid]
        row = g.iloc[0]
        bvec = Path(str(row["nifti"]).replace(".nii.gz", ".bvec"))
        bval = Path(str(row["nifti"]).replace(".nii.gz", ".bval"))
        if not bvec.is_file() or not bval.is_file():
            continue
        dirs = unique_directions_from_bvec(bvec, bval)
        letter = pid.replace("Protocol ", "")
        stem = out_dir / f"GradientSphere_protocol{letter}"
        title = (
            f"{pid}: b={row['unique_bvals']}, "
            f"{int(row['n_diffusion_directions'])} dir"
        )
        figure_gradient_sphere(dirs, title, stem)
        paths.append(stem.with_suffix(".png"))
        # Also alias Protocol A/B style names for first two
        if i < 2:
            alias = out_dir / f"GradientSphere_protocol{chr(ord('A') + i)}.png"
            if stem.with_suffix(".png") != alias:
                try:
                    if alias.exists():
                        alias.unlink()
                    alias.symlink_to(stem.with_suffix(".png").name)
                except OSError:
                    import shutil

                    shutil.copy2(stem.with_suffix(".png"), alias)
    return paths
