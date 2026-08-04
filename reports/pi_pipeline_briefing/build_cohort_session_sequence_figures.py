#!/usr/bin/env python3
"""PI figures: sessions by cohort (135-session research inventory) + sequence completeness.

Sources:
  metadata/sessions.tsv                          -> 1 vs 2 sessions per cohort
  reports/protocol_completeness/protocol_completeness_participants.csv
                                                 -> T1 / FLAIR / DWI / ... presence

Includes the 11 non-Control ses-02 that are AUTO_CONFIRMED in sessions.tsv but
not yet present in the BIDS tree (124/135).
"""

from __future__ import annotations

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

COHORT_MAP = {
    "Control": "Control",
    "DataON": "DataON",
    "Data_ON": "DataON",
    "DataTON": "DataTON",
    "Data_TON": "DataTON",
    "Glaucoma": "Glaucoma",
}
COHORT_ORDER = ["Control", "Glaucoma", "DataON", "DataTON"]
COLORS = {
    "Control": "#4C9A9A",
    "Glaucoma": "#C47A3A",
    "DataON": "#7A9B6D",
    "DataTON": "#7B6B9B",
}
COLOR_1SES = "#B8B0A4"
COLOR_2SES = "#3D6B8C"
MODS = ["T1", "FLAIR", "fMRI", "Movie", "DWI", "Fieldmaps"]


def load_session_counts() -> tuple[pd.DataFrame, np.ndarray, np.ndarray]:
    ses = pd.read_csv(ROOT / "metadata" / "sessions.tsv", sep="\t")
    ses["cohort_disp"] = ses["cohort"].map(lambda c: COHORT_MAP.get(c, c))
    ns = ses.groupby(["participant_id", "cohort_disp"]).size().reset_index(name="n_ses")
    counts = (
        ns.groupby(["cohort_disp", "n_ses"]).size().unstack(fill_value=0).reindex(COHORT_ORDER)
    )
    one = counts[1].astype(float).to_numpy()
    two = counts[2].astype(float).to_numpy()
    return counts, one, two


def load_protocol() -> pd.DataFrame:
    pc = pd.read_csv(
        ROOT / "reports" / "protocol_completeness" / "protocol_completeness_participants.csv"
    )
    pc["cohort_disp"] = pc["cohort"].map(lambda c: COHORT_MAP.get(c, c))
    for m in MODS:
        pc[m] = pc[m].astype(str).str.strip().isin(["✓", "1", "True", "true"]).astype(int)
    pc["_ord"] = pc["cohort_disp"].map({c: i for i, c in enumerate(COHORT_ORDER)})
    return pc.sort_values(["_ord", "participant_id"]).reset_index(drop=True)


def gap_lines(pc: pd.DataFrame) -> list[str]:
    lines: list[str] = []
    for m in MODS:
        miss = pc.loc[pc[m] == 0, "participant_id"].tolist()
        if miss:
            lines.append(f"{m}: {', '.join(miss)}")
    return lines


