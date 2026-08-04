#!/usr/bin/env python3
"""Generate PI / publication figures for DICOM de-identification (2026-07-24).

Outputs:
  figures/Fig01–Fig06  (PNG 300 dpi + PDF) — présentation PI (FR)
  figure_*.png/.svg    — assets manuscrit Scientific Data (EN), mêmes contenus
"""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch, Circle, Wedge
import numpy as np

OUT = Path(__file__).resolve().parent
FIG = OUT / "figures"
FIG.mkdir(parents=True, exist_ok=True)

DPI = 300

# Restrained palette (aligned with MRIQC PI figures; no purple/glow)
C = {
    "ink": "#1a1a1a",
    "muted": "#5c5c5c",
    "grid": "#e6e6e6",
    "ok": "#2a6f4e",
    "ok_fill": "#d8ebe1",
    "warn": "#a65d16",
    "warn_fill": "#f3e2cf",
    "bad": "#9b2c2c",
    "bad_fill": "#f3d6d6",
    "blue": "#2f5f8a",
    "blue_fill": "#d6e3ef",
    "gray": "#7a7a7a",
    "gray_fill": "#ececec",
}

# Policy counts (Supplementary Table / dicom_tag_action_counts.csv)
ACTIONS = [
    ("Cleared / effacés", "Cleared", 32, C["bad"]),
    ("Pseudonymized", "Pseudonymized", 2, C["warn"]),
    ("UID remapped", "UID remapped", 8, C["blue"]),
    ("Date shifted", "Date shifted", 8, "#3d7ea6"),
    ("Preserved / conservés", "Preserved", 14, C["ok"]),
    ("Private tags removed", "Removed private tags", 1, C["gray"]),
    ("Pixel data unchanged", "Pixel data unchanged", 1, "#1e7a6a"),
]


def style_ax(ax) -> None:
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color(C["grid"])
    ax.spines["bottom"].set_color(C["grid"])
    ax.tick_params(colors=C["muted"])
    ax.yaxis.label.set_color(C["ink"])
    ax.xaxis.label.set_color(C["ink"])
    ax.title.set_color(C["ink"])


def _configure() -> None:
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 10,
            "axes.titlesize": 12,
            "axes.labelsize": 10,
            "figure.dpi": DPI,
            "savefig.dpi": DPI,
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
            "svg.fonttype": "none",
        }
    )


