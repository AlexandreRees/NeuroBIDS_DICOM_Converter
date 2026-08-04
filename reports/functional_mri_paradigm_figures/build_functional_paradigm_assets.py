#!/usr/bin/env python3
"""Build publication tables/figures for Functional MRI paradigms (Scientific Data).

Outputs (this directory):
  Table1_Functional_paradigm_summary.{md,tex,pdf,png,docx}
  Table2_Movie_run_eye_assignment.{md,tex,pdf,png,docx}
  Figure1_task_fmri_block_design.{svg,pdf,png}
  Figure2_functional_paradigm_overview.{svg,pdf,png}
  captions.md
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, Rectangle
from matplotlib.lines import Line2D

OUT = Path(__file__).resolve().parent
TR_MS = 937


def _duration_min(volumes: int) -> str:
    minutes = volumes * TR_MS / 1000.0 / 60.0
    return f"{minutes:.1f}"


def write_markdown(path: Path, title: str, caption: str, headers: list[str], rows: list[list[str]]) -> None:
    lines = [f"# {title}", "", caption, "", "| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(row) + " |")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def write_latex_table(
    path: Path,
    caption: str,
    headers: list[str],
    rows: list[list[str]],
    col_spec: str,
) -> None:
    header_cells = " & ".join(rf"\textcolor{{headergray}}{{\textbf{{{h}}}}}" for h in headers) + r" \\"
    body = []
    for i, row in enumerate(rows):
        cells = []
        for j, cell in enumerate(row):
            text = cell.replace("_", r"\_").replace("→", r"$\rightarrow$")
            if j == 0 or (headers[j].lower().startswith("bids") if j < len(headers) else False):
                # monospace for BIDS labels / first column task labels when they look like code
                if cell.startswith("task-") or cell.startswith("Movie") or cell.startswith("run"):
                    text = rf"{{\ttfamily\footnotesize {text}}}"
                elif cell.startswith("`"):
                    text = rf"{{\ttfamily\footnotesize {text.strip('`')}}}"
            cells.append(text)
        row_tex = " & ".join(cells) + r" \\"
        if i % 2 == 1:
            row_tex = r"\rowcolor{tablealt} " + row_tex
        body.append(row_tex)

    tex = rf"""\documentclass[11pt]{{article}}
\usepackage[margin=18mm,paperwidth=210mm,paperheight=297mm]{{geometry}}
\usepackage{{booktabs}}
\usepackage{{tabularx}}
\usepackage{{array}}
\usepackage[table]{{xcolor}}
\usepackage{{caption}}
\usepackage{{microtype}}
\usepackage[T1]{{fontenc}}
\usepackage{{lmodern}}

\definecolor{{tablealt}}{{RGB}}{{245,247,250}}
\definecolor{{headergray}}{{RGB}}{{55,65,81}}
\captionsetup{{font=small,labelfont=bf,skip=8pt,justification=centering}}