def fig_sessions_by_cohort(one: np.ndarray, two: np.ndarray) -> Path:
    n_subj = one + two
    n_ses_c = one + 2 * two
    total_subj = int(n_subj.sum())
    total_ses = int(n_ses_c.sum())
    assert total_ses == 135 and total_subj == 84

    fig, ax = plt.subplots(figsize=(7.2, 4.6), dpi=180)
    x = np.arange(len(COHORT_ORDER))
    w = 0.62
    ax.bar(x, one, width=w, color=COLOR_1SES, label="1 session", edgecolor="white", zorder=2)
    ax.bar(
        x, two, width=w, bottom=one, color=COLOR_2SES, label="2 sessions", edgecolor="white", zorder=2
    )
    for i in range(len(COHORT_ORDER)):
        n1, n2 = int(one[i]), int(two[i])
        tot = n1 + n2
        if n1:
            ax.text(i, n1 / 2.0, str(n1), ha="center", va="center", fontsize=10, color="#3a3530")
        if n2:
            ax.text(
                i,
                one[i] + n2 / 2.0,
                str(n2),
                ha="center",
                va="center",
                fontsize=10,
                color="white",
                fontweight="medium",
            )
        ax.text(
            i,
            tot + 1.2,
            f"n={tot}\n({int(n_ses_c[i])} ses)",
            ha="center",
            va="bottom",
            fontsize=8.5,
            color="#444",
        )
    ax.set_xticks(x)
    ax.set_xticklabels(COHORT_ORDER, fontsize=11)
    ax.set_ylabel("Number of subjects", fontsize=11)
    ax.set_ylim(0, float(n_subj.max()) + 12)
    ax.set_title(
        f"Sessions by cohort — research inventory (n={total_subj} subjects · {total_ses} sessions)",
        fontsize=12,
        pad=10,
        fontweight="medium",
    )
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.yaxis.grid(True, color="#E6E6E6", linewidth=0.8, zorder=0)
    ax.set_axisbelow(True)
    ax.legend(frameon=False, loc="upper right", fontsize=10)
    fig.text(
        0.5,
        0.015,
        "Source: metadata/sessions.tsv (135 AUTO_CONFIRMED). "
        "Includes 11 non-Control ses-02 not yet in BIDS tree (9 Glaucoma, 1 DataON, 1 DataTON).",
        ha="center",
        va="bottom",
        fontsize=7.5,
        color="#666",
        style="italic",
    )
    fig.tight_layout(rect=[0, 0.06, 1, 1])
    path = OUT / "Figure_sessions_by_cohort_PI.png"
    fig.savefig(path, dpi=200, bbox_inches="tight", facecolor="white")
    fig.savefig(path.with_suffix(".pdf"), bbox_inches="tight", facecolor="white")
    plt.close(fig)

    # Update cohort.png (stacked 1 vs 2, cohort colours on 2-session segment)
    fig, ax = plt.subplots(figsize=(6.2, 4.2), dpi=180)
    ax.bar(x, one, width=w, color=COLOR_1SES, label="1 session", edgecolor="white", zorder=2)
    ax.bar(
        x,
        two,
        width=w,
        bottom=one,
        color=[COLORS[c] for c in COHORT_ORDER],
        label="2 sessions",
        edgecolor="white",
        zorder=2,
    )
    for i in range(len(COHORT_ORDER)):
        n1, n2 = int(one[i]), int(two[i])
        tot = n1 + n2
        if n1:
            ax.text(i, n1 / 2.0, str(n1), ha="center", va="center", fontsize=9.5, color="#333")
        if n2:
            ax.text(
                i,
                one[i] + n2 / 2.0,
                str(n2),
                ha="center",
                va="center",
                fontsize=9.5,
                color="white",
                fontweight="medium",
            )
        ax.text(i, tot + 1.0, str(tot), ha="center", va="bottom", fontsize=10, color="#333", fontweight="medium")
    ax.set_xticks(x)
    ax.set_xticklabels(COHORT_ORDER, fontsize=11)
    ax.set_ylabel("n", fontsize=11)
    ax.set_ylim(0, float(n_subj.max()) + 10)
    ax.set_title(f"Cohort × sessions (n={total_subj} · {total_ses} sessions)", fontsize=12, pad=8)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.legend(
        handles=[
            mpatches.Patch(color=COLOR_1SES, label="1 session"),
            mpatches.Patch(color="#555555", label="2 sessions (cohort colour)"),
        ],
        frameon=False,
        loc="upper right",
        fontsize=9,
    )
    ax.yaxis.grid(True, color="#E6E6E6", linewidth=0.8, zorder=0)
    ax.set_axisbelow(True)
    fig.text(
        0.5,
        0.01,
        "Includes 11 pending BIDS ses-02 (research inventory).",
        ha="center",
        fontsize=7.5,
        color="#666",
        style="italic",
    )
    fig.tight_layout(rect=[0, 0.05, 1, 1])
    fig.savefig(OUT / "cohort.png", dpi=200, bbox_inches="tight", facecolor="white")
    fig.savefig(OUT / "cohort_sessions.png", dpi=200, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return path


def fig_sequence_completeness(pc: pd.DataFrame) -> Path:
    from matplotlib.colors import ListedColormap

    mat = pc[MODS].to_numpy().astype(float)
    pct = pc[MODS].mean() * 100
    n_miss = (1 - pc[MODS]).sum().astype(int)

    fig = plt.figure(figsize=(9.2, 10.5), dpi=160)
    gs = fig.add_gridspec(2, 1, height_ratios=[1.15, 3.6], hspace=0.32)

    ax0 = fig.add_subplot(gs[0])
    ax0.barh(MODS[::-1], pct.values[::-1], color="#4C9A9A", height=0.62, zorder=2)
    for i, mod in enumerate(MODS[::-1]):
        p = float(pct[mod])
        m = int(n_miss[mod])
        label = f"{p:.0f}%  ({84 - m}/84)" + (f"  · missing {m}" if m else "")
        ax0.text(min(p + 1.2, 98), i, label, va="center", fontsize=9, color="#333")
    ax0.set_xlim(0, 108)
    ax0.set_xlabel("% of subjects with ≥1 series", fontsize=10)
    ax0.set_title("MRI sequence completeness (subject-level)", fontsize=13, pad=8, fontweight="medium")
    ax0.spines["top"].set_visible(False)
    ax0.spines["right"].set_visible(False)
    ax0.xaxis.grid(True, color="#E6E6E6", linewidth=0.8, zorder=0)
    ax0.set_axisbelow(True)

    ax1 = fig.add_subplot(gs[1])
    cmap = ListedColormap(["#E8A598", "#5B9A9A"])
    ax1.imshow(mat, aspect="auto", cmap=cmap, vmin=0, vmax=1, interpolation="nearest")
    ax1.set_xticks(range(len(MODS)))
    ax1.set_xticklabels(MODS, fontsize=10)
    ax1.set_yticks(range(len(pc)))
    ax1.set_yticklabels(
        [f"{r.participant_id}  {r.cohort_disp}" for r in pc.itertuples()],
        fontsize=6.2,
        fontfamily="monospace",
    )
    for i in range(1, len(pc)):
        if pc.loc[i, "cohort_disp"] != pc.loc[i - 1, "cohort_disp"]:
            ax1.axhline(i - 0.5, color="white", linewidth=2.2)
    for i in range(mat.shape[0]):
        for j in range(mat.shape[1]):
            if mat[i, j] == 0:
                ax1.add_patch(
                    plt.Rectangle(
                        (j - 0.5, i - 0.5), 1, 1, fill=False, edgecolor="#8B2E1F", linewidth=1.1
                    )
                )
    ax1.set_xlabel("Sequence family (≥1 session)", fontsize=10)
    ax1.set_title("Who is missing what — coral = absent", fontsize=11, pad=6)
    ax1.legend(
        handles=[
            mpatches.Patch(color="#5B9A9A", label="Present"),
            mpatches.Patch(color="#E8A598", label="Missing"),
        ],
        loc="upper right",
        bbox_to_anchor=(1.18, 1.0),
        frameon=False,
        fontsize=9,
    )

    gaps = gap_lines(pc)
    fig.text(
        0.5,
        0.012,
        ("Gaps — " + "  |  ".join(gaps) if gaps else "No modality gaps.")
        + "\nSource: metadata/session_mapping.csv via protocol_completeness "
        "(research inventory; not limited to BIDS 124-session tree).",
        ha="center",
        va="bottom",
        fontsize=7.5,
        color="#555",
    )
    fig.subplots_adjust(left=0.18, right=0.88, top=0.95, bottom=0.07, hspace=0.32)
    path = OUT / "Figure_sequence_completeness_PI.png"
    fig.savefig(path, dpi=200, bbox_inches="tight", facecolor="white")
    fig.savefig(path.with_suffix(".pdf"), bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return path


def fig_combined(one: np.ndarray, two: np.ndarray, pc: pd.DataFrame) -> Path:
    n_subj = one + two
    total_subj = int(n_subj.sum())
    total_ses = int((one + 2 * two).sum())
    present_n = pc[MODS].sum().astype(int).to_numpy()
    missing_n = 84 - present_n
    gaps = gap_lines(pc)

    fig, axes = plt.subplots(
        1, 2, figsize=(11.2, 4.8), dpi=170, gridspec_kw={"width_ratios": [1.15, 1.0]}
    )
    x = np.arange(len(COHORT_ORDER))
    w = 0.62

    ax = axes[0]
    ax.bar(x, one, width=w, color=COLOR_1SES, label="1 session", edgecolor="white", zorder=2)
    ax.bar(
        x, two, width=w, bottom=one, color=COLOR_2SES, label="2 sessions", edgecolor="white", zorder=2
    )
    for i in range(len(COHORT_ORDER)):
        n1, n2 = int(one[i]), int(two[i])
        tot = n1 + n2
        if n1:
            ax.text(i, n1 / 2.0, str(n1), ha="center", va="center", fontsize=9, color="#333")
        if n2:
            ax.text(
                i,
                one[i] + n2 / 2.0,
                str(n2),
                ha="center",
                va="center",
                fontsize=9,
                color="white",
                fontweight="medium",
            )
        ax.text(i, tot + 1.1, f"n={tot}", ha="center", va="bottom", fontsize=8.5, color="#444")
    ax.set_xticks(x)
    ax.set_xticklabels(COHORT_ORDER)
    ax.set_ylabel("Subjects")
    ax.set_title(
        f"A. Subjects with 1 vs 2 sessions\n({total_ses} sessions incl. 11 pending BIDS)",
        fontsize=11,
    )
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.legend(frameon=False, fontsize=9)
    ax.yaxis.grid(True, color="#EEE", zorder=0)
    ax.set_axisbelow(True)
    ax.set_ylim(0, float(n_subj.max()) + 10)

    ax = axes[1]
    y = np.arange(len(MODS))
    ax.barh(y, present_n, color="#5B9A9A", height=0.65, label="Present", zorder=2)
    ax.barh(y, missing_n, left=present_n, color="#E8A598", height=0.65, label="Missing", zorder=2)
    for i in range(len(MODS)):
        ax.text(
            present_n[i] / 2.0,
            i,
            str(int(present_n[i])),
            ha="center",
            va="center",
            color="white",
            fontsize=9,
            fontweight="medium",
        )
        if missing_n[i] > 0:
            ax.text(
                float(present_n[i] + missing_n[i]) + 0.6,
                i,
                f"−{int(missing_n[i])}",
                ha="left",
                va="center",
                color="#8B2E1F",
                fontsize=9,
                fontweight="medium",
            )
    ax.set_yticks(y)
    ax.set_yticklabels(MODS)
    ax.set_xlabel(f"Subjects (n={total_subj})")
    ax.set_xlim(0, 92)
    ax.set_title("B. Sequence completeness\n(who has T1 / DWI / …)", fontsize=11)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.legend(frameon=False, loc="lower right", fontsize=9)
    ax.xaxis.grid(True, color="#EEE", zorder=0)
    ax.set_axisbelow(True)

    fig.text(
        0.5,
        0.02,
        "Missing sequences — " + "   ·   ".join(gaps),
        ha="center",
        fontsize=8,
        color="#555",
    )
    fig.tight_layout(rect=[0, 0.07, 1, 1])
    path = OUT / "Figure_cohort_sessions_and_sequences_PI.png"
    fig.savefig(path, dpi=200, bbox_inches="tight", facecolor="white")
    fig.savefig(path.with_suffix(".pdf"), bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return path


def write_captions(gaps: list[str]) -> None:
    (OUT / "Figure_sessions_by_cohort_PI_caption.md").write_text(
        "Figure. Subjects with 1 vs 2 sessions by cohort (research inventory).\n"
        "Total: 84 subjects, 135 AUTO_CONFIRMED sessions "
        "(includes 11 non-Control ses-02 not yet converted into the BIDS tree: "
        "9 Glaucoma, 1 DataON, 1 DataTON). Source: metadata/sessions.tsv.\n"
    )
    (OUT / "Figure_sequence_completeness_PI_caption.md").write_text(
        "Figure. MRI sequence completeness at subject level.\n"
        "Top: % of subjects with ≥1 series per sequence family. "
        "Bottom: presence matrix (teal = present, coral = missing). "
        f"Gaps: {'; '.join(gaps)}. "
        "Source: metadata/session_mapping.csv (protocol_completeness).\n"
    )


def main() -> None:
    _, one, two = load_session_counts()
    pc = load_protocol()
    gaps = gap_lines(pc)
    p1 = fig_sessions_by_cohort(one, two)
    p2 = fig_sequence_completeness(pc)
    p3 = fig_combined(one, two, pc)
    write_captions(gaps)
    print("Wrote:")
    for p in (p1, p2, p3, OUT / "cohort.png"):
        print(" ", p)


if __name__ == "__main__":
    main()