def save_pi(fig, stem: str):
    pdf = FIG / f"{stem}.pdf"
    png = FIG / f"{stem}.png"
    fig.savefig(pdf, bbox_inches="tight", facecolor="white")
    fig.savefig(png, dpi=DPI, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return pdf, png


def save_pub(fig, stem: str, also_svg: bool = True):
    """Manuscript filenames in folder root."""
    png = OUT / f"{stem}.png"
    fig.savefig(png, dpi=DPI, bbox_inches="tight", facecolor="white")
    if also_svg:
        svg = OUT / f"{stem}.svg"
        fig.savefig(svg, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return png


def _box(ax, xy, w, h, text, *, fc, ec, fontsize=9, bold=True, tc=None):
    x, y = xy
    ax.add_patch(
        FancyBboxPatch(
            (x, y),
            w,
            h,
            boxstyle="round,pad=0.015,rounding_size=0.04",
            linewidth=1.5,
            edgecolor=ec,
            facecolor=fc,
            zorder=2,
        )
    )
    ax.text(
        x + w / 2,
        y + h / 2,
        text,
        ha="center",
        va="center",
        fontsize=fontsize,
        color=tc or C["ink"],
        fontweight="bold" if bold else "normal",
        linespacing=1.25,
        zorder=3,
    )


def _arrow(ax, start, end, color=C["ink"], ls="-"):
    ax.annotate(
        "",
        xy=end,
        xytext=start,
        arrowprops=dict(
            arrowstyle="-|>",
            color=color,
            lw=1.5,
            linestyle=ls,
            mutation_scale=12,
        ),
        zorder=1,
    )


# ---------------------------------------------------------------------------
# Fig 01 — Workflow
# ---------------------------------------------------------------------------
def fig01_workflow():
    _configure()
    fig, ax = plt.subplots(figsize=(9.2, 10.8))
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 14.2)
    ax.axis("off")
    fig.patch.set_facecolor("white")

    ax.text(
        5,
        13.85,
        "Déidentification DICOM — workflow de préparation",
        ha="center",
        fontsize=14,
        fontweight="bold",
        color=C["ink"],
    )
    ax.text(
        5,
        13.4,
        "Copies dérivées uniquement · archive brute jamais écrasée",
        ha="center",
        fontsize=9.5,
        color=C["muted"],
        style="italic",
    )

    # Raw column
    ax.add_patch(
        FancyBboxPatch(
            (0.35, 8.55),
            2.7,
            4.35,
            boxstyle="round,pad=0.02,rounding_size=0.05",
            facecolor=C["blue_fill"],
            edgecolor=C["blue"],
            linewidth=1.8,
            linestyle=(0, (4, 3)),
            zorder=1,
        )
    )
    ax.text(
        1.7,
        12.55,
        "Acquisitions\nd’origine",
        ha="center",
        fontsize=9,
        fontweight="bold",
        color=C["blue"],
    )
    _box(
        ax,
        (0.55, 9.35),
        2.3,
        2.4,
        "DICOM brut\n(immutable)\n\nlecture seule",
        fc="white",
        ec=C["blue"],
        fontsize=9.5,
    )

    # Main spine
    steps = [
        (11.55, "1. Inventaire non destructif\n(catalogue métadonnées)", C["warn_fill"], C["warn"]),
        (10.15, "2. Mapping participant–session\n(tables d’identité approuvées)", C["warn_fill"], C["warn"]),
        (8.55, "3. Déidentification automatisée\nsur copies dérivées", C["bad_fill"], C["bad"]),
    ]
    for y, text, fc, ec in steps:
        _box(ax, (3.6, y), 5.9, 1.15, text, fc=fc, ec=ec, fontsize=9.5)

    for y1, y2 in [(11.55, 11.3), (10.15, 9.7)]:
        _arrow(ax, (6.55, y1), (6.55, y2))

    ax.annotate(
        "",
        xy=(3.6, 12.05),
        xytext=(3.05, 12.05),
        arrowprops=dict(arrowstyle="-|>", color=C["blue"], lw=1.3, linestyle="--", mutation_scale=10),
    )
    ax.text(3.3, 12.35, "read-only", fontsize=7.5, color=C["blue"], ha="center")

    ax.annotate(
        "",
        xy=(3.6, 9.0),
        xytext=(1.7, 9.35),
        arrowprops=dict(
            arrowstyle="-|>",
            color=C["bad"],
            lw=1.4,
            connectionstyle="arc3,rad=0.28",
            mutation_scale=11,
        ),
    )
    ax.text(1.85, 8.55, "copie &\ntransforme", fontsize=7.5, color=C["bad"], ha="center", fontweight="bold")

    # Transform grid
    transforms = [
        (3.6, 7.15, "Effacement PHI"),
        (6.75, 7.15, "Décalage dates"),
        (3.6, 6.05, "Remapping UID"),
        (6.75, 6.05, "Tags privés retirés"),
    ]
    for x, y, lab in transforms:
        _box(ax, (x, y), 2.75, 0.85, lab, fc=C["bad_fill"], ec=C["bad"], fontsize=8.5, bold=False)

    _arrow(ax, (6.55, 8.55), (5.0, 8.0), color=C["bad"])
    _arrow(ax, (6.55, 8.55), (8.1, 8.0), color=C["bad"])

    _box(
        ax,
        (3.6, 4.55),
        5.9,
        1.1,
        "Dépôt DICOM déidentifié\n(provenance conservée · pixels inchangés)",
        fc=C["ok_fill"],
        ec=C["ok"],
        fontsize=9.5,
    )
    _arrow(ax, (6.55, 6.05), (6.55, 5.65), color=C["ok"])

    _box(
        ax,
        (3.6, 3.05),
        5.9,
        1.05,
        "Conversion DICOM → NIfTI → BIDS",
        fc=C["blue_fill"],
        ec=C["blue"],
        fontsize=10,
    )
    _arrow(ax, (6.55, 4.55), (6.55, 4.1))

    _box(
        ax,
        (3.6, 1.55),
        5.9,
        1.05,
        "Validation privacy + contrôle qualité",
        fc=C["gray_fill"],
        ec=C["gray"],
        fontsize=10,
    )
    _arrow(ax, (6.55, 3.05), (6.55, 2.6))

    ax.text(
        5,
        0.55,
        "Orientation DICOM PS3.15 Basic Application Level Confidentiality (sous-ensemble documenté)",
        ha="center",
        fontsize=8,
        color=C["muted"],
    )

    fig.tight_layout()
    # Also write EN publication copy
    paths = save_pi(fig, "Fig01_deidentification_workflow")

    # Rebuild EN manuscript version (same layout, EN labels)
    fig2, ax2 = plt.subplots(figsize=(9.2, 10.8))
    ax2.set_xlim(0, 10)
    ax2.set_ylim(0, 14.2)
    ax2.axis("off")
    fig2.patch.set_facecolor("white")
    ax2.text(
        5,
        13.85,
        "De-identification workflow for research release preparation",
        ha="center",
        fontsize=13,
        fontweight="bold",
        color=C["ink"],
    )
    ax2.text(
        5,
        13.4,
        "Downstream processing uses derived copies; the raw archive is never overwritten",
        ha="center",
        fontsize=9,
        color=C["muted"],
        style="italic",
    )
    ax2.add_patch(
        FancyBboxPatch(
            (0.35, 8.55),
            2.7,
            4.35,
            boxstyle="round,pad=0.02,rounding_size=0.05",
            facecolor=C["blue_fill"],
            edgecolor=C["blue"],
            linewidth=1.8,
            linestyle=(0, (4, 3)),
            zorder=1,
        )
    )
    ax2.text(1.7, 12.55, "Original\nacquisitions", ha="center", fontsize=9, fontweight="bold", color=C["blue"])
    _box(ax2, (0.55, 9.35), 2.3, 2.4, "Raw DICOM\nrepository\n\nread-only", fc="white", ec=C["blue"], fontsize=9.5)
    for y, text, fc, ec in [
        (11.55, "Non-destructive inventory\n(metadata catalogue only)", C["warn_fill"], C["warn"]),
        (10.15, "Participant–session mapping\n(approved identity tables)", C["warn_fill"], C["warn"]),
        (8.55, "Automated DICOM de-identification\non derived copies", C["bad_fill"], C["bad"]),
    ]:
        _box(ax2, (3.6, y), 5.9, 1.15, text, fc=fc, ec=ec, fontsize=9.5)
    for y1, y2 in [(11.55, 11.3), (10.15, 9.7)]:
        _arrow(ax2, (6.55, y1), (6.55, y2))
    ax2.annotate(
        "",
        xy=(3.6, 12.05),
        xytext=(3.05, 12.05),
        arrowprops=dict(arrowstyle="-|>", color=C["blue"], lw=1.3, linestyle="--", mutation_scale=10),
    )
    ax2.text(3.3, 12.35, "read-only", fontsize=7.5, color=C["blue"], ha="center")
    ax2.annotate(
        "",
        xy=(3.6, 9.0),
        xytext=(1.7, 9.35),
        arrowprops=dict(
            arrowstyle="-|>",
            color=C["bad"],
            lw=1.4,
            connectionstyle="arc3,rad=0.28",
            mutation_scale=11,
        ),
    )
    ax2.text(1.85, 8.55, "copy &\ntransform", fontsize=7.5, color=C["bad"], ha="center", fontweight="bold")
    for x, y, lab in [
        (3.6, 7.15, "PHI removal"),
        (6.75, 7.15, "Date shifting"),
        (3.6, 6.05, "UID remapping"),
        (6.75, 6.05, "Private tag removal"),
    ]:
        _box(ax2, (x, y), 2.75, 0.85, lab, fc=C["bad_fill"], ec=C["bad"], fontsize=8.5, bold=False)
    _arrow(ax2, (6.55, 8.55), (5.0, 8.0), color=C["bad"])
    _arrow(ax2, (6.55, 8.55), (8.1, 8.0), color=C["bad"])
    _box(
        ax2,
        (3.6, 4.55),
        5.9,
        1.1,
        "De-identified DICOM repository\n(provenance retained; pixels unchanged)",
        fc=C["ok_fill"],
        ec=C["ok"],
        fontsize=9.5,
    )
    _arrow(ax2, (6.55, 6.05), (6.55, 5.65), color=C["ok"])
    _box(ax2, (3.6, 3.05), 5.9, 1.05, "DICOM-to-NIfTI conversion → BIDS dataset", fc=C["blue_fill"], ec=C["blue"], fontsize=10)
    _arrow(ax2, (6.55, 4.55), (6.55, 4.1))
    _box(ax2, (3.6, 1.55), 5.9, 1.05, "Privacy validation & quality control", fc=C["gray_fill"], ec=C["gray"], fontsize=10)
    _arrow(ax2, (6.55, 3.05), (6.55, 2.6))
    ax2.text(
        5,
        0.55,
        "Oriented toward DICOM PS3.15 Basic Application Level Confidentiality (documented custom subset)",
        ha="center",
        fontsize=8,
        color=C["muted"],
    )
    fig2.tight_layout()
    save_pub(fig2, "figure_deidentification_workflow")
    return paths


# ---------------------------------------------------------------------------
# Fig 02 — Tag action bar chart
# ---------------------------------------------------------------------------
def fig02_tag_actions():
    _configure()
    labels_fr = [a[0] for a in ACTIONS]
    labels_en = [a[1] for a in ACTIONS]
    values = [a[2] for a in ACTIONS]
    colors = [a[3] for a in ACTIONS]

    fig, ax = plt.subplots(figsize=(9.0, 5.2))
    style_ax(ax)
    y = np.arange(len(labels_fr))
    bars = ax.barh(y, values, color=colors, edgecolor=C["ink"], linewidth=0.5, height=0.68, zorder=2)
    ax.set_yticks(y)
    ax.set_yticklabels(labels_fr)
    ax.invert_yaxis()
    ax.set_xlabel("Nombre de champs / catégories catalogueés dans la politique")
    ax.set_title("Transformations DICOM lors de la déidentification", fontweight="bold", pad=10)
    ax.set_xlim(0, max(values) + 6)
    ax.grid(axis="x", color=C["grid"], linewidth=0.8, zorder=0)
    for bar, val in zip(bars, values):
        ax.text(
            val + 0.3,
            bar.get_y() + bar.get_height() / 2,
            str(val),
            va="center",
            fontsize=10,
            fontweight="bold",
            color=C["ink"],
        )
    ax.text(
        0.0,
        -0.18,
        "Source: table de politique DICOM (Supplementary Table). "
        "« Private tags » et « Pixel data » = catégories de politique (toutes / inchangées).",
        transform=ax.transAxes,
        ha="left",
        va="top",
        fontsize=7.5,
        color=C["muted"],
    )
    fig.tight_layout()
    paths = save_pi(fig, "Fig02_dicom_tag_actions")

    # EN manuscript
    fig2, ax2 = plt.subplots(figsize=(9.0, 5.2))
    style_ax(ax2)
    bars = ax2.barh(y, values, color=colors, edgecolor=C["ink"], linewidth=0.5, height=0.68, zorder=2)
    ax2.set_yticks(y)
    ax2.set_yticklabels(labels_en)
    ax2.invert_yaxis()
    ax2.set_xlabel("Number of explicitly catalogued DICOM fields / categories")
    ax2.set_title(
        "Summary of DICOM metadata transformations during de-identification",
        fontweight="bold",
        pad=10,
    )
    ax2.set_xlim(0, max(values) + 6)
    ax2.grid(axis="x", color=C["grid"], linewidth=0.8, zorder=0)
    for bar, val in zip(bars, values):
        ax2.text(
            val + 0.3,
            bar.get_y() + bar.get_height() / 2,
            str(val),
            va="center",
            fontsize=10,
            fontweight="bold",
            color=C["ink"],
        )
    ax2.text(
        0.0,
        -0.18,
        "Counts reflect the documented tag policy. "
        "‘Removed private tags’ and ‘Pixel data unchanged’ are single policy categories.",
        transform=ax2.transAxes,
        ha="left",
        va="top",
        fontsize=7.5,
        color=C["muted"],
    )
    fig2.tight_layout()
    save_pub(fig2, "figure_dicom_tag_actions")
    return paths


# ---------------------------------------------------------------------------
# Fig 03 — Before / after
# ---------------------------------------------------------------------------
def fig03_before_after():
    _configure()
    fig, ax = plt.subplots(figsize=(10.5, 5.8))
    ax.set_xlim(0, 12)
    ax.set_ylim(0, 8)
    ax.axis("off")
    fig.patch.set_facecolor("white")

    ax.text(
        6,
        7.55,
        "Transformation d’en-tête DICOM (exemple synthétique)",
        ha="center",
        fontsize=13,
        fontweight="bold",
        color=C["ink"],
    )
    ax.text(
        6,
        7.15,
        "Aucun identifiant réel de participant n’est montré",
        ha="center",
        fontsize=9,
        color=C["muted"],
        style="italic",
    )

    ax.add_patch(
        FancyBboxPatch(
            (0.35, 0.5),
            5.1,
            6.2,
            boxstyle="round,pad=0.02,rounding_size=0.05",
            facecolor=C["bad_fill"],
            edgecolor=C["bad"],
            linewidth=1.8,
        )
    )
    ax.text(2.9, 6.3, "Avant déidentification", ha="center", fontsize=11, fontweight="bold", color=C["bad"])

    before = [
        ("PatientName", "SUBXYZ_VisitA_YYYYMMDD"),
        ("PatientID", "SCANNER_LOCAL_ID_12345"),
        ("StudyDate", "20230505"),
        ("StudyInstanceUID", "1.2.840.113619.2.xx.original"),
    ]
    y = 5.5
    for key, val in before:
        ax.text(0.65, y, key, fontsize=9.5, fontweight="bold", color=C["ink"])
        ax.text(0.65, y - 0.38, val, fontsize=8.5, color=C["muted"], family="DejaVu Sans Mono")
        y -= 1.25

    ax.add_patch(
        FancyBboxPatch(
            (6.55, 0.5),
            5.1,
            6.2,
            boxstyle="round,pad=0.02,rounding_size=0.05",
            facecolor=C["ok_fill"],
            edgecolor=C["ok"],
            linewidth=1.8,
        )
    )
    ax.text(9.1, 6.3, "Après déidentification", ha="center", fontsize=11, fontweight="bold", color=C["ok"])

    after = [
        ("PatientName", "SUBC000  (code étude canonique)"),
        ("PatientID", "SUBC000  (code étude canonique)"),
        ("StudyDate", "20141212  (décalé, offset fixe)"),
        ("StudyInstanceUID", "2.25.9062200888896994…"),
    ]
    y = 5.5
    for key, val in after:
        ax.text(6.85, y, key, fontsize=9.5, fontweight="bold", color=C["ink"])
        ax.text(6.85, y - 0.38, val, fontsize=8.5, color=C["muted"], family="DejaVu Sans Mono")
        y -= 1.25

    ax.annotate(
        "",
        xy=(6.45, 3.55),
        xytext=(5.55, 3.55),
        arrowprops=dict(arrowstyle="-|>", color=C["ink"], lw=2.0, mutation_scale=14),
    )
    ax.text(6.0, 3.95, "transforme", ha="center", fontsize=8.5, color=C["muted"], fontweight="bold")

    fig.tight_layout()
    paths = save_pi(fig, "Fig03_before_after_deidentification")

    # EN
    fig2, ax2 = plt.subplots(figsize=(10.5, 5.8))
    ax2.set_xlim(0, 12)
    ax2.set_ylim(0, 8)
    ax2.axis("off")
    fig2.patch.set_facecolor("white")
    ax2.text(
        6,
        7.55,
        "Illustrative DICOM header transformation (synthetic example)",
        ha="center",
        fontsize=13,
        fontweight="bold",
        color=C["ink"],
    )
    ax2.text(
        6,
        7.15,
        "No real participant identifiers are shown",
        ha="center",
        fontsize=9,
        color=C["muted"],
        style="italic",
    )
    ax2.add_patch(
        FancyBboxPatch(
            (0.35, 0.5),
            5.1,
            6.2,
            boxstyle="round,pad=0.02,rounding_size=0.05",
            facecolor=C["bad_fill"],
            edgecolor=C["bad"],
            linewidth=1.8,
        )
    )
    ax2.text(2.9, 6.3, "Before de-identification", ha="center", fontsize=11, fontweight="bold", color=C["bad"])
    y = 5.5
    for key, val in before:
        ax2.text(0.65, y, key, fontsize=9.5, fontweight="bold", color=C["ink"])
        ax2.text(0.65, y - 0.38, val, fontsize=8.5, color=C["muted"], family="DejaVu Sans Mono")
        y -= 1.25
    ax2.add_patch(
        FancyBboxPatch(
            (6.55, 0.5),
            5.1,
            6.2,
            boxstyle="round,pad=0.02,rounding_size=0.05",
            facecolor=C["ok_fill"],
            edgecolor=C["ok"],
            linewidth=1.8,
        )
    )
    ax2.text(9.1, 6.3, "After de-identification", ha="center", fontsize=11, fontweight="bold", color=C["ok"])
    after_en = [
        ("PatientName", "SUBC000  (canonical study code)"),
        ("PatientID", "SUBC000  (canonical study code)"),
        ("StudyDate", "20141212  (shifted by fixed offset)"),
        ("StudyInstanceUID", "2.25.9062200888896994…"),
    ]
    y = 5.5
    for key, val in after_en:
        ax2.text(6.85, y, key, fontsize=9.5, fontweight="bold", color=C["ink"])
        ax2.text(6.85, y - 0.38, val, fontsize=8.5, color=C["muted"], family="DejaVu Sans Mono")
        y -= 1.25
    ax2.annotate(
        "",
        xy=(6.45, 3.55),
        xytext=(5.55, 3.55),
        arrowprops=dict(arrowstyle="-|>", color=C["ink"], lw=2.0, mutation_scale=14),
    )
    ax2.text(6.0, 3.95, "transform", ha="center", fontsize=8.5, color=C["muted"], fontweight="bold")
    fig2.tight_layout()
    save_pub(fig2, "figure_before_after_deidentification")
    return paths


# ---------------------------------------------------------------------------
# Fig 04 — Provenance
# ---------------------------------------------------------------------------
def fig04_provenance():
    _configure()
    fig, ax = plt.subplots(figsize=(8.4, 10.6))
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 13.5)
    ax.axis("off")
    fig.patch.set_facecolor("white")

    ax.text(5, 13.05, "Provenance et intégrité des données", ha="center", fontsize=14, fontweight="bold", color=C["ink"])
    ax.text(
        5,
        12.55,
        "Les acquisitions d’origine restent intactes tout au long du pipeline",
        ha="center",
        fontsize=9.5,
        color=C["ok"],
        fontweight="bold",
        style="italic",
    )

    ax.add_patch(
        FancyBboxPatch(
            (0.3, 0.7),
            2.8,
            11.3,
            boxstyle="round,pad=0.02,rounding_size=0.05",
            facecolor=C["blue_fill"],
            edgecolor=C["blue"],
            linewidth=2.0,
            linestyle=(0, (5, 3)),
        )
    )
    ax.text(1.7, 11.5, "DICOM brut\nimmutable", ha="center", fontsize=10, fontweight="bold", color=C["blue"])
    ax.text(1.7, 10.3, "Jamais\nécrasé", ha="center", fontsize=8.5, color=C["muted"])
    ax.text(
        1.7,
        2.4,
        "Snapshots\nd’intégrité\nvérifiés avant\nconversion",
        ha="center",
        fontsize=8,
        color=C["blue"],
    )

    stages = [
        (11.0, "Inventaire\n(extraction métadonnées)"),
        (9.55, "Mapping participant–session"),
        (8.1, "Déidentification\n(copies dérivées)"),
        (6.65, "Validation privacy"),
        (5.2, "Conversion BIDS"),
        (3.75, "Validation dataset"),
        (2.3, "Contrôle qualité"),
        (0.85, "Jeu de données\nouvert (recherche)"),
    ]
    for y, label in stages:
        is_open = "ouvert" in label
        _box(
            ax,
            (4.0, y),
            5.5,
            1.15,
            label,
            fc=C["ok_fill"] if is_open else "white",
            ec=C["ok"] if is_open else C["blue"],
            fontsize=9.5,
        )

    for i in range(len(stages) - 1):
        y_top = stages[i][0]
        y_bot = stages[i + 1][0] + 1.15
        _arrow(ax, (6.75, y_top), (6.75, y_bot))

    for y, lab in ((11.5, "source"), (8.55, "copie")):
        ax.annotate(
            "",
            xy=(4.0, y),
            xytext=(3.1, y),
            arrowprops=dict(arrowstyle="-|>", color=C["blue"], lw=1.1, linestyle="--", mutation_scale=9),
        )
        ax.text(3.45, y + 0.25, lab, fontsize=7, color=C["blue"], ha="center")

    fig.tight_layout()
    paths = save_pi(fig, "Fig04_data_provenance")

    # EN
    fig2, ax2 = plt.subplots(figsize=(8.4, 10.6))
    ax2.set_xlim(0, 10)
    ax2.set_ylim(0, 13.5)
    ax2.axis("off")
    fig2.patch.set_facecolor("white")
    ax2.text(5, 13.05, "Data provenance and integrity", ha="center", fontsize=14, fontweight="bold", color=C["ink"])
    ax2.text(
        5,
        12.55,
        "Original acquisitions remain untouched throughout",
        ha="center",
        fontsize=9.5,
        color=C["ok"],
        fontweight="bold",
        style="italic",
    )
    ax2.add_patch(
        FancyBboxPatch(
            (0.3, 0.7),
            2.8,
            11.3,
            boxstyle="round,pad=0.02,rounding_size=0.05",
            facecolor=C["blue_fill"],
            edgecolor=C["blue"],
            linewidth=2.0,
            linestyle=(0, (5, 3)),
        )
    )
    ax2.text(1.7, 11.5, "Immutable\nraw DICOM", ha="center", fontsize=10, fontweight="bold", color=C["blue"])
    ax2.text(1.7, 10.3, "Never\noverwritten", ha="center", fontsize=8.5, color=C["muted"])
    ax2.text(
        1.7,
        2.4,
        "Integrity\nsnapshots\nchecked before\nconversion",
        ha="center",
        fontsize=8,
        color=C["blue"],
    )
    stages_en = [
        (11.0, "Inventory\n(metadata extraction)"),
        (9.55, "Participant–session\nmapping"),
        (8.1, "De-identification\n(derived copies)"),
        (6.65, "Privacy validation"),
        (5.2, "BIDS conversion"),
        (3.75, "Dataset validation"),
        (2.3, "Quality control"),
        (0.85, "Open research\ndataset"),
    ]
    for y, label in stages_en:
        is_open = "Open" in label
        _box(
            ax2,
            (4.0, y),
            5.5,
            1.15,
            label,
            fc=C["ok_fill"] if is_open else "white",
            ec=C["ok"] if is_open else C["blue"],
            fontsize=9.5,
        )
    for i in range(len(stages_en) - 1):
        y_top = stages_en[i][0]
        y_bot = stages_en[i + 1][0] + 1.15
        _arrow(ax2, (6.75, y_top), (6.75, y_bot))
    for y, lab in ((11.5, "source"), (8.55, "copy")):
        ax2.annotate(
            "",
            xy=(4.0, y),
            xytext=(3.1, y),
            arrowprops=dict(arrowstyle="-|>", color=C["blue"], lw=1.1, linestyle="--", mutation_scale=9),
        )
        ax2.text(3.45, y + 0.25, lab, fontsize=7, color=C["blue"], ha="center")
    fig2.tight_layout()
    save_pub(fig2, "figure_data_provenance")
    return paths


