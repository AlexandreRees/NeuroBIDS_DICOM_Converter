#!/usr/bin/env python3
"""Session completeness figure: subjects with grating / rest / movie by ses-01 vs ses-02.

X = functional paradigms (grating=task-fmri, resting-state=task-rest, movie=task-movie)
Y = number of subjects with ≥1 magnitude BOLD for that task in the session
Colors = ses-01 vs ses-02

Usage:
  python3 code/make_functional_session_completeness_figure.py
"""

from __future__ import annotations

import csv
import re
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

SCRATCH = Path("/home/alexrees/scratch")
DEFAULT_ROOT = SCRATCH / "release_dataset"
OUT_DIR = SCRATCH / "reports" / "functional_session_completeness"

# Paradigm display label → BIDS task entity
PARADIGMS = (
    ("Grating", "fmri"),
    ("Resting-state", "rest"),
    ("Movie", "movie"),
)

# Distinct, non-purple session colors
COLOR_SES01 = "#4C78A8"  # steel blue
COLOR_SES02 = "#F58518"  # amber/orange


def count_subjects(root: Path) -> dict[str, dict[str, set[str]]]:
    """task_label → session → set of subjects with ≥1 mag BOLD."""
    out: dict[str, dict[str, set[str]]] = {
        label: {"ses-01": set(), "ses-02": set()} for label, _ in PARADIGMS
    }
    label_by_task = {task: label for label, task in PARADIGMS}
    for label, task in PARADIGMS:
        for p in root.glob(f"sub-*/ses-*/func/*task-{task}*_bold.nii.gz"):
            if "part-phase" in p.name:
                continue
            m = re.search(r"(sub-\d+)/(ses-\d+)/", str(p))
            if not m:
                continue
            sub, ses = m.group(1), m.group(2)
            if ses in out[label]:
                out[label][ses].add(sub)
    return out


def write_tsv(path: Path, counts: dict[str, dict[str, set[str]]], n_cohort: int) -> None:
    rows = []
    for label, _ in PARADIGMS:
        for ses in ("ses-01", "ses-02"):
            n = len(counts[label][ses])
            rows.append(
                {
                    "paradigm": label,
                    "bids_task": dict(PARADIGMS)[label],
                    "session": ses,
                    "n_subjects": n,
                    "n_cohort_subjects": n_cohort,
                    "completeness_pct": f"{100.0 * n / n_cohort:.1f}" if n_cohort else "",
                }
            )
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()), delimiter="\t")
        w.writeheader()
        w.writerows(rows)


def make_figure(counts: dict[str, dict[str, set[str]]], out_dir: Path, n_cohort: int) -> None:
    labels = [p[0] for p in PARADIGMS]
    n01 = [len(counts[lab]["ses-01"]) for lab in labels]
    n02 = [len(counts[lab]["ses-02"]) for lab in labels]

    x = np.arange(len(labels))
    width = 0.36

    fig, ax = plt.subplots(figsize=(7.2, 4.6), dpi=150)
    b1 = ax.bar(
        x - width / 2,
        n01,
        width,
        label="ses-01",
        color=COLOR_SES01,
        edgecolor="white",
        linewidth=0.6,
    )
    b2 = ax.bar(
        x + width / 2,
        n02,
        width,
        label="ses-02",
        color=COLOR_SES02,
        edgecolor="white",
        linewidth=0.6,
    )

    # Cohort reference
    ax.axhline(
        n_cohort,
        color="#333333",
        linestyle="--",
        linewidth=1.0,
        alpha=0.7,
        label=f"Cohort (n={n_cohort})",
    )

    ax.set_ylabel("Number of subjects")
    ax.set_xlabel("Functional paradigm")
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.set_ylim(0, max(n_cohort, max(n01 + n02)) * 1.12)
    ax.set_title("Functional completeness by session")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    def annotate(bars):
        for bar in bars:
            h = bar.get_height()
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                h + 1.2,
                f"{int(h)}",
                ha="center",
                va="bottom",
                fontsize=9,
            )

    annotate(b1)
    annotate(b2)

    # Legend below the axes (outside the plotting area)
    fig.legend(
        handles=[b1, b2, ax.lines[0]],
        labels=["ses-01", "ses-02", f"Cohort (n={n_cohort})"],
        loc="upper center",
        bbox_to_anchor=(0.5, -0.02),
        ncol=3,
        frameon=False,
    )
    fig.tight_layout()
    out_dir.mkdir(parents=True, exist_ok=True)
    for ext in ("png", "pdf"):
        fig.savefig(
            out_dir / f"Figure_functional_completeness_by_session.{ext}",
            bbox_inches="tight",
            pad_inches=0.25,
        )
    plt.close(fig)


def main() -> int:
    root = DEFAULT_ROOT
    counts = count_subjects(root)
    n_cohort = len([p for p in root.glob("sub-*") if p.is_dir()])
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    write_tsv(OUT_DIR / "functional_completeness_by_session.tsv", counts, n_cohort)
    make_figure(counts, OUT_DIR, n_cohort)

    # Caption
    lines = [
        "# Functional completeness by session",
        "",
        "Grouped bars: number of subjects with ≥1 magnitude BOLD for each paradigm,",
        "split by `ses-01` (blue) and `ses-02` (orange). Dashed line = cohort size (84).",
        "",
        "| Paradigm | ses-01 | ses-02 |",
        "| --- | ---: | ---: |",
    ]
    for label, _ in PARADIGMS:
        lines.append(
            f"| {label} | {len(counts[label]['ses-01'])} | {len(counts[label]['ses-02'])} |"
        )
    lines += [
        "",
        "Source tree: `release_dataset/`.",
        "Grating = BIDS `task-fmri`; Resting-state = `task-rest`; Movie = `task-movie`.",
        "",
    ]
    (OUT_DIR / "README.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote figures under {OUT_DIR}")
    for label, _ in PARADIGMS:
        print(
            f"  {label}: ses-01={len(counts[label]['ses-01'])} "
            f"ses-02={len(counts[label]['ses-02'])}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
