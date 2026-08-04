#!/usr/bin/env python3
"""Generate a PI-friendly overview figure of associated (non-DICOM) data.

Reads the read-only inventory produced by the associated-data audit and
renders a single multi-panel figure summarising, per data category:
  A. number of files
  B. total size on disk
  C. subject coverage (how many of the 84 subjects have that data type)
  D. planned BIDS-conversion status

Usage:
    python3 code/plot_associated_data_overview.py \
        --inventory reports/associated_data_inventory.tsv \
        --out figures/associated_data_overview.png
"""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter

# Human-friendly labels and a colour-blind-safe palette (Okabe-Ito).
CATEGORY_ORDER = ["stimulus", "task_timing", "eye_tracking", "physiology", "unknown"]
CATEGORY_LABELS = {
    "stimulus": "Stimuli\n(movies, audio, media)",
    "task_timing": "Task timing\n(onsets, events, triggers)",
    "eye_tracking": "Eye tracking\n(gaze, pupil, EDF/ASC)",
    "physiology": "Physiology\n(ECG, respiration, pulse)",
    "unknown": "Unclassified\n(needs review)",
}
CATEGORY_COLORS = {
    "stimulus": "#0072B2",
    "task_timing": "#E69F00",
    "eye_tracking": "#009E73",
    "physiology": "#D55E00",
    "unknown": "#999999",
}

# Category x BIDS-status matrix (from reports/.../bids_conversion_plan.md).
BIDS_STATUS = {
    "stimulus": {"Convertible to BIDS": 1252, "Requires custom converter": 416, "Should remain as auxiliary data": 2048},
    "task_timing": {"Convertible to BIDS": 1108},
    "eye_tracking": {"Requires custom converter": 448},
    "physiology": {"Convertible to BIDS": 339},
    "unknown": {"Should remain as auxiliary data": 145},
}
STATUS_ORDER = ["Convertible to BIDS", "Requires custom converter", "Should remain as auxiliary data"]
STATUS_COLORS = {
    "Convertible to BIDS": "#009E73",
    "Requires custom converter": "#E69F00",
    "Should remain as auxiliary data": "#BBBBBB",
}

TOTAL_SUBJECTS = 84


