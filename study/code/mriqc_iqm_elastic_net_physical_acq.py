#!/usr/bin/env python3
"""Exploratory Elastic Net: Control vs Glaucoma from 56 physical-acq IQMs.

Subject-grouped nested CV (StratifiedGroupKFold, group=subject_id).
The same subject never appears in both train and validation.
Scaling/imputation occur inside each training fold only.

Predictors are the 56 IQMs. Cohort, age, sex, session, acquisition
variables and subject_id are excluded from X.

Exploratory only: coefficients are not causal and are not quality scores.
Data_ON / Data_TON are excluded; four-class classification is not primary.
"""

from __future__ import annotations

import argparse
import logging
import sys
import warnings
from datetime import datetime, timezone
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mriqc_iqm_lib import fail, to_numeric_iqm  # noqa: E402
from mriqc_iqm_physical_acq_lib import (  # noqa: E402
    FAMILY_COLORS,
    assert_unmodified,
    family_group,
    load_physical_acquisition_table,
    load_t1w_iqm_names,
    snapshot_protected,
    study_root_default,
)

LOGGER = logging.getLogger("mriqc_iqm.physical_acq.elastic_net")
POS_LABEL = 1
RANDOM_STATE = 0
N_OUTER = 5
N_INNER = 3
C_GRID = [float(x) for x in np.logspace(-2, 2, 7)]
L1_GRID = [0.15, 0.5, 0.85, 1.0]


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--study-root", type=Path, default=None)
    args = p.parse_args(argv)
    root = args.study_root.resolve() if args.study_root else study_root_default(Path(__file__))
    qc = root / "qc_reports" / "mriqc_iqm"
    args.study_root = root
    args.phys = root / "metadata" / "mriqc_iqm_physical_acquisition.tsv"
    args.loadings = qc / "pca_physical_acq_loadings.tsv"
    args.out_dir = qc
    return args


def configure_logging():
    LOGGER.setLevel(logging.INFO)
    LOGGER.handlers.clear()
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S"))
    LOGGER.addHandler(h)


def import_sklearn():
    try:
        from sklearn.impute import SimpleImputer
        from sklearn.linear_model import LogisticRegression
        from sklearn.metrics import (
            balanced_accuracy_score,
            confusion_matrix,
            f1_score,
            precision_score,
            recall_score,
            roc_auc_score,
            roc_curve,
        )
        from sklearn.model_selection import GridSearchCV, StratifiedGroupKFold
        from sklearn.pipeline import Pipeline
        from sklearn.preprocessing import StandardScaler
    except ImportError as exc:
        fail(
            "scikit-learn is required for Elastic Net. "
            "On Narval: module load scipy-stack/2025a && pip install --user scikit-learn. "
            f"Import error: {exc}"
        )
    return {
        "SimpleImputer": SimpleImputer,
        "LogisticRegression": LogisticRegression,
        "balanced_accuracy_score": balanced_accuracy_score,
        "confusion_matrix": confusion_matrix,
        "f1_score": f1_score,
        "precision_score": precision_score,
        "recall_score": recall_score,
        "roc_auc_score": roc_auc_score,
        "roc_curve": roc_curve,
        "GridSearchCV": GridSearchCV,
        "StratifiedGroupKFold": StratifiedGroupKFold,
        "Pipeline": Pipeline,
        "StandardScaler": StandardScaler,
    }


def metric_block(y_true: np.ndarray, y_pred: np.ndarray, y_proba: np.ndarray, sk: dict) -> dict:
    tn, fp, fn, tp = sk["confusion_matrix"](y_true, y_pred, labels=[0, 1]).ravel()
    spec = tn / (tn + fp) if (tn + fp) else float("nan")
    out = {
        "roc_auc": float(sk["roc_auc_score"](y_true, y_proba)) if len(np.unique(y_true)) > 1 else float("nan"),
        "balanced_accuracy": float(sk["balanced_accuracy_score"](y_true, y_pred)),
        "sensitivity": float(sk["recall_score"](y_true, y_pred, pos_label=1, zero_division=0)),
        "specificity": float(spec),
        "precision": float(sk["precision_score"](y_true, y_pred, pos_label=1, zero_division=0)),
        "f1": float(sk["f1_score"](y_true, y_pred, pos_label=1, zero_division=0)),
        "tn": int(tn),
        "fp": int(fp),
        "fn": int(fn),
        "tp": int(tp),
    }
    return out


