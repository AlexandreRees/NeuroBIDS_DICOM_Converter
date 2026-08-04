#!/usr/bin/env python3
"""Sequence completeness by session — PI figure (stacked Present/Missing bars).

Same visual design as Figure_sequence_completeness_by_session_PI.png:
  teal Present / coral Missing, ses-01|ses-02 paired bars, in-bar counts,
  −N missing labels, faint y-grid, no top/right spines.

Category changes vs original (T1, FLAIR, fMRI, Movie, DWI, Fieldmaps):
  - Aggregate fMRI → rest-fMRI / Gratings fMRI / fMRI reversed-PE control / Movie
  - Aggregate DWI → GSLD (AP) + GSLD PA + Resolve (AP) + RESOLVE PA

Denominator = participants imaged at that session (sessions.tsv).
Source = metadata/session_mapping.csv.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
import pandas as pd

ROOT = Path("/home/alexrees/scratch")
OUT = ROOT / "reports" / "pi_pipeline_briefing" / "figures"
OUT.mkdir(parents=True, exist_ok=True)

ACQUISITIONS = [
    ("T1w_MPR", r"(?i)^t1w_mpr$|^t1w_mpr_nd$"),
    ("WMn_MPRAGE_sagittal", r"(?i)wmn_mprage"),
    ("Sag FLAIR 3D", r"(?i)sag\s*flair\s*3d"),
    ("REST1_AP", r"(?i)^rest1_ap$"),
    ("fMRI1_AP", r"(?i)^fmri1_ap$"),
    ("fMRI2_AP", r"(?i)^fmri2_ap$"),
    ("fMRI3_AP", r"(?i)^fmri3_ap$"),
    ("fMRI4_AP", r"(?i)^fmri4_ap$"),
    ("Control acquisitions", r"(?i)^control\d+_(?:ap|pa)$"),
    ("Movie1_AP", r"(?i)^movie1_ap$"),
    ("Movie2_AP", r"(?i)^movie2_ap$"),
    ("Movie3_AP", r"(?i)^movie3_ap$"),
    ("Movie4_AP", r"(?i)^movie4_ap$"),
    ("SpinEchoFieldMap_AP", r"(?i)^spinechofieldmap_ap$"),
    ("SpinEchoFieldMap_PA", r"(?i)^spinechofieldmap_pa$"),
    ("gsld_76dir_b2000_1mmiso_AP", r"(?i)gsld_76dir_b2000"),
    ("gsld_75TE_PA_3b0", r"(?i)^gsld_75TE_PA_3b0"),
    ("RESOLVE diffusion AP", r"(?i)^resolve_.*_AP$"),
    ("RESOLVE diffusion PA", r"(?i)^resolve_.*_PA$"),
]

# fMRI → four paradigms. DWI → multi-shell EPI / reverse-PE b0 / RESOLVE AP+PA.
MATRIX_CATEGORIES = [
    ("T1w", "T1w", ["T1w_MPR"]),
    ("WMn", "WMn", ["WMn_MPRAGE_sagittal"]),
    ("FLAIR", "FLAIR", ["Sag FLAIR 3D"]),
    ("Rest", "rest-fMRI", ["REST1_AP"]),
    ("Grating", "Gratings", ["fMRI1_AP", "fMRI2_AP", "fMRI3_AP", "fMRI4_AP"]),
    (
        "Control",
        "fMRI reversed phase\nencoding control",
        ["Control acquisitions"],
    ),
    ("Movie", "Movie", ["Movie1_AP", "Movie2_AP", "Movie3_AP", "Movie4_AP"]),
    (
        "GSLD",
        "Multi-shell diffusion-\nweighted EPI (AP)",
        ["gsld_76dir_b2000_1mmiso_AP"],
    ),
    (
        "GSLD_PA",
        "Reverse phase-encoding\nb0 reference (PA)",
        ["gsld_75TE_PA_3b0"],
    ),
    (
        "Resolve",
        "Readout-segmented\ndiffusion MRI\n(RESOLVE, AP)",
        ["RESOLVE diffusion AP"],
    ),
    (
        "Resolve_PA",
        "Readout-segmented\ndiffusion MRI\n(RESOLVE, PA)",
        ["RESOLVE diffusion PA"],
    ),
    ("Fieldmaps", "Fieldmaps", ["SpinEchoFieldMap_AP", "SpinEchoFieldMap_PA"]),
]

COLOR_PRESENT = "#5B9A9A"
COLOR_MISSING = "#E8A598"


def main() -> None:
    mods = [m for m, _, _ in MATRIX_CATEGORIES]
    mains = [main for _, main, _ in MATRIX_CATEGORIES]

    sessions = pd.read_csv(ROOT / "metadata" / "sessions.tsv", sep="\t")
    attended = {
        "ses-01": set(sessions.loc[sessions.session_id == "ses-01", "participant_id"]),
        "ses-02": set(sessions.loc[sessions.session_id == "ses-02", "participant_id"]),
    }

    sm = pd.read_csv(ROOT / "metadata" / "session_mapping.csv", dtype=str, low_memory=False).fillna("")
    sm["participant_id"] = sm["participant_id"].astype(str).str.strip()
    sm["session_id"] = sm["session_id"].astype(str).str.strip()
    sm["series_description"] = sm["series_description"].astype(str)

    acq_hits: dict[str, set[tuple[str, str]]] = {}
    for lab, pat in ACQUISITIONS:
        hit = sm.loc[
            sm["series_description"].str.contains(pat, regex=True, na=False),
            ["participant_id", "session_id"],
        ].drop_duplicates()
        acq_hits[lab] = set(zip(hit.participant_id, hit.session_id))

    rows = []
    for mod, _, acq_list in MATRIX_CATEGORIES:
        for sid in ("ses-01", "ses-02"):
            denom = attended[sid]
            present_ids = {
                pid
                for pid in denom
                if any((pid, sid) in acq_hits[a] for a in acq_list)
            }
            missing_ids = sorted(denom - present_ids)
            rows.append(
                {
                    "modality": mod,
                    "session": sid,
                    "n_present": len(present_ids),
                    "n_missing": len(denom) - len(present_ids),
                    "n_total": len(denom),
                    "missing_ids": missing_ids,
                }
            )
            print(
                f"{mod:10s} {sid}: present={len(present_ids):3d} "
                f"missing={len(missing_ids):3d} / {len(denom)}"
            )

    df = pd.DataFrame(rows)

    print("X-axis labels:")
    for m, lab in zip(mods, mains):
        print(f"  {m}: {lab.replace(chr(10), ' / ')}")

    fig, ax = plt.subplots(figsize=(17.0, 5.8), dpi=180)
    x = np.arange(len(mods), dtype=float)
    w = 0.36
    gap = 0.04
    x01 = x - (w / 2 + gap / 2)
    x02 = x + (w / 2 + gap / 2)

    for xi, sid, xpos in ((0, "ses-01", x01), (1, "ses-02", x02)):
        sub = df[df["session"] == sid].set_index("modality").reindex(mods)
        present = sub["n_present"].to_numpy(float)
        missing = sub["n_missing"].to_numpy(float)
        ax.bar(
            xpos,
            present,
            width=w,
            color=COLOR_PRESENT,
            edgecolor="white",
            linewidth=0.6,
            zorder=2,
            label="Present" if xi == 0 else None,
        )
        ax.bar(
            xpos,
            missing,
            width=w,
            bottom=present,
            color=COLOR_MISSING,
            edgecolor="white",
            linewidth=0.6,
            zorder=2,
            label="Missing" if xi == 0 else None,
        )
        for i in range(len(mods)):
            p, m = int(present[i]), int(missing[i])
            if p:
                ax.text(
                    xpos[i],
                    p / 2.0,
                    str(p),
                    ha="center",
                    va="center",
                    fontsize=7.5,
                    color="white",
                    fontweight="medium",
                    zorder=3,
                )
            if m:
                ax.text(
                    xpos[i],
                    float(p + m) + 0.8,
                    f"−{m}",
                    ha="center",
                    va="bottom",
                    fontsize=7.5,
                    color="#8B2E1F",
                    fontweight="medium",
                    zorder=3,
                )

    # Custom x labels: ses tags just under bars, category name clearly below.
    ax.set_xticks(x)
    ax.set_xticklabels([])
    ax.tick_params(axis="x", length=0, pad=0)
    ax.set_ylabel("Number of participants", fontsize=11)
    ax.set_ylim(0, max(len(attended["ses-01"]), len(attended["ses-02"])) + 12)
    ax.set_title(
        "Sequence completeness by session\n"
        f"(ses-01 n={len(attended['ses-01'])} · ses-02 n={len(attended['ses-02'])})",
        fontsize=12,
        pad=10,
        fontweight="medium",
    )
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.yaxis.grid(True, color="#E6E6E6", linewidth=0.8, zorder=0)
    ax.set_axisbelow(True)

    # Compact bottom: room for x-labels + tight footer under them.
    fig.subplots_adjust(bottom=0.30, top=0.88, left=0.055, right=0.985)

    y_ses = -0.018
    y_main = -0.090
    label_artists = []
    for i in range(len(mods)):
        ax.text(
            x01[i],
            y_ses,
            "ses-01",
            transform=ax.get_xaxis_transform(),
            ha="center",
            va="top",
            fontsize=6.5,
            color="#555",
            clip_on=False,
        )
        ax.text(
            x02[i],
            y_ses,
            "ses-02",
            transform=ax.get_xaxis_transform(),
            ha="center",
            va="top",
            fontsize=6.5,
            color="#555",
            clip_on=False,
        )
        nlines = mains[i].count("\n") + 1
        label_artists.append(
            ax.text(
                x[i],
                y_main,
                mains[i],
                transform=ax.get_xaxis_transform(),
                ha="center",
                va="top",
                fontsize=7.2 if nlines >= 3 else (8.0 if nlines == 2 else 9.0),
                color="#222",
                linespacing=1.12,
                clip_on=False,
                zorder=5,
            )
        )
    ax.legend(
        handles=[
            mpatches.Patch(color=COLOR_PRESENT, label="Present"),
            mpatches.Patch(color=COLOR_MISSING, label="Missing"),
        ],
        frameon=False,
        loc="upper right",
        fontsize=10,
    )

    gap_parts = []
    for mod in mods:
        for sid in ("ses-01", "ses-02"):
            miss = df.loc[
                (df["modality"] == mod) & (df["session"] == sid), "missing_ids"
            ].iloc[0]
            if miss:
                gap_parts.append(f"{mod} {sid}: {', '.join(miss)}")
    missing_line = (
        ("Missing — " + "  ·  ".join(gap_parts)) if gap_parts else "No modality gaps."
    )
    source_line = (
        "Denominator = participants imaged at that session. "
        "Source: metadata/session_mapping.csv."
    )

    # Wrap footer to axes width, then park it just under the x-labels.
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    ax_bbox = ax.get_position()
    max_w_px = ax_bbox.width * fig.bbox.width
    labels_bottom_px = min(
        a.get_window_extent(renderer=renderer).y0 for a in label_artists
    )
    # Small gap (~6 px) between category labels and grey footer.
    footer_top_fig = (labels_bottom_px - 6.0) / fig.bbox.height

    wrap_chars = 155
    footer_artist = None
    for _ in range(12):
        footer = textwrap.fill(missing_line, width=wrap_chars) + "\n" + source_line
        if footer_artist is not None:
            footer_artist.remove()
        footer_artist = fig.text(
            ax_bbox.x0,
            footer_top_fig,
            footer,
            ha="left",
            va="top",
            fontsize=5.3,
            color="#555",
            linespacing=1.2,
            transform=fig.transFigure,
            clip_on=False,
        )
        fig.canvas.draw()
        bb = footer_artist.get_window_extent(renderer=renderer)
        if bb.width <= max_w_px * 1.01:
            break
        wrap_chars = max(40, wrap_chars - 15)

    # Trim leftover white space under the footer.
    footer_bottom_fig = bb.y0 / fig.bbox.height
    new_bottom = max(0.02, footer_bottom_fig - 0.008)
    if new_bottom < ax_bbox.y0 - 0.01:
        # Shift axes block down only via subplots_adjust bottom if needed;
        # keep current axes — just ensure save includes footer with little pad.
        pass
    print(
        f"Footer wrap_chars={wrap_chars}, "
        f"width_px={bb.width:.0f}/{max_w_px:.0f}, "
        f"gap_to_labels_px={labels_bottom_px - bb.y1:.1f}"
    )

    out = OUT / "Figure_sequence_completeness_by_session_PI.png"
    # Tight pad under footer; keep left/right fixed so width match stays.
    fig.savefig(out, dpi=200, bbox_inches="tight", pad_inches=0.12, facecolor="white")
    fig.savefig(
        out.with_suffix(".pdf"),
        bbox_inches="tight",
        pad_inches=0.12,
        facecolor="white",
    )
    plt.close(fig)

    (OUT / "Figure_sequence_completeness_by_session_PI_caption.md").write_text(
        "Figure. Sequence completeness by imaging session.\n"
        "For each sequence family, paired bars show ses-01 and ses-02. "
        "Within each bar, teal = participants with ≥1 matching series at that session; "
        "coral = participants imaged at that session but missing the sequence. "
        f"Denominators: ses-01 n={len(attended['ses-01'])}, "
        f"ses-02 n={len(attended['ses-02'])}. "
        "T1 split into T1w (classic MPRAGE) and WMn (WMn_MPRAGE). "
        "Functional MRI as rest-fMRI / Gratings / "
        "fMRI reversed phase encoding control / Movie; "
        "diffusion as Multi-shell diffusion-weighted EPI (AP), "
        "Reverse phase-encoding b0 reference (PA), "
        "and Readout-segmented diffusion MRI (RESOLVE, AP/PA). "
        "Source: metadata/session_mapping.csv.\n",
        encoding="utf-8",
    )
    print("Wrote", out)
    print("Columns:", " | ".join(mods))


if __name__ == "__main__":
    main()
