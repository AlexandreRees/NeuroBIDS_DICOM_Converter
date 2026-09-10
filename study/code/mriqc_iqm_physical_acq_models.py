"""Shared MixedLM helpers for physical-acquisition robustness / variance scripts."""

from __future__ import annotations

import logging
import math
import traceback
import warnings
from typing import Any

import numpy as np
import pandas as pd

from mriqc_iqm_cohort_analysis import nakagawa_r2
from mriqc_iqm_lib import to_numeric_iqm
from mriqc_iqm_physical_acq_lib import FDR_ALPHA, REF_COHORT, REF_SOFTWARE

LOGGER = logging.getLogger("mriqc_iqm.physical_acq.models")

COHORT_RHS = f'C(cohort, Treatment("{REF_COHORT}"))'
SOFTWARE_RHS = f'C(software_platform, Treatment("{REF_SOFTWARE}"))'
COVARIATE_RHS = "age + C(sex) + C(session)"
FULL_RHS = f"{COHORT_RHS} + {SOFTWARE_RHS} + {COVARIATE_RHS}"
ACQUISITION_RHS = f"{SOFTWARE_RHS} + {COVARIATE_RHS}"
COHORT_ONLY_RHS = f"{COHORT_RHS} + {COVARIATE_RHS}"


def import_stats() -> dict[str, Any]:
    missing: list[str] = []
    out: dict[str, Any] = {"ok": True, "missing": missing}
    try:
        import scipy  # noqa: F401

        out["scipy"] = scipy.__version__
    except ImportError as exc:
        missing.append(f"scipy ({exc})")
    try:
        import statsmodels
        import statsmodels.formula.api as smf
        from statsmodels.stats.multitest import multipletests

        out["statsmodels"] = statsmodels.__version__
        out["smf"] = smf
        out["multipletests"] = multipletests
    except ImportError as exc:
        missing.append(f"statsmodels ({exc})")
    if missing:
        out["ok"] = False
    return out


def fdr_bh(pvals: list[float], multipletests: Any) -> list[float]:
    arr = np.asarray(pvals, dtype=float)
    out = np.full(arr.shape, np.nan)
    ok = np.isfinite(arr)
    if int(ok.sum()) == 0:
        return out.tolist()
    _, adj, _, _ = multipletests(arr[ok], alpha=FDR_ALPHA, method="fdr_bh")
    out[ok] = adj
    return out.tolist()


def wald_terms(fit: Any, prefix: str) -> tuple[str, float, float, float]:
    names = list(fit.params.index)
    terms = [n for n in names if str(n).startswith(prefix)]
    if not terms:
        return f"wald_{prefix}_missing", float("nan"), float("nan"), float("nan")
    r_matrix = np.zeros((len(terms), len(names)))
    for i, term in enumerate(terms):
        r_matrix[i, names.index(term)] = 1.0
    wres = fit.wald_test(r_matrix, scalar=True)
    stat = float(np.asarray(wres.statistic).squeeze())
    p = float(np.asarray(wres.pvalue).squeeze())
    return f"wald_test_{prefix}", stat, float(len(terms)), p


def term_lookup(fit: Any, substr: str) -> dict[str, float]:
    out = {
        "coef": float("nan"),
        "se": float("nan"),
        "ci_low": float("nan"),
        "ci_high": float("nan"),
        "p": float("nan"),
    }
    names = [n for n in fit.params.index if substr in str(n)]
    if not names:
        return out
    name = names[0]
    ci = fit.conf_int()
    out["coef"] = float(fit.params[name])
    out["se"] = float(fit.bse[name])
    out["ci_low"] = float(ci.loc[name, 0])
    out["ci_high"] = float(ci.loc[name, 1])
    out["p"] = float(fit.pvalues[name])
    return out


def _fixed_fitted(fit: Any, work: pd.DataFrame) -> np.ndarray:
    re = fit.random_effects
    blup = work["subject_id"].map(lambda s: float(np.asarray(re[s]).reshape(-1)[0]))
    return np.asarray(fit.fittedvalues) - blup.to_numpy(dtype=float)