\newcolumntype{{L}}[1]{{>{{\raggedright\arraybackslash}}p{{#1}}}}
\newcolumntype{{Y}}{{>{{\raggedright\arraybackslash}}X}}
\newcolumntype{{C}}[1]{{>{{\centering\arraybackslash}}p{{#1}}}}

\begin{{document}}
\pagestyle{{empty}}
\vspace*{{0pt}}
\begin{{center}}
\setlength{{\tabcolsep}}{{5pt}}
\renewcommand{{\arraystretch}}{{1.30}}
\begin{{minipage}}{{0.98\textwidth}}
\captionof{{table}}{{{caption}}}
\centering
\begin{{tabularx}}{{\textwidth}}{{{col_spec}}}
\toprule
{header_cells}
\midrule
{chr(10).join(body)}
\bottomrule
\end{{tabularx}}
\end{{minipage}}
\end{{center}}
\end{{document}}
"""
    path.write_text(tex, encoding="utf-8")


def write_docx_via_pandoc(md_path: Path, docx_path: Path) -> None:
    subprocess.run(
        ["pandoc", str(md_path), "-o", str(docx_path), "--from", "markdown", "--to", "docx"],
        check=True,
    )


def compile_pdf(tex_path: Path, pdf_path: Path) -> None:
    work = tex_path.parent
    for _ in range(2):
        proc = subprocess.run(
            ["pdflatex", "-interaction=nonstopmode", tex_path.name],
            cwd=work,
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0 and "Output written on" not in (proc.stdout + proc.stderr):
            raise RuntimeError(proc.stdout[-2000:] + "\n" + proc.stderr[-1000:])
    produced = work / (tex_path.stem + ".pdf")
    if produced.resolve() != pdf_path.resolve():
        pdf_path.write_bytes(produced.read_bytes())
    for ext in (".aux", ".log", ".out"):
        aux = work / (tex_path.stem + ext)
        if aux.exists():
            aux.unlink()


def render_png_from_pdf(pdf_path: Path, png_path: Path) -> None:
    subprocess.run(
        [
            "magick",
            "-density",
            "300",
            str(pdf_path) + "[0]",
            "-background",
            "white",
            "-alpha",
            "remove",
            "-alpha",
            "off",
            "-colorspace",
            "sRGB",
            "-depth",
            "8",
            "-trim",
            "+repage",
            "-quality",
            "100",
            str(png_path),
        ],
        check=True,
    )


def build_summary_table() -> None:
    caption = (
        "Functional MRI paradigm summary. All BOLD runs share TR 937 ms, TE 37 ms, "
        "flip angle 52$^{\\circ}$, 2 mm isotropic voxels, and multiband acceleration factor 8. "
        "Durations are approximate (volumes $\\times$ TR). Stimulation was monocular; "
        "the non-stimulated eye was occluded."
    )
    headers = ["BIDS task", "Description", "Runs/session", "Volumes/run", "Duration (min)"]
    rows = [
        ["`task-rest`", "Fixation-only monocular resting-state", "1", "320", _duration_min(320)],
        ["`task-movie`", "Naturalistic movie segments with fixation overlay", "4", "210", _duration_min(210)],
        ["`task-fmri`", "Block-design grating/checkerboard stimulation", "4", "226", _duration_min(226)],
        ["`task-control`", "Short control EPI acquisitions", "3", "20", _duration_min(20)],
    ]
    stem = OUT / "Table1_Functional_paradigm_summary"
    # Markdown uses plain text duration note
    md_caption = (
        "Functional MRI paradigm summary. All BOLD runs share TR 937 ms, TE 37 ms, "
        "flip angle 52°, 2 mm isotropic voxels, and multiband acceleration factor 8. "
        "Durations are approximate (volumes × TR). Stimulation was monocular; "
        "the non-stimulated eye was occluded."
    )
    write_markdown(stem.with_suffix(".md"), "Functional paradigm summary", md_caption, headers, rows)
    # LaTeX rows without backticks
    latex_rows = [
        [r"{\ttfamily task-rest}", "Fixation-only monocular resting-state", "1", "320", _duration_min(320)],
        [r"{\ttfamily task-movie}", "Naturalistic movie segments with fixation overlay", "4", "210", _duration_min(210)],
        [r"{\ttfamily task-fmri}", "Block-design grating/checkerboard stimulation", "4", "226", _duration_min(226)],
        [r"{\ttfamily task-control}", "Short control EPI acquisitions", "3", "20", _duration_min(20)],
    ]
    write_latex_table(
        stem.with_suffix(".tex"),
        caption,
        headers,
        latex_rows,
        r"@{}L{2.6cm}Y C{2.2cm} C{2.2cm} C{2.4cm}@{}",
    )
    # Fix LaTeX writer double-escaping: write a dedicated clean tex
    tex = rf"""\documentclass[11pt]{{article}}
\usepackage[margin=18mm,paperwidth=210mm,paperheight=297mm]{{geometry}}
\usepackage{{booktabs}}
\usepackage{{tabularx}}
\usepackage{{array}}
\usepackage[table]{{xcolor}}
\usepackage{{caption}}
\usepackage{{microtype}}
\usepackage[T1]{{fontenc}}
\usepackage{{lmodern}}

\definecolor{{tablealt}}{{RGB}}{{245,247,250}}
\definecolor{{headergray}}{{RGB}}{{55,65,81}}
\captionsetup{{font=small,labelfont=bf,skip=8pt,justification=centering}}

\newcolumntype{{L}}[1]{{>{{\raggedright\arraybackslash}}p{{#1}}}}
\newcolumntype{{Y}}{{>{{\raggedright\arraybackslash}}X}}
\newcolumntype{{C}}[1]{{>{{\centering\arraybackslash}}p{{#1}}}}

\begin{{document}}
\pagestyle{{empty}}
\vspace*{{0pt}}
\begin{{center}}
\setlength{{\tabcolsep}}{{5pt}}
\renewcommand{{\arraystretch}}{{1.30}}
\begin{{minipage}}{{0.98\textwidth}}
\captionof{{table}}{{{caption}}}
\centering
\begin{{tabularx}}{{\textwidth}}{{@{{}}L{{2.6cm}}Y C{{2.2cm}} C{{2.2cm}} C{{2.4cm}}@{{}}}}
\toprule
\textcolor{{headergray}}{{\textbf{{BIDS task}}}} &
\textcolor{{headergray}}{{\textbf{{Description}}}} &
\textcolor{{headergray}}{{\textbf{{Runs/session}}}} &
\textcolor{{headergray}}{{\textbf{{Volumes/run}}}} &
\textcolor{{headergray}}{{\textbf{{Duration (min)}}}} \\
\midrule
{{\ttfamily task-rest}} & Fixation-only monocular resting-state & 1 & 320 & {_duration_min(320)} \\
\rowcolor{{tablealt}} {{\ttfamily task-movie}} & Naturalistic movie segments with fixation overlay & 4 & 210 & {_duration_min(210)} \\
{{\ttfamily task-fmri}} & Block-design grating/checkerboard stimulation & 4 & 226 & {_duration_min(226)} \\
\rowcolor{{tablealt}} {{\ttfamily task-control}} & Short control EPI acquisitions & 3 & 20 & {_duration_min(20)} \\
\bottomrule
\end{{tabularx}}
\end{{minipage}}
\end{{center}}
\end{{document}}
"""
    stem.with_suffix(".tex").write_text(tex, encoding="utf-8")
    write_docx_via_pandoc(stem.with_suffix(".md"), stem.with_suffix(".docx"))
    compile_pdf(stem.with_suffix(".tex"), stem.with_suffix(".pdf"))
    render_png_from_pdf(stem.with_suffix(".pdf"), stem.with_suffix(".png"))


def build_movie_table() -> None:
    caption = (
        "Monocular movie-run assignment for {\\ttfamily task-movie}. "
        "Each run presented one movie segment with a fixation overlay. "
        "Left- or right-eye stimulation was assigned by run; the contralateral eye was occluded. "
        "Stimulus timing files are not included in the public release."
    )
    md_caption = (
        "Monocular movie-run assignment for `task-movie`. "
        "Each run presented one movie segment with a fixation overlay. "
        "Left- or right-eye stimulation was assigned by run; the contralateral eye was occluded. "
        "Stimulus timing files are not included in the public release."
    )
    headers = ["BIDS run", "Movie segment", "Stimulated eye", "Volumes", "Duration (min)"]
    rows = [
        ["run-01", "Movie1A", "Left", "210", _duration_min(210)],
        ["run-02", "Movie2A", "Right", "210", _duration_min(210)],
        ["run-03", "Movie1B", "Right", "210", _duration_min(210)],
        ["run-04", "Movie2B", "Left", "210", _duration_min(210)],
    ]
    stem = OUT / "Table2_Movie_run_eye_assignment"
    write_markdown(stem.with_suffix(".md"), "Movie run eye assignment", md_caption, headers, rows)
    tex = rf"""\documentclass[11pt]{{article}}
\usepackage[margin=18mm,paperwidth=210mm,paperheight=297mm]{{geometry}}
\usepackage{{booktabs}}
\usepackage{{tabularx}}
\usepackage{{array}}
\usepackage[table]{{xcolor}}
\usepackage{{caption}}
\usepackage{{microtype}}
\usepackage[T1]{{fontenc}}
\usepackage{{lmodern}}

\definecolor{{tablealt}}{{RGB}}{{245,247,250}}
\definecolor{{headergray}}{{RGB}}{{55,65,81}}
\captionsetup{{font=small,labelfont=bf,skip=8pt,justification=centering}}

\newcolumntype{{L}}[1]{{>{{\raggedright\arraybackslash}}p{{#1}}}}
\newcolumntype{{Y}}{{>{{\raggedright\arraybackslash}}X}}
\newcolumntype{{C}}[1]{{>{{\centering\arraybackslash}}p{{#1}}}}

\begin{{document}}
\pagestyle{{empty}}
\vspace*{{0pt}}
\begin{{center}}
\setlength{{\tabcolsep}}{{6pt}}
\renewcommand{{\arraystretch}}{{1.30}}
\begin{{minipage}}{{0.92\textwidth}}
\captionof{{table}}{{{caption}}}
\centering
\begin{{tabularx}}{{\textwidth}}{{@{{}}C{{2.4cm}} Y C{{3.0cm}} C{{2.2cm}} C{{2.6cm}}@{{}}}}
\toprule
\textcolor{{headergray}}{{\textbf{{BIDS run}}}} &
\textcolor{{headergray}}{{\textbf{{Movie segment}}}} &
\textcolor{{headergray}}{{\textbf{{Stimulated eye}}}} &
\textcolor{{headergray}}{{\textbf{{Volumes}}}} &
\textcolor{{headergray}}{{\textbf{{Duration (min)}}}} \\
\midrule
{{\ttfamily run-01}} & Movie1A & Left & 210 & {_duration_min(210)} \\
\rowcolor{{tablealt}} {{\ttfamily run-02}} & Movie2A & Right & 210 & {_duration_min(210)} \\
{{\ttfamily run-03}} & Movie1B & Right & 210 & {_duration_min(210)} \\
\rowcolor{{tablealt}} {{\ttfamily run-04}} & Movie2B & Left & 210 & {_duration_min(210)} \\
\bottomrule
\end{{tabularx}}
\end{{minipage}}
\end{{center}}
\end{{document}}
"""
    stem.with_suffix(".tex").write_text(tex, encoding="utf-8")
    write_docx_via_pandoc(stem.with_suffix(".md"), stem.with_suffix(".docx"))
    compile_pdf(stem.with_suffix(".tex"), stem.with_suffix(".pdf"))
    render_png_from_pdf(stem.with_suffix(".pdf"), stem.with_suffix(".png"))


def _save_fig(fig: plt.Figure, stem: Path) -> None:
    for ext in (".svg", ".pdf", ".png"):
        fig.savefig(
            stem.with_suffix(ext),
            bbox_inches="tight",
            pad_inches=0.15,
            dpi=300 if ext == ".png" else None,
            facecolor="white",
        )
    plt.close(fig)


def build_block_design_figure() -> None:
    """Timeline for one task-fmri run: 10 TR baseline + 12×(8 stim + 10 baseline)."""
    first_baseline = 10
    stim = 8
    baseline = 10
    n_cycles = 12
    total = first_baseline + n_cycles * (stim + baseline)  # 226

    fig, ax = plt.subplots(figsize=(11.5, 3.6))
    ax.set_xlim(0, total)
    ax.set_ylim(0, 1.55)
    ax.axis("off")

    # Colors: restrained scientific palette (teal / slate), not purple gradient
    col_baseline = "#D6DEE8"
    col_stim = "#2F6F8F"
    edge = "#334155"

    def add_block(x0: float, width: float, color: str, label: str | None = None, y0: float = 0.55, h: float = 0.55):
        rect = Rectangle((x0, y0), width, h, facecolor=color, edgecolor=edge, linewidth=0.6)
        ax.add_patch(rect)
        if label and width >= 7:
            ax.text(
                x0 + width / 2,
                y0 + h / 2,
                label,
                ha="center",
                va="center",
                fontsize=8,
                color="white" if color == col_stim else "#1E293B",
                fontweight="medium",
            )

    # Initial baseline
    add_block(0, first_baseline, col_baseline, "Baseline\n10 TR")
    x = first_baseline
    for i in range(n_cycles):
        add_block(x, stim, col_stim, "Stim" if i in (0, 1, 2, 11) else None)
        x += stim
        # Only label a few baselines to avoid clutter
        bl_label = "Base" if i in (0, 1) else None
        add_block(x, baseline, col_baseline, bl_label)
        x += baseline

    # Bracket / cycle annotation above first full cycle
    cycle_start = first_baseline
    cycle_end = first_baseline + stim + baseline
    y_br = 1.22
    ax.annotate(
        "",
        xy=(cycle_start, y_br),
        xytext=(cycle_end, y_br),
        arrowprops=dict(arrowstyle="<->", color="#475569", lw=1.1),
    )
    ax.text(
        (cycle_start + cycle_end) / 2,
        y_br + 0.08,
        "1 cycle = 8 TR stimulus + 10 TR baseline  (×12)",
        ha="center",
        va="bottom",
        fontsize=9,
        color="#334155",
    )

    # Axis line and ticks
    ax.plot([0, total], [0.42, 0.42], color="#64748B", lw=1.0, solid_capstyle="butt")
    for tick, lab in [(0, "0"), (first_baseline, "10"), (total // 2, str(total // 2)), (total, "226")]:
        ax.plot([tick, tick], [0.38, 0.42], color="#64748B", lw=1.0)
        ax.text(tick, 0.28, lab, ha="center", va="top", fontsize=8, color="#475569")
    ax.text(total / 2, 0.08, "Volume / TR index (TR = 937 ms; run ≈ 3.5 min)", ha="center", va="top", fontsize=9, color="#334155")

    ax.text(
        0,
        1.48,
        r"task-fmri block design (one run)",
        fontsize=12,
        fontweight="bold",
        color="#0F172A",
        ha="left",
        va="top",
    )
    ax.text(
        0,
        1.34,
        "Initial baseline (10 TR) → 12 stimulus/baseline cycles → 226 volumes total",
        fontsize=9,
        color="#475569",
        ha="left",
        va="top",
    )

    legend = [
        Line2D([0], [0], color=col_stim, lw=8, label="Stimulus (grating / checkerboard)"),
        Line2D([0], [0], color=col_baseline, lw=8, label="Baseline / fixation"),
    ]
    ax.legend(handles=legend, loc="lower right", frameon=False, fontsize=8, bbox_to_anchor=(1.0, 0.55))

    _save_fig(fig, OUT / "Figure1_task_fmri_block_design")


def build_overview_figure() -> None:
    """Four-panel schematic of the functional paradigms."""
    fig, axes = plt.subplots(2, 2, figsize=(11.2, 6.8))
    fig.subplots_adjust(hspace=0.42, wspace=0.28, left=0.06, right=0.98, top=0.90, bottom=0.06)

    slate = "#0F172A"
    muted = "#475569"
    teal = "#2F6F8F"
    soft = "#E8EEF3"
    accent = "#B45309"  # restrained amber for “stim on”

    # --- panel A: rest ---
    ax = axes[0, 0]
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 6)
    ax.axis("off")
    ax.add_patch(FancyBboxPatch((0.4, 0.6), 9.2, 4.6, boxstyle="round,pad=0.05,rounding_size=0.15", facecolor=soft, edgecolor="#94A3B8", linewidth=1))
    # fixation cross on gray
    ax.add_patch(Rectangle((2.2, 1.5), 5.6, 3.0, facecolor="#C5CBD3", edgecolor="#64748B", lw=0.8))
    ax.plot([5.0, 5.0], [2.7, 3.3], color="white", lw=2.2)
    ax.plot([4.7, 5.3], [3.0, 3.0], color="white", lw=2.2)
    ax.text(0.6, 5.55, "A  task-rest", fontsize=11, fontweight="bold", color=slate, va="top")
    ax.text(0.6, 5.15, "1 run · 320 volumes · ~5.0 min", fontsize=8.5, color=muted, va="top")
    ax.text(5.0, 1.15, "Monocular fixation (no stimulus blocks)", ha="center", fontsize=8, color=muted)

    # --- panel B: movie ---
    ax = axes[0, 1]
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 6)
    ax.axis("off")
    ax.add_patch(FancyBboxPatch((0.4, 0.6), 9.2, 4.6, boxstyle="round,pad=0.05,rounding_size=0.15", facecolor=soft, edgecolor="#94A3B8", linewidth=1))
    ax.text(0.6, 5.55, "B  task-movie", fontsize=11, fontweight="bold", color=slate, va="top")
    ax.text(0.6, 5.15, "4 runs · 210 volumes each · ~3.3 min", fontsize=8.5, color=muted, va="top")
    # four run chips
    mapping = [
        ("run-01", "Movie1A", "L"),
        ("run-02", "Movie2A", "R"),
        ("run-03", "Movie1B", "R"),
        ("run-04", "Movie2B", "L"),
    ]
    for i, (run, mov, eye) in enumerate(mapping):
        y = 4.15 - i * 0.85
        ax.add_patch(FancyBboxPatch((1.0, y - 0.35), 8.0, 0.7, boxstyle="round,pad=0.02,rounding_size=0.08", facecolor="white", edgecolor="#94A3B8", lw=0.8))
        ax.text(1.3, y, run, fontsize=8, fontfamily="monospace", color=teal, va="center", fontweight="bold")
        ax.text(4.0, y, mov, fontsize=8.5, color=slate, va="center")
        ax.text(8.4, y, f"{eye} eye", fontsize=8, color=muted, va="center", ha="right")
    ax.text(5.0, 0.85, "Fixation overlay during playback", ha="center", fontsize=8, color=muted)

    # --- panel C: task-fmri ---
    ax = axes[1, 0]
    ax.set_xlim(0, 30)
    ax.set_ylim(0, 6)
    ax.axis("off")
    ax.add_patch(FancyBboxPatch((0.5, 0.6), 29.0, 4.6, boxstyle="round,pad=0.05,rounding_size=0.25", facecolor=soft, edgecolor="#94A3B8", linewidth=1))
    ax.text(0.9, 5.55, "C  task-fmri", fontsize=11, fontweight="bold", color=slate, va="top")
    ax.text(0.9, 5.15, "4 runs · 226 volumes · ~3.5 min · 12 stim conditions", fontsize=8.5, color=muted, va="top")
    # mini timeline
    x = 1.5
    ax.add_patch(Rectangle((x, 2.2), 2.2, 1.4, facecolor="#D6DEE8", edgecolor="#64748B", lw=0.6))
    ax.text(x + 1.1, 2.9, "10\nTR", ha="center", va="center", fontsize=7, color=slate)
    x += 2.4
    for i in range(4):
        ax.add_patch(Rectangle((x, 2.2), 1.6, 1.4, facecolor=teal, edgecolor="#1E3A4A", lw=0.5))
        ax.text(x + 0.8, 2.9, "8", ha="center", va="center", fontsize=7, color="white")
        x += 1.7
        ax.add_patch(Rectangle((x, 2.2), 2.0, 1.4, facecolor="#D6DEE8", edgecolor="#64748B", lw=0.5))
        ax.text(x + 1.0, 2.9, "10", ha="center", va="center", fontsize=7, color=slate)
        x += 2.2
    ax.text(x + 0.3, 2.9, "… ×12", fontsize=9, color=muted, va="center")
    ax.text(15, 1.55, "Block design locked to scanner TR (stimuli stim-01 … stim-12)", ha="center", fontsize=8, color=muted)
    ax.text(15, 1.05, "Stimulus order randomised across subjects", ha="center", fontsize=8, color=muted)

    # --- panel D: control ---
    ax = axes[1, 1]
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 6)
    ax.axis("off")
    ax.add_patch(FancyBboxPatch((0.4, 0.6), 9.2, 4.6, boxstyle="round,pad=0.05,rounding_size=0.15", facecolor=soft, edgecolor="#94A3B8", linewidth=1))
    ax.text(0.6, 5.55, "D  task-control", fontsize=11, fontweight="bold", color=slate, va="top")
    ax.text(0.6, 5.15, "3 runs · 20 volumes each · ~0.3 min", fontsize=8.5, color=muted, va="top")
    for i, label in enumerate(["run-01", "run-02", "run-03"]):
        x0 = 1.2 + i * 2.8
        ax.add_patch(FancyBboxPatch((x0, 2.0), 2.4, 2.0, boxstyle="round,pad=0.02,rounding_size=0.1", facecolor="white", edgecolor="#94A3B8", lw=0.9))
        ax.text(x0 + 1.2, 3.2, label, ha="center", fontsize=8, fontfamily="monospace", color=teal, fontweight="bold")
        ax.text(x0 + 1.2, 2.5, "20 vol", ha="center", fontsize=8.5, color=slate)
    ax.text(5.0, 1.15, "Stimulus content not fully documented", ha="center", fontsize=8, color=accent)

    fig.suptitle(
        "Functional MRI paradigms (monocular BOLD)",
        fontsize=13,
        fontweight="bold",
        color=slate,
        y=0.97,
    )
    fig.text(
        0.5,
        0.925,
        "Shared EPI: TR 937 ms · TE 37 ms · FA 52° · 2 mm isotropic · MB 8",
        ha="center",
        fontsize=9,
        color=muted,
    )

    _save_fig(fig, OUT / "Figure2_functional_paradigm_overview")


def write_captions() -> None:
    text = """# Captions — Functional MRI paradigm assets

**Provenance:** Methods draft section *Functional MRI paradigms*; `reports/functional_mri_paradigm_report.md`; MRI acquisition table.

## Table 1. Functional paradigm summary

`Table1_Functional_paradigm_summary.png` (also `.pdf`, `.tex`, `.md`, `.docx`)

**Caption.** Functional MRI paradigm summary. All BOLD runs share TR 937 ms, TE 37 ms, flip angle 52°, 2 mm isotropic voxels, and multiband acceleration factor 8. Durations are approximate (volumes × TR). Stimulation was monocular; the non-stimulated eye was occluded.

## Table 2. Movie run eye assignment

`Table2_Movie_run_eye_assignment.png` (also `.pdf`, `.tex`, `.md`, `.docx`)

**Caption.** Monocular movie-run assignment for `task-movie`. Each run presented one movie segment with a fixation overlay. Left- or right-eye stimulation was assigned by run; the contralateral eye was occluded. Stimulus timing files are not included in the public release.

## Figure 1. Block-design timeline (`task-fmri`)

`Figure1_task_fmri_block_design.png` (also `.svg`, `.pdf`)

**Caption.** Block-design structure of one `task-fmri` run. After an initial 10-TR baseline, 12 cycles of 8-TR stimulus presentation and 10-TR baseline were acquired (226 volumes; TR = 937 ms). Twelve stimulus conditions (`stim-01`–`stim-12`) encompassed magnocellular and parvocellular grating and checkerboard variants; stimulus order was randomised across subjects.

## Figure 2. Paradigm overview

`Figure2_functional_paradigm_overview.png` (also `.svg`, `.pdf`)

**Caption.** Overview of the four complementary BOLD paradigms released under BIDS task labels `task-rest`, `task-movie`, `task-fmri`, and `task-control`. All runs used monocular stimulation with the non-stimulated eye occluded. Panel A: fixation-only resting-state. Panel B: naturalistic movie runs with eye assignment by run. Panel C: TR-locked block-design visual stimulation. Panel D: short control EPI acquisitions (stimulus content not fully documented).

## Suggested placement in Methods

Place **Table 1** immediately after the introductory paragraph of *Functional MRI paradigms*.  
Place **Figure 1** (and optionally **Table 2**) with the `task-fmri` / `task-movie` subsections.  
**Figure 2** can replace or precede the prose overview if a single visual summary is preferred.
"""
    (OUT / "captions.md").write_text(text, encoding="utf-8")


def main() -> None:
    build_summary_table()
    build_movie_table()
    build_block_design_figure()
    build_overview_figure()
    write_captions()
    print(f"Wrote assets to {OUT}")
    for p in sorted(OUT.iterdir()):
        if p.suffix in {".png", ".pdf", ".svg", ".md", ".tex", ".docx"}:
            print(f"  {p.name} ({p.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
