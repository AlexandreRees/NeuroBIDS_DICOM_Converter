#!/usr/bin/env python3
"""Scientific validation: does Pizarro transfer learning learn Siemens NORM vs quality?

READ-ONLY w.r.t. raw_original/, bids/, derivatives/, and
reports/pizarro_qc_transfer_calibrated/.

Reuses precomputed 128-D embeddings. Does not recompute embeddings unless absent.
QC positive class (FAIL): pizarro_score / artifact_probability >= 50.
"""

from __future__ import annotations

import json
import sys
import warnings
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats
from sklearn.calibration import calibration_curve
from sklearn.decomposition import PCA
from sklearn.inspection import permutation_importance
from sklearn.linear_model import LogisticRegression
from sklearn.manifold import TSNE
from sklearn.metrics import (
    accuracy_score,
    balanced_accuracy_score,
    confusion_matrix,
    f1_score,
    matthews_corrcoef,
    precision_score,
    recall_score,
    roc_auc_score,
    roc_curve,
)
from sklearn.model_selection import StratifiedKFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=UserWarning)

ROOT = Path("/lustre07/scratch/alexrees")
TL_DIR = ROOT / "pizarro_transfer_learning" / "output" / "with_embeddings"
CAL_DIR = ROOT / "reports" / "pizarro_qc_transfer_calibrated"
OUT_DIR = ROOT / "reports" / "pizarro_qc_transfer_norm_analysis"

QC_THRESHOLD = 50.0
POSITIVE_LABEL = 1  # FAIL
N_BOOT = 2000
N_SPLITS = 5
RANDOM_STATE = 1010
DPI = 300

# Nature-ish style
mpl.rcParams.update(
    {
        "figure.dpi": DPI,
        "savefig.dpi": DPI,
        "font.family": "DejaVu Sans",
        "font.size": 9,
        "axes.labelsize": 10,
        "axes.titlesize": 11,
        "axes.linewidth": 0.8,
        "xtick.major.width": 0.8,
        "ytick.major.width": 0.8,
        "legend.fontsize": 8,
        "pdf.fonttype": 42,
        "ps.fonttype": 42,
        "axes.spines.top": False,
        "axes.spines.right": False,
    }
)


def build_lr() -> Pipeline:
    return Pipeline(
        steps=[
            ("scaler", StandardScaler()),
            (
                "clf",
                LogisticRegression(
                    max_iter=2000,
                    class_weight="balanced",
                    C=1.0,
                    solver="lbfgs",
                    random_state=RANDOM_STATE,
                ),
            ),
        ]
    )


def normalize_run(s: pd.Series) -> pd.Series:
    return s.astype(str).str.replace(r"^run-", "", regex=True).str.zfill(2)


def load_data() -> tuple[pd.DataFrame, np.ndarray]:
    emb_path = TL_DIR / "pizarro_embeddings.npy"
    idx_path = TL_DIR / "pizarro_embeddings_index.tsv"
    scores_path = TL_DIR / "pizarro_original_scores.tsv"
    if not emb_path.is_file() or not idx_path.is_file():
        raise FileNotFoundError(
            "Embeddings missing. Expected precomputed files under "
            f"{TL_DIR}. Refusing to recompute (read-only analysis)."
        )

    emb = np.load(emb_path)
    idx = pd.read_csv(idx_path, sep="\t")
    scores = pd.read_csv(scores_path, sep="\t")
    if len(emb) != len(idx):
        raise RuntimeError(f"Embedding/index length mismatch: {len(emb)} vs {len(idx)}")

    idx = idx.copy()
    scores = scores.copy()
    idx["run"] = normalize_run(idx["run"])
    scores["run"] = normalize_run(scores["run"])
    key_cols = ["subject", "session", "run"]
    for c in key_cols:
        idx[c] = idx[c].astype(str)
        scores[c] = scores[c].astype(str)

    # Prefer calibrated table artifact_probability when available (read-only)
    cal_path = CAL_DIR / "image_level_predictions.tsv"
    if cal_path.is_file():
        cal = pd.read_csv(cal_path, sep="\t")
        cal["run"] = normalize_run(cal["run"])
        for c in key_cols:
            cal[c] = cal[c].astype(str)
        score_src = cal[key_cols + ["artifact_probability"]].rename(
            columns={"artifact_probability": "pizarro_score"}
        )
    else:
        score_src = scores[key_cols + ["pizarro_score"]]

    df = idx.merge(score_src, on=key_cols, how="left", validate="one_to_one")
    # fallback to TL scores if merge missed
    if df["pizarro_score"].isna().any():
        fallback = scores[key_cols + ["pizarro_score"]].rename(
            columns={"pizarro_score": "pizarro_score_fb"}
        )
        df = df.merge(fallback, on=key_cols, how="left")
        df["pizarro_score"] = df["pizarro_score"].fillna(df["pizarro_score_fb"])
        df = df.drop(columns=["pizarro_score_fb"])

    if "label" in scores.columns:
        lab = scores[key_cols + ["label"]].copy()
        df = df.merge(lab, on=key_cols, how="left")
    else:
        df["label"] = np.where(df["run"] == "01", "non-NORM", "NORM")

    df["qc_fail"] = (df["pizarro_score"] >= QC_THRESHOLD).astype(int)
    df["qc_label"] = np.where(df["qc_fail"] == 1, "FAIL", "PASS")
    df["embedding_row"] = np.arange(len(df))
    return df, emb


def metrics_from_scores(y_true: np.ndarray, y_score: np.ndarray, threshold: float = 0.5) -> dict[str, float]:
    y_true = np.asarray(y_true).astype(int)
    y_score = np.asarray(y_score, dtype=float)
    y_pred = (y_score >= threshold).astype(int)
    out: dict[str, float] = {
        "n": float(len(y_true)),
        "n_positive": float(y_true.sum()),
        "n_negative": float((y_true == 0).sum()),
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "balanced_accuracy": float(balanced_accuracy_score(y_true, y_pred)),
        "precision": float(precision_score(y_true, y_pred, zero_division=0)),
        "recall": float(recall_score(y_true, y_pred, zero_division=0)),
        "f1": float(f1_score(y_true, y_pred, zero_division=0)),
        "mcc": float(matthews_corrcoef(y_true, y_pred)) if len(np.unique(y_true)) > 1 else float("nan"),
    }
    try:
        out["roc_auc"] = float(roc_auc_score(y_true, y_score))
    except ValueError:
        out["roc_auc"] = float("nan")
    tn, fp, fn, tp = confusion_matrix(y_true, y_pred, labels=[0, 1]).ravel()
    out.update({"tn": float(tn), "fp": float(fp), "fn": float(fn), "tp": float(tp)})
    return out