def plot_performance(fold_df: pd.DataFrame, oof: dict, dest: Path) -> None:
    metrics = ["roc_auc", "balanced_accuracy", "sensitivity", "specificity", "precision", "f1"]
    means = [float(fold_df[m].mean()) for m in metrics]
    sds = [float(fold_df[m].std(ddof=1)) if len(fold_df) > 1 else 0.0 for m in metrics]
    fig, axes = plt.subplots(1, 2, figsize=(11.2, 4.6))
    ax = axes[0]
    x = np.arange(len(metrics))
    ax.bar(x, means, yerr=sds, capsize=4, color="#4C78A8", alpha=0.85)
    ax.set_xticks(x, metrics, rotation=30, ha="right")
    ax.set_ylim(0, 1.05)
    ax.set_ylabel("score")
    ax.set_title("Outer-fold mean ± SD (grouped CV)")
    ax.axhline(0.5, color="#888888", lw=0.8, ls="--")
    ax = axes[1]
    fpr, tpr, _ = oof["roc_curve"]
    ax.plot(fpr, tpr, color="#F58518", lw=2, label=f"OOF ROC-AUC={oof['roc_auc']:.3f}")
    ax.plot([0, 1], [0, 1], color="#888888", lw=0.8, ls="--")
    ax.set_xlabel("false positive rate")
    ax.set_ylabel("true positive rate")
    ax.set_title("Pooled out-of-fold ROC")
    ax.legend(frameon=False, loc="lower right")
    fig.suptitle("Elastic Net Control vs Glaucoma  (subject-grouped nested CV; exploratory)")
    fig.tight_layout()
    fig.savefig(dest, dpi=160)
    plt.close(fig)


def plot_coefficients(stab: pd.DataFrame, dest: Path, top_n: int = 20) -> None:
    work = stab.copy()
    work["abs_mean"] = work["mean_coefficient"].abs()
    work = work.sort_values("abs_mean", ascending=False, kind="mergesort").head(top_n)
    work = work.iloc[::-1]
    colors = [FAMILY_COLORS.get(family_group(i), "#BAB0AC") for i in work["IQM"]]
    fig, ax = plt.subplots(figsize=(8.0, 7.2))
    ax.barh(
        range(len(work)),
        work["mean_coefficient"],
        xerr=work["coefficient_sd"],
        color=colors,
        capsize=3,
        alpha=0.9,
    )
    ax.set_yticks(range(len(work)), work["IQM"].tolist(), fontsize=8)
    ax.axvline(0, color="#333333", lw=0.8)
    ax.set_xlabel("mean coefficient across outer folds (SD-scaled IQMs)")
    ax.set_title("Elastic Net coefficient stability (top |mean|; not causal / not quality)")
    fig.tight_layout()
    fig.savefig(dest, dpi=160)
    plt.close(fig)


def plot_confusion(cm: np.ndarray, dest: Path) -> None:
    fig, ax = plt.subplots(figsize=(5.2, 4.6))
    im = ax.imshow(cm, cmap="Blues")
    ax.set_xticks([0, 1], ["pred Control", "pred Glaucoma"])
    ax.set_yticks([0, 1], ["true Control", "true Glaucoma"])
    for i in range(2):
        for j in range(2):
            ax.text(j, i, str(int(cm[i, j])), ha="center", va="center", fontsize=14)
    ax.set_title("Out-of-fold confusion matrix")
    fig.colorbar(im, ax=ax, fraction=0.046)
    fig.tight_layout()
    fig.savefig(dest, dpi=160)
    plt.close(fig)