def fit_mixed_iqm(
    df: pd.DataFrame,
    iqm: str,
    rhs: str,
    stats: dict[str, Any],
) -> dict[str, Any]:
    smf = stats["smf"]
    needed = ["subject_id", iqm, "cohort", "age", "sex", "session", "software_platform"]
    work = df[needed].copy()
    work[iqm] = to_numeric_iqm(work[iqm])
    work = work.dropna()
    n_obs = int(len(work))
    n_subj = int(work["subject_id"].nunique())
    empty = {
        "iqm": iqm,
        "n_obs": n_obs,
        "n_subjects": n_subj,
        "status": "failed",
        "converged": False,
        "r2_marginal": float("nan"),
        "r2_conditional": float("nan"),
        "cohort_stat": float("nan"),
        "cohort_df": float("nan"),
        "cohort_p": float("nan"),
        "acquisition_stat": float("nan"),
        "acquisition_df": float("nan"),
        "acquisition_p": float("nan"),
        "glaucoma_coef": float("nan"),
        "glaucoma_p": float("nan"),
        "xa30_coef": float("nan"),
        "xa30_p": float("nan"),
        "on_coef": float("nan"),
        "ton_coef": float("nan"),
        "aic": float("nan"),
        "formula": f'Q("{iqm}") ~ {rhs}',
    }
    if n_obs < 10 or n_subj < 5:
        empty["status"] = "too_few_rows"
        return empty
    formula = f'Q("{iqm}") ~ {rhs}'
    try:
        md = smf.mixedlm(formula, data=work, groups=work["subject_id"])
        fit = None
        last_exc: Exception | None = None
        attempts: list[dict[str, Any]] = [
            {"reml": True, "maxiter": 300},
            {"method": "nm", "reml": True, "maxiter": 400},
            {"method": "powell", "reml": True, "maxiter": 400},
        ]
        for kwargs in attempts:
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    cand = md.fit(**kwargs)
                fit = cand
                if bool(getattr(cand, "converged", False)):
                    break
            except Exception as exc:
                last_exc = exc
                LOGGER.debug("mixed %s optimizer %s failed: %s", iqm, kwargs, exc)
        if fit is None:
            raise last_exc if last_exc is not None else RuntimeError("MixedLM produced no fit")
        converged = bool(getattr(fit, "converged", False))
        try:
            fe_fitted = _fixed_fitted(fit, work)
            r2m, r2c = nakagawa_r2(fit, fe_fitted)
        except Exception:
            r2m, r2c = float("nan"), float("nan")
        c_method, c_stat, c_df, c_p = wald_terms(fit, "C(cohort")
        a_method, a_stat, a_df, a_p = wald_terms(fit, "C(software_platform")
        glau = term_lookup(fit, "T.Glaucoma")
        on = term_lookup(fit, "T.Data_ON")
        ton = term_lookup(fit, "T.Data_TON")
        xa = term_lookup(fit, "T.XA30")
        return {
            "iqm": iqm,
            "n_obs": n_obs,
            "n_subjects": n_subj,
            "status": "ok" if converged else "not_converged",
            "converged": converged,
            "r2_marginal": r2m,
            "r2_conditional": r2c,
            "cohort_method": c_method,
            "cohort_stat": c_stat,
            "cohort_df": c_df,
            "cohort_p": c_p,
            "acquisition_method": a_method,
            "acquisition_stat": a_stat,
            "acquisition_df": a_df,
            "acquisition_p": a_p,
            "glaucoma_coef": glau["coef"],
            "glaucoma_p": glau["p"],
            "xa30_coef": xa["coef"],
            "xa30_p": xa["p"],
            "on_coef": on["coef"],
            "ton_coef": ton["coef"],
            "aic": float(fit.aic) if fit.aic is not None else float("nan"),
            "formula": formula,
        }
    except Exception as exc:
        LOGGER.warning("mixed %s failed: %s", iqm, exc)
        LOGGER.debug(traceback.format_exc())
        empty["status"] = f"failed: {exc}"
        return empty


def classify_family_findings(
    full_hits: list[str],
    core_hits: list[str],
    tissue_hits: list[str],
) -> str:
    n_full = len(full_hits)
    n_core = len(core_hits)
    n_tissue = len(tissue_hits)
    if n_full == 0 and n_core == 0 and n_tissue == 0:
        return "NOT_REPLICATED"
    if n_full == 1 and n_core <= 1 and n_tissue <= 1 and (n_core + n_tissue) <= 1:
        return "SINGLE_IQM_DRIVEN"
    if n_core >= 1 and n_tissue >= 1:
        return "ROBUST_ACROSS_FAMILIES"
    if n_core >= 1 or n_tissue >= 1 or n_full >= 1:
        return "FAMILY_DEPENDENT"
    return "NOT_REPLICATED"


def finite(value: Any) -> bool:
    try:
        return bool(math.isfinite(float(value)))
    except (TypeError, ValueError):
        return False
