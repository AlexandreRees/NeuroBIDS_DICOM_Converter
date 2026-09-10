#!/usr/bin/env python3
"""Detailed characterization of PC1–PC10 from the existing T1w IQM PCA.

Reads only pca_T1w_loadings.tsv and pca_T1w_variance.tsv.
Does not recompute PCA, does not modify those files, and does not use
cohorts, FreeSurfer, statistical tests, or machine learning.

Example:
  python code/mriqc_iqm_pca_interpretation_detailed.py
  python code/mriqc_iqm_pca_interpretation_detailed.py --help
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mriqc_iqm_lib import fail, iqm_family, require_columns, require_file  # noqa: E402

LOGGER = logging.getLogger("mriqc_iqm.pca_interpretation_detailed")

N_PCS = 10
TOP_N = 10
N_IQMS_EXPECTED = 56
PC_NAMES = [f"PC{i}" for i in range(1, N_PCS + 1)]
CONTRIB_TOL = 1e-6
INPUT_HASH_TOL_NOTE = (
    "A loading is an association with a PCA axis after IQM z-scoring. "
    "It is not a causal effect, not a quality grade, and not an MRIQC pass/fail."
)

# Conservative groups from MRIQC 24.0.2 anatomical IQM taxonomy
# (noise / information theory / artifacts / other tissue-spatial measures).
# Unlisted names fall through to "other" rather than a guessed label.
FAMILY_GROUP_ORDER = [
    "signal / SNR",
    "contrast",
    "intensity",
    "homogeneity / bias field",
    "artifact",
    "entropy / information",
    "morphology / tissue",
    "smoothness / sharpness",
    "other",
]
FAMILY_COLORS = {
    "signal / SNR": "#4C78A8",
    "contrast": "#F58518",
    "intensity": "#54A24B",
    "homogeneity / bias field": "#E45756",
    "artifact": "#B279A2",
    "entropy / information": "#72B7B2",
    "morphology / tissue": "#FF9DA6",
    "smoothness / sharpness": "#9D755D",
    "other": "#BAB0AC",
}

NEW_OUTPUTS = (
    "pca_T1w_PC1_PC10_detailed.tsv",
    "pca_T1w_PC1_PC10_top10.tsv",
    "pca_T1w_PC1_PC10_family_contributions.tsv",
    "pca_T1w_PC1_PC10_summary.tsv",
    "pca_T1w_PC1_PC10_detailed_report.txt",
    "pca_T1w_PC1_PC10_top_loadings.png",
    "pca_T1w_PC1_PC10_family_contributions.png",
)


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
            "Does not recompute PCA. Does not rename components as quality, "
            "motion, or disease. Loadings are associations, not causes."
        ),
    )
    parser.add_argument(
        "--study-root",
        type=Path,
        default=None,
        help="Study directory (default: parent of this script).",
    )
    parser.add_argument("--loadings-tsv", type=Path, default=None)
    parser.add_argument("--variance-tsv", type=Path, default=None)
    parser.add_argument("--out-dir", type=Path, default=None)
    args = parser.parse_args(argv)
    root = args.study_root.resolve() if args.study_root else study_root_default()
    out = root / "qc_reports" / "mriqc_iqm"
    args.study_root = root
    args.loadings_tsv = (
        args.loadings_tsv.resolve() if args.loadings_tsv else out / "pca_T1w_loadings.tsv"
    )
    args.variance_tsv = (
        args.variance_tsv.resolve() if args.variance_tsv else out / "pca_T1w_variance.tsv"
    )
    args.out_dir = args.out_dir.resolve() if args.out_dir else out
    return args


def configure_logging() -> None:
    LOGGER.setLevel(logging.INFO)
    LOGGER.handlers.clear()
    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S")
    )
    LOGGER.addHandler(handler)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def family_group(iqm: str) -> str:
    """Map an IQM to a broad MRIQC family. Ambiguous names stay 'other'."""
    if iqm.startswith("snrd_") or iqm.startswith("snr_"):
        return "signal / SNR"
    if iqm in {"cjv", "cnr"}:
        return "contrast"
    if iqm.startswith("inu_"):
        return "homogeneity / bias field"
    if iqm.startswith("qi_"):
        return "artifact"
    if iqm in {"efc", "fber"}:
        return "entropy / information"
    if iqm.startswith("fwhm_"):
        return "smoothness / sharpness"
    if iqm.startswith(("icvs_", "rpve_", "tpm_overlap_")):
        return "morphology / tissue"
    if iqm.startswith("summary_") or iqm == "wm2max":
        return "intensity"
    return "other"


def load_loadings(path: Path) -> pd.DataFrame:
    require_file(path, "PCA loadings table")
    df = pd.read_csv(path, sep="\t")
    if "iqm" not in df.columns:
        fail(f"{path} is missing column 'iqm'. Columns: {list(df.columns)}")
    missing_pcs = [c for c in PC_NAMES if c not in df.columns]
    if missing_pcs:
        fail(f"{path} is missing {missing_pcs}. Refusing to recompute PCA.")
    if df["iqm"].isna().any() or (df["iqm"].astype(str).str.strip() == "").any():
        fail(f"{path} has missing IQM names.")
    df = df.set_index("iqm")
    if df.index.has_duplicates:
        fail(f"Duplicate IQM rows in {path}.")
    if len(df) != N_IQMS_EXPECTED:
        fail(f"Expected {N_IQMS_EXPECTED} IQM rows in loadings, found {len(df)}.")
    unexpected_zero_var = [n for n in ("qi_1", "summary_bg_p05") if n in df.index]
    if unexpected_zero_var:
        fail(
            f"Zero-variance IQMs unexpectedly present in loadings: {unexpected_zero_var}."
        )
    numeric = df[PC_NAMES].apply(pd.to_numeric, errors="coerce")
    if numeric.isna().any().any():
        bad = numeric.columns[numeric.isna().any()].tolist()
        fail(f"Non-numeric or missing loadings for {bad} in {path}.")
    if not np.isfinite(numeric.to_numpy()).all():
        fail(f"Non-finite loadings in {path}.")
    return numeric


def load_variance(path: Path) -> pd.DataFrame:
    require_file(path, "PCA variance table")
    df = pd.read_csv(path, sep="\t")
    require_columns(
        df,
        ["component", "explained_variance_ratio", "cumulative_ratio"],
        "PCA variance table",
    )
    missing = [c for c in PC_NAMES if c not in set(df["component"].astype(str))]
    if missing:
        fail(f"{path} is missing variance rows {missing}.")
    out = df.copy()
    out["component"] = out["component"].astype(str)
    ratio = pd.to_numeric(out["explained_variance_ratio"], errors="coerce")
    cumul = pd.to_numeric(out["cumulative_ratio"], errors="coerce")
    if ratio.isna().any() or cumul.isna().any():
        fail(f"Non-numeric variance values in {path}.")
    return out


def n_to_reach(sorted_contrib: np.ndarray, threshold: float) -> int:
    if sorted_contrib.size == 0:
        fail("Empty contribution vector.")
    csum = np.cumsum(sorted_contrib)
    idx = int(np.searchsorted(csum, threshold, side="left"))
    return int(min(idx + 1, sorted_contrib.size))


def characterize(
    loadings: pd.DataFrame, variance: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, list[str]]:
    checks: list[str] = []
    detailed_rows: list[dict[str, object]] = []
    family_rows: list[dict[str, object]] = []
    summary_rows: list[dict[str, object]] = []

    checks.append(f"PC1–PC10 present in loadings: yes ({', '.join(PC_NAMES)})")
    checks.append(f"N IQMs in loadings: {loadings.shape[0]} (expected {N_IQMS_EXPECTED})")
    checks.append("Unexpected missing loadings on PC1–PC10: none")

    for pc in PC_NAMES:
        vec = loadings[pc].astype(float)
        ss = float(np.square(vec).sum())
        if ss <= 0:
            fail(f"{pc} has a zero loading vector.")
        contrib = np.square(vec) / ss
        contrib_sum = float(contrib.sum())
        if abs(contrib_sum - 1.0) > CONTRIB_TOL:
            fail(f"{pc} relative contributions sum to {contrib_sum:.10f}, not 1.")
        if abs(ss - 1.0) > 1e-4:
            checks.append(f"{pc} sum(loading^2)={ss:.8f} (contributions still normalized to 1)")
        else:
            checks.append(f"{pc} sum(loading^2)={ss:.8f}; sum(relative contribution)={contrib_sum:.10f}")

        order = vec.abs().sort_values(ascending=False).index
        ranked_contrib = np.array([float(contrib.loc[iqm]) for iqm in order], dtype=float)
        n50 = n_to_reach(ranked_contrib, 0.50)
        n75 = n_to_reach(ranked_contrib, 0.75)
        n90 = n_to_reach(ranked_contrib, 0.90)

        var_row = variance.loc[variance["component"] == pc].iloc[0]
        var_ratio = float(var_row["explained_variance_ratio"])
        cumul = float(var_row["cumulative_ratio"])

        family_share: dict[str, float] = {name: 0.0 for name in FAMILY_GROUP_ORDER}
        family_n: dict[str, int] = {name: 0 for name in FAMILY_GROUP_ORDER}
        for iqm in vec.index:
            grp = family_group(str(iqm))
            family_share[grp] = family_share.get(grp, 0.0) + float(contrib.loc[iqm])
            family_n[grp] = family_n.get(grp, 0) + 1

        for grp in FAMILY_GROUP_ORDER:
            family_rows.append(
                {
                    "pc": pc,
                    "family_group": grp,
                    "n_iqms": family_n[grp],
                    "contribution": family_share[grp],
                    "contribution_pct": 100.0 * family_share[grp],
                    "explained_variance_ratio": var_ratio,
                }
            )
        fam_sum = sum(family_share.values())
        if abs(fam_sum - 1.0) > CONTRIB_TOL:
            fail(f"{pc} family contributions sum to {fam_sum:.10f}, not 1.")

        dominant_family = max(FAMILY_GROUP_ORDER, key=lambda g: family_share[g])
        top_iqms = list(order[:TOP_N])
        top5 = list(order[:5])
        top_contrib = float(sum(float(contrib.loc[i]) for i in top_iqms))
        top5_contrib = float(sum(float(contrib.loc[i]) for i in top5))
        n_pos = sum(1 for i in top_iqms if float(vec.loc[i]) > 0)
        n_neg = sum(1 for i in top_iqms if float(vec.loc[i]) < 0)

        for rank, iqm in enumerate(order, start=1):
            loading = float(vec.loc[iqm])
            if loading > 0:
                sign = "+"
            elif loading < 0:
                sign = "-"
            else:
                sign = "0"
            detailed_rows.append(
                {
                    "pc": pc,
                    "rank_abs_loading": rank,
                    "iqm": iqm,
                    "iqm_family": iqm_family(str(iqm)),
                    "family_group": family_group(str(iqm)),
                    "loading": loading,
                    "abs_loading": abs(loading),
                    "loading_squared": float(loading * loading),
                    "contribution": float(contrib.loc[iqm]),
                    "sign": sign,
                    "in_top10": rank <= TOP_N,
                    "explained_variance_ratio": var_ratio,
                    "cumulative_ratio": cumul,
                    "sum_loading_squared": ss,
                }
            )

        summary_rows.append(
            {
                "pc": pc,
                "explained_variance_ratio": var_ratio,
                "cumulative_ratio": cumul,
                "explained_variance_pct": 100.0 * var_ratio,
                "top5_iqms": ";".join(str(i) for i in top5),
                "top10_iqms": ";".join(str(i) for i in top_iqms),
                "top5_contribution": top5_contrib,
                "top10_contribution": top_contrib,
                "dominant_family": dominant_family,
                "dominant_family_contribution": family_share[dominant_family],
                "n_iqms_for_50pct": n50,
                "n_iqms_for_75pct": n75,
                "n_iqms_for_90pct": n90,
                "n_positive_in_top10": n_pos,
                "n_negative_in_top10": n_neg,
            }
        )

    detailed = pd.DataFrame(detailed_rows)
    top = detailed.loc[detailed["in_top10"]].copy()
    families = pd.DataFrame(family_rows)
    summary = pd.DataFrame(summary_rows)
    if len(detailed) != N_PCS * N_IQMS_EXPECTED:
        fail(f"Expected {N_PCS * N_IQMS_EXPECTED} detailed rows, found {len(detailed)}.")
    if len(top) != N_PCS * TOP_N:
        fail(f"Expected {N_PCS * TOP_N} top-10 rows, found {len(top)}.")
    checks.append("Relative contributions sum to ~100% on every PC1–PC10: yes")
    checks.append("Family contributions sum to ~100% on every PC1–PC10: yes")
    checks.append("PCA was not recomputed.")
    return detailed, top, families, summary, checks


def describe_concentration(n50: int, n75: int, n90: int, top10_share: float) -> str:
    if n50 <= 3 and top10_share >= 0.70:
        return (
            "Contribution is concentrated: a small subset of IQMs accounts for "
            f"most of this axis (50% by {n50} IQMs; 90% by {n90}; "
            f"Top 10 share {100 * top10_share:.1f}%)."
        )
    if n50 >= 10 or top10_share < 0.45:
        return (
            "Contribution is dispersed across many IQMs "
            f"(50% requires {n50} IQMs; 90% requires {n90}; "
            f"Top 10 share {100 * top10_share:.1f}%)."
        )
    return (
        "Contribution is moderately concentrated "
        f"(50% by {n50} IQMs; 75% by {n75}; 90% by {n90}; "
        f"Top 10 share {100 * top10_share:.1f}%)."
    )


def signed_iqm_phrase(pc: str, detailed: pd.DataFrame, n: int = 5) -> tuple[str, str]:
    sub = detailed.loc[detailed["pc"] == pc].sort_values("rank_abs_loading")
    pos = [r.iqm for r in sub.itertuples(index=False) if r.loading > 0][:n]
    neg = [r.iqm for r in sub.itertuples(index=False) if r.loading < 0][:n]
    pos_txt = ", ".join(pos) if pos else "none among the leading loadings"
    neg_txt = ", ".join(neg) if neg else "none among the leading loadings"
    return pos_txt, neg_txt


def interpret_pc(
    pc: str,
    summary_row: pd.Series,
    families: pd.DataFrame,
    detailed: pd.DataFrame,
) -> list[str]:
    fam = families.loc[families["pc"] == pc].sort_values("contribution", ascending=False)
    top_fams = fam.loc[fam["contribution"] > 0.08]
    fam_txt = "; ".join(
        f"{r.family_group} ({100 * r.contribution:.1f}%)" for r in top_fams.itertuples(index=False)
    )
    top = detailed.loc[detailed["pc"] == pc].sort_values("rank_abs_loading").head(TOP_N)
    top_lines = [
        f"    {int(r.rank_abs_loading):2d}. {r.iqm:18s}  "
        f"loading={r.loading:+.4f}  contribution={100 * r.contribution:.2f}%  "
        f"[{r.family_group}]"
        for r in top.itertuples(index=False)
    ]
    pos_lead, neg_lead = signed_iqm_phrase(pc, top, n=5)
    n_pos = int(summary_row["n_positive_in_top10"])
    n_neg = int(summary_row["n_negative_in_top10"])
    conc = describe_concentration(
        int(summary_row["n_iqms_for_50pct"]),
        int(summary_row["n_iqms_for_75pct"]),
        int(summary_row["n_iqms_for_90pct"]),
        float(summary_row["top10_contribution"]),
    )
    dominant = str(summary_row["dominant_family"])
    var_pct = float(summary_row["explained_variance_pct"])
    cumul_pct = 100.0 * float(summary_row["cumulative_ratio"])

    top1 = top.iloc[0]
    top1_note = (
        f" The single largest |loading| is {top1['iqm']} "
        f"[{top1['family_group']}; loading={float(top1['loading']):+.3f}]."
    )
    n_intensity = int(fam.loc[fam["family_group"] == "intensity", "n_iqms"].iloc[0])
    size_note = (
        f" Family shares are sums of loading². The intensity group contains "
        f"{n_intensity} IQMs (summary_* and wm2max), so it can rank first even "
        "when the largest individual loadings belong to another group."
    )

    functional = {
        "signal / SNR": (
            "This component appears to capture a multivariate axis on which "
            "signal-to-noise IQMs (including Dietrich SNR where present) have "
            "large weights."
        ),
        "contrast": (
            "This component appears to capture a multivariate axis dominated by "
            "contrast-related IQMs (CJV/CNR)."
        ),
        "intensity": (
            "This component appears to capture a multivariate axis dominated by "
            "tissue or background intensity-summary IQMs."
        ),
        "homogeneity / bias field": (
            "This component appears to capture a multivariate axis with a large "
            "share of intensity-nonuniformity (INU / bias-field) IQMs."
        ),
        "artifact": (
            "This component appears to capture a multivariate axis with a "
            "noticeable weight on Mortamet QI2 (artifact-related)."
        ),
        "entropy / information": (
            "This component appears to capture a multivariate axis involving "
            "information-theory IQMs (EFC and/or FBER)."
        ),
        "morphology / tissue": (
            "This component appears to capture a multivariate axis dominated by "
            "tissue-fraction, residual partial-volume, and/or template-overlap IQMs."
        ),
        "smoothness / sharpness": (
            "This component appears to capture a multivariate axis dominated by "
            "spatial smoothness / FWHM IQMs."
        ),
    }.get(
        dominant,
        "This component does not have a single well-identified family dominating the loadings.",
    )

    # PC-specific descriptive notes from the actual leading IQMs (not quality labels).
    extra = ""
    names = set(top["iqm"].astype(str))
    if pc == "PC1":
        extra = (
            " Leading weights mix high-percentile GM/WM intensities, INU magnitude, "
            "WM-to-max intensity, WM volume fraction, and opposite CJV vs CNR signs. "
            "That is a joint intensity–, contrast–, and bias-field-related combination, "
            "not a demonstration that PC1 equals image quality."
        )
    elif pc == "PC2":
        extra = (
            " Standard SNR IQMs load in one direction while residual partial-volume "
            "IQMs (rpve_*) load in the opposite direction among the leaders. "
            "This describes co-variation along the axis, not a motion or disease score."
        )
    elif pc == "PC3":
        extra = (
            " Dietrich SNR IQMs (snrd_*) share the same sign among the leaders, "
            "while EFC and QI2 take the opposite sign. That is consistent with a "
            "noise-model / information-theory contrast on this axis, not a quality grade."
        )
    elif pc == "PC4":
        extra = (
            " The four FWHM IQMs occupy the top ranks with the same sign, so the "
            "axis is closely aligned with spatial smoothness / sharpness metrics."
        )
    elif pc == "PC5":
        extra = (
            " CSF-related SNR and CSF intensity percentiles appear among the leaders "
            "together with Dietrich SNR. This remains a description of metric co-variation."
        )
    elif pc == "PC6":
        extra = (
            " Background-intensity summaries (summary_bg_*) occupy most of the top ranks. "
            "The axis is therefore largely an intensity-summary combination in air/background."
        )
    elif pc == "PC7":
        extra = (
            " Template-overlap IQMs appear together with mixed SNR and intensity summaries. "
            "No single MRIQC construct is exclusive on this axis."
        )
    elif pc == "PC8" and {"rpve_wm", "rpve_gm", "rpve_csf"} <= names:
        extra = (
            " The three residual partial-volume IQMs lead with the same sign, so the "
            "axis is closely aligned with rpve_* co-variation."
        )
    elif pc == "PC9":
        extra = (
            " Intensity-distribution kurtosis (summary_csf_k vs summary_bg_k) and "
            "template-overlap IQMs dominate. Opposite signs among kurtosis IQMs "
            "describe an opposition along this axis, not a clinical label."
        )
    elif pc == "PC10":
        extra = (
            " Background kurtosis, template overlap, and QI2 appear among the leaders. "
            "The axis is mixed rather than a single named artifact construct."
        )

    lines = [
        f"{pc} — explained variance {var_pct:.2f}% (cumulative {cumul_pct:.2f}%)",
        f"  Dominant family by squared-loading share: {dominant} "
        f"({100 * float(summary_row['dominant_family_contribution']):.1f}%).",
        f"  Families with contribution > 8%: {fam_txt or 'none'}.",
        f"  Top 5 contribution: {100 * float(summary_row['top5_contribution']):.1f}%. "
        f"Top 10 contribution: {100 * float(summary_row['top10_contribution']):.1f}%.",
        f"  IQMs needed for 50/75/90% of this PC: "
        f"{int(summary_row['n_iqms_for_50pct'])}/"
        f"{int(summary_row['n_iqms_for_75pct'])}/"
        f"{int(summary_row['n_iqms_for_90pct'])}.",
        f"  {conc}",
        f"  Among the Top 10, {n_pos} loading(s) are positive and {n_neg} are negative.",
        f"  Leading positive loadings: {pos_lead}.",
        f"  Leading negative loadings: {neg_lead}.",
        "  Top 10 IQMs by |loading|:",
        *top_lines,
        f"  Descriptive reading: {functional}{extra}{top1_note} {size_note}",
        f"  {INPUT_HASH_TOL_NOTE}",
        "",
    ]
    return lines


def plot_top_loadings(top: pd.DataFrame, dest: Path) -> None:
    fig, axes = plt.subplots(5, 2, figsize=(12.5, 16.5))
    axes = np.atleast_1d(axes).ravel()
    for i, pc in enumerate(PC_NAMES):
        ax = axes[i]
        sub = top.loc[top["pc"] == pc].sort_values("abs_loading", ascending=True)
        colors = ["#4C78A8" if s == "+" else "#E45756" for s in sub["sign"]]
        ax.barh(sub["iqm"], sub["loading"], color=colors)
        ax.axvline(0.0, color="#333333", lw=0.8)
        ax.set_title(pc, fontsize=10)
        ax.tick_params(labelsize=7)
        ax.set_xlabel("loading" if i >= 8 else "")
    fig.suptitle(
        "T1w PCA PC1–PC10: 10 IQMs with largest |loading|\n"
        "blue = positive loading; red = negative loading\n"
        "Loadings are associations with the axis, not quality scores"
    )
    fig.subplots_adjust(left=0.18, right=0.98, top=0.93, bottom=0.04, wspace=0.55, hspace=0.38)
    fig.savefig(dest, dpi=130)
    plt.close(fig)
    LOGGER.info("Wrote %s", dest)


def plot_family_contributions(families: pd.DataFrame, dest: Path) -> None:
    pivot = (
        families.pivot(index="pc", columns="family_group", values="contribution")
        .reindex(PC_NAMES)
        .reindex(columns=FAMILY_GROUP_ORDER)
        .fillna(0.0)
    )
    fig, ax = plt.subplots(figsize=(11.2, 5.8))
    bottoms = np.zeros(len(PC_NAMES))
    x = np.arange(len(PC_NAMES))
    for fam in FAMILY_GROUP_ORDER:
        vals = pivot[fam].to_numpy(dtype=float)
        if np.allclose(vals, 0.0):
            continue
        ax.bar(
            x,
            vals,
            bottom=bottoms,
            label=fam,
            color=FAMILY_COLORS.get(fam, "#BAB0AC"),
            width=0.78,
        )
        bottoms = bottoms + vals
    ax.set_xticks(x)
    ax.set_xticklabels(PC_NAMES)
    ax.set_ylabel("Share of PC variance (sum of loading²)")
    ax.set_ylim(0.0, 1.02)
    ax.set_title(
        "T1w PCA PC1–PC10: IQM family contributions\n"
        "(squared loadings; families from MRIQC anatomical taxonomy)"
    )
    ax.legend(loc="upper right", fontsize=8, frameon=False, ncol=2)
    fig.tight_layout()
    fig.savefig(dest, dpi=130)
    plt.close(fig)
    LOGGER.info("Wrote %s", dest)


def write_report(
    path: Path,
    *,
    loadings_path: Path,
    variance_path: Path,
    hashes: dict[str, str],
    checks: list[str],
    detailed: pd.DataFrame,
    families: pd.DataFrame,
    summary: pd.DataFrame,
) -> None:
    lines = [
        "T1w IQM PCA detailed interpretation (PC1–PC10)",
        f"generated_at: {datetime.now(timezone.utc).isoformat()}",
        "",
        "SCOPE",
        "  Existing PCA loadings and variance were read only. PCA was not recomputed.",
        "  Source PCA files were not rewritten. Cohorts were not analysed.",
        "  FreeSurfer was not used. No statistical tests and no machine learning.",
        "  Components are not renamed as quality, motion, or disease.",
        "",
        "INPUTS (read-only)",
        f"  loadings: {loadings_path}",
        f"  loadings sha256: {hashes['loadings']}",
        f"  variance: {variance_path}",
        f"  variance sha256: {hashes['variance']}",
        "",
        "DEFINITIONS",
        "  loading: signed weight of a z-scored IQM on a principal component.",
        f"  {INPUT_HASH_TOL_NOTE}",
        "  loading_squared: loading^2.",
        "  contribution: loading_squared / sum(loading_squared) on that PC.",
        "  The global sign of a PC is arbitrary (SVD sign flip); relative signs",
        "  within one PC remain interpretable as opposite directions on that axis.",
        "",
        "FAMILY MAPPING (conservative, MRIQC 24.0.2 anatomical taxonomy)",
        "  signal / SNR            snr_*, snrd_*",
        "  contrast                cjv, cnr",
        "  intensity               summary_*, wm2max",
        "  homogeneity / bias field inu_* (INU)",
        "  artifact                qi_* (QI2; QI1 was zero-variance and not in PCA)",
        "  entropy / information   efc, fber",
        "  morphology / tissue     icvs_*, rpve_*, tpm_overlap_*",
        "  smoothness / sharpness  fwhm_* (MRIQC: sharpness / blurriness)",
        "  other                   unused fallback; no IQM was forced into a family",
        "  Fine-grained iqm_family labels from mriqc_iqm_lib are kept in the TSV.",
        "",
        "CHECKS",
    ]
    lines.extend(f"  - {c}" for c in checks)
    lines.extend(["", "COMPONENT NOTES", ""])
    for _, row in summary.iterrows():
        lines.extend(interpret_pc(str(row["pc"]), row, families, detailed))
    lines.extend(
        [
            "CAVEATS",
            "  Do not read PC1 as 'quality', PC2 as 'motion', or later PCs as disease.",
            "  Those labels are not demonstrated by loadings alone.",
            "  Family contributions are sums of loading². A large family (intensity",
            "  summaries) can dominate the family table without being the largest",
            "  individual loading. Compare the family table with the Top 10 IQMs.",
            "  Family contributions describe which MRIQC metric groups have large",
            "  squared weights on an axis in this T1w sample.",
            "",
            "OUTPUTS (new files only)",
            *[f"  {name}" for name in NEW_OUTPUTS],
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    LOGGER.info("Wrote %s", path)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    configure_logging()
    LOGGER.info("Detailed characterization of existing T1w PCA PC1–PC10")

    hashes = {
        "loadings": file_sha256(args.loadings_tsv),
        "variance": file_sha256(args.variance_tsv),
    }
    loadings = load_loadings(args.loadings_tsv)
    variance = load_variance(args.variance_tsv)
    detailed, top, families, summary, checks = characterize(loadings, variance)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    detailed_path = args.out_dir / "pca_T1w_PC1_PC10_detailed.tsv"
    top_path = args.out_dir / "pca_T1w_PC1_PC10_top10.tsv"
    fam_path = args.out_dir / "pca_T1w_PC1_PC10_family_contributions.tsv"
    sum_path = args.out_dir / "pca_T1w_PC1_PC10_summary.tsv"
    detailed.to_csv(detailed_path, sep="\t", index=False, float_format="%.10g")
    top.to_csv(top_path, sep="\t", index=False, float_format="%.10g")
    families.to_csv(fam_path, sep="\t", index=False, float_format="%.10g")
    summary.to_csv(sum_path, sep="\t", index=False, float_format="%.10g")
    LOGGER.info("Wrote %s", detailed_path)
    LOGGER.info("Wrote %s", top_path)
    LOGGER.info("Wrote %s", fam_path)
    LOGGER.info("Wrote %s", sum_path)

    plot_top_loadings(top, args.out_dir / "pca_T1w_PC1_PC10_top_loadings.png")
    plot_family_contributions(
        families, args.out_dir / "pca_T1w_PC1_PC10_family_contributions.png"
    )

    hashes_after = {
        "loadings": file_sha256(args.loadings_tsv),
        "variance": file_sha256(args.variance_tsv),
    }
    if hashes != hashes_after:
        fail("Input PCA files changed during the run; refusing silent overwrite.")
    checks.append("Source PCA file hashes unchanged after write: yes")

    write_report(
        args.out_dir / "pca_T1w_PC1_PC10_detailed_report.txt",
        loadings_path=args.loadings_tsv,
        variance_path=args.variance_tsv,
        hashes=hashes,
        checks=checks,
        detailed=detailed,
        families=families,
        summary=summary,
    )

    print()
    for _, row in summary.iterrows():
        print(
            f"{row['pc']} — variance: {float(row['explained_variance_pct']):.2f}% "
            f"— dominant family: {row['dominant_family']}"
        )
    print("PCA recomputed: no")
    print("source PCA files unmodified: yes")
    print(f"N detailed rows: {len(detailed)}")
    print(f"N top-10 rows: {len(top)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