# ---------------------------------------------------------------------------
# Fig 05 — Policy composition donut
# ---------------------------------------------------------------------------
def fig05_policy_donut():
    _configure()
    # Group for readable donut: PHI cleared+pseudo, linkage (UID+dates), science keep, other
    groups = [
        ("PHI effacé / pseudonymisé", 34, C["bad"]),
        ("Lien rompu (UID + dates)", 16, C["blue"]),
        ("Métadonnées scientifiques\nconservées", 14, C["ok"]),
        ("Politique pixels / privés", 2, C["gray"]),
    ]
    labels = [g[0] for g in groups]
    sizes = [g[1] for g in groups]
    colors = [g[2] for g in groups]

    fig, ax = plt.subplots(figsize=(8.5, 5.6))
    fig.patch.set_facecolor("white")
    wedges, *_ = ax.pie(
        sizes,
        colors=colors,
        startangle=90,
        wedgeprops=dict(width=0.42, edgecolor="white", linewidth=2),
    )
    ax.text(0, 0.08, "66", ha="center", va="center", fontsize=28, fontweight="bold", color=C["ink"])
    ax.text(0, -0.22, "entrées\npolitique", ha="center", va="center", fontsize=10, color=C["muted"])
    ax.set_title("Composition de la politique de déidentification DICOM", fontweight="bold", color=C["ink"], pad=12)

    legend = [
        mpatches.Patch(facecolor=c, edgecolor=C["ink"], linewidth=0.4, label=f"{lab}  ({n})")
        for lab, n, c in groups
    ]
    ax.legend(handles=legend, frameon=False, loc="center left", bbox_to_anchor=(1.02, 0.5), fontsize=9)
    ax.text(
        0.5,
        -0.08,
        "Ne pas revendiquer une conformité PS3.15 Basic « certifiée » — sous-ensemble documenté orienté Basic.",
        transform=ax.transAxes,
        ha="center",
        fontsize=8,
        color=C["muted"],
    )
    fig.tight_layout()
    return save_pi(fig, "Fig05_policy_composition")