def bootstrap_ci(
    y_true: np.ndarray,
    y_score: np.ndarray,
    n_boot: int = N_BOOT,
    seed: int = RANDOM_STATE,
) -> dict[str, Any]:
    rng = np.random.default_rng(seed)
    y_true = np.asarray(y_true).astype(int)
    y_score = np.asarray(y_score, dtype=float)
    keys = [
        "roc_auc",
        "accuracy",
        "balanced_accuracy",
        "precision",
        "recall",
        "f1",
        "mcc",
    ]
    store = {k: [] for k in keys}
    n = len(y_true)
    for _ in range(n_boot):
        idx = rng.integers(0, n, size=n)
        yt, ys = y_true[idx], y_score[idx]
        if len(np.unique(yt)) < 2:
            continue
        m = metrics_from_scores(yt, ys)
        for k in keys:
            store[k].append(m[k])
    ci: dict[str, Any] = {}
    for k, vals in store.items():
        arr = np.asarray(vals, dtype=float)
        if len(arr) == 0:
            ci[k] = {"mean": float("nan"), "ci95_low": float("nan"), "ci95_high": float("nan"), "n_boot_valid": 0}
        else:
            ci[k] = {
                "mean": float(np.nanmean(arr)),
                "ci95_low": float(np.nanpercentile(arr, 2.5)),
                "ci95_high": float(np.nanpercentile(arr, 97.5)),
                "n_boot_valid": int(np.isfinite(arr).sum()),
            }
    return ci


def oof_cv_predict(X: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, Pipeline]:
    """Stratified CV OOF probabilities; also return model fit on all data."""
    y = np.asarray(y).astype(int)
    n_splits = min(N_SPLITS, int(np.bincount(y).min()))
    if n_splits < 2:
        raise ValueError(f"Need >=2 samples per class; counts={np.bincount(y).tolist()}")
    skf = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=RANDOM_STATE)
    oof = np.full(len(y), np.nan, dtype=float)
    for tr, te in skf.split(X, y):
        pipe = build_lr()
        pipe.fit(X[tr], y[tr])
        oof[te] = pipe.predict_proba(X[te])[:, 1]
    full = build_lr()
    full.fit(X, y)
    return oof, full


def plot_roc(y_true: np.ndarray, y_score: np.ndarray, title: str, out_base: Path) -> None:
    fpr, tpr, _ = roc_curve(y_true, y_score)
    auc = roc_auc_score(y_true, y_score)
    fig, ax = plt.subplots(figsize=(3.5, 3.5))
    ax.plot(fpr, tpr, color="#0B3D91", lw=1.8, label=f"AUC = {auc:.3f}")
    ax.plot([0, 1], [0, 1], color="#888888", lw=1.0, ls="--")
    ax.set_xlabel("False positive rate")
    ax.set_ylabel("True positive rate")
    ax.set_title(title)
    ax.legend(frameon=False, loc="lower right")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    fig.tight_layout()
    fig.savefig(f"{out_base}.png")
    fig.savefig(f"{out_base}.pdf")
    plt.close(fig)


def plot_confusion(y_true: np.ndarray, y_score: np.ndarray, title: str, out_base: Path) -> None:
    y_pred = (y_score >= 0.5).astype(int)
    cm = confusion_matrix(y_true, y_pred, labels=[0, 1])
    fig, ax = plt.subplots(figsize=(3.4, 3.2))
    im = ax.imshow(cm, cmap="Blues")
    ax.set_xticks([0, 1], ["PASS", "FAIL"])
    ax.set_yticks([0, 1], ["PASS", "FAIL"])
    ax.set_xlabel("Predicted")
    ax.set_ylabel("True")
    ax.set_title(title)
    for i in range(2):
        for j in range(2):
            ax.text(j, i, str(cm[i, j]), ha="center", va="center", color="black")
    fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    fig.tight_layout()
    fig.savefig(f"{out_base}.png")
    fig.savefig(f"{out_base}.pdf")
    plt.close(fig)


def plot_calibration(y_true: np.ndarray, y_score: np.ndarray, title: str, out_base: Path) -> None:
    fig, ax = plt.subplots(figsize=(3.5, 3.5))
    try:
        frac_pos, mean_pred = calibration_curve(y_true, y_score, n_bins=8, strategy="quantile")
        ax.plot(mean_pred, frac_pos, "o-", color="#0B3D91", lw=1.5, label="Model")
    except ValueError:
        ax.text(0.5, 0.5, "Calibration undefined\n(insufficient class support)", ha="center", va="center")
    ax.plot([0, 1], [0, 1], "--", color="#888888", lw=1.0, label="Ideal")
    ax.set_xlabel("Mean predicted probability")
    ax.set_ylabel("Fraction of positives (FAIL)")
    ax.set_title(title)
    ax.legend(frameon=False)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    fig.tight_layout()
    fig.savefig(f"{out_base}.png")
    fig.savefig(f"{out_base}.pdf")
    plt.close(fig)


