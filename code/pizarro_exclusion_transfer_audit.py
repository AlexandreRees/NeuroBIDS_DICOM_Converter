#!/usr/bin/env python3
"""Audit listed T1w images vs Pizarro / MRIQC and transfer-learning AUC with/without them.

Read-only: does not modify BIDS, MRIQC, or original Pizarro derivatives.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path("/lustre07/scratch/alexrees")
OUT = ROOT / "reports" / "pizarro_exclusion_transfer_audit"
CKPT = ROOT / "pizarro_transfer_learning/output/with_embeddings/extraction_checkpoint.npz"
PRED = ROOT / "reports/pizarro_qc_transfer_calibrated/image_level_predictions.tsv"
PIZ_IMG = ROOT / "neuro_pipeline/reports/pizarro_qc/pizarro_image_results.tsv"
IQM = ROOT / "reports/mriqc_publication_audit/tables/mriqc_iqm_current.tsv"
BIDS = ROOT / "bids"
RELEASE = ROOT / "release_dataset"

# User-listed groups
EMPTY_RUN03 = [
    "sub-039_ses-02_run-03_T1w",
    "sub-058_ses-01_run-03_T1w",
    "sub-066_ses-02_run-03_T1w",
]
LOW_CNR_MPR_RUN01 = [
    "sub-066_ses-01_run-01_T1w",
    "sub-040_ses-01_run-01_T1w",
    "sub-013_ses-01_run-01_T1w",
    "sub-071_ses-01_run-01_T1w",
    "sub-040_ses-02_run-01_T1w",
    "sub-082_ses-01_run-01_T1w",
    "sub-076_ses-01_run-01_T1w",
    "sub-078_ses-01_run-01_T1w",
]
UNCERTAIN_50 = [
    "sub-080_ses-01_run-01_T1w",
    "sub-067_ses-01_run-02_T1w",
    "sub-018_ses-01_run-02_T1w",
    "sub-017_ses-01_run-02_T1w",
    "sub-029_ses-01_run-02_T1w",
]
WMN_MRIQC = [
    "sub-084_ses-01_run-03_T1w",
    "sub-030_ses-01_run-03_T1w",
    "sub-066_ses-01_run-03_T1w",
    "sub-012_ses-01_run-03_T1w",
    "sub-012_ses-02_run-03_T1w",
]

STEM_RE = re.compile(r"(sub-\d+_ses-\d+_run-\d+_T1w)")


def stem_of(s: str) -> str:
    m = STEM_RE.search(str(s))
    return m.group(1) if m else Path(str(s)).name.replace(".nii.gz", "")


def run_of(stem: str) -> str:
    m = re.search(r"run-(\d+)", stem)
    return m.group(1) if m else ""


def nifti_header_stats(path: Path) -> dict:
    """Sidecar + existence only (no NIfTI voxel/header load)."""
    out = {
        "exists": path.is_file(),
        "series_description": "",
        "protocol_name": "",
    }
    js = Path(str(path).replace(".nii.gz", ".json"))
    if js.is_file():
        try:
            meta = json.loads(js.read_text(encoding="utf-8"))
            out["series_description"] = str(meta.get("SeriesDescription", ""))
            out["protocol_name"] = str(meta.get("ProtocolName", ""))
        except Exception:
            pass
    return out


def roc_auc(y: np.ndarray, scores: np.ndarray) -> float:
    y = np.asarray(y).astype(int)
    s = np.asarray(scores, dtype=float)
    pos = s[y == 1]
    neg = s[y == 0]
    if pos.size == 0 or neg.size == 0:
        return float("nan")
    diff = pos[:, None] - neg[None, :]
    return float((np.sum(diff > 0) + 0.5 * np.sum(diff == 0)) / (pos.size * neg.size))


def accuracy(y, p):
    y = np.asarray(y).astype(int)
    p = np.asarray(p).astype(int)
    return float((y == p).mean())


def balanced_acc(y, p):
    y = np.asarray(y).astype(int)
    p = np.asarray(p).astype(int)
    recs = []
    for c in (0, 1):
        m = y == c
        recs.append((p[m] == c).mean() if m.any() else np.nan)
    return float(np.nanmean(recs))


def f1_bin(y, p):
    y = np.asarray(y).astype(int)
    p = np.asarray(p).astype(int)
    tp = np.sum((y == 1) & (p == 1))
    fp = np.sum((y == 0) & (p == 1))
    fn = np.sum((y == 1) & (p == 0))
    prec = tp / (tp + fp) if (tp + fp) else 0.0
    rec = tp / (tp + fn) if (tp + fn) else 0.0
    return float(0.0 if (prec + rec) == 0 else 2 * prec * rec / (prec + rec))


def mcc_bin(y, p):
    y = np.asarray(y).astype(int)
    p = np.asarray(p).astype(int)
    tp = np.sum((y == 1) & (p == 1))
    tn = np.sum((y == 0) & (p == 0))
    fp = np.sum((y == 0) & (p == 1))
    fn = np.sum((y == 1) & (p == 0))
    den = np.sqrt((tp + fp) * (tp + fn) * (tn + fp) * (tn + fn))
    return float(((tp * tn) - (fp * fn)) / den) if den else float("nan")


def fit_lr_balanced(X: np.ndarray, y: np.ndarray, n_iter: int = 400, l2: float = 1.0) -> np.ndarray:
    """L2-regularized logistic regression with class-balanced sample weights."""
    y = np.asarray(y).astype(float)
    mu = X.mean(axis=0)
    sd = X.std(axis=0)
    sd[sd == 0] = 1.0
    Xs = (X - mu) / sd
    Xs = np.c_[np.ones(len(Xs)), Xs]
    n1 = max(y.sum(), 1.0)
    n0 = max(len(y) - n1, 1.0)
    wgt = np.where(y == 1.0, 0.5 * len(y) / n1, 0.5 * len(y) / n0)
    w = np.zeros(Xs.shape[1])
    step = 0.5
    for _ in range(n_iter):
        z = np.clip(Xs @ w, -30, 30)
        p = 1.0 / (1.0 + np.exp(-z))
        grad = (Xs.T @ (wgt * (p - y))) / len(y)
        grad[1:] += (l2 / len(y)) * w[1:]
        w -= step * grad
    return w, mu, sd


def predict_lr(X, w, mu, sd):
    sd = sd.copy()
    sd[sd == 0] = 1.0
    Xs = np.c_[np.ones(len(X)), (X - mu) / sd]
    z = np.clip(Xs @ w, -30, 30)
    return 1.0 / (1.0 + np.exp(-z))


def lr_oof(X: np.ndarray, y: np.ndarray, seed: int = 1010, n_splits: int = 5) -> dict:
    y = np.asarray(y).astype(int)
    rng = np.random.default_rng(seed)
    if len(np.unique(y)) < 2:
        return {"n": int(len(y)), "roc_auc": np.nan, "accuracy": np.nan,
                "balanced_accuracy": np.nan, "f1": np.nan, "mcc": np.nan,
                "n_pos": int(y.sum()), "n_neg": int((1 - y).sum())}
    idx = np.arange(len(y))
    folds = np.zeros(len(y), dtype=int)
    for c in (0, 1):
        cidx = idx[y == c]
        rng.shuffle(cidx)
        folds[cidx] = np.arange(len(cidx)) % n_splits
    proba = np.zeros(len(y), dtype=float)
    for k in range(n_splits):
        te = folds == k
        tr = ~te
        if len(np.unique(y[tr])) < 2:
            proba[te] = y[tr].mean()
            continue
        w, mu, sd = fit_lr_balanced(X[tr], y[tr])
        proba[te] = predict_lr(X[te], w, mu, sd)
    pred = (proba >= 0.5).astype(int)
    return {
        "n": int(len(y)),
        "n_pos": int(y.sum()),
        "n_neg": int((1 - y).sum()),
        "roc_auc": roc_auc(y, proba),
        "accuracy": accuracy(y, pred),
        "balanced_accuracy": balanced_acc(y, pred),
        "f1": f1_bin(y, pred),
        "mcc": mcc_bin(y, pred),
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    print("loading checkpoint", CKPT, flush=True)
    ckpt = np.load(CKPT, allow_pickle=True)
    paths = np.asarray(ckpt["image_paths"])
    X_all = np.asarray(ckpt["embeddings"], dtype=np.float32)
    pz_all = np.asarray(ckpt["pizarro_scores"], dtype=float)
    stems = np.array([stem_of(p) for p in paths])
    runs = np.array([run_of(s) for s in stems])
    # Transfer labels: run-01 = non-NORM (1), run-02 = NORM (0)  [P(non-NORM)]
    y_norm = np.array([1 if r == "01" else 0 for r in runs], dtype=int)
    # QC proxy used in NORM-confounding analysis
    y_qc = (pz_all >= 50).astype(int)

    pred = pd.read_csv(PRED, sep="\t")
    pred["stem"] = pred["filename"].map(stem_of)
    print("loaded predictions", len(pred), flush=True)
    iqm = pd.read_csv(IQM, sep="\t")
    iqm["stem"] = iqm["filename"].map(lambda x: stem_of(str(x)))
    iqm_t1 = iqm[iqm["suffix"].astype(str).str.contains("T1w", case=False, na=False)].copy()
    print("IQM T1w rows", len(iqm_t1), flush=True)

    groups = {
        "empty_run03": EMPTY_RUN03,
        "low_cnr_mpr_run01": LOW_CNR_MPR_RUN01,
        "uncertain_50_50": UNCERTAIN_50,
        "wmn_mriqc": WMN_MRIQC,
    }

    rows = []
    for group, stems_g in groups.items():
        for stem in stems_g:
            rec = {"group": group, "stem": stem, "run": run_of(stem)}
            in_transfer = stem in set(stems)
            rec["in_transfer_set"] = bool(in_transfer)
            rec["in_bids"] = (BIDS / stem.split("_")[0] / stem.split("_")[1] / "anat" / f"{stem}.nii.gz").is_file()
            rec["in_release"] = (
                RELEASE / stem.split("_")[0] / stem.split("_")[1] / "anat" / f"{stem}.nii.gz"
            ).is_file()
            pr = pred[pred["stem"] == stem]
            if len(pr):
                rec["artifact_probability"] = float(pr["artifact_probability"].iloc[0])
                rec["uncertainty"] = float(pr["uncertainty"].iloc[0])
                rec["confidence"] = float(pr["confidence"].iloc[0])
                rec["has_transfer_score"] = bool(pr["has_transfer_score"].iloc[0])
                tp = pr["transfer_proba_nonNORM"].iloc[0]
                rec["transfer_proba_nonNORM"] = float(tp) if pd.notna(tp) else np.nan
            else:
                rec["artifact_probability"] = np.nan
                rec["uncertainty"] = np.nan
                rec["confidence"] = np.nan
                rec["has_transfer_score"] = False
                rec["transfer_proba_nonNORM"] = np.nan
            iq = iqm_t1[iqm_t1["stem"] == stem]
            rec["has_mriqc"] = bool(len(iq))
            for col in ("cnr", "cjv", "qi_2", "snr_csf", "tpm_overlap_gm", "snr_total"):
                rec[col] = float(iq[col].iloc[0]) if len(iq) and col in iq.columns else np.nan
            # NIfTI stats: prefer bids, then release
            bidsp = BIDS / stem.split("_")[0] / stem.split("_")[1] / "anat" / f"{stem}.nii.gz"
            relp = RELEASE / stem.split("_")[0] / stem.split("_")[1] / "anat" / f"{stem}.nii.gz"
            st = nifti_header_stats(bidsp if bidsp.is_file() else relp)
            rec.update({f"nifti_{k}": v for k, v in st.items()})
            if in_transfer:
                idx = int(np.where(stems == stem)[0][0])
                rec["embedding_pizarro_score"] = float(pz_all[idx])
                rec["y_norm_nonNORM"] = int(y_norm[idx])
                rec["y_qc_fail"] = int(y_qc[idx])
            rows.append(rec)

    detail = pd.DataFrame(rows)
    detail.to_csv(OUT / "listed_images_status.tsv", sep="\t", index=False)

    # Transfer ablation
    exclude_in_transfer = {
        "none": set(),
        "low_cnr_mpr_run01": set(LOW_CNR_MPR_RUN01) & set(stems),
        "uncertain_50_50": set(UNCERTAIN_50) & set(stems),
        "low_cnr_plus_uncertain": (set(LOW_CNR_MPR_RUN01) | set(UNCERTAIN_50)) & set(stems),
        "all_listed_in_transfer": (
            set(LOW_CNR_MPR_RUN01) | set(UNCERTAIN_50) | set(EMPTY_RUN03) | set(WMN_MRIQC)
        )
        & set(stems),
    }

    metrics_rows = []
    for name, ex in exclude_in_transfer.items():
        mask = np.array([s not in ex for s in stems])
        for task, y in (("norm_vs_nonNORM", y_norm), ("qc_fail_pizarro_ge50", y_qc)):
            m = lr_oof(X_all[mask], y[mask])
            m.update(
                {
                    "exclusion": name,
                    "task": task,
                    "n_excluded": int((~mask).sum()),
                    "n_kept": int(mask.sum()),
                }
            )
            metrics_rows.append(m)
    metrics = pd.DataFrame(metrics_rows)
    metrics.to_csv(OUT / "transfer_auc_with_without_exclusions.tsv", sep="\t", index=False)

    # Published transfer scores (already-fit LR): evaluate AUC after dropping listed images
    tmap = {
        str(s): float(v)
        for s, v, ht in zip(pred["stem"], pred["transfer_proba_nonNORM"], pred["has_transfer_score"])
        if bool(ht) and pd.notna(v)
    }
    published_rows = []
    for name, ex in exclude_in_transfer.items():
        mask = np.array([s not in ex for s in stems])
        scores = np.array([tmap.get(s, np.nan) for s in stems], dtype=float)
        ok = mask & np.isfinite(scores)
        published_rows.append(
            {
                "exclusion": name,
                "task": "published_transfer_P_nonNORM",
                "n_kept": int(ok.sum()),
                "n_excluded": int(mask.sum() - ok.sum()) + int((~mask).sum()),
                "roc_auc": roc_auc(y_norm[ok], scores[ok]) if ok.sum() else np.nan,
            }
        )
        published_rows.append(
            {
                "exclusion": name,
                "task": "published_transfer_vs_qc_fail",
                "n_kept": int(ok.sum()),
                "n_excluded": int((~mask).sum()),
                "roc_auc": roc_auc(y_qc[ok], scores[ok]) if ok.sum() else np.nan,
            }
        )
    pub = pd.DataFrame(published_rows)
    pub.to_csv(OUT / "published_transfer_auc_exclusions.tsv", sep="\t", index=False)

    # Original Pizarro screening stats on full calibrated table
    def piz_summary(df: pd.DataFrame, label: str) -> dict:
        p = pd.to_numeric(df["artifact_probability"], errors="coerce")
        return {
            "subset": label,
            "n": int(p.notna().sum()),
            "mean_P": float(p.mean()),
            "median_P": float(p.median()),
            "frac_P_ge90": float((p >= 90).mean()),
            "frac_P_ge50": float((p >= 50).mean()),
            "frac_uncertain_50": float((p == 50).mean()) if p.notna().any() else np.nan,
        }

    empty_stems = set(EMPTY_RUN03)
    wmn_stems = set(WMN_MRIQC)
    listed_all = set(EMPTY_RUN03 + LOW_CNR_MPR_RUN01 + UNCERTAIN_50 + WMN_MRIQC)
    screen_rows = [
        piz_summary(pred, "all_scored_T1w"),
        piz_summary(pred[~pred["stem"].isin(empty_stems)], "drop_empty_run03"),
        piz_summary(pred[~pred["stem"].isin(wmn_stems)], "drop_listed_wmn_run03"),
        piz_summary(pred[~pred["stem"].isin(listed_all)], "drop_all_listed"),
        piz_summary(pred[pred["run"].astype(str).isin(["1", "01", "1.0"]) | (pred["run"].astype(str) == "01")], "run01_only"),
    ]
    # run filter more carefully
    pred["run_norm"] = pred["run"].astype(str).str.replace(r"^0", "", regex=True)
    screen_rows = [
        piz_summary(pred, "all_scored_T1w"),
        piz_summary(pred[~pred["stem"].isin(empty_stems)], "drop_empty_run03"),
        piz_summary(pred[~pred["stem"].isin(wmn_stems)], "drop_listed_wmn_run03"),
        piz_summary(pred[~pred["stem"].isin(listed_all)], "drop_all_listed"),
        piz_summary(pred[pred["run_norm"] == "1"], "run01_only"),
        piz_summary(pred[pred["run_norm"] == "2"], "run02_only"),
        piz_summary(pred[pred["run_norm"] == "3"], "run03_only"),
        piz_summary(
            pred[(pred["run_norm"] == "3") & ~pred["stem"].isin(empty_stems | wmn_stems)],
            "run03_drop_listed",
        ),
    ]
    pd.DataFrame(screen_rows).to_csv(OUT / "pizarro_screening_stats_exclusions.tsv", sep="\t", index=False)

    # Baseline vs excluded AUC delta
    base_norm = metrics[(metrics.exclusion == "none") & (metrics.task == "norm_vs_nonNORM")].iloc[0]
    base_qc = metrics[(metrics.exclusion == "none") & (metrics.task == "qc_fail_pizarro_ge50")].iloc[0]
    summary = {
        "transfer_n": int(len(stems)),
        "empty_run03_in_transfer": [s for s in EMPTY_RUN03 if s in set(stems)],
        "wmn_run03_in_transfer": [s for s in WMN_MRIQC if s in set(stems)],
        "low_cnr_in_transfer": sorted(set(LOW_CNR_MPR_RUN01) & set(stems)),
        "uncertain_in_transfer": sorted(set(UNCERTAIN_50) & set(stems)),
        "auc_norm_baseline": base_norm["roc_auc"],
        "auc_qc_baseline": base_qc["roc_auc"],
        "in_bids_empty": {s: bool(detail.loc[detail.stem == s, "in_bids"].iloc[0]) for s in EMPTY_RUN03 if (detail.stem == s).any()},
        "in_release_empty": {s: bool(detail.loc[detail.stem == s, "in_release"].iloc[0]) for s in EMPTY_RUN03 if (detail.stem == s).any()},
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    print(metrics.to_string(index=False))
    print("wrote", OUT)


if __name__ == "__main__":
    main()
