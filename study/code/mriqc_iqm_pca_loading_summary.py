#!/usr/bin/env python3
"""Summarize existing T1w IQM PCA loadings for PC1–PC10.

Reads previously computed PCA tables only. Does not rerun PCA, does not
modify source files, and does not run cohort, FreeSurfer, or outlier steps.

Example:
  python code/mriqc_iqm_pca_loading_summary.py
  python code/mriqc_iqm_pca_loading_summary.py --help
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mriqc_iqm_lib import fail, require_columns, require_file  # noqa: E402

LOGGER = logging.getLogger("mriqc_iqm.pca_loading_summary")
N_PCS = 10
TOP_N = 10
PC_NAMES = [f"PC{i}" for i in range(1, N_PCS + 1)]

PCA_FILENAMES = {
    "loadings": "pca_T1w_loadings.tsv",
    "variance": "pca_T1w_variance.tsv",
    "family": "pca_T1w_PC1_PC10_family_contributions.tsv",
    "top10": "pca_T1w_PC1_PC10_top10.tsv",
}

FAMILY_PHRASE = {
    "intensity": "intensity",
    "contrast": "tissue-contrast",
    "signal / SNR": "signal-to-noise",
    "homogeneity / bias field": "bias-field / intensity-homogeneity",
    "artifact": "artifact-metric",
    "entropy / information": "entropy / energy",
    "morphology / tissue": "tissue-morphology",
    "smoothness / sharpness": "smoothness / sharpness",
    "other": "mixed",
}


def study_root_default() -> Path:
    root = Path(__file__).resolve().parent.parent
    if not (root / "metadata").is_dir() or not (root / "qc_reports").is_dir():
        fail(
            f"Cannot resolve study root from {Path(__file__).resolve()}. "
            "Expected metadata/ and qc_reports/ next to code/. "
            "Pass --study-root explicitly."
        )
    return root


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Each PC is a covariance pattern among IQMs, not a measure of "
            "image quality. Existing PCA files are read only."
        ),
    )
    parser.add_argument("--study-root", type=Path, default=None)
    parser.add_argument("--pca-dir", type=Path, default=None)
    parser.add_argument("--out-dir", type=Path, default=None)
    args = parser.parse_args(argv)
    root = args.study_root.resolve() if args.study_root else study_root_default()
    default_out = root / "qc_reports" / "mriqc_iqm"
    args.study_root = root
    args.out_dir = args.out_dir.resolve() if args.out_dir else default_out
    args.pca_dir = args.pca_dir.resolve() if args.pca_dir else None
    return args


def configure_logging() -> None:
    LOGGER.setLevel(logging.INFO)
    LOGGER.handlers.clear()
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    LOGGER.addHandler(handler)


def resolve_pca_file(study_root: Path, pca_dir: Path | None, filename: str) -> Path:
    candidates: list[Path] = []
    if pca_dir is not None:
        candidates.append(pca_dir / filename)
    candidates.extend(
        [
            study_root / "metadata" / filename,
            study_root / "qc_reports" / "mriqc_iqm" / filename,
        ]
    )
    seen: set[Path] = set()
    unique: list[Path] = []
    for path in candidates:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        unique.append(path)
        if path.is_file():
            return path
    fail(
        f"PCA file {filename} not found. Looked in: "
        + ", ".join(str(p) for p in unique)
    )
    raise AssertionError("unreachable")


def load_variance(path: Path) -> pd.DataFrame:
    require_file(path, "PCA variance table")
    df = pd.read_csv(path, sep="\t")
    require_columns(df, ["component", "explained_variance_ratio"], "PCA variance table")
    df = df.copy()
    df["component"] = df["component"].astype(str)
    missing = [pc for pc in PC_NAMES if pc not in set(df["component"])]
    if missing:
        fail(f"{path} is missing components: {missing}")
    return df.set_index("component")


def load_top10(path: Path) -> pd.DataFrame:
    require_file(path, "PCA PC1–PC10 top-10 table")
    df = pd.read_csv(path, sep="\t")
    require_columns(
        df,
        ["pc", "rank_abs_loading", "iqm", "iqm_family", "family_group", "loading", "abs_loading"],
        "PCA PC1–PC10 top-10 table",
    )
    df = df.copy()
    df["pc"] = df["pc"].astype(str)
    df = df[df["pc"].isin(PC_NAMES)].copy()
    df["rank_abs_loading"] = df["rank_abs_loading"].astype(int)
    df = df.sort_values(["pc", "rank_abs_loading"], kind="mergesort")
    counts = df.groupby("pc").size()
    bad = [pc for pc in PC_NAMES if int(counts.get(pc, 0)) != TOP_N]
    if bad:
        fail(f"{path} does not have exactly {TOP_N} rows for: {bad}")
    return df


def load_family_contributions(path: Path) -> pd.DataFrame:
    require_file(path, "PCA family contribution table")
    df = pd.read_csv(path, sep="\t")
    require_columns(
        df,
        ["pc", "family_group", "contribution", "contribution_pct"],
        "PCA family contribution table",
    )
    df = df.copy()
    df["pc"] = df["pc"].astype(str)
    df = df[df["pc"].isin(PC_NAMES)].copy()
    return df


def load_loadings(path: Path) -> pd.DataFrame:
    require_file(path, "PCA loadings table")
    df = pd.read_csv(path, sep="\t")
    require_columns(df, ["iqm"] + PC_NAMES, "PCA loadings table")
    return df.set_index("iqm")


def contribution_from_loadings(loadings: pd.DataFrame, pc: str, iqms: list[str]) -> float:
    vec = pd.to_numeric(loadings[pc], errors="coerce")
    if vec.isna().any():
        fail(f"Non-numeric loadings on {pc}.")
    total = float((vec * vec).sum())
    if total <= 0:
        fail(f"Sum of squared loadings is {total} for {pc}.")
    selected = vec.loc[iqms]
    return float((selected * selected).sum() / total)


def dominant_family(fam_df: pd.DataFrame, pc: str) -> tuple[str, float]:
    sub = fam_df[fam_df["pc"] == pc]
    if sub.empty:
        fail(f"No family contributions for {pc}.")
    ranked = sub.sort_values("contribution", ascending=False, kind="mergesort")
    row = ranked.iloc[0]
    return str(row["family_group"]), float(row["contribution_pct"])


def ranked_families(fam_df: pd.DataFrame, pc: str) -> list[tuple[str, float]]:
    sub = fam_df[fam_df["pc"] == pc].copy()
    sub = sub[sub["family_group"].astype(str) != "other"]
    sub = sub[sub["contribution"] > 0]
    sub = sub.sort_values("contribution", ascending=False, kind="mergesort")
    return [
        (str(row["family_group"]), float(row["contribution_pct"]))
        for _, row in sub.iterrows()
    ]


def interpretation(pc: str, dominant: str, families: list[tuple[str, float]], top_iqms: list[str]) -> str:
    themes: list[str] = [FAMILY_PHRASE.get(dominant, dominant)]
    top_set = set(top_iqms)
    if {"cjv", "cnr"} & top_set:
        contrast = FAMILY_PHRASE["contrast"]
        if contrast not in themes:
            themes.append(contrast)
    if len(families) > 1:
        second_name, second_pct = families[1]
        second_label = FAMILY_PHRASE.get(second_name, second_name)
        if second_pct >= 15.0 and second_label not in themes:
            themes.append(second_label)
    if len(themes) == 1 and len(families) > 1:
        second_name, second_pct = families[1]
        if second_pct >= 12.0:
            themes.append(FAMILY_PHRASE.get(second_name, second_name))
    themes = themes[:3]
    if len(themes) == 1:
        body = f"{themes[0]}-related variation"
    elif len(themes) == 2:
        body = f"{themes[0]} and {themes[1]}-related variation"
    else:
        body = f"{themes[0]}, {themes[1]}, and {themes[2]}-related variation"
    return f"{pc} is primarily characterized by {body}."


def fmt_loading(value: float) -> str:
    sign = "+" if value > 0 else "-" if value < 0 else " "
    return f"{sign}{abs(value):.6f}"


def write_summary_tsv(dest: Path, rows: list[dict[str, object]]) -> None:
    out = pd.DataFrame(
        rows,
        columns=["PC", "variance_explained", "rank", "IQM", "loading", "abs_loading", "family"],
    )
    dest.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(dest, sep="\t", index=False, float_format="%.10g")
    LOGGER.info("Wrote %s", dest)


def write_summary_txt(
    dest: Path,
    variance: pd.DataFrame,
    top10: pd.DataFrame,
    fam_df: pd.DataFrame,
    loadings: pd.DataFrame,
    source_paths: dict[str, Path],
) -> None:
    lines: list[str] = []
    lines.append("T1w MRIQC IQM PCA — loading summary (PC1–PC10)")
    lines.append("")
    lines.append("Built from existing PCA tables only. PCA was not rerun.")
    lines.append("Each PC is a covariance pattern among IQMs, not a measure of image quality.")
    lines.append("")
    lines.append("Source files:")
    for key in ("loadings", "variance", "family", "top10"):
        lines.append(f"  {key}: {source_paths[key]}")
    lines.append("")

    recap: list[tuple[str, float, str, str, float]] = []

    for pc in PC_NAMES:
        var_ratio = float(variance.loc[pc, "explained_variance_ratio"])
        pc_top = top10[top10["pc"] == pc].sort_values("rank_abs_loading", kind="mergesort")
        iqms = [str(x) for x in pc_top["iqm"].tolist()]
        top5_share = contribution_from_loadings(loadings, pc, iqms[:5])
        top10_share = contribution_from_loadings(loadings, pc, iqms[:10])
        dom_name, dom_pct = dominant_family(fam_df, pc)
        families = ranked_families(fam_df, pc)
        leading = iqms[0]
        recap.append((pc, var_ratio, dom_name, leading, top10_share))

        lines.append("=" * 78)
        lines.append(pc)
        lines.append(f"Variance explained: {100.0 * var_ratio:.2f}%")
        lines.append(
            f"Dominant family: {dom_name} "
            f"({dom_pct:.1f}% of this PC via squared loadings)"
        )
        lines.append(
            f"Top-5 IQM concentration: {100.0 * top5_share:.1f}% of this PC"
        )
        lines.append(
            f"Top-10 IQM concentration: {100.0 * top10_share:.1f}% of this PC"
        )
        lines.append("")
        lines.append("Top 10 IQMs by absolute loading:")
        lines.append(
            f"  {'rank':>4}  {'IQM':<22}  {'loading':>12}  {'|loading|':>10}  family"
        )
        for _, row in pc_top.iterrows():
            rank = int(row["rank_abs_loading"])
            iqm = str(row["iqm"])
            loading = float(row["loading"])
            abs_loading = float(row["abs_loading"])
            family = str(row["iqm_family"])
            lines.append(
                f"  {rank:>4}  {iqm:<22}  {fmt_loading(loading):>12}  "
                f"{abs_loading:>10.6f}  {family}"
            )
        lines.append("")
        lines.append("Interpretation:")
        lines.append(f"  {interpretation(pc, dom_name, families, iqms)}")
        lines.append(
            "  This describes covariance among IQMs on this axis, "
            "not a direct image-quality score."
        )
        lines.append("")

    lines.append("=" * 78)
    lines.append("Summary (PC1–PC10)")
    lines.append("")
    lines.append(
        f"{'PC':<5}  {'var%':>7}  {'dominant family':<28}  "
        f"{'leading IQM':<22}  {'top-10 conc.':>12}"
    )
    lines.append("-" * 78)
    for pc, var_ratio, dom_name, leading, top10_share in recap:
        lines.append(
            f"{pc:<5}  {100.0 * var_ratio:6.2f}%  {dom_name:<28}  "
            f"{leading:<22}  {100.0 * top10_share:10.1f}%"
        )
    lines.append("")
    lines.append(
        "Loadings are associations with a covariance axis. They are not "
        "causal effects and do not measure image quality."
    )
    lines.append("")

    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("\n".join(lines), encoding="utf-8")
    LOGGER.info("Wrote %s", dest)


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    args = parse_args(argv)

    source_paths = {
        key: resolve_pca_file(args.study_root, args.pca_dir, filename)
        for key, filename in PCA_FILENAMES.items()
    }
    for path in source_paths.values():
        LOGGER.info("Using %s", path)

    variance = load_variance(source_paths["variance"])
    top10 = load_top10(source_paths["top10"])
    fam_df = load_family_contributions(source_paths["family"])
    loadings = load_loadings(source_paths["loadings"])

    tsv_rows: list[dict[str, object]] = []
    for pc in PC_NAMES:
        var_ratio = float(variance.loc[pc, "explained_variance_ratio"])
        pc_top = top10[top10["pc"] == pc].sort_values("rank_abs_loading", kind="mergesort")
        for _, row in pc_top.iterrows():
            tsv_rows.append(
                {
                    "PC": pc,
                    "variance_explained": var_ratio,
                    "rank": int(row["rank_abs_loading"]),
                    "IQM": str(row["iqm"]),
                    "loading": float(row["loading"]),
                    "abs_loading": float(row["abs_loading"]),
                    "family": str(row["iqm_family"]),
                }
            )

    out_tsv = args.out_dir / "pca_loading_summary.tsv"
    out_txt = args.out_dir / "pca_loading_summary.txt"
    if out_tsv.resolve() in {p.resolve() for p in source_paths.values()}:
        fail(f"Refusing to overwrite a PCA source file: {out_tsv}")
    if out_txt.resolve() in {p.resolve() for p in source_paths.values()}:
        fail(f"Refusing to overwrite a PCA source file: {out_txt}")

    write_summary_tsv(out_tsv, tsv_rows)
    write_summary_txt(out_txt, variance, top10, fam_df, loadings, source_paths)
    print("PCA loading summary completed successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