def human_size(num_bytes: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(num_bytes) < 1024.0:
            return f"{num_bytes:.1f} {unit}"
        num_bytes /= 1024.0
    return f"{num_bytes:.1f} PB"


def load_inventory(path: Path):
    counts: dict[str, int] = defaultdict(int)
    sizes: dict[str, int] = defaultdict(int)
    subjects: dict[str, set[str]] = defaultdict(set)
    total_files = 0
    all_subjects: set[str] = set()

    with path.open(newline="", encoding="utf-8", errors="replace") as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        for row in reader:
            cat = (row.get("category") or "unknown").strip() or "unknown"
            subj = (row.get("subject") or "").strip()
            try:
                size = int(row.get("size") or 0)
            except ValueError:
                size = 0
            counts[cat] += 1
            sizes[cat] += size
            total_files += 1
            if subj:
                subjects[cat].add(subj)
                all_subjects.add(subj)

    return counts, sizes, subjects, total_files, len(all_subjects)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--inventory", default="reports/associated_data_inventory.tsv")
    ap.add_argument("--out", default="figures/associated_data_overview.png")
    args = ap.parse_args()

    root = Path(__file__).resolve().parent.parent
    inv_path = (root / args.inventory) if not Path(args.inventory).is_absolute() else Path(args.inventory)
    out_path = (root / args.out) if not Path(args.out).is_absolute() else Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    counts, sizes, subjects, total_files, n_subjects = load_inventory(inv_path)
    cats = [c for c in CATEGORY_ORDER if c in counts] + [c for c in counts if c not in CATEGORY_ORDER]
    total_size = sum(sizes.values())

    plt.rcParams.update({
        "font.size": 11,
        "axes.titlesize": 13,
        "axes.titleweight": "bold",
        "axes.spines.top": False,
        "axes.spines.right": False,
    })

    fig = plt.figure(figsize=(15, 9))
    gs = fig.add_gridspec(2, 2, hspace=0.42, wspace=0.28, left=0.13, right=0.97, top=0.86, bottom=0.09)

    labels = [CATEGORY_LABELS.get(c, c) for c in cats]
    colors = [CATEGORY_COLORS.get(c, "#777777") for c in cats]
    y = range(len(cats))

    # --- Panel A: file counts ---
    axA = fig.add_subplot(gs[0, 0])
    vals = [counts[c] for c in cats]
    barsA = axA.barh(list(y), vals, color=colors)
    axA.set_yticks(list(y))
    axA.set_yticklabels(labels)
    axA.invert_yaxis()
    axA.set_xlabel("Number of files")
    axA.set_title("A. How many files of each type")
    axA.set_xlim(0, max(vals) * 1.18)
    for bar, v in zip(barsA, vals):
        axA.text(bar.get_width() + max(vals) * 0.01, bar.get_y() + bar.get_height() / 2,
                 f"{v:,}", va="center", ha="left", fontsize=10)

    # --- Panel B: total size ---
    axB = fig.add_subplot(gs[0, 1])
    vals_gb = [sizes[c] / 1024**3 for c in cats]
    barsB = axB.barh(list(y), vals_gb, color=colors)
    axB.set_yticks(list(y))
    axB.set_yticklabels(labels)
    axB.invert_yaxis()
    axB.set_xlabel("Total size on disk (GB)")
    axB.set_title("B. How much disk space each type uses")
    axB.set_xlim(0, max(vals_gb) * 1.18)
    for bar, c in zip(barsB, cats):
        axB.text(bar.get_width() + max(vals_gb) * 0.01, bar.get_y() + bar.get_height() / 2,
                 human_size(sizes[c]), va="center", ha="left", fontsize=10)

    # --- Panel C: subject coverage ---
    axC = fig.add_subplot(gs[1, 0])
    covered = [len(subjects[c]) for c in cats]
    axC.barh(list(y), [TOTAL_SUBJECTS] * len(cats), color="#EEEEEE")
    barsC = axC.barh(list(y), covered, color=colors)
    axC.set_yticks(list(y))
    axC.set_yticklabels(labels)
    axC.invert_yaxis()
    axC.set_xlabel(f"Subjects with this data type (out of {n_subjects})")
    axC.set_title("C. How many subjects have each type")
    axC.set_xlim(0, TOTAL_SUBJECTS * 1.12)
    for bar, v in zip(barsC, covered):
        pct = 100 * v / n_subjects if n_subjects else 0
        axC.text(v + TOTAL_SUBJECTS * 0.01, bar.get_y() + bar.get_height() / 2,
                 f"{v}/{n_subjects} ({pct:.0f}%)", va="center", ha="left", fontsize=10)

    # --- Panel D: BIDS conversion status (stacked) ---
    axD = fig.add_subplot(gs[1, 1])
    for i, c in enumerate(cats):
        left = 0.0
        status_map = BIDS_STATUS.get(c, {})
        for status in STATUS_ORDER:
            v = status_map.get(status, 0)
            if v <= 0:
                continue
            axD.barh(i, v, left=left, color=STATUS_COLORS[status])
            if v > total_files * 0.015:
                axD.text(left + v / 2, i, f"{v:,}", va="center", ha="center",
                         fontsize=9, color="white", fontweight="bold")
            left += v
    axD.set_yticks(list(y))
    axD.set_yticklabels(labels)
    axD.invert_yaxis()
    axD.set_xlabel("Number of files")
    axD.set_title("D. Plan to bring each type into BIDS")
    handles = [plt.Rectangle((0, 0), 1, 1, color=STATUS_COLORS[s]) for s in STATUS_ORDER]
    axD.legend(handles, STATUS_ORDER, loc="lower right", fontsize=9, frameon=False)

    fig.suptitle(
        "Associated (non-imaging) data in the dataset",
        fontsize=18, fontweight="bold", x=0.13, ha="left", y=0.965,
    )
    fig.text(
        0.13, 0.905,
        f"{total_files:,} files  ·  {human_size(total_size)}  ·  {n_subjects} subjects  ·  "
        f"read-only audit of raw_original/ (no source files modified)",
        fontsize=11.5, ha="left", color="#333333",
    )

    for ext in ("png", "svg"):
        fig.savefig(out_path.with_suffix(f".{ext}"), dpi=200, bbox_inches="tight")
    print(f"Wrote {out_path.with_suffix('.png')}")
    print(f"Wrote {out_path.with_suffix('.svg')}")


if __name__ == "__main__":
    main()
