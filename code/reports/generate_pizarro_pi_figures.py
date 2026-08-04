#!/usr/bin/env python3
"""Regenerate Pizarro PI presentation figures from the revised package.

Reads ``reports/pizarro_qc_revised/`` and writes figures under
``reports/pi_pipeline_briefing/figures/pizarro/``.

Uses only numpy/matplotlib (no pandas) so it runs in the Pizarro venv.

Example:
  ~/scratch/venvs/pizarro_qc/bin/python code/reports/generate_pizarro_pi_figures.py
"""
from __future__ import annotations

import argparse
import csv
import shutil
import statistics
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import FancyBboxPatch

HOME = Path.home()
DEFAULT_SRC = HOME / "scratch" / "reports" / "pizarro_qc_revised"
DEFAULT_OUT = HOME / "scratch" / "reports" / "pi_pipeline_briefing" / "figures" / "pizarro"
DEFAULT_MS = HOME / "scratch" / "reports" / "scientific_data_manuscript_draft" / "figures"

C_TXT = "#1F2937"
C_EDGE = "#333333"


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh, delimiter="\t"))


def short_name(fn: object) -> str:
    return Path(str(fn)).name.replace("_T1w.nii.gz", "")


def fget(row: dict[str, str], key: str) -> float:
    return float(row[key])


def normalize_run(value: object) -> str:
    s = str(value).strip()
    if s.isdigit():
        return f"{int(s):02d}"
    if s.startswith("run-"):
        return normalize_run(s[4:])
    return s


def filter_rows_by_run(rows: list[dict[str, str]], run: str | None) -> list[dict[str, str]]:
    if not run:
        return rows
    want = normalize_run(run)
    out: list[dict[str, str]] = []
    for r in rows:
        run_val = r.get("run", "")
        if run_val:
            if normalize_run(run_val) == want:
                out.append(r)
            continue
        fn = str(r.get("filename", ""))
        if f"run-{want}" in fn:
            out.append(r)
    return out


def top_n(rows: list[dict[str, str]], key: str, n: int = 10) -> list[dict[str, str]]:
    return sorted(rows, key=lambda r: fget(r, key), reverse=True)[:n]


