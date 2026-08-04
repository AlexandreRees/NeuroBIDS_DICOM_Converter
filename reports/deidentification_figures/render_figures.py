#!/usr/bin/env python3
"""Render publication-ready de-identification figures (PNG 300 dpi + SVG).

Workflow / provenance diagrams: Graphviz (dot).
Bar chart and before/after schematic: matplotlib.
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch
import numpy as np

OUT = Path(__file__).resolve().parent
DPI = 300

# Scientific Data–friendly palette (muted, high contrast, no glow)
INK = "#1A1A1A"
MUTED = "#4A4A4A"
RAW = "#1F4E79"
ACTION = "#A93226"
OK = "#196F3D"
DERIV = "#1A5276"
LIGHT_RAW = "#D6EAF8"
LIGHT_WARN = "#FCF3CF"
LIGHT_ACTION = "#FADBD8"
LIGHT_OK = "#D5F5E3"
LIGHT_DERIV = "#D4E6F1"
LIGHT_GRAY = "#EAECEE"


def _configure_matplotlib() -> None:
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 10,
            "axes.titlesize": 12,
            "axes.labelsize": 10,
            "xtick.labelsize": 9,
            "ytick.labelsize": 10,
            "figure.dpi": DPI,
            "savefig.dpi": DPI,
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
            "svg.fonttype": "none",
        }
    )


def _embed_dpi(path: Path, dpi: int = DPI) -> None:
    """Ensure PNG files carry explicit dpi metadata for journals."""
    from PIL import Image

    image = Image.open(path)
    image.save(path, dpi=(dpi, dpi))


def _run_dot(dot_source: str, stem: str) -> None:
    """Compile Graphviz DOT to PNG (300 dpi) and SVG."""
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / f"{stem}.dot"
        src.write_text(dot_source, encoding="utf-8")
        for fmt in ("png", "svg"):
            out = OUT / f"{stem}.{fmt}"
            if fmt == "png":
                cmd = ["dot", "-Tpng", f"-Gdpi={DPI}", str(src), "-o", str(out)]
            else:
                cmd = ["dot", "-Tsvg", str(src), "-o", str(out)]
            subprocess.run(cmd, check=True, capture_output=True, text=True)
            if fmt == "png":
                _embed_dpi(out)
            print(f"Wrote {out.name} ({out.stat().st_size} bytes)")


def figure_workflow() -> None:
    """Figure 1 — de-identification workflow (Graphviz)."""
    dot = r'''
digraph deidentification_workflow {
  graph [
    rankdir=TB
    bgcolor="white"
    pad="0.4"
    nodesep="0.35"
    ranksep="0.45"
    fontname="Helvetica"
    fontsize=11
    label="De-identification workflow for research release preparation\nDownstream processing uses derived copies; the raw archive is never overwritten"
    labelloc="t"
    labeljust="c"
    fontcolor="#1A1A1A"
  ];
  node [
    shape=box
    style="rounded,filled"
    fontname="Helvetica"
    fontsize=10
    color="#333333"
    penwidth=1.4
    margin="0.18,0.12"
  ];
  edge [
    fontname="Helvetica"
    fontsize=8
    color="#333333"
    penwidth=1.3
    arrowsize=0.8
  ];

  raw [
    label="Raw DICOM repository\n(original acquisitions)"
    fillcolor="#D6EAF8"
    color="#1F4E79"
    penwidth=2.0
  ];

  inventory [
    label="Non-destructive inventory\n(metadata catalogue only)"
    fillcolor="#FCF3CF"
  ];

  mapping [
    label="Participant–session mapping\n(approved identity tables)"
    fillcolor="#FCF3CF"
  ];

  deid [
    label="Automated DICOM de-identification\n(derived copies only)"
    fillcolor="#FADBD8"
    color="#A93226"
    penwidth=2.0
  ];

  phi [label="PHI removal" fillcolor="#F5B7B1" fontsize=9];
  dates [label="Date shifting" fillcolor="#F5B7B1" fontsize=9];
  uids [label="UID remapping" fillcolor="#F5B7B1" fontsize=9];
  priv [label="Private tag removal" fillcolor="#F5B7B1" fontsize=9];

  deid_repo [
    label="De-identified DICOM repository\n(provenance retained; pixels unchanged)"
    fillcolor="#D5F5E3"
    color="#196F3D"
    penwidth=2.0
  ];

  bids [
    label="DICOM-to-NIfTI conversion\n→ BIDS dataset"
    fillcolor="#D4E6F1"
    color="#1A5276"
  ];

  qc [
    label="Quality control and validation"
    fillcolor="#EAECEE"
  ];

  raw -> inventory [style=dashed label="read-only" fontcolor="#1F4E79"];
  inventory -> mapping;
  mapping -> deid;
  raw -> deid [style=dashed label="copy & transform" fontcolor="#A93226" constraint=false];
  deid -> phi;
  deid -> dates;
  deid -> uids;
  deid -> priv;
  phi -> deid_repo;
  dates -> deid_repo;
  uids -> deid_repo;
  priv -> deid_repo;
  deid_repo -> bids;
  bids -> qc;

  {rank=same; phi; dates; uids; priv;}
}
'''
    _run_dot(dot, "figure_deidentification_workflow")


def figure_provenance() -> None:
    """Figure 4 — data provenance and integrity (Graphviz)."""
    dot = r'''
digraph data_provenance {
  graph [
    rankdir=TB
    bgcolor="white"
    pad="0.45"
    nodesep="0.4"
    ranksep="0.42"
    fontname="Helvetica"
    fontsize=12
    label="Data provenance and integrity\nOriginal acquisitions remain untouched throughout"
    labelloc="t"
    fontcolor="#1A1A1A"
  ];
  node [
    shape=box
    style="rounded,filled"
    fontname="Helvetica"
    fontsize=10
    color="#333333"
    penwidth=1.4
    margin="0.16,0.10"
  ];
  edge [
    fontname="Helvetica"
    fontsize=8
    color="#333333"
    penwidth=1.3
    arrowsize=0.8
  ];

  raw [
    label="Immutable raw DICOM\nNever overwritten\nIntegrity snapshots checked\nbefore conversion"
    fillcolor="#D6EAF8"
    color="#1F4E79"
    penwidth=2.2
    style="rounded,filled,dashed"
  ];

  inventory [label="Inventory\n(metadata extraction)" fillcolor="white"];
  mapping [label="Participant–session mapping" fillcolor="white"];
  deid [label="De-identification\n(derived copies)" fillcolor="#FADBD8" color="#A93226"];
  privacy [label="Privacy validation" fillcolor="white"];
  bids [label="BIDS conversion" fillcolor="#D4E6F1"];
  validation [label="Dataset validation" fillcolor="white"];
  qc [label="Quality control" fillcolor="white"];
  open [label="Open research dataset" fillcolor="#D5F5E3" color="#196F3D" penwidth=2.0];

  inventory -> mapping -> deid -> privacy -> bids -> validation -> qc -> open;

  raw -> inventory [style=dashed label="source" fontcolor="#1F4E79"];
  raw -> deid [style=dashed label="copy" fontcolor="#A93226"];
}
'''
    _run_dot(dot, "figure_data_provenance")


def figure_tag_actions() -> None:
    """Figure 2 — quantitative summary of DICOM tag actions (matplotlib)."""
    _configure_matplotlib()
    categories = [
        "Cleared",
        "Pseudonymized",
        "UID remapped",
        "Date shifted",
        "Preserved",
        "Removed private tags",
        "Pixel data unchanged",
    ]
    values = [32, 2, 8, 8, 14, 1, 1]
    colors = [
        "#A93226",
        "#B9770E",
        "#1F618D",
        "#2874A6",
        "#196F3D",
        "#566573",
        "#117A65",
    ]

    fig, ax = plt.subplots(figsize=(8.8, 4.8))
    fig.patch.set_facecolor("white")
    y = np.arange(len(categories))
    bars = ax.barh(y, values, color=colors, edgecolor=INK, linewidth=0.6, height=0.65)
    ax.set_yticks(y)
    ax.set_yticklabels(categories)
    ax.invert_yaxis()
    ax.set_xlabel("Number of explicitly catalogued DICOM fields / categories")
    ax.set_title(
        "Summary of DICOM metadata transformations during de-identification",
        fontweight="bold",
        color=INK,
        pad=10,
    )
    ax.set_xlim(0, max(values) + 5)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color(MUTED)
    ax.spines["bottom"].set_color(MUTED)
    ax.tick_params(colors=MUTED)
    ax.xaxis.label.set_color(INK)
    for bar, val in zip(bars, values):
        ax.text(
            val + 0.25,
            bar.get_y() + bar.get_height() / 2,
            str(val),
            va="center",
            ha="left",
            fontsize=9,
            color=INK,
            fontweight="bold",
        )
    ax.text(
        0.0,
        -0.22,
        (
            "Counts reflect the documented tag policy. "
            "‘Removed private tags’ and ‘Pixel data unchanged’ are single policy categories "
            "(all private tags removed; pixel matrices unaltered)."
        ),
        transform=ax.transAxes,
        ha="left",
        va="top",
        fontsize=7.5,
        color=MUTED,
        wrap=True,
    )
    fig.tight_layout()
    for ext in ("png", "svg"):
        path = OUT / f"figure_dicom_tag_actions.{ext}"
        fig.savefig(path, dpi=DPI, bbox_inches="tight", facecolor="white")
        print(f"Wrote {path.name}")
    plt.close(fig)


def figure_before_after() -> None:
    """Figure 3 — synthetic before/after header schematic (matplotlib)."""
    _configure_matplotlib()
    fig, ax = plt.subplots(figsize=(10.0, 5.4))
    ax.set_xlim(0, 12)
    ax.set_ylim(0, 8)
    ax.axis("off")
    fig.patch.set_facecolor("white")

    ax.text(
        6,
        7.55,
        "Illustrative DICOM header transformation (synthetic example)",
        ha="center",
        fontsize=12,
        fontweight="bold",
        color=INK,
    )
    ax.text(
        6,
        7.15,
        "No real participant identifiers are shown",
        ha="center",
        fontsize=8.5,
        color=MUTED,
        style="italic",
    )

    ax.add_patch(
        FancyBboxPatch(
            (0.4, 0.55),
            5.0,
            6.15,
            boxstyle="round,pad=0.02,rounding_size=0.03",
            facecolor=LIGHT_ACTION,
            edgecolor=ACTION,
            linewidth=1.6,
        )
    )
    ax.text(
        2.9,
        6.3,
        "Before de-identification",
        ha="center",
        fontsize=11,
        fontweight="bold",
        color=ACTION,
    )

    before = [
        ("PatientName", "SUBXYZ_VisitA_YYYYMMDD"),
        ("PatientID", "SCANNER_LOCAL_ID_12345"),
        ("StudyDate", "20230505"),
        ("StudyInstanceUID", "1.2.840.113619.2.xx.original"),
    ]
    y = 5.5
    for key, val in before:
        ax.text(0.7, y, key, fontsize=9, fontweight="bold", color=INK)
        ax.text(0.7, y - 0.38, val, fontsize=8.5, color=MUTED, family="DejaVu Sans Mono")
        y -= 1.25

    ax.add_patch(
        FancyBboxPatch(
            (6.6, 0.55),
            5.0,
            6.15,
            boxstyle="round,pad=0.02,rounding_size=0.03",
            facecolor=LIGHT_OK,
            edgecolor=OK,
            linewidth=1.6,
        )
    )
    ax.text(
        9.1,
        6.3,
        "After de-identification",
        ha="center",
        fontsize=11,
        fontweight="bold",
        color=OK,
    )

    after = [
        ("PatientName", "SUBC000  (canonical study code)"),
        ("PatientID", "SUBC000  (canonical study code)"),
        ("StudyDate", "20141212  (shifted by fixed offset)"),
        ("StudyInstanceUID", "2.25.9062200888896994…"),
    ]
    y = 5.5
    for key, val in after:
        ax.text(6.9, y, key, fontsize=9, fontweight="bold", color=INK)
        ax.text(6.9, y - 0.38, val, fontsize=8.5, color=MUTED, family="DejaVu Sans Mono")
        y -= 1.25

    ax.annotate(
        "",
        xy=(6.5, 3.55),
        xytext=(5.5, 3.55),
        arrowprops=dict(arrowstyle="-|>", color=INK, lw=1.8, mutation_scale=14),
    )
    ax.text(6.0, 3.95, "transform", ha="center", fontsize=8, color=MUTED, fontweight="bold")

    fig.tight_layout()
    for ext in ("png", "svg"):
        path = OUT / f"figure_before_after_deidentification.{ext}"
        fig.savefig(path, dpi=DPI, bbox_inches="tight", facecolor="white")
        print(f"Wrote {path.name}")
    plt.close(fig)


def main() -> None:
    figure_workflow()
    figure_tag_actions()
    figure_before_after()
    figure_provenance()
    print("All figures rendered.")


if __name__ == "__main__":
    main()