def write_report(
    path: Path,
    n_obs: int,
    n_subj: int,
    n_control_subj: int,
    n_glaucoma_subj: int,
    fold_df: pd.DataFrame,
    oof: dict,
    stab: pd.DataFrame,
    best_params: list[dict],
) -> None:
    top = stab.assign(abs_mean=stab["mean_coefficient"].abs()).sort_values(
        "abs_mean", ascending=False, kind="mergesort"
    ).head(10)
    lines = [
        "Physical-acquisition Elastic Net report (exploratory)",
        f"generated_utc: {datetime.now(timezone.utc).isoformat()}",
        "",
        "Task: Control vs Glaucoma. Data_ON and Data_TON excluded.",
        "Four-class classification is not primary (Data_TON n subjects ~2).",
        f"N observations={n_obs}  N subjects={n_subj}  "
        f"(Control subjects={n_control_subj}, Glaucoma subjects={n_glaucoma_subj})",
        "Predictors: 56 T1w IQMs only.",
        "Excluded from X: cohort, age, sex, session, software_platform, scanner, subject_id.",
        "",
        "Leakage control:",
        "  StratifiedGroupKFold, group=subject_id (equivalent grouped CV; stratified",
        "  so outer folds keep both classes). The same subject is never in train and",
        "  validation. Longitudinal sessions of one subject stay in the same fold.",
        "  SimpleImputer(median) + StandardScaler fit on training fold only.",
        "",
        f"Estimator: logistic regression, penalty=elasticnet, solver=saga, class_weight=balanced.",
        f"Hyperparameters tuned inside each outer fold: C={list(C_GRID)}, l1_ratio={L1_GRID}.",
        f"Outer folds={N_OUTER}  inner folds={N_INNER}  scoring=roc_auc.",
        f"Selected params per outer fold: {best_params}",
        "",
        "Primary metrics (outer-fold mean ± SD):",
        f"  ROC-AUC: {fold_df['roc_auc'].mean():.3f} ± {fold_df['roc_auc'].std(ddof=1):.3f}",
        f"  balanced accuracy: {fold_df['balanced_accuracy'].mean():.3f} ± "
        f"{fold_df['balanced_accuracy'].std(ddof=1):.3f}",
        "Pooled out-of-fold:",
        f"  ROC-AUC={oof['roc_auc']:.3f}  balanced_accuracy={oof['balanced_accuracy']:.3f}",
        f"  sensitivity={oof['sensitivity']:.3f}  specificity={oof['specificity']:.3f}",
        f"  precision={oof['precision']:.3f}  F1={oof['f1']:.3f}",
        f"  confusion TN={oof['tn']} FP={oof['fp']} FN={oof['fn']} TP={oof['tp']}",
        "",
        "Coefficients are on z-scored IQMs, averaged across outer-fold models.",
        "They are not causal effects and are not image-quality scores.",
        "Highest |mean coefficient|:",
    ]
    for _, r in top.iterrows():
        lines.append(
            f"  {r['IQM']} ({family_group(str(r['IQM']))}): mean={r['mean_coefficient']:.4g}  "
            f"sd={r['coefficient_sd']:.4g}  nonzero={r['nonzero_fraction']:.2f}  "
            f"sign_consistency={r['sign_consistency']:.2f}"
        )
    lines.append("")
    lines.append("Limitations: small Glaucoma n, correlated IQMs, no anatomy covariates,")
    lines.append("software-platform imbalance, exploratory nested CV on one dataset.")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv=None) -> int:
    configure_logging()
    args = parse_args(argv)
    before = snapshot_protected(args.study_root)
    sk = import_sklearn()
    iqms = load_t1w_iqm_names(args.loadings)
    df = load_physical_acquisition_table(args.phys, iqms)
    work = df.loc[df["cohort"].isin(["Control", "Glaucoma"])].copy()
    if work.empty:
        fail("No Control/Glaucoma rows in the physical-acquisition table.")
    for col in iqms:
        work[col] = to_numeric_iqm(work[col])
    X = work[iqms].to_numpy(dtype=float)
    y = (work["cohort"].astype(str) == "Glaucoma").to_numpy(dtype=int)
    groups = work["subject_id"].astype(str).to_numpy()
    n_subj = int(pd.Series(groups).nunique())
    n_control = int(work.loc[work["cohort"] == "Control", "subject_id"].nunique())
    n_glaucoma = int(work.loc[work["cohort"] == "Glaucoma", "subject_id"].nunique())
    LOGGER.info(
        "Elastic Net Control vs Glaucoma: n_obs=%d n_subj=%d glaucoma_subj=%d",
        len(work),
        n_subj,
        n_glaucoma,
    )

    pipe = sk["Pipeline"](
        steps=[
            ("imputer", sk["SimpleImputer"](strategy="median")),
            ("scaler", sk["StandardScaler"]()),
            (
                "clf",
                sk["LogisticRegression"](
                    penalty="elasticnet",
                    solver="saga",
                    class_weight="balanced",
                    max_iter=20000,
                    random_state=RANDOM_STATE,
                ),
            ),
        ]
    )
    param_grid = {"clf__C": list(C_GRID), "clf__l1_ratio": list(L1_GRID)}
    outer = sk["StratifiedGroupKFold"](n_splits=N_OUTER, shuffle=True, random_state=RANDOM_STATE)
    inner_cv = sk["StratifiedGroupKFold"](n_splits=N_INNER, shuffle=True, random_state=RANDOM_STATE)

    oof_true = np.full(len(y), np.nan)
    oof_pred = np.full(len(y), np.nan)
    oof_proba = np.full(len(y), np.nan)
    fold_rows = []
    coef_folds = []
    best_params = []
    for fold, (tr, te) in enumerate(outer.split(X, y, groups), start=1):
        X_tr, y_tr, g_tr = X[tr], y[tr], groups[tr]
        X_te, y_te = X[te], y[te]
        inner_splits = list(inner_cv.split(X_tr, y_tr, g_tr))
        gs = sk["GridSearchCV"](
            pipe,
            param_grid,
            cv=inner_splits,
            scoring="roc_auc",
            n_jobs=1,
            refit=True,
        )
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            gs.fit(X_tr, y_tr)
        pred = gs.predict(X_te)
        proba = gs.predict_proba(X_te)[:, 1]
        oof_true[te] = y_te
        oof_pred[te] = pred
        oof_proba[te] = proba
        mets = metric_block(y_te, pred, proba, sk)
        mets["fold"] = fold
        mets["n_test_obs"] = int(len(te))
        mets["n_test_subjects"] = int(pd.Series(groups[te]).nunique())
        mets["best_C"] = float(gs.best_params_["clf__C"])
        mets["best_l1_ratio"] = float(gs.best_params_["clf__l1_ratio"])
        fold_rows.append(mets)
        best_params.append(
            {
                "fold": fold,
                "C": mets["best_C"],
                "l1_ratio": mets["best_l1_ratio"],
            }
        )
        coef = gs.best_estimator_.named_steps["clf"].coef_.ravel()
        coef_folds.append(coef)
        LOGGER.info(
            "fold %d AUC=%.3f balacc=%.3f C=%s l1=%s",
            fold,
            mets["roc_auc"],
            mets["balanced_accuracy"],
            gs.best_params_["clf__C"],
            gs.best_params_["clf__l1_ratio"],
        )

    fold_df = pd.DataFrame(fold_rows)
    mask = np.isfinite(oof_true)
    oof_y = oof_true[mask].astype(int)
    oof_p = oof_pred[mask].astype(int)
    oof_pr = oof_proba[mask]
    oof = metric_block(oof_y, oof_p, oof_pr, sk)
    fpr, tpr, _ = sk["roc_curve"](oof_y, oof_pr)
    oof["roc_curve"] = (fpr, tpr, None)
    cm = np.array([[oof["tn"], oof["fp"]], [oof["fn"], oof["tp"]]], dtype=float)

    coef_mat = np.vstack(coef_folds)
    stab_rows = []
    for j, iqm in enumerate(iqms):
        vals = coef_mat[:, j]
        nz = np.abs(vals) > 1e-8
        signs = np.sign(vals)
        stab_rows.append(
            {
                "IQM": iqm,
                "family_group": family_group(iqm),
                "mean_coefficient": float(np.mean(vals)),
                "median_coefficient": float(np.median(vals)),
                "coefficient_sd": float(np.std(vals, ddof=1)) if len(vals) > 1 else 0.0,
                "nonzero_fraction": float(nz.mean()),
                "sign_consistency": float(np.abs(np.mean(signs))),
            }
        )
    stab = pd.DataFrame(stab_rows)

    result_rows = []
    for _, r in fold_df.iterrows():
        rec = r.to_dict()
        rec["split"] = f"fold_{int(r['fold'])}"
        result_rows.append(rec)
    pooled = {k: v for k, v in oof.items() if k != "roc_curve"}
    pooled["split"] = "oof_pooled"
    pooled["fold"] = np.nan
    pooled["n_test_obs"] = int(mask.sum())
    pooled["n_test_subjects"] = n_subj
    pooled["best_C"] = np.nan
    pooled["best_l1_ratio"] = np.nan
    result_rows.append(pooled)
    pd.DataFrame(result_rows).to_csv(
        args.out_dir / "elastic_net_subject_grouped_results.tsv",
        sep="\t",
        index=False,
        float_format="%.10g",
    )
    stab.to_csv(
        args.out_dir / "elastic_net_coefficient_stability.tsv",
        sep="\t",
        index=False,
        float_format="%.10g",
    )
    plot_performance(fold_df, oof, args.out_dir / "elastic_net_performance.png")
    plot_coefficients(stab, args.out_dir / "elastic_net_coefficients.png")
    plot_confusion(cm, args.out_dir / "elastic_net_confusion_matrix.png")
    write_report(
        args.out_dir / "elastic_net_report.txt",
        n_obs=len(work),
        n_subj=n_subj,
        n_control_subj=n_control,
        n_glaucoma_subj=n_glaucoma,
        fold_df=fold_df,
        oof=oof,
        stab=stab,
        best_params=best_params,
    )
    assert_unmodified(before)
    print(
        "OOF ROC-AUC",
        f"{oof['roc_auc']:.3f}",
        "balanced_accuracy",
        f"{oof['balanced_accuracy']:.3f}",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