# ---------------------------------------------------------------------------
# Fig 06 — PI one-pager
# ---------------------------------------------------------------------------
def fig06_pi_onepager():
    _configure()
    fig = plt.figure(figsize=(11, 6.2))
    fig.patch.set_facecolor("white")
    ax = fig.add_axes([0, 0, 1, 1])
    ax.axis("off")

    ax.text(0.04, 0.90, "Déidentification DICOM — synthèse (PI)", fontsize=20, fontweight="bold", color=C["ink"])
    ax.text(
        0.04,
        0.83,
        "mri_anonymization 2.0 · orientation PS3.15 Basic · copies dérivées uniquement",
        fontsize=11,
        color=C["muted"],
    )

    boxes = [
        (0.04, 0.52, "32", "Champs PHI\neffacés", C["bad_fill"], C["bad"]),
        (0.28, 0.52, "8+8", "UID remappés\n+ dates décalées", C["blue_fill"], C["blue"]),
        (0.52, 0.52, "14", "Paramètres\nscientifiques gardés", C["ok_fill"], C["ok"]),
        (0.76, 0.52, "0", "Écriture sur\nraw (immutable)", C["ok_fill"], C["ok"]),
    ]
    for x, y, val, lab, fill, edge in boxes:
        ax.add_patch(
            plt.Rectangle(
                (x, y),
                0.20,
                0.24,
                transform=ax.transAxes,
                facecolor=fill,
                edgecolor=edge,
                linewidth=1.5,
            )
        )
        ax.text(x + 0.10, y + 0.14, val, ha="center", va="center", fontsize=20, fontweight="bold", color=edge)
        ax.text(x + 0.10, y + 0.05, lab, ha="center", va="center", fontsize=9, color=C["muted"])

    bullets = [
        "• Raw DICOM = archive immuable; déidentification uniquement sur copies → puis BIDS.",
        "• Pseudonymisation: PatientName/ID → code étude (SUBC…); UIDs → 2.25.*; dates décalées / participant.",
        "• Pixels inchangés à cette étape; defacing anatomique = piste release séparée (pas ce stage).",
        "• Verdict publication: PASS avec caveats — documenter un sous-ensemble PS3.15, pas une conformité certifiée.",
        "• Recommandation PI: accepter le framing Methods + Supplementary Table; garder offsets/maps en privé.",
    ]
    y = 0.42
    for b in bullets:
        ax.text(0.04, y, b, fontsize=11, color=C["ink"], va="top")
        y -= 0.07

    ax.text(
        0.04,
        0.05,
        "Sources: reports/deidentification_figures · reports/deidentification_report.md · "
        "reports/deidentification_ps315_openneuro_audit.md",
        fontsize=8,
        color=C["muted"],
    )
    return save_pi(fig, "Fig06_PI_onepager_deidentification")


def main():
    _configure()
    writers = [
        fig01_workflow,
        fig02_tag_actions,
        fig03_before_after,
        fig04_provenance,
        fig05_policy_donut,
        fig06_pi_onepager,
    ]
    for fn in writers:
        res = fn()
        if res:
            print("wrote", res[1].name)
    print("Done. PI figures →", FIG)
    print("Publication EN figures refreshed in", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
