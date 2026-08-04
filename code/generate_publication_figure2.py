#!/usr/bin/env python3
"""Publication Figure 2 — Functional MRI paradigm overview (Scientific Data).

Nature / Scientific Data illustration style: minimalist, vector, four-panel
horizontal layout (A–D). Regenerates the figure from scratch.

Does NOT modify the older auto-diagram generator in
reports/functional_mri_paradigm_figures/build_functional_paradigm_assets.py.

Outputs:
  reports/functional_mri_paradigm_figures/Figure2_functional_paradigm_overview.svg
  reports/functional_mri_paradigm_figures/Figure2_functional_paradigm_overview.pdf
  reports/functional_mri_paradigm_figures/Figure2_functional_paradigm_overview.png  (600 dpi)

Example:
  python code/generate_publication_figure2.py
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties
from matplotlib.gridspec import GridSpec
from matplotlib.patches import (
    Circle,
    Ellipse,
    FancyBboxPatch,
    FancyArrowPatch,
    Polygon,
    Rectangle,
)
import numpy as np

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
ROOT = Path("/home/alexrees/scratch")
OUT_DIR = ROOT / "reports" / "functional_mri_paradigm_figures"
STEM = "Figure2_functional_paradigm_overview"

# ---------------------------------------------------------------------------
# Palette — exactly four colours + white
# ---------------------------------------------------------------------------
WHITE = "#FFFFFF"
DARK = "#333333"       # dark gray (text, thin rules)
LIGHT = "#C8C8C8"      # light gray (baseline / secondary)
BLUE = "#5B8FB8"       # blue (accent fills)
DBLUE = "#1F4E79"      # dark blue (panel letters, emphasis)

TR_S = 0.937

# Double-column landscape (inches). Generous width → readable when reduced.
FIG_W, FIG_H = 16.0, 6.2
DPI_PNG = 600

# Liberation Sans ≈ Arial metrics (Arial often absent on HPC nodes)
FONT_NAME = "Liberation Sans"
FP = FontProperties(family=FONT_NAME)
FP_BOLD = FontProperties(family=FONT_NAME, weight="bold")
FP_ITALIC = FontProperties(family=FONT_NAME, style="italic")

plt.rcParams.update(
    {
        "font.family": "sans-serif",
        "font.sans-serif": [FONT_NAME, "Arial", "Helvetica", "DejaVu Sans"],
        "font.size": 9,
        "axes.linewidth": 0.5,
        "pdf.fonttype": 42,      # TrueType → editable in Illustrator
        "ps.fonttype": 42,
        "svg.fonttype": "none",  # keep text as <text> in SVG
        "text.color": DARK,
    }
)


def dur_min(n_vol: int) -> float:
    return n_vol * TR_S / 60.0


# ===========================================================================
# Drawing primitives (axes-fraction coordinates; aspect-corrected circles)
# ===========================================================================
def _aspect(ax) -> float:
    """Axes width/height in display units (for circular glyphs)."""
    bb = ax.get_window_extent()
    if bb.height == 0:
        return 1.0
    return bb.width / bb.height


def ellipse(ax, cx, cy, r, facecolor=None, edgecolor=DARK, lw=0.8, z=5):
    """Visually circular disk in axes coordinates."""
    a = _aspect(ax)
    e = Ellipse(
        (cx, cy),
        width=2 * r / a,
        height=2 * r,
        facecolor=facecolor if facecolor is not None else "none",
        edgecolor=edgecolor,
        linewidth=lw,
        transform=ax.transAxes,
        clip_on=False,
        zorder=z,
    )
    ax.add_patch(e)
    return e


def line(ax, x0, y0, x1, y1, color=DARK, lw=0.8, z=4):
    ax.plot(
        [x0, x1],
        [y0, y1],
        transform=ax.transAxes,
        color=color,
        lw=lw,
        solid_capstyle="round",
        zorder=z,
        clip_on=False,
    )


def txt(ax, x, y, s, *, size=8, weight="normal", style="normal", color=DARK,
        ha="center", va="center", alpha=1.0, z=6):
    fp = FontProperties(family=FONT_NAME, weight=weight, style=style, size=size)
    ax.text(
        x, y, s,
        transform=ax.transAxes,
        fontproperties=fp,
        color=color,
        ha=ha,
        va=va,
        alpha=alpha,
        zorder=z,
        clip_on=False,
    )


def v_arrow(ax, x, y0, y1, color=LIGHT, lw=0.7):
    ax.annotate(
        "",
        xy=(x, y1),
        xytext=(x, y0),
        xycoords=ax.transAxes,
        textcoords=ax.transAxes,
        arrowprops=dict(
            arrowstyle="-|>",
            color=color,
            lw=lw,
            mutation_scale=7,
            shrinkA=1,
            shrinkB=1,
        ),
        zorder=3,
        clip_on=False,
    )


def h_arrow(ax, x0, x1, y, color=LIGHT, lw=0.7):
    ax.annotate(
        "",
        xy=(x1, y),
        xytext=(x0, y),
        xycoords=ax.transAxes,
        textcoords=ax.transAxes,
        arrowprops=dict(
            arrowstyle="-|>",
            color=color,
            lw=lw,
            mutation_scale=6,
            shrinkA=1,
            shrinkB=1,
        ),
        zorder=3,
        clip_on=False,
    )


# --- Icons -----------------------------------------------------------------
def icon_eye(ax, cx, cy, s=1.0, color=DARK, pupil=DBLUE):
    a = _aspect(ax)
    w, h = 0.055 * s / a, 0.032 * s
    theta = np.linspace(0, 2 * np.pi, 100)
    xs = cx + w * np.cos(theta)
    ys = cy + h * np.sin(theta)
    ax.plot(xs, ys, transform=ax.transAxes, color=color, lw=0.9, zorder=5, clip_on=False)
    ellipse(ax, cx, cy, 0.011 * s, facecolor=pupil, edgecolor="none", z=6)
    ellipse(ax, cx + 0.004 * s / a, cy + 0.004 * s, 0.0035 * s, facecolor=WHITE, edgecolor="none", z=7)


def icon_fixation(ax, cx, cy, s=1.0, color=DARK, lw=1.15):
    d = 0.022 * s
    a = _aspect(ax)
    line(ax, cx - d / a, cy, cx + d / a, cy, color=color, lw=lw, z=6)
    line(ax, cx, cy - d, cx, cy + d, color=color, lw=lw, z=6)


def icon_movie(ax, cx, cy, s=1.0):
    a = _aspect(ax)
    w, h = 0.070 * s / a, 0.048 * s
    ax.add_patch(
        Rectangle(
            (cx - w / 2, cy - h / 2),
            w, h,
            fill=False,
            edgecolor=DARK,
            linewidth=0.85,
            transform=ax.transAxes,
            zorder=5,
            clip_on=False,
        )
    )
    # sprockets
    for dx in (-0.024, -0.008, 0.008, 0.024):
        ax.add_patch(
            Rectangle(
                (cx + (dx * s) / a - 0.005 / a, cy + h / 2 - 0.002),
                0.010 / a,
                0.010 * s,
                facecolor=DARK,
                edgecolor="none",
                transform=ax.transAxes,
                zorder=6,
                clip_on=False,
            )
        )
    tri = Polygon(
        [
            (cx - 0.014 * s / a, cy - 0.014 * s),
            (cx - 0.014 * s / a, cy + 0.014 * s),
            (cx + 0.022 * s / a, cy),
        ],
        closed=True,
        facecolor=BLUE,
        edgecolor="none",
        transform=ax.transAxes,
        zorder=6,
        clip_on=False,
    )
    ax.add_patch(tri)


def icon_checker(ax, cx, cy, s=1.0):
    a = _aspect(ax)
    n = 4
    cell = 0.010 * s
    x0 = cx - (n * cell / a) / 2
    y0 = cy - (n * cell) / 2
    for i in range(n):
        for j in range(n):
            if (i + j) % 2 == 0:
                ax.add_patch(
                    Rectangle(
                        (x0 + i * cell / a, y0 + j * cell),
                        cell / a,
                        cell,
                        facecolor=DBLUE,
                        edgecolor="none",
                        transform=ax.transAxes,
                        zorder=5,
                        clip_on=False,
                    )
                )
    ax.add_patch(
        Rectangle(
            (x0, y0),
            n * cell / a,
            n * cell,
            fill=False,
            edgecolor=DARK,
            linewidth=0.55,
            transform=ax.transAxes,
            zorder=6,
            clip_on=False,
        )
    )


def icon_grating(ax, cx, cy, s=1.0):
    a = _aspect(ax)
    w, h = 0.040 * s / a, 0.034 * s
    x0, y0 = cx - w / 2, cy - h / 2
    ax.add_patch(
        Rectangle(
            (x0, y0), w, h,
            fill=False, edgecolor=DARK, linewidth=0.55,
            transform=ax.transAxes, zorder=6, clip_on=False,
        )
    )
    for i in range(5):
        xi = x0 + (i + 0.5) * w / 5
        line(ax, xi, y0 + 0.002, xi, y0 + h - 0.002, color=BLUE, lw=1.05, z=5)


def panel_letter(ax, letter: str):
    """Large bold panel label — no enclosing software-style card."""
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    txt(ax, 0.04, 0.96, letter, size=15, weight="bold", color=DBLUE, ha="left", va="top", z=20)


# ===========================================================================
# Panel A — Study overview (vertical protocol timeline)
# ===========================================================================
def draw_panel_a(ax):
    panel_letter(ax, "A")
    txt(ax, 0.12, 0.96, "Study overview", size=10, weight="bold", ha="left", va="top")
    txt(ax, 0.12, 0.915, "Complete session protocol", size=7.5, color=DARK, ha="left", va="top", alpha=0.65)

    # Grouped protocol: keep every acquisition as its own bar (user request),
    # but use a quiet ribbon + right labels for an illustrator look.
    steps = [
        ("Session 1", None, "session", None),
        ("Resting-state", 320, "rest", "task-rest"),
        ("Movie 1A", 210, "movie", None),
        ("Movie 2A", 210, "movie", None),
        ("Movie 1B", 210, "movie", None),
        ("Movie 2B", 210, "movie", None),
        ("Visual task 1", 226, "task", None),
        ("Visual task 2", 226, "task", None),
        ("Visual task 3", 226, "task", None),
        ("Visual task 4", 226, "task", None),
        ("Control ×3", 20, "ctrl", "task-control"),
        ("Structural MRI", None, "struct", None),
        ("Diffusion MRI", None, "dwi", None),
        ("Session 2", None, "session", "6-month follow-up"),
    ]

    top, bot = 0.875, 0.04
    n = len(steps)
    gap = 0.005
    usable = top - bot - gap * (n - 1)

    # Soft proportional heights (sqrt compression)
    weights = []
    for name, vol, kind, _ in steps:
        if kind == "session":
            weights.append(1.25)
        elif kind in ("struct", "dwi"):
            weights.append(1.15)
        elif kind == "ctrl":
            weights.append(0.70)
        else:
            weights.append(max(0.85, dur_min(vol) ** 0.5))
    heights = [usable * w / sum(weights) for w in weights]

    # Colour map
    face_of = {
        "session": WHITE,
        "rest": LIGHT,
        "movie": BLUE,
        "task": DBLUE,
        "ctrl": LIGHT,
        "struct": LIGHT,
        "dwi": LIGHT,
    }

    x_bar = 0.10
    max_w = 0.36
    max_dur = max(dur_min(v) for _, v, k, _ in steps if v is not None and k != "ctrl")
    spine_x = 0.045

    y = top
    centers = []
    for (name, vol, kind, extra), h in zip(steps, heights):
        y1 = y - h
        cy = 0.5 * (y + y1)
        centers.append(cy)

        if kind == "session":
            bar_w = max_w
            edge, lw = DBLUE, 1.05
        elif vol is not None and kind != "ctrl":
            bar_w = 0.16 + 0.20 * (dur_min(vol) / max_dur)
            edge, lw = DARK, 0.35
        elif kind == "ctrl":
            bar_w = 0.12
            edge, lw = DARK, 0.35
        else:
            bar_w = 0.28
            edge, lw = DARK, 0.35

        ax.add_patch(
            Rectangle(
                (x_bar, y1),
                bar_w,
                h,
                facecolor=face_of[kind],
                edgecolor=edge,
                linewidth=lw,
                transform=ax.transAxes,
                clip_on=False,
                zorder=2,
            )
        )

        lx = x_bar + max_w + 0.025
        if kind == "session":
            txt(ax, lx, cy, name, size=8, weight="bold", color=DBLUE, ha="left", va="center")
            if extra:
                txt(ax, lx, cy - 0.018, extra, size=6.2, color=DARK, ha="left", va="top", alpha=0.65)
        else:
            txt(
                ax, lx, cy + (0.006 if h > 0.035 else 0.0), name,
                size=7.0, weight="normal", ha="left",
                va="bottom" if h > 0.035 else "center",
            )
            if vol is not None:
                if kind == "ctrl":
                    sub = f"{vol} vol / run   ·   ~{dur_min(vol):.1f} min"
                else:
                    sub = f"{vol} vol   ·   ~{dur_min(vol):.1f} min"
            else:
                sub = "T1w / FLAIR / WMn" if kind == "struct" else "multi-shell DWI"
            if h > 0.035:
                txt(ax, lx, cy - 0.004, sub, size=6.0, ha="left", va="top", alpha=0.60)

        y = y1 - gap

    # Vertical flow spine with arrows between consecutive steps
    for i in range(len(centers) - 1):
        v_arrow(ax, spine_x, centers[i] - 0.012, centers[i + 1] + 0.012, color=LIGHT, lw=0.65)
    for cy, (_, _, kind, _) in zip(centers, steps):
        ellipse(
            ax, spine_x, cy, 0.006,
            facecolor=DBLUE if kind == "session" else LIGHT,
            edgecolor=DBLUE if kind == "session" else DARK,
            lw=0.4,
            z=4,
        )

    # Quiet colour key
    key_y = 0.015
    for i, (lab, col) in enumerate([("Rest / control", LIGHT), ("Movie", BLUE), ("Visual task", DBLUE)]):
        kx = 0.08 + i * 0.30
        ax.add_patch(
            Rectangle(
                (kx, key_y), 0.025, 0.014,
                facecolor=col, edgecolor=DARK, linewidth=0.3,
                transform=ax.transAxes, clip_on=False, zorder=5,
            )
        )
        txt(ax, kx + 0.035, key_y + 0.007, lab, size=5.8, ha="left", va="center", alpha=0.75)


# ===========================================================================
# Panel B — Resting-state
# ===========================================================================
def draw_panel_b(ax):
    panel_letter(ax, "B")
    txt(ax, 0.12, 0.96, "Resting-state", size=10, weight="bold", ha="left", va="top")
    txt(ax, 0.12, 0.915, "task-rest", size=7.5, style="italic", color=BLUE, ha="left", va="top")

    # Central viewing card
    card_x, card_w = 0.18, 0.64
    card_y, card_h = 0.38, 0.42
    ax.add_patch(
        Rectangle(
            (card_x, card_y),
            card_w,
            card_h,
            facecolor=LIGHT,
            edgecolor=DARK,
            linewidth=0.6,
            transform=ax.transAxes,
            clip_on=False,
            zorder=2,
        )
    )
    # white fixation
    icon_fixation(ax, 0.50, card_y + card_h * 0.55, s=1.6, color=WHITE, lw=1.6)
    txt(ax, 0.50, card_y + 0.06, "Grey field  ·  fixation", size=7.0, color=DARK, alpha=0.85)

    # Eye above card
    icon_eye(ax, 0.50, 0.88, s=1.35, color=DARK, pupil=DBLUE)
    v_arrow(ax, 0.50, 0.84, card_y + card_h + 0.01, color=LIGHT, lw=0.75)
    txt(ax, 0.50, 0.825, "Monocular fixation", size=7.2, va="top")

    # Annotations under card
    txt(ax, 0.50, 0.325, "Non-stimulated eye occluded", size=7.0, alpha=0.80)
    txt(ax, 0.50, 0.285, "No visual stimulation", size=7.0, alpha=0.80)

    # Metrics box
    ax.add_patch(
        Rectangle(
            (0.18, 0.08),
            0.64,
            0.15,
            facecolor=WHITE,
            edgecolor=DBLUE,
            linewidth=1.0,
            transform=ax.transAxes,
            clip_on=False,
            zorder=2,
        )
    )
    txt(ax, 0.50, 0.185, "320 BOLD volumes", size=9, weight="bold", color=DBLUE)
    txt(ax, 0.50, 0.125, "≈ 5.0 min    ·    1 run", size=7.5)


# ===========================================================================
# Panel C — Naturalistic movie
# ===========================================================================
def draw_panel_c(ax):
    panel_letter(ax, "C")
    txt(ax, 0.12, 0.96, "Naturalistic movie", size=10, weight="bold", ha="left", va="top")
    txt(ax, 0.12, 0.915, "task-movie", size=7.5, style="italic", color=BLUE, ha="left", va="top")

    movies = [
        ("Movie 1A", "Left", "L"),
        ("Movie 2A", "Right", "R"),
        ("Movie 1B", "Right", "R"),
        ("Movie 2B", "Left", "L"),
    ]

    left, right = 0.06, 0.94
    top, bot = 0.86, 0.34
    n = 4
    gap = 0.022
    bw = (right - left - gap * (n - 1)) / n
    cxs = []

    for i, (title, eye, code) in enumerate(movies):
        x0 = left + i * (bw + gap)
        cx = x0 + bw / 2
        cxs.append(cx)

        # Quiet column — hairline only, no filled header chrome
        ax.add_patch(
            Rectangle(
                (x0, bot),
                bw,
                top - bot,
                facecolor=WHITE,
                edgecolor=LIGHT,
                linewidth=0.7,
                transform=ax.transAxes,
                clip_on=False,
                zorder=2,
            )
        )
        # accent top rule
        ax.add_patch(
            Rectangle(
                (x0, top - 0.008),
                bw,
                0.008,
                facecolor=DBLUE if code == "L" else BLUE,
                edgecolor="none",
                transform=ax.transAxes,
                clip_on=False,
                zorder=3,
            )
        )

        txt(ax, cx, top - 0.055, title, size=7.2, weight="bold")
        icon_movie(ax, cx, 0.68, s=1.05)
        icon_fixation(ax, cx, 0.545, s=0.85, color=DARK, lw=1.0)
        txt(ax, cx, 0.490, "Fixation", size=6.0, alpha=0.70)
        txt(ax, cx, 0.425, "210 vol", size=7.5, weight="bold")
        txt(ax, cx, 0.375, "~3.3 min", size=6.5, alpha=0.70)

    # Eye alternation
    txt(ax, 0.50, 0.275, "Stimulated eye", size=7.5, weight="bold")
    ey = 0.155
    for i, (cx, (_, eye, code)) in enumerate(zip(cxs, movies)):
        icon_eye(ax, cx, ey + 0.025, s=0.85, pupil=DBLUE if code == "L" else BLUE)
        txt(ax, cx, ey - 0.055, f"{eye} eye", size=6.5, alpha=0.85)
        if i < n - 1:
            h_arrow(ax, cx + 0.055, cxs[i + 1] - 0.055, ey + 0.025, color=LIGHT, lw=0.7)


# ===========================================================================
# Panel D — Visual stimulation block design
# ===========================================================================
def draw_panel_d(ax):
    panel_letter(ax, "D")
    txt(ax, 0.12, 0.96, "Visual stimulation", size=10, weight="bold", ha="left", va="top")
    txt(ax, 0.12, 0.915, "task-fmri  ·  block design", size=7.5, style="italic", color=BLUE, ha="left", va="top")

    # Legend (top-right, compact)
    ax.add_patch(Rectangle((0.58, 0.875), 0.035, 0.028, facecolor=LIGHT, edgecolor=DARK, lw=0.35, transform=ax.transAxes, clip_on=False))
    txt(ax, 0.63, 0.889, "Baseline", size=6.5, ha="left")
    ax.add_patch(Rectangle((0.78, 0.875), 0.035, 0.028, facecolor=BLUE, edgecolor=DARK, lw=0.35, transform=ax.transAxes, clip_on=False))
    txt(ax, 0.83, 0.889, "Stimulus", size=6.5, ha="left")

    # True block-design timeline (schematic with correct ratios)
    # Show: 10 + 3×(8+10) + ellipsis + (8+10)  — annotated as ×12 cycles
    y0, yh = 0.68, 0.09
    x0, x1 = 0.07, 0.93
    span = x1 - x0

    units = [
        ("B", 10, "Baseline\n10 TR"),
        ("S", 8, "Stim\n8 TR"),
        ("B", 10, "Base\n10 TR"),
        ("S", 8, None),
        ("B", 10, None),
        ("S", 8, None),
        ("B", 10, None),
        ("E", 5, None),   # ellipsis spacer
        ("S", 8, None),
        ("B", 10, None),
    ]
    tot = sum(u for _, u, _ in units)

    x = x0
    nlab = 0
    # Track first cycle bounds for bracket
    cycle_x0 = cycle_x1 = None
    u_acc = 0
    for kind, u, lab in units:
        w = span * u / tot
        if kind == "E":
            txt(ax, x + w / 2, y0 + yh / 2, "···", size=12, color=DARK, alpha=0.7)
        else:
            face = LIGHT if kind == "B" else BLUE
            ax.add_patch(
                Rectangle(
                    (x, y0), w, yh,
                    facecolor=face, edgecolor=DARK, linewidth=0.35,
                    transform=ax.transAxes, clip_on=False, zorder=2,
                )
            )
            if lab is not None and nlab < 3:
                txt(
                    ax, x + w / 2, y0 + yh / 2, lab,
                    size=5.6, color=DARK if kind == "B" else WHITE,
                )
                nlab += 1
            # first cycle = first S+B after initial baseline
            if u_acc == 10:
                cycle_x0 = x
            if u_acc == 10 + 8 + 10:
                cycle_x1 = x
        u_acc += u
        x += w

    if cycle_x0 is not None and cycle_x1 is not None:
        by = y0 + yh + 0.03
        ax.annotate(
            "",
            xy=(cycle_x1, by),
            xytext=(cycle_x0, by),
            xycoords=ax.transAxes,
            textcoords=ax.transAxes,
            arrowprops=dict(arrowstyle="<->", color=DARK, lw=0.65, mutation_scale=6),
            clip_on=False,
        )
        txt(ax, 0.5 * (cycle_x0 + cycle_x1), by + 0.022, "1 cycle  (×12)", size=6.5)

    # Axis
    line(ax, x0, y0 - 0.02, x1, y0 - 0.02, color=DARK, lw=0.55)
    txt(ax, x0, y0 - 0.04, "0", size=6.0, ha="center", va="top")
    txt(ax, x1, y0 - 0.04, "226 TR", size=6.0, ha="right", va="top")
    txt(ax, 0.50, y0 - 0.075, "One run  ·  226 volumes  ·  ≈ 3.5 min  ·  4 runs / session", size=6.8, alpha=0.85)

    # Stimulus conditions
    txt(ax, 0.07, 0.48, "Stimulus conditions", size=8, weight="bold", ha="left")
    stim_y = 0.385
    s0, s1 = 0.07, 0.93
    n_stim = 12
    sg = 0.006
    sw = (s1 - s0 - sg * (n_stim - 1)) / n_stim
    for i in range(n_stim):
        sx = s0 + i * (sw + sg)
        face = BLUE if i % 2 == 0 else DBLUE
        ax.add_patch(
            Rectangle(
                (sx, stim_y - 0.028), sw, 0.056,
                facecolor=face, edgecolor="none",
                transform=ax.transAxes, clip_on=False, zorder=2,
            )
        )
        txt(ax, sx + sw / 2, stim_y, f"{i + 1:02d}", size=5.5, color=WHITE, weight="bold")
    txt(ax, 0.50, stim_y - 0.055, "stim-01  ···  stim-12", size=6.5, alpha=0.70)

    # Condition-family legend
    txt(ax, 0.07, 0.24, "Condition families", size=7.5, weight="bold", ha="left")

    ax.add_patch(
        Rectangle(
            (0.07, 0.10), 0.22, 0.08,
            facecolor=LIGHT, edgecolor="none",
            transform=ax.transAxes, clip_on=False,
        )
    )
    txt(ax, 0.18, 0.14, "Magno / Parvo", size=6.5)

    icon_checker(ax, 0.40, 0.14, s=1.0)
    txt(ax, 0.46, 0.14, "Checkerboard", size=6.5, ha="left")

    icon_grating(ax, 0.72, 0.14, s=1.0)
    txt(ax, 0.78, 0.14, "Grating", size=6.5, ha="left")

    txt(ax, 0.50, 0.045, "Order randomised across subjects", size=6.5, style="italic", alpha=0.65)


# ===========================================================================
# Figure chrome
# ===========================================================================
def draw_footer(fig):
    # Shared sequence note
    fig.text(
        0.02,
        0.038,
        "Shared BOLD EPI:   TR 937 ms  ·  TE 37 ms  ·  FA 52°  ·  2 mm isotropic  ·  MB 8",
        transform=fig.transFigure,
        ha="left",
        va="center",
        fontproperties=FontProperties(family=FONT_NAME, size=6.8),
        color=DARK,
        alpha=0.70,
        zorder=30,
    )

    # Info box — lower right
    box = Rectangle(
        (0.70, 0.012),
        0.28,
        0.078,
        facecolor=WHITE,
        edgecolor=LIGHT,
        linewidth=0.8,
        transform=fig.transFigure,
        clip_on=False,
        zorder=30,
    )
    fig.patches.append(box)
    facts = [
        "84 participants",
        "2 sessions",
        "12 BOLD runs / complete protocol",
        "~3,300 functional volumes",
    ]
    for i, line in enumerate(facts):
        fig.text(
            0.715,
            0.078 - i * 0.016,
            "·  " + line,
            transform=fig.transFigure,
            ha="left",
            va="top",
            fontproperties=FontProperties(family=FONT_NAME, size=6.5),
            color=DARK,
            zorder=31,
        )


def build_figure() -> plt.Figure:
    fig = plt.figure(figsize=(FIG_W, FIG_H), facecolor=WHITE)

    # Force a draw so window extents (for circular icons) are valid
    fig.canvas.draw()

    gs = GridSpec(
        1,
        4,
        figure=fig,
        left=0.018,
        right=0.985,
        top=0.955,
        bottom=0.115,
        wspace=0.055,
        width_ratios=[1.08, 0.88, 1.12, 1.12],
    )

    axes = [fig.add_subplot(gs[0, i]) for i in range(4)]
    for ax in axes:
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.axis("off")

    # Draw once so transforms resolve, then draw panels
    fig.canvas.draw()

    draw_panel_a(axes[0])
    draw_panel_b(axes[1])
    draw_panel_c(axes[2])
    draw_panel_d(axes[3])
    draw_footer(fig)

    return fig


def verify_layout(fig: plt.Figure) -> None:
    axes = fig.axes
    assert len(axes) == 4, f"Expected 4 panels, found {len(axes)}"
    pos = [ax.get_position() for ax in axes]
    tops = {round(p.y1, 5) for p in pos}
    bots = {round(p.y0, 5) for p in pos}
    assert len(tops) == 1, f"Panel tops misaligned: {tops}"
    assert len(bots) == 1, f"Panel bottoms misaligned: {bots}"
    gaps = [pos[i + 1].x0 - pos[i].x1 for i in range(3)]
    assert max(gaps) - min(gaps) < 0.012, f"Uneven gaps: {gaps}"
    for i in range(3):
        assert pos[i].x0 < pos[i + 1].x0
    print(f"OK  panels aligned; gaps={[round(g, 4) for g in gaps]}")


def export(fig: plt.Figure) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    # Re-draw so icon aspect corrections use final layout
    fig.canvas.draw()
    for ext in ("svg", "pdf", "png"):
        path = OUT_DIR / f"{STEM}.{ext}"
        kw = dict(
            format=ext,
            bbox_inches="tight",
            pad_inches=0.10,
            facecolor=WHITE,
            edgecolor="none",
        )
        if ext == "png":
            kw["dpi"] = DPI_PNG
        fig.savefig(path, **kw)
        print(f"Wrote {path} ({path.stat().st_size:,} bytes)")


def main() -> None:
    fig = build_figure()
    verify_layout(fig)
    export(fig)
    plt.close(fig)
    print("Done.")


if __name__ == "__main__":
    main()