def build_figures(
    src: Path,
    out: Path,
    ms: Path | None,
    *,
    scope_label: str = "T1w only",
    run: str | None = None,
) -> dict[str, float | int]:
    out.mkdir(parents=True, exist_ok=True)
    rows = filter_rows_by_run(read_tsv(src / "image_level_predictions.tsv"), run)
    if not rows:
        raise SystemExit(f"No rows after run filter={run!r} from {src}")
    if run:
        top_p = top_n(rows, "artifact_probability")
        top_u = top_n(rows, "uncertainty")
    else:
        top_p = read_tsv(src / "manual_review_top10_artifact_probability.tsv")
        top_u = read_tsv(src / "manual_review_top10_uncertainty.tsv")

    probs = [fget(r, "artifact_probability") for r in rows]
    uncs = [fget(r, "uncertainty") for r in rows]
    confs = [fget(r, "confidence") for r in rows]
    n = len(rows)
    n_subj = len({r["subject"] for r in rows})
    mean_p = float(statistics.mean(probs))
    median_p = float(statistics.median(probs))
    n_ses02 = sum(1 for r in rows if "ses-02" in str(r.get("session", "")))

    fig, ax = plt.subplots(figsize=(16, 8.5), dpi=200)
    ax.set_xlim(0, 16)
    ax.set_ylim(0, 8.5)
    ax.axis("off")
    fig.patch.set_facecolor("white")
    ax.text(
        8,
        8.05,
        "Pizarro QC — automated T1w artifact screening",
        ha="center",
        fontsize=18,
        fontweight="bold",
        color=C_TXT,
    )
    ax.text(
        8,
        7.55,
        f"Pizarro et al., 2023  ·  model Pizarro2023-FINAL  ·  Monte Carlo dropout (10 runs)  ·  {scope_label}",
        ha="center",
        fontsize=10.5,
        color="#4B5563",
    )
    cards = [
        (
            0.5,
            "#DBEAFE",
            "What it does",
            [
                "Deep-learning classifier on each T1w",
                "Outputs continuous scores:",
                "• artifact probability (0–100)",
                "• confidence",
                "• uncertainty",
                f"Scores {n} T1w images ({n_subj} subjects)",
            ],
        ),
        (
            5.6,
            "#D1FAE5",
            "How we use it",
            [
                "Prioritize targeted visual review",
                "Complementary to MRIQC IQMs",
                "NOT an automatic exclusion rule",
                "NOT a cohort “failure rate”",
                "No subject removed by the model alone",
                "Human review remains the gate",
            ],
        ),
        (
            10.7,
            "#FEF3C7",
            "Why it is useful",
            [
                "Flags scans worth a second look",
                "Transparent, published method",
                "Fits Scientific Data QC narrative",
                "Shows due diligence beyond MRIQC",
                "Supports reproducibility of review",
                "Lightweight addition to the release",
            ],
        ),
    ]
    for x, fc, title, lines in cards:
        ax.add_patch(
            FancyBboxPatch(
                (x, 2.6),
                4.8,
                4.5,
                boxstyle="round,pad=0.02,rounding_size=0.14",
                facecolor=fc,
                edgecolor=C_EDGE,
                lw=1.4,
            )
        )
        ax.text(x + 2.4, 6.7, title, ha="center", fontsize=14, fontweight="bold", color=C_TXT)
        ax.text(
            x + 2.4,
            4.6,
            "\n".join(lines),
            ha="center",
            va="center",
            fontsize=11,
            color="#374151",
            linespacing=1.55,
        )

    ax.add_patch(
        FancyBboxPatch(
            (0.5, 0.45),
            15,
            1.8,
            boxstyle="round,pad=0.02,rounding_size=0.12",
            facecolor="#F8FAFC",
            edgecolor="#CBD5E1",
            lw=1.2,
        )
    )
    stats = [
        (str(n), "T1w scored"),
        (str(n_subj), "subjects"),
        ("0", "inference errors"),
        (f"{mean_p:.1f}", "mean artifact P"),
        (f"{median_p:.0f}", "median artifact P"),
    ]
    for i, (val, lab) in enumerate(stats):
        xx = 1.5 + i * 2.9
        ax.text(
            xx,
            1.55,
            val,
            ha="center",
            fontsize=20,
            fontweight="bold",
            color="#1B7A4E" if i < 3 else "#C47A00",
        )
        ax.text(xx, 0.9, lab, ha="center", fontsize=10, color="#4B5563")

    for ext in ("png", "pdf"):
        fig.savefig(out / f"Figure_Pizarro_overview_PI.{ext}", dpi=220, bbox_inches="tight", facecolor="white")
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(10, 5.8), dpi=200)
    bins = np.arange(0, 110, 10)
    ax.hist(probs, bins=bins, color="#3B82F6", edgecolor="white", linewidth=1.2)
    ax.axvline(median_p, color="#C47A00", ls="--", lw=2, label=f"Median = {median_p:.0f}")
    ax.axvline(mean_p, color="#1B7A4E", ls="--", lw=2, label=f"Mean = {mean_p:.1f}")
    ax.set_xlabel("Artifact probability (0–100)", fontsize=12)
    ax.set_ylabel("Number of T1w images", fontsize=12)
    ax.set_title(
        f"Pizarro — image-level artifact probability (n={n} T1w)",
        fontsize=14,
        fontweight="bold",
        color=C_TXT,
    )
    ax.legend(frameon=False, fontsize=10)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.text(
        0.98,
        0.02,
        "Descriptive only — not a failure rate / not used for exclusion",
        transform=ax.transAxes,
        ha="right",
        va="bottom",
        fontsize=8.5,
        color="#6B7280",
        style="italic",
    )
    fig.tight_layout()
    for ext in ("png", "pdf"):
        fig.savefig(
            out / f"Figure_Pizarro_probability_hist_PI.{ext}",
            dpi=220,
            bbox_inches="tight",
            facecolor="white",
        )
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(9.5, 6.2), dpi=200)
    sc = ax.scatter(probs, uncs, c=confs, cmap="viridis", s=28, alpha=0.75, edgecolors="none")
    cb = fig.colorbar(sc, ax=ax, pad=0.02)
    cb.set_label("Confidence", fontsize=10)
    ax.set_xlabel("Artifact probability", fontsize=12)
    ax.set_ylabel("Uncertainty (bits)", fontsize=12)
    ax.set_title(
        "Pizarro screening space — probability vs uncertainty",
        fontsize=14,
        fontweight="bold",
        color=C_TXT,
    )
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.text(
        0.02,
        0.98,
        "High P → review first\nHigh U → ambiguous votes (also review)",
        transform=ax.transAxes,
        va="top",
        fontsize=9.5,
        color="#374151",
        bbox=dict(boxstyle="round,pad=0.35", facecolor="#F8FAFC", edgecolor="#CBD5E1"),
    )
    fig.tight_layout()
    for ext in ("png", "pdf"):
        fig.savefig(
            out / f"Figure_Pizarro_prob_vs_uncert_PI.{ext}",
            dpi=220,
            bbox_inches="tight",
            facecolor="white",
        )
    plt.close(fig)

    fig, axes = plt.subplots(1, 2, figsize=(15, 6.5), dpi=200)
    panels = [
        (axes[0], top_p, "Top 10 — highest artifact probability\n(inspect first)", "artifact_probability", "#B42318"),
        (axes[1], top_u, "Top 10 — highest uncertainty\n(ambiguous model votes)", "uncertainty", "#C47A00"),
    ]
    for ax, tab, title, colkey, color in panels:
        ax.axis("off")
        ax.set_title(title, fontsize=12, fontweight="bold", color=C_TXT, pad=12)
        fn_col = "filename" if tab and "filename" in tab[0] else (list(tab[0].keys())[0] if tab else "filename")
        y0 = 0.92
        ax.text(0.02, y0, "#", fontweight="bold", fontsize=9, transform=ax.transAxes)
        ax.text(0.10, y0, "Image", fontweight="bold", fontsize=9, transform=ax.transAxes)
        ax.text(0.78, y0, colkey.replace("_", " ")[:14], fontweight="bold", fontsize=9, transform=ax.transAxes)
        for i, row in enumerate(tab[:10], start=1):
            y = 0.84 - (i - 1) * 0.075
            ax.add_patch(
                FancyBboxPatch(
                    (0.01, y - 0.025),
                    0.98,
                    0.065,
                    transform=ax.transAxes,
                    boxstyle="round,pad=0.01,rounding_size=0.02",
                    facecolor="#F8FAFC" if i % 2 else "white",
                    edgecolor="#E5E7EB",
                    lw=0.8,
                )
            )
            ax.text(0.03, y, str(i), transform=ax.transAxes, fontsize=9, va="center", fontweight="bold", color=color)
            ax.text(
                0.10,
                y,
                short_name(row.get(fn_col, "")),
                transform=ax.transAxes,
                fontsize=8.2,
                va="center",
                family="monospace",
            )
            raw = row.get(colkey, "")
            try:
                val_s = f"{float(raw):.2g}"
            except (TypeError, ValueError):
                val_s = str(raw)
            ax.text(0.90, y, val_s, transform=ax.transAxes, fontsize=9, va="center", ha="right", fontweight="bold")
        ax.text(
            0.5,
            0.02,
            "Visual QC priority only — not an exclusion list",
            transform=ax.transAxes,
            ha="center",
            fontsize=8,
            color="#6B7280",
            style="italic",
        )
    fig.suptitle("Pizarro — manual review priority lists", fontsize=15, fontweight="bold", color=C_TXT, y=0.98)
    fig.tight_layout(rect=[0, 0, 1, 0.95])
    for ext in ("png", "pdf"):
        fig.savefig(
            out / f"Figure_Pizarro_review_priority_PI.{ext}",
            dpi=220,
            bbox_inches="tight",
            facecolor="white",
        )
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(9.5, 5.5), dpi=200)
    ax.hist(uncs, bins=12, color="#8B5CF6", edgecolor="white", linewidth=1.2)
    ax.set_xlabel("Uncertainty (bits)", fontsize=12)
    ax.set_ylabel("Number of T1w images", fontsize=12)
    ax.set_title("Pizarro — uncertainty distribution (MC dropout)", fontsize=14, fontweight="bold", color=C_TXT)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.text(
        0.98,
        0.02,
        "Max uncertainty = 1 bit when artifact votes are split 50/50",
        transform=ax.transAxes,
        ha="right",
        fontsize=8.5,
        color="#6B7280",
        style="italic",
    )
    fig.tight_layout()
    for ext in ("png", "pdf"):
        fig.savefig(
            out / f"Figure_Pizarro_uncertainty_PI.{ext}",
            dpi=220,
            bbox_inches="tight",
            facecolor="white",
        )
    plt.close(fig)

    if ms is not None:
        ms.mkdir(parents=True, exist_ok=True)
        for p in out.glob("Figure_Pizarro_*_PI.*"):
            shutil.copy2(p, ms / p.name)

    return {
        "n_images": n,
        "n_subjects": n_subj,
        "n_ses02": n_ses02,
        "mean_p": mean_p,
        "median_p": median_p,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--src", type=Path, default=DEFAULT_SRC)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--manuscript-dir", type=Path, default=DEFAULT_MS)
    ap.add_argument("--no-manuscript-copy", action="store_true")
    ap.add_argument(
        "--scope-label",
        default=None,
        help="Subtitle scope string shown on the overview figure",
    )
    ap.add_argument(
        "--run",
        default=None,
        help="Keep only this BIDS run (e.g. 01 or run-01). Recomputes top-10 lists.",
    )
    args = ap.parse_args()
    ms = None if args.no_manuscript_copy else args.manuscript_dir
    run = normalize_run(args.run) if args.run else None
    if args.scope_label is not None:
        scope_label = args.scope_label
    elif run:
        scope_label = f"T1w only · run-{run}"
    else:
        scope_label = "T1w_MPR (all runs)"
    stats = build_figures(
        args.src.expanduser(),
        args.out.expanduser(),
        ms,
        scope_label=scope_label,
        run=run,
    )
    run_txt = f" run-{run}" if run else ""
    print(
        f"Wrote PI figures to {args.out}{run_txt} "
        f"(n={stats['n_images']} subjects={stats['n_subjects']} "
        f"ses02={stats['n_ses02']} mean={stats['mean_p']:.1f} median={stats['median_p']:.0f})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