def run_within_split(
    name: str,
    X: np.ndarray,
    y: np.ndarray,
    meta: pd.DataFrame,
    out_dir: Path,
) -> dict[str, Any]:
    print(f"\n=== Analysis {name}: n={len(y)} FAIL={int(y.sum())} PASS={int((y==0).sum())} ===")
    oof, model = oof_cv_predict(X, y)
    m = metrics_from_scores(y, oof)
    ci = bootstrap_ci(y, oof)

    pred = meta.copy()
    pred["y_true_qc_fail"] = y
    pred["y_score"] = oof
    pred["y_pred"] = (oof >= 0.5).astype(int)
    pred_path = out_dir / f"{name}_predictions.tsv"
    pred.to_csv(pred_path, sep="\t", index=False)

    plot_roc(y, oof, f"ROC — {name}", out_dir / f"{name}_ROC")
    plot_confusion(y, oof, f"Confusion — {name}", out_dir / f"{name}_confusion_matrix")
    plot_calibration(y, oof, f"Calibration — {name}", out_dir / f"{name}_calibration")

    result = {
        "analysis": name,
        "label_definition": f"FAIL if pizarro_score >= {QC_THRESHOLD}",
        "positive_class": "FAIL",
        "cv": f"StratifiedKFold n_splits<={N_SPLITS} OOF",
        "metrics": m,
        "bootstrap_95ci": ci,
        "n_boot": N_BOOT,
    }
    (out_dir / f"{name}_metrics.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    joblib.dump(model, out_dir / f"{name}_model.joblib")
    return {"metrics": m, "ci": ci, "oof": oof, "y": y, "model": model, "meta": meta}


def run_cross(
    train_name: str,
    test_name: str,
    X_tr: np.ndarray,
    y_tr: np.ndarray,
    X_te: np.ndarray,
    y_te: np.ndarray,
    meta_te: pd.DataFrame,
    out_dir: Path,
) -> dict[str, Any]:
    tag = f"cross_{train_name}_to_{test_name}"
    print(f"\n=== {tag}: train n={len(y_tr)} test n={len(y_te)} ===")
    model = build_lr()
    model.fit(X_tr, y_tr)
    score = model.predict_proba(X_te)[:, 1]
    m = metrics_from_scores(y_te, score)
    ci = bootstrap_ci(y_te, score)

    pred = meta_te.copy()
    pred["y_true_qc_fail"] = y_te
    pred["y_score"] = score
    pred["y_pred"] = (score >= 0.5).astype(int)
    pred.to_csv(out_dir / f"{tag}_predictions.tsv", sep="\t", index=False)

    plot_roc(y_te, score, f"ROC — train {train_name} → test {test_name}", out_dir / f"{tag}_ROC")
    plot_confusion(y_te, score, f"Confusion — {tag}", out_dir / f"{tag}_confusion_matrix")
    plot_calibration(y_te, score, f"Calibration — {tag}", out_dir / f"{tag}_calibration")

    result = {
        "analysis": tag,
        "train": train_name,
        "test": test_name,
        "label_definition": f"FAIL if pizarro_score >= {QC_THRESHOLD}",
        "metrics": m,
        "bootstrap_95ci": ci,
        "n_boot": N_BOOT,
    }
    (out_dir / f"{tag}_metrics.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return {"metrics": m, "ci": ci, "score": score, "y": y_te, "model": model}


def delong_roc_test(y_true: np.ndarray, p1: np.ndarray, p2: np.ndarray) -> dict[str, float]:
    """DeLong et al. test for correlated ROC AUCs (same sample)."""
    y_true = np.asarray(y_true).astype(int)
    p1 = np.asarray(p1, dtype=float)
    p2 = np.asarray(p2, dtype=float)

    def _auc_and_v(y, pred):
        pos = pred[y == 1]
        neg = pred[y == 0]
        n1, n0 = len(pos), len(neg)
        if n1 == 0 or n0 == 0:
            return float("nan"), np.array([]), np.array([])
        # Structural components
        v10 = np.array([(neg < x).mean() + 0.5 * (neg == x).mean() for x in pos])
        v01 = np.array([(pos > x).mean() + 0.5 * (pos == x).mean() for x in neg])
        auc = v10.mean()
        return float(auc), v10, v01

    auc1, v10_1, v01_1 = _auc_and_v(y_true, p1)
    auc2, v10_2, v01_2 = _auc_and_v(y_true, p2)
    if not np.isfinite(auc1) or not np.isfinite(auc2):
        return {"auc1": auc1, "auc2": auc2, "z": float("nan"), "p_value": float("nan")}

    s10 = np.cov(np.vstack([v10_1, v10_2]))
    s01 = np.cov(np.vstack([v01_1, v01_2]))
    n1 = (y_true == 1).sum()
    n0 = (y_true == 0).sum()
    var = s10 / n1 + s01 / n0
    # var of difference
    var_diff = var[0, 0] + var[1, 1] - 2 * var[0, 1]
    if var_diff <= 0:
        z = 0.0
        p = 1.0
    else:
        z = (auc1 - auc2) / np.sqrt(var_diff)
        p = float(2 * stats.norm.sf(abs(z)))
    return {
        "auc1": float(auc1),
        "auc2": float(auc2),
        "delta_auc": float(auc1 - auc2),
        "z": float(z),
        "p_value": float(p),
        "method": "DeLong",
    }


def bootstrap_auc_diff(
    y1: np.ndarray,
    s1: np.ndarray,
    y2: np.ndarray,
    s2: np.ndarray,
    n_boot: int = N_BOOT,
    seed: int = RANDOM_STATE,
) -> dict[str, float]:
    """Bootstrap CI for AUC1 - AUC2 (independent samples OK)."""
    rng = np.random.default_rng(seed)
    diffs = []
    for _ in range(n_boot):
        i1 = rng.integers(0, len(y1), size=len(y1))
        i2 = rng.integers(0, len(y2), size=len(y2))
        yt1, ys1 = y1[i1], s1[i1]
        yt2, ys2 = y2[i2], s2[i2]
        if len(np.unique(yt1)) < 2 or len(np.unique(yt2)) < 2:
            continue
        diffs.append(roc_auc_score(yt1, ys1) - roc_auc_score(yt2, ys2))
    arr = np.asarray(diffs, dtype=float)
    if len(arr) == 0:
        return {"delta_auc": float("nan"), "ci95_low": float("nan"), "ci95_high": float("nan"), "p_value": float("nan"), "method": "bootstrap"}
    # two-sided p from bootstrap distribution around 0
    p = float(2 * min((arr <= 0).mean(), (arr >= 0).mean()))
    return {
        "delta_auc": float(np.mean(arr)),
        "ci95_low": float(np.percentile(arr, 2.5)),
        "ci95_high": float(np.percentile(arr, 97.5)),
        "p_value": p,
        "method": "bootstrap",
    }


def domain_shift_analysis(df: pd.DataFrame, emb: np.ndarray, out_dir: Path) -> dict[str, Any]:
    print("\n=== Domain-shift embedding analysis ===")
    X = emb[df["embedding_row"].to_numpy()]
    run = df["run"].to_numpy()
    qc = df["qc_label"].to_numpy()
    session = df["session"].to_numpy()
    subject = df["subject"].to_numpy()

    pca = PCA(n_components=2, random_state=RANDOM_STATE)
    X_pca = pca.fit_transform(StandardScaler().fit_transform(X))
    tsne = TSNE(
        n_components=2,
        perplexity=min(30, max(5, len(X) // 4)),
        random_state=RANDOM_STATE,
        init="pca",
        learning_rate="auto",
    )
    X_tsne = tsne.fit_transform(StandardScaler().fit_transform(X))

    try:
        import umap

        reducer = umap.UMAP(n_components=2, random_state=RANDOM_STATE, n_neighbors=15, min_dist=0.1)
        X_umap = reducer.fit_transform(StandardScaler().fit_transform(X))
        umap_ok = True
    except Exception as exc:  # noqa: BLE001
        print(f"UMAP unavailable ({exc}); using PCA copy as placeholder panel")
        X_umap = X_pca.copy()
        umap_ok = False

    def _scatter_grid(coords: np.ndarray, title: str, out_base: Path) -> None:
        fig, axes = plt.subplots(2, 2, figsize=(7.2, 6.8))
        panels = [
            (run, "Run", {"01": "#D55E00", "02": "#0072B2"}),
            (qc, "QC (PASS/FAIL)", {"PASS": "#009E73", "FAIL": "#CC79A7"}),
            (session, "Session", None),
            (subject, "Subject", None),
        ]
        for ax, (labels, lab_title, cmap) in zip(axes.ravel(), panels):
            labs = np.asarray(labels)
            uniq = pd.unique(labs)
            if cmap is None:
                codes = pd.Categorical(labs).codes
                ax.scatter(
                    coords[:, 0],
                    coords[:, 1],
                    c=codes,
                    s=12,
                    cmap="tab20",
                    alpha=0.85,
                    linewidths=0,
                )
                if lab_title == "Session":
                    for i, u in enumerate(list(uniq)[:8]):
                        ax.scatter([], [], c=[plt.cm.tab20(i % 20)], label=str(u), s=12)
                    ax.legend(frameon=False, fontsize=7, title=lab_title)
                else:
                    ax.text(
                        0.02,
                        0.98,
                        f"n subjects={len(uniq)}",
                        transform=ax.transAxes,
                        va="top",
                        fontsize=7,
                    )
            else:
                for u, color in cmap.items():
                    m = labs == u
                    ax.scatter(coords[m, 0], coords[m, 1], s=14, c=color, label=str(u), alpha=0.85, linewidths=0)
                ax.legend(frameon=False, fontsize=7, title=lab_title)
            ax.set_title(lab_title)
            ax.set_xticks([])
            ax.set_yticks([])
        fig.suptitle(title, fontsize=12, y=0.995)
        fig.tight_layout()
        fig.savefig(f"{out_base}.png")
        fig.savefig(f"{out_base}.pdf")
        plt.close(fig)

    _scatter_grid(X_pca, f"PCA of Pizarro embeddings (var={pca.explained_variance_ratio_.sum():.2f})", out_dir / "embedding_PCA")
    _scatter_grid(X_tsne, "t-SNE of Pizarro embeddings", out_dir / "embedding_TSNE")
    _scatter_grid(X_umap, "UMAP of Pizarro embeddings" + ("" if umap_ok else " (PCA fallback)"), out_dir / "embedding_UMAP")

    # Distances in standardized space
    Xs = StandardScaler().fit_transform(X)
    from sklearn.metrics import pairwise_distances, silhouette_score, davies_bouldin_score

    d = pairwise_distances(Xs)
    r01 = run == "01"
    r02 = run == "02"
    intra = []
    for mask in (r01, r02):
        sub = d[np.ix_(mask, mask)]
        iu = np.triu_indices_from(sub, k=1)
        intra.append(float(sub[iu].mean()) if len(iu[0]) else float("nan"))
    inter = d[np.ix_(r01, r02)].mean()
    sil = float(silhouette_score(Xs, run))
    dbi = float(davies_bouldin_score(Xs, run))

    stats_out = {
        "mean_intra_run01_distance": intra[0],
        "mean_intra_run02_distance": intra[1],
        "mean_intra_run_distance": float(np.nanmean(intra)),
        "mean_inter_run_distance": float(inter),
        "silhouette_score_by_run": sil,
        "davies_bouldin_index_by_run": dbi,
        "pca_variance_explained_2d": pca.explained_variance_ratio_.tolist(),
        "umap_available": umap_ok,
        "strong_domain_shift": bool(sil > 0.25 and inter > np.nanmean(intra) * 1.15),
    }
    (out_dir / "domain_shift_stats.json").write_text(json.dumps(stats_out, indent=2), encoding="utf-8")

    # Compact publication embedding figure (PCA + UMAP, colored by run and QC)
    fig, axes = plt.subplots(2, 2, figsize=(7.0, 6.5))
    for ax, coords, ttl in [
        (axes[0, 0], X_pca, "PCA — run"),
        (axes[0, 1], X_pca, "PCA — QC"),
        (axes[1, 0], X_umap, "UMAP — run"),
        (axes[1, 1], X_umap, "UMAP — QC"),
    ]:
        if "run" in ttl:
            for u, color in {"01": "#D55E00", "02": "#0072B2"}.items():
                m = run == u
                ax.scatter(coords[m, 0], coords[m, 1], s=12, c=color, label=f"run-{u}", alpha=0.85, linewidths=0)
        else:
            for u, color in {"PASS": "#009E73", "FAIL": "#CC79A7"}.items():
                m = qc == u
                ax.scatter(coords[m, 0], coords[m, 1], s=12, c=color, label=u, alpha=0.85, linewidths=0)
        ax.set_title(ttl)
        ax.set_xticks([])
        ax.set_yticks([])
        ax.legend(frameon=False, fontsize=7)
    fig.tight_layout()
    fig.savefig(out_dir / "publication_embedding.png")
    fig.savefig(out_dir / "publication_embedding.pdf")
    plt.close(fig)

    return {"stats": stats_out, "X_pca": X_pca, "X_umap": X_umap, "X_tsne": X_tsne}


def feature_importance_analysis(
    name: str,
    model: Pipeline,
    X: np.ndarray,
    y: np.ndarray,
    out_dir: Path,
) -> pd.DataFrame:
    print(f"\n=== Feature importance ({name}) ===")
    # Coefficients in standardized feature space
    coef = model.named_steps["clf"].coef_.ravel()
    # Permutation importance on probability AUC
    perm = permutation_importance(
        model,
        X,
        y,
        scoring="roc_auc",
        n_repeats=30,
        random_state=RANDOM_STATE,
        n_jobs=1,
    )
    tab = pd.DataFrame(
        {
            "dimension": np.arange(X.shape[1]),
            "lr_coefficient": coef,
            "abs_lr_coefficient": np.abs(coef),
            "permutation_importance_mean": perm.importances_mean,
            "permutation_importance_std": perm.importances_std,
        }
    ).sort_values("permutation_importance_mean", ascending=False)
    tab.to_csv(out_dir / f"feature_importance_{name}.tsv", sep="\t", index=False)

    top = tab.head(20).iloc[::-1]
    fig, axes = plt.subplots(1, 2, figsize=(7.5, 4.8))
    axes[0].barh(top["dimension"].astype(str), top["permutation_importance_mean"], color="#0B3D91")
    axes[0].set_xlabel("Permutation importance (Δ AUC)")
    axes[0].set_ylabel("Embedding dimension")
    axes[0].set_title(f"{name}: top permutation importance")
    top_c = tab.sort_values("abs_lr_coefficient", ascending=False).head(20).iloc[::-1]
    axes[1].barh(top_c["dimension"].astype(str), top_c["lr_coefficient"], color="#D55E00")
    axes[1].set_xlabel("Logistic regression coefficient")
    axes[1].set_title(f"{name}: top |coefficients|")
    fig.tight_layout()
    fig.savefig(out_dir / f"feature_importance_{name}.png")
    fig.savefig(out_dir / f"feature_importance_{name}.pdf")
    plt.close(fig)
    return tab


def norm_effect_stats(df: pd.DataFrame, out_dir: Path) -> dict[str, Any]:
    print("\n=== NORM / run confounding regressions ===")
    import statsmodels.api as sm
    import statsmodels.formula.api as smf

    d = df.copy()
    d["qc_fail"] = d["qc_fail"].astype(int)
    d["run02"] = (d["run"] == "02").astype(int)

    models = {}
    # QC ~ run
    m1 = smf.logit("qc_fail ~ C(run)", data=d).fit(disp=False)
    models["QC ~ run"] = m1
    # QC ~ run + session
    m2 = smf.logit("qc_fail ~ C(run) + C(session)", data=d).fit(disp=False)
    models["QC ~ run + session"] = m2
    # QC ~ run + subject (may be singular with few obs/subject)
    try:
        m3 = smf.logit("qc_fail ~ C(run) + C(subject)", data=d).fit(disp=False, maxiter=100)
        models["QC ~ run + subject"] = m3
    except Exception as exc:  # noqa: BLE001
        print(f"Subject model failed: {exc}")
        m3 = None

    rows = []
    for name, m in models.items():
        params = m.params
        conf = m.conf_int()
        # effect of run-02 vs run-01
        key = [k for k in params.index if "run" in k and "T.02" in k]
        if not key:
            key = [k for k in params.index if k != "Intercept" and "run" in k.lower()]
        if key:
            k = key[0]
            beta = float(params[k])
            lo, hi = map(float, conf.loc[k])
            or_ = float(np.exp(beta))
            rows.append(
                {
                    "model": name,
                    "term": k,
                    "beta": beta,
                    "odds_ratio": or_,
                    "or_ci95_low": float(np.exp(lo)),
                    "or_ci95_high": float(np.exp(hi)),
                    "p_value": float(m.pvalues[k]),
                    "pseudo_r2_mcfadden": float(m.prsquared),
                    "aic": float(m.aic),
                    "bic": float(m.bic),
                    "nobs": int(m.nobs),
                }
            )
        else:
            rows.append(
                {
                    "model": name,
                    "term": "NA",
                    "beta": np.nan,
                    "odds_ratio": np.nan,
                    "or_ci95_low": np.nan,
                    "or_ci95_high": np.nan,
                    "p_value": np.nan,
                    "pseudo_r2_mcfadden": float(m.prsquared),
                    "aic": float(m.aic),
                    "bic": float(m.bic),
                    "nobs": int(m.nobs),
                }
            )

    tab = pd.DataFrame(rows)
    tab.to_csv(out_dir / "norm_effect_regression.tsv", sep="\t", index=False)
    summary = {
        "models": rows,
        "contingency_run_by_qc": pd.crosstab(df["run"], df["qc_label"]).to_dict(),
    }
    (out_dir / "norm_effect_stats.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def publication_roc_figure(curves: dict[str, tuple[np.ndarray, np.ndarray]], out_dir: Path) -> None:
    fig, ax = plt.subplots(figsize=(4.2, 4.0))
    colors = {
        "Global": "#000000",
        "Run01": "#D55E00",
        "Run02": "#0072B2",
        "Cross12": "#009E73",
        "Cross21": "#CC79A7",
    }
    for name, (y, s) in curves.items():
        if len(np.unique(y)) < 2:
            continue
        fpr, tpr, _ = roc_curve(y, s)
        auc = roc_auc_score(y, s)
        ax.plot(fpr, tpr, lw=1.7, color=colors.get(name, None), label=f"{name} (AUC={auc:.3f})")
    ax.plot([0, 1], [0, 1], "--", color="#888888", lw=1.0)
    ax.set_xlabel("False positive rate")
    ax.set_ylabel("True positive rate")
    ax.set_title("Transfer embedding LR: ROC by analysis")
    ax.legend(frameon=False, fontsize=7, loc="lower right")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    fig.tight_layout()
    fig.savefig(out_dir / "publication_ROC.png")
    fig.savefig(out_dir / "publication_ROC.pdf")
    # also required alias names
    fig.savefig(out_dir / "Figure1_ROC.png")
    fig.savefig(out_dir / "Figure1_ROC.pdf")
    plt.close(fig)


def publication_calibration_figure(curves: dict[str, tuple[np.ndarray, np.ndarray]], out_dir: Path) -> None:
    fig, ax = plt.subplots(figsize=(4.2, 4.0))
    colors = {
        "Global": "#000000",
        "Run01": "#D55E00",
        "Run02": "#0072B2",
        "Cross12": "#009E73",
        "Cross21": "#CC79A7",
    }
    for name, (y, s) in curves.items():
        try:
            frac, meanp = calibration_curve(y, s, n_bins=6, strategy="quantile")
            ax.plot(meanp, frac, "o-", lw=1.4, color=colors.get(name), label=name, markersize=4)
        except ValueError:
            continue
    ax.plot([0, 1], [0, 1], "--", color="#888888", lw=1.0)
    ax.set_xlabel("Mean predicted probability")
    ax.set_ylabel("Fraction of FAIL")
    ax.set_title("Calibration curves")
    ax.legend(frameon=False, fontsize=7)
    fig.tight_layout()
    fig.savefig(out_dir / "publication_calibration.png")
    fig.savefig(out_dir / "publication_calibration.pdf")
    fig.savefig(out_dir / "Figure4_calibration.png")
    fig.savefig(out_dir / "Figure4_calibration.pdf")
    plt.close(fig)


def write_report(
    out_dir: Path,
    df: pd.DataFrame,
    global_m: dict,
    run01_m: dict,
    run02_m: dict,
    cross12_m: dict,
    cross21_m: dict,
    domain: dict,
    norm_stats: dict,
    auc_table: pd.DataFrame,
) -> tuple[str, str]:
    g = global_m["metrics"]["roc_auc"]
    a1 = run01_m["metrics"]["roc_auc"]
    a2 = run02_m["metrics"]["roc_auc"]
    c12 = cross12_m["metrics"]["roc_auc"]
    c21 = cross21_m["metrics"]["roc_auc"]
    mean_within = np.nanmean([a1, a2])
    mean_cross = np.nanmean([c12, c21])
    drop = mean_within - mean_cross

    strong_shift = bool(domain["stats"].get("strong_domain_shift"))
    sil = domain["stats"]["silhouette_score_by_run"]

    if drop <= 0.05 and mean_cross >= 0.70:
        case = 1
        conclusion = (
            "The model generalizes across Siemens reconstruction regimes "
            "(cross-run AUC remains comparable to within-run AUC)."
        )
        confound = "LOW"
    elif drop >= 0.10 or mean_cross < 0.60:
        case = 2
        conclusion = (
            "The model learns primarily Siemens reconstruction differences "
            "(NORM vs non-NORM) rather than transferable artifact signal: "
            "cross-run AUC drops markedly relative to within-run performance."
        )
        confound = "HIGH"
    else:
        case = 3 if strong_shift else 2
        conclusion = (
            "Partial confounding: within-run discrimination is stronger than "
            "cross-run generalization, consistent with a contribution from "
            "Siemens NORM/non-NORM domain shift."
        )
        confound = "MODERATE"

    if strong_shift or sil > 0.35:
        domain_flag = "YES"
        domain_note = 'Strong domain shift detected.'
    elif sil > 0.15:
        domain_flag = "YES"
        domain_note = "Moderate domain shift detected between run-01 and run-02 embeddings."
    else:
        domain_flag = "NO"
        domain_note = "No strong run-linked separation in embedding space."

    # odds ratio from QC ~ run
    or_row = next((r for r in norm_stats["models"] if r["model"] == "QC ~ run"), {})
    or_txt = (
        f"OR(run-02 vs run-01)={or_row.get('odds_ratio', float('nan')):.3f} "
        f"[95% CI {or_row.get('or_ci95_low', float('nan')):.3f}–{or_row.get('or_ci95_high', float('nan')):.3f}], "
        f"p={or_row.get('p_value', float('nan')):.2e}, "
        f"McFadden pseudo-R²={or_row.get('pseudo_r2_mcfadden', float('nan')):.3f}"
        if or_row
        else "NA"
    )

    md = f"""# Transfer learning NORM confounding analysis

**Date:** {date.today().isoformat()}  
**Status:** READ-ONLY validation (no modification of `raw_original/`, `bids/`, `derivatives/`, or `reports/pizarro_qc_transfer_calibrated/`)  
**Embeddings:** reused from `pizarro_transfer_learning/output/with_embeddings/` (128-D `activation_22/Relu:0`)  
**QC label:** FAIL if original Pizarro score / artifact probability ≥ {QC_THRESHOLD:.0f}; PASS otherwise  

## 1. Why this analysis

The previously reported embedding logistic regression achieved ROC-AUC ≈ 0.964 when labels were defined as:

- run-01 → Siemens **non-NORM**
- run-02 → Siemens **NORM**

Because label ≡ reconstruction regime, that high AUC may reflect domain encoding of NORM rather than image quality. This report therefore re-targets learning to a **quality proxy independent of the label definition used in the original transfer experiment**, and tests within-run vs cross-run generalization.

## 2. Why NORM can bias transfer learning

If latent features primarily separate Siemens reconstruction kernels, a classifier trained on mixed runs with NORM-proxy labels will look excellent while failing as an artifact/quality detector under distribution shift. The critical test is whether quality prediction **trained in one reconstruction regime transfers to the other**.

## 3. Dataset

| Subset | N | FAIL | PASS |
| --- | ---: | ---: | ---: |
| All (run-01/02) | {len(df)} | {int(df.qc_fail.sum())} | {int((df.qc_fail==0).sum())} |
| run-01 (non-NORM) | {(df.run=='01').sum()} | {int(df.loc[df.run=='01','qc_fail'].sum())} | {int((df.loc[df.run=='01','qc_fail']==0).sum())} |
| run-02 (NORM) | {(df.run=='02').sum()} | {int(df.loc[df.run=='02','qc_fail'].sum())} | {int((df.loc[df.run=='02','qc_fail']==0).sum())} |

## 4. Methods (common pipeline)

Pizarro CNN frozen → 128-D embedding → Logistic Regression (`StandardScaler` + balanced LR, C=1).  
Within-run/global metrics use stratified OOF CV. Cross experiments train on one run and test on the other. Uncertainty: bootstrap 95% CI ({N_BOOT} resamples).

## 5. Results — discrimination

| Analysis | ROC-AUC | Accuracy | Balanced Acc. | F1 | MCC |
| --- | ---: | ---: | ---: | ---: | ---: |
| Global (mixed runs CV) | {g:.3f} | {global_m['metrics']['accuracy']:.3f} | {global_m['metrics']['balanced_accuracy']:.3f} | {global_m['metrics']['f1']:.3f} | {global_m['metrics']['mcc']:.3f} |
| Run-01 only CV | {a1:.3f} | {run01_m['metrics']['accuracy']:.3f} | {run01_m['metrics']['balanced_accuracy']:.3f} | {run01_m['metrics']['f1']:.3f} | {run01_m['metrics']['mcc']:.3f} |
| Run-02 only CV | {a2:.3f} | {run02_m['metrics']['accuracy']:.3f} | {run02_m['metrics']['balanced_accuracy']:.3f} | {run02_m['metrics']['f1']:.3f} | {run02_m['metrics']['mcc']:.3f} |
| Cross run-01→run-02 | {c12:.3f} | {cross12_m['metrics']['accuracy']:.3f} | {cross12_m['metrics']['balanced_accuracy']:.3f} | {cross12_m['metrics']['f1']:.3f} | {cross12_m['metrics']['mcc']:.3f} |
| Cross run-02→run-01 | {c21:.3f} | {cross21_m['metrics']['accuracy']:.3f} | {cross21_m['metrics']['balanced_accuracy']:.3f} | {cross21_m['metrics']['f1']:.3f} | {cross21_m['metrics']['mcc']:.3f} |

Mean within-run AUC = **{mean_within:.3f}**; mean cross-run AUC = **{mean_cross:.3f}**; drop = **{drop:.3f}**.

See `AUC_COMPARISON.tsv` for CIs and pairwise tests.

## 6. Domain shift (embeddings)

- Mean intra-run distance: {domain['stats']['mean_intra_run_distance']:.3f}
- Mean inter-run distance: {domain['stats']['mean_inter_run_distance']:.3f}
- Silhouette (by run): {sil:.3f}
- Davies–Bouldin (by run): {domain['stats']['davies_bouldin_index_by_run']:.3f}

**Domain shift detected: {domain_flag}**  
{domain_note}

## 7. Does run alone predict QC?

Logistic regression `QC_fail ~ run`: {or_txt}

AIC/BIC comparisons across `run`, `run+session`, and `run+subject` (when identifiable) are in `norm_effect_regression.tsv`. If run is highly predictive of FAIL/PASS, reconstruction regime is a confounder for any quality label correlated with acquisition settings.

## 8. Automatic conclusion (case {case})

{conclusion}

**Potential NORM confounding: {confound}**

### Interpretation caveat

Using Pizarro score ≥ {QC_THRESHOLD:.0f} as QC ground truth is itself model-derived. This analysis therefore tests whether the **embedding+LR stack recovers/generalizes that score across Siemens reconstruction domains**, which is exactly the right stress test for NORM confounding of the transfer pipeline. It does **not** replace expert visual QC labels.

## 9. Figures

- `publication_ROC.png/.pdf`
- `publication_embedding.png/.pdf` (PCA/UMAP)
- `publication_calibration.png/.pdf`
- `feature_importance_run01.png`, `feature_importance_run02.png`
- `embedding_PCA.png`, `embedding_TSNE.png`, `embedding_UMAP.png`

## 10. Reproducibility

```bash
/lustre07/scratch/alexrees/venvs/pizarro_qc/bin/python \\
  /lustre07/scratch/alexrees/code/pizarro_transfer_norm_analysis.py
```
"""
    (out_dir / "TRANSFER_LEARNING_NORM_ANALYSIS.md").write_text(md, encoding="utf-8")
    return domain_flag, confound


def main() -> int:
    out_dir = OUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    df, emb = load_data()
    # restrict to runs with embeddings (01/02)
    df = df[df["run"].isin(["01", "02"])].reset_index(drop=True)
    X_all = emb[df["embedding_row"].to_numpy()]
    y_all = df["qc_fail"].to_numpy().astype(int)

    print("=" * 60)
    print("Pizarro transfer NORM confounding analysis (READ-ONLY)")
    print("=" * 60)
    print(f"Number of scans: {len(df)}")
    print(f"run-01: {(df.run=='01').sum()}")
    print(f"run-02: {(df.run=='02').sum()}")

    # Global
    global_res = run_within_split(
        "global",
        X_all,
        y_all,
        df[["subject", "session", "run", "image_path", "pizarro_score", "label", "qc_label"]],
        out_dir,
    )

    m01 = df["run"] == "01"
    m02 = df["run"] == "02"
    run01_res = run_within_split(
        "run01",
        X_all[m01],
        y_all[m01],
        df.loc[m01, ["subject", "session", "run", "image_path", "pizarro_score", "label", "qc_label"]],
        out_dir,
    )
    run02_res = run_within_split(
        "run02",
        X_all[m02],
        y_all[m02],
        df.loc[m02, ["subject", "session", "run", "image_path", "pizarro_score", "label", "qc_label"]],
        out_dir,
    )

    cross12 = run_cross(
        "run01",
        "run02",
        X_all[m01],
        y_all[m01],
        X_all[m02],
        y_all[m02],
        df.loc[m02, ["subject", "session", "run", "image_path", "pizarro_score", "label", "qc_label"]],
        out_dir,
    )
    cross21 = run_cross(
        "run02",
        "run01",
        X_all[m02],
        y_all[m02],
        X_all[m01],
        y_all[m01],
        df.loc[m01, ["subject", "session", "run", "image_path", "pizarro_score", "label", "qc_label"]],
        out_dir,
    )

    # Domain shift
    domain = domain_shift_analysis(df, emb, out_dir)

    # Feature importance
    feature_importance_analysis("run01", run01_res["model"], X_all[m01], y_all[m01], out_dir)
    feature_importance_analysis("run02", run02_res["model"], X_all[m02], y_all[m02], out_dir)
    # Combined publication feature figure
    fig, axes = plt.subplots(1, 2, figsize=(7.5, 4.8))
    for ax, name in zip(axes, ["run01", "run02"]):
        tab = pd.read_csv(out_dir / f"feature_importance_{name}.tsv", sep="\t")
        top = tab.head(15).iloc[::-1]
        ax.barh(top["dimension"].astype(str), top["permutation_importance_mean"], color="#0B3D91")
        ax.set_title(f"{name} permutation importance")
        ax.set_xlabel("Δ AUC")
    fig.tight_layout()
    fig.savefig(out_dir / "publication_feature_importance.png")
    fig.savefig(out_dir / "publication_feature_importance.pdf")
    fig.savefig(out_dir / "Figure5_feature_importance.png")
    fig.savefig(out_dir / "Figure5_feature_importance.pdf")
    plt.close(fig)

    # Stats / AUC comparison
    rows = []
    for tag, res in [
        ("AUC_global", global_res),
        ("AUC_run01", run01_res),
        ("AUC_run02", run02_res),
        ("AUC_cross12", cross12),
        ("AUC_cross21", cross21),
    ]:
        m = res["metrics"]
        ci = res["ci"]["roc_auc"]
        rows.append(
            {
                "metric": tag,
                "roc_auc": m["roc_auc"],
                "ci95_low": ci["ci95_low"],
                "ci95_high": ci["ci95_high"],
                "accuracy": m["accuracy"],
                "balanced_accuracy": m["balanced_accuracy"],
                "precision": m["precision"],
                "recall": m["recall"],
                "f1": m["f1"],
                "mcc": m["mcc"],
            }
        )
    auc_table = pd.DataFrame(rows)

    # Pairwise tests
    # DeLong where same test sample (run02 oof vs cross12 scores on run02)
    delong_12 = delong_roc_test(run02_res["y"], run02_res["oof"], cross12["score"])
    delong_21 = delong_roc_test(run01_res["y"], run01_res["oof"], cross21["score"])
    boot_within_vs_cross = bootstrap_auc_diff(
        np.concatenate([run01_res["y"], run02_res["y"]]),
        np.concatenate([run01_res["oof"], run02_res["oof"]]),
        np.concatenate([cross12["y"], cross21["y"]]),
        np.concatenate([cross12["score"], cross21["score"]]),
    )
    test_rows = [
        {
            "comparison": "run02_within_vs_cross_run01_to_run02",
            **delong_12,
        },
        {
            "comparison": "run01_within_vs_cross_run02_to_run01",
            **delong_21,
        },
        {
            "comparison": "pooled_within_vs_pooled_cross",
            **boot_within_vs_cross,
        },
    ]
    pd.DataFrame(test_rows).to_csv(out_dir / "AUC_PAIRWISE_TESTS.tsv", sep="\t", index=False)
    auc_table.to_csv(out_dir / "AUC_COMPARISON.tsv", sep="\t", index=False)
    (out_dir / "AUC_COMPARISON.json").write_text(
        json.dumps({"table": rows, "pairwise_tests": test_rows}, indent=2),
        encoding="utf-8",
    )

    # NORM effect regressions
    try:
        norm_stats = norm_effect_stats(df, out_dir)
    except Exception as exc:  # noqa: BLE001
        print(f"statsmodels regression failed: {exc}")
        norm_stats = {"models": [], "error": str(exc)}

    # Publication figures
    curves = {
        "Global": (global_res["y"], global_res["oof"]),
        "Run01": (run01_res["y"], run01_res["oof"]),
        "Run02": (run02_res["y"], run02_res["oof"]),
        "Cross12": (cross12["y"], cross12["score"]),
        "Cross21": (cross21["y"], cross21["score"]),
    }
    publication_roc_figure(curves, out_dir)
    publication_calibration_figure(curves, out_dir)
    # alias figure 2/3
    for src, dst in [
        ("embedding_PCA", "Figure2_PCA"),
        ("embedding_UMAP", "Figure3_UMAP"),
    ]:
        for ext in (".png", ".pdf"):
            s = out_dir / f"{src}{ext}"
            d = out_dir / f"{dst}{ext}"
            if s.exists():
                d.write_bytes(s.read_bytes())

    domain_flag, confound = write_report(
        out_dir,
        df,
        global_res,
        run01_res,
        run02_res,
        cross12,
        cross21,
        domain,
        norm_stats,
        auc_table,
    )

    readme = f"""# Pizarro transfer learning — NORM confounding validation

Read-only scientific analysis. Embeddings were **not** recomputed.

## Key outputs

- `TRANSFER_LEARNING_NORM_ANALYSIS.md` — full report
- `run01_metrics.json`, `run02_metrics.json`
- `cross_run01_to_run02_metrics.json`, `cross_run02_to_run01_metrics.json`
- `AUC_COMPARISON.tsv`
- Embedding plots: `embedding_PCA/TSNE/UMAP.png`
- Publication figures: `publication_ROC.png/.pdf`, `publication_embedding.png/.pdf`

## QC label

FAIL if `pizarro_score` / artifact probability ≥ {QC_THRESHOLD:.0f}.

## Reproduce

```bash
/lustre07/scratch/alexrees/venvs/pizarro_qc/bin/python \\
  {ROOT}/code/pizarro_transfer_norm_analysis.py
```
"""
    (out_dir / "README.md").write_text(readme, encoding="utf-8")

    validation = {
        "status": "READ ONLY COMPLETED",
        "date": datetime.now(timezone.utc).isoformat(),
        "forbidden_paths_untouched": [
            str(ROOT / "raw_original"),
            str(ROOT / "bids"),
            str(ROOT / "derivatives"),
            str(CAL_DIR),
        ],
        "embeddings_recomputed": False,
        "embeddings_source": str(TL_DIR / "pizarro_embeddings.npy"),
        "n_scans": int(len(df)),
        "n_run01": int((df.run == "01").sum()),
        "n_run02": int((df.run == "02").sum()),
        "qc_threshold": QC_THRESHOLD,
        "auc_global": global_res["metrics"]["roc_auc"],
        "auc_run01": run01_res["metrics"]["roc_auc"],
        "auc_run02": run02_res["metrics"]["roc_auc"],
        "auc_run01_to_run02": cross12["metrics"]["roc_auc"],
        "auc_run02_to_run01": cross21["metrics"]["roc_auc"],
        "domain_shift_detected": domain_flag,
        "potential_norm_confounding": confound,
        "output_dir": str(out_dir),
    }
    (out_dir / "validation.json").write_text(json.dumps(validation, indent=2), encoding="utf-8")

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Number of scans: {len(df)}")
    print(f"run-01: {(df.run=='01').sum()}")
    print(f"run-02: {(df.run=='02').sum()}")
    print(f"AUC global: {global_res['metrics']['roc_auc']:.4f}")
    print(f"AUC run01: {run01_res['metrics']['roc_auc']:.4f}")
    print(f"AUC run02: {run02_res['metrics']['roc_auc']:.4f}")
    print(f"AUC run01→run02: {cross12['metrics']['roc_auc']:.4f}")
    print(f"AUC run02→run01: {cross21['metrics']['roc_auc']:.4f}")
    print(f"Domain shift detected: {domain_flag}")
    print(f"Potential NORM confounding: {confound}")
    print(f"Outputs → {out_dir}")
    print("READ ONLY COMPLETED.")
    return 0


if __name__ == "__main__":
    # Fix accidental syntax error in import if any during editing
    try:
        raise SystemExit(main())
    except Exception:
        raise
