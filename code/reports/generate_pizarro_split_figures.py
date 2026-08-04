#!/usr/bin/env python3
"""Generate Pizarro figures split by BIDS run and by T1 modality.

Outputs under reports/pizarro_qc_split_figures/:

  by_run/run-01|02|03/     — full PI figure set for that run (all T1 modalities)
  by_modality/<SeriesDescription>/  — full PI figure set for that sequence (all runs)

Modalities kept (T1 only):
  T1w_MPR, WMn_MPRAGE_sagittal, T1w_MPR_ND

Example:
  python3 code/reports/generate_pizarro_split_figures.py
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import sys
from collections import defaultdict
from pathlib import Path

HOME = Path.home()
SCRATCH = HOME / "scratch"
DEFAULT_PRED = SCRATCH / "reports" / "pizarro_qc_revised" / "image_level_predictions.tsv"
DEFAULT_BIDS = SCRATCH / "bids"
DEFAULT_OUT = SCRATCH / "reports" / "pizarro_qc_split_figures"

# Canonical modality labels for filenames / folders
MODALITY_ALIASES = {
    "T1w_MPR": "T1w_MPR",
    "T1w": "T1w_MPR",
    "T1w_MPR_ND": "T1w_MPR_ND",
    "WMn_MPRAGE_sagittal": "WMn_MPRAGE_sagittal",
}
KEEP_MODALITIES = ("T1w_MPR", "WMn_MPRAGE_sagittal", "T1w_MPR_ND")
KEEP_RUNS = ("01", "02", "03")


def normalize_run(value: object) -> str:
    s = str(value).strip()
    if s.isdigit():
        return f"{int(s):02d}"
    if s.startswith("run-"):
        return normalize_run(s[4:])
    return s


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh, delimiter="\t"))


def write_tsv(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames, delimiter="\t", extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def modality_from_bids(bids: Path, row: dict[str, str]) -> str:
    """Resolve SeriesDescription / ProtocolName from BIDS sidecar."""
    img = Path(str(row.get("image_path") or ""))
    if not img.is_file():
        # rebuild from BIDS root
        sub = row.get("subject", "")
        ses = row.get("session", "")
        fn = row.get("filename", "")
        img = bids / sub / ses / "anat" / fn
    js = img.with_name(img.name.replace("_T1w.nii.gz", "_T1w.json"))
    if not js.is_file():
        return "UNKNOWN"
    try:
        meta = json.loads(js.read_text(encoding="utf-8"))
    except Exception:
        return "UNKNOWN"
    series = str(meta.get("SeriesDescription") or "").strip()
    proto = str(meta.get("ProtocolName") or "").strip()
    raw = series or proto or "UNKNOWN"
    return MODALITY_ALIASES.get(raw, raw)


def enrich_rows(pred_tsv: Path, bids: Path) -> list[dict[str, str]]:
    rows = read_tsv(pred_tsv)
    out: list[dict[str, str]] = []
    for r in rows:
        r = dict(r)
        r["run"] = normalize_run(r.get("run", ""))
        r["modality"] = modality_from_bids(bids, r)
        # keep T1 only (all Pizarro rows should already be T1w)
        if not str(r.get("filename", "")).endswith("_T1w.nii.gz"):
            continue
        out.append(r)
    return out


def write_mini_package(dest: Path, rows: list[dict[str, str]]) -> None:
    """Write a pizarro_qc_revised-like folder consumable by generate_pizarro_pi_figures."""
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True, exist_ok=True)
    if not rows:
        raise ValueError(f"empty subset for {dest}")
    keys = list(rows[0].keys())
    write_tsv(dest / "image_level_predictions.tsv", rows, keys)
    # top-10 lists
    top_p = sorted(rows, key=lambda r: float(r["artifact_probability"]), reverse=True)[:10]
    top_u = sorted(rows, key=lambda r: float(r["uncertainty"]), reverse=True)[:10]
    write_tsv(dest / "manual_review_top10_artifact_probability.tsv", top_p, keys)
    write_tsv(dest / "manual_review_top10_uncertainty.tsv", top_u, keys)


def run_figure_builder(
    src_pkg: Path,
    out_dir: Path,
    scope_label: str,
) -> dict:
    # Import sibling module
    sys.path.insert(0, str(SCRATCH / "code" / "reports"))
    from generate_pizarro_pi_figures import build_figures  # noqa: WPS433

    out_dir.mkdir(parents=True, exist_ok=True)
    return build_figures(
        src_pkg,
        out_dir,
        ms=None,
        scope_label=scope_label,
        run=None,
    )


def safe_folder(name: str) -> str:
    return name.replace("/", "_").replace(" ", "_")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--predictions", type=Path, default=DEFAULT_PRED)
    ap.add_argument("--bids", type=Path, default=DEFAULT_BIDS)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument(
        "--also-run-by-modality",
        action="store_true",
        help="Also write by_run_and_modality/run-XX/<modality>/ figure sets",
    )
    args = ap.parse_args()

    out = args.out.expanduser()
    out.mkdir(parents=True, exist_ok=True)

    print("Enriching predictions with SeriesDescription from BIDS…", flush=True)
    rows = enrich_rows(args.predictions.expanduser(), args.bids.expanduser())
    write_tsv(
        out / "image_level_predictions_with_modality.tsv",
        rows,
        list(rows[0].keys()),
    )

    # counts
    by_mod: dict[str, int] = defaultdict(int)
    by_run: dict[str, int] = defaultdict(int)
    for r in rows:
        by_mod[r["modality"]] += 1
        by_run[r["run"]] += 1
    print("By modality:", dict(by_mod), flush=True)
    print("By run:", dict(by_run), flush=True)

    staging = out / "_staging"
    if staging.exists():
        shutil.rmtree(staging)

    summary_lines = [
        "# Pizarro figures split by run and modality",
        "",
        "Generated from `pizarro_qc_revised/image_level_predictions.tsv` + BIDS `*_T1w.json`.",
        "",
        "## Coverage",
        "",
        f"- Total T1w scored rows: **{len(rows)}**",
        "",
        "### By run",
        "",
    ]
    for run in KEEP_RUNS:
        summary_lines.append(f"- run-{run}: {by_run.get(run, 0)}")
    summary_lines += ["", "### By modality", ""]
    for mod in KEEP_MODALITIES:
        summary_lines.append(f"- `{mod}`: {by_mod.get(mod, 0)}")
    summary_lines += ["", "## Outputs", ""]

    # --- by run ---
    for run in KEEP_RUNS:
        subset = [r for r in rows if r["run"] == run]
        if not subset:
            print(f"Skip run-{run}: empty", flush=True)
            continue
        pkg = staging / f"run-{run}"
        fig_dir = out / "by_run" / f"run-{run}"
        write_mini_package(pkg, subset)
        label = f"T1w only · run-{run} (all T1 sequences)"
        stats = run_figure_builder(pkg, fig_dir, label)
        print(
            f"run-{run}: n={stats['n_images']} mean={stats['mean_p']:.1f} → {fig_dir}",
            flush=True,
        )
        summary_lines.append(
            f"- `by_run/run-{run}/` — n={stats['n_images']}, "
            f"mean artifact P={stats['mean_p']:.1f}, median={stats['median_p']:.0f}"
        )

    # --- by modality ---
    summary_lines += ["", "### By modality folders", ""]
    for mod in KEEP_MODALITIES:
        subset = [r for r in rows if r["modality"] == mod]
        if not subset:
            print(f"Skip modality {mod}: empty", flush=True)
            continue
        pkg = staging / f"mod_{safe_folder(mod)}"
        fig_dir = out / "by_modality" / safe_folder(mod)
        write_mini_package(pkg, subset)
        label = f"T1w · {mod} (all runs)"
        stats = run_figure_builder(pkg, fig_dir, label)
        print(
            f"{mod}: n={stats['n_images']} mean={stats['mean_p']:.1f} → {fig_dir}",
            flush=True,
        )
        summary_lines.append(
            f"- `by_modality/{safe_folder(mod)}/` — n={stats['n_images']}, "
            f"mean artifact P={stats['mean_p']:.1f}, median={stats['median_p']:.0f}"
        )

    # --- optional run × modality ---
    if args.also_run_by_modality:
        summary_lines += ["", "### By run × modality", ""]
        for run in KEEP_RUNS:
            for mod in KEEP_MODALITIES:
                subset = [r for r in rows if r["run"] == run and r["modality"] == mod]
                if len(subset) < 3:
                    continue
                pkg = staging / f"run-{run}_{safe_folder(mod)}"
                fig_dir = out / "by_run_and_modality" / f"run-{run}" / safe_folder(mod)
                write_mini_package(pkg, subset)
                label = f"T1w · {mod} · run-{run}"
                stats = run_figure_builder(pkg, fig_dir, label)
                print(
                    f"run-{run} × {mod}: n={stats['n_images']} → {fig_dir}",
                    flush=True,
                )
                summary_lines.append(
                    f"- `by_run_and_modality/run-{run}/{safe_folder(mod)}/` — n={stats['n_images']}"
                )

    (out / "README.md").write_text("\n".join(summary_lines) + "\n", encoding="utf-8")

    # cleanup staging (keep predictions enriched)
    if staging.exists():
        shutil.rmtree(staging)

    print(f"\nDone. Figures under {out}", flush=True)
    print("See README.md for index.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
