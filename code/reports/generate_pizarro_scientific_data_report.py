#!/usr/bin/env python3
"""Generate a Scientific Data–oriented Pizarro QC report package.

Uses **existing** Pizarro prediction outputs only. Does **not** rerun inference.
Does **not** modify BIDS or derivatives.

Role of Pizarro in this package
-------------------------------
Automated structural MRI **quality screening / prioritization** for targeted
manual visual inspection. Not an exclusion classifier.

Default inputs
--------------
``~/scratch/neuro_pipeline/reports/pizarro_qc/subject_results/*_pizarro.tsv``

Default outputs
---------------
``~/scratch/reports/pizarro_qc_scientific_data/``

Example
-------
Dry-run (no files written)::

    python code/reports/generate_pizarro_scientific_data_report.py --dry-run

Generate package::

    python code/reports/generate_pizarro_scientific_data_report.py
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import logging
import math
import os
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.patches import FancyBboxPatch  # noqa: E402

LOGGER = logging.getLogger("generate_pizarro_scientific_data_report")

HOME = Path.home()
DEFAULT_SOURCE = HOME / "scratch" / "neuro_pipeline" / "reports" / "pizarro_qc"
DEFAULT_OUT = HOME / "scratch" / "reports" / "pizarro_qc_scientific_data"
DEFAULT_MODEL = (
    HOME
    / "scratch"
    / "neuro_pipeline"
    / "external"
    / "Pizarro-et-al-2023-DL-detects-MRI-artifacts"
    / "production"
    / "model.FINAL.onnx"
)
DEFAULT_LOG_DIR = HOME / "scratch" / "logs" / "pizarro_qc"
DEFAULT_LEGACY_IMAGE_TSV = HOME / "scratch" / "reports" / "pizarro_qc" / "pizarro_image_results.tsv"

N_MC_RUNS = 10
SEED = 1010
MODEL_LABEL = "Pizarro2023-FINAL"
MODEL_CITATION = "Pizarro et al. (2023)"
MODEL_FILENAME = "model.FINAL.onnx"

# Screening prioritization thresholds (not exclusion rules).
HIGH_PROBABILITY_THRESHOLD = 90.0  # model-estimated artifact probability (%)
HIGH_UNCERTAINTY_THRESHOLD = 0.9  # binary entropy (bits)

REQUIRED_STATEMENT = (
    "No image or subject was excluded based solely on the Pizarro model output. "
    "Predictions were used exclusively to prioritize targeted manual visual inspection."
)

MRIQC_STATEMENT = (
    "The Pizarro model was used as an automated structural MRI quality screening tool. "
    "Model outputs were not used for exclusion decisions but rather to prioritize images "
    "for targeted visual inspection. Quantitative MRI quality assessment remains provided "
    "by MRIQC."
)

IMAGE_COLUMNS = (
    "image_identifier",
    "subject",
    "session",
    "run",
    "filename",
    "image_path",
    "model_estimated_artifact_probability",
    "model_confidence",
    "model_uncertainty",
    "n_mc_runs",
    "n_artifact_votes",
    "model",
    "inference_date",
)

SUBJECT_COLUMNS = (
    "subject",
    "n_t1w_images",
    "n_sessions",
    "median_model_estimated_artifact_probability",
    "iqr_model_estimated_artifact_probability",
    "q1_model_estimated_artifact_probability",
    "q3_model_estimated_artifact_probability",
    "n_images_prioritized_for_visual_review",
    "n_images_high_model_estimated_artifact_probability",
    "n_images_high_model_uncertainty",
)

PRIORITY_COLUMNS = (
    "priority_basis",
    "rank",
    "image_identifier",
    "subject",
    "session",
    "run",
    "filename",
    "model_estimated_artifact_probability",
    "model_uncertainty",
    "model_confidence",
    "image_path",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _configure_logging(verbose: bool = False) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
        force=True,
    )


def _to_float(value: str | float | None) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def binary_entropy(p: float) -> float:
    """Shannon entropy (bits) of a Bernoulli(p). Max = 1 bit at p = 0.5."""
    p = min(max(float(p), 0.0), 1.0)
    if p <= 0.0 or p >= 1.0:
        return 0.0
    return float(-(p * math.log2(p) + (1.0 - p) * math.log2(1.0 - p)))


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def is_t1w_row(row: dict[str, str]) -> bool:
    """True only for BIDS T1-weighted anatomical NIfTI rows."""
    mod = (row.get("modality") or "").strip()
    name = Path(row.get("image_path") or row.get("filename") or "").name
    if mod and mod != "T1w":
        return False
    return name.endswith("_T1w.nii.gz")


def assert_analysis_is_t1w_only(rows: Iterable[dict[str, Any]]) -> None:
    """Raise if any non-T1w modality enters the analysis set."""
    offenders: list[str] = []
    for r in rows:
        path = str(r.get("image_path") or "")
        name = Path(path).name or str(r.get("filename") or "")
        mod = str(r.get("modality") or "T1w")
        if mod != "T1w" or not name.endswith("_T1w.nii.gz"):
            offenders.append(f"{mod}:{name or path}")
    if offenders:
        preview = ", ".join(offenders[:8])
        more = "" if len(offenders) <= 8 else f" (+{len(offenders) - 8} more)"
        raise RuntimeError(
            "Non-T1w modality entered the analysis set (forbidden). "
            f"Offenders: {preview}{more}"
        )


def continuous_metrics_from_row(row: dict[str, str]) -> dict[str, Any] | None:
    """Derive continuous screening scores from stored MC majority collation.

    Existing subject TSVs store:
      classification ∈ {clean, artifact, error}
      probability    = 100 × (# MC runs agreeing with majority) / n_mc

    Recovered continuous quantities:
      model_estimated_artifact_probability — % of MC runs voting artifact
      model_confidence                     — majority agreement (%)
      model_uncertainty                    — binary entropy of artifact vote fraction
    """
    classification = (row.get("classification") or "").strip().lower()
    if classification == "error":
        return None
    if classification not in {"clean", "artifact"}:
        return None

    agree = _to_float(row.get("probability"))
    if agree is None:
        return None

    n_mc = N_MC_RUNS
    agree_count = int(round(agree / 100.0 * n_mc))
    agree_count = min(max(agree_count, 0), n_mc)
    n_art = agree_count if classification == "artifact" else n_mc - agree_count
    p_art = n_art / n_mc
    confidence = 100.0 * max(p_art, 1.0 - p_art)
    uncertainty = binary_entropy(p_art)

    path = Path(row.get("image_path") or "")
    filename = path.name
    subject = row.get("subject") or ""
    session = row.get("session") or ""
    run = row.get("run") or ""
    image_id = filename if filename else f"{subject}_{session}_run-{run}_T1w.nii.gz"

    return {
        "image_identifier": image_id,
        "subject": subject,
        "session": session,
        "run": run,
        "filename": filename,
        "image_path": str(path),
        "modality": "T1w",
        "model_estimated_artifact_probability": round(100.0 * p_art, 6),
        "model_confidence": round(confidence, 6),
        "model_uncertainty": round(uncertainty, 6),
        "n_mc_runs": n_mc,
        "n_artifact_votes": n_art,
        "model": row.get("model") or MODEL_LABEL,
        "inference_date": row.get("date") or "",
        "_p": 100.0 * p_art,
        "_u": uncertainty,
        "_c": confidence,
    }


def load_prediction_rows(source_dir: Path) -> tuple[list[dict[str, Any]], list[dict[str, str]], int]:
    """Load subject TSVs; return (t1w_scored, excluded_non_t1w_raw, n_t1w_errors)."""
    results_dir = source_dir / "subject_results"
    if not results_dir.is_dir():
        raise FileNotFoundError(f"Missing subject_results directory: {results_dir}")

    tsvs = sorted(results_dir.glob("*_pizarro.tsv"))
    if not tsvs:
        raise FileNotFoundError(f"No *_pizarro.tsv files under {results_dir}")

    scored: list[dict[str, Any]] = []
    excluded: list[dict[str, str]] = []
    n_errors = 0

    for path in tsvs:
        with path.open(newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh, delimiter="\t"):
                cleaned = {k: (v or "").strip() for k, v in row.items()}
                if not is_t1w_row(cleaned):
                    excluded.append(cleaned)
                    continue
                if cleaned.get("classification", "").lower() == "error":
                    n_errors += 1
                    continue
                metrics = continuous_metrics_from_row(cleaned)
                if metrics is None:
                    n_errors += 1
                    continue
                scored.append(metrics)

    assert_analysis_is_t1w_only(scored)
    return scored, excluded, n_errors


def count_legacy_non_t1w(legacy_tsv: Path | None) -> int:
    """Optional informational count from a legacy multi-modality aggregate TSV."""
    if legacy_tsv is None or not legacy_tsv.is_file():
        return 0
    n = 0
    with legacy_tsv.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh, delimiter="\t"):
            cleaned = {k: (v or "").strip() for k, v in row.items()}
            if not is_t1w_row(cleaned):
                n += 1
    return n


def prioritize(row: dict[str, Any]) -> bool:
    return (
        float(row["_p"]) >= HIGH_PROBABILITY_THRESHOLD
        or float(row["_u"]) >= HIGH_UNCERTAINTY_THRESHOLD
    )


def subject_summaries(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_subj: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by_subj[r["subject"]].append(r)

    out: list[dict[str, Any]] = []
    for subject in sorted(by_subj, key=lambda s: (len(s), s)):
        items = by_subj[subject]
        probs = np.asarray([float(i["_p"]) for i in items], dtype=float)
        q1, median, q3 = np.percentile(probs, [25, 50, 75])
        iqr = float(q3 - q1)
        n_high_p = sum(1 for i in items if float(i["_p"]) >= HIGH_PROBABILITY_THRESHOLD)
        n_high_u = sum(1 for i in items if float(i["_u"]) >= HIGH_UNCERTAINTY_THRESHOLD)
        n_prio = sum(1 for i in items if prioritize(i))
        sessions = {i["session"] for i in items if i.get("session")}
        out.append(
            {
                "subject": subject,
                "n_t1w_images": len(items),
                "n_sessions": len(sessions),
                "median_model_estimated_artifact_probability": round(float(median), 6),
                "iqr_model_estimated_artifact_probability": round(iqr, 6),
                "q1_model_estimated_artifact_probability": round(float(q1), 6),
                "q3_model_estimated_artifact_probability": round(float(q3), 6),
                "n_images_prioritized_for_visual_review": n_prio,
                "n_images_high_model_estimated_artifact_probability": n_high_p,
                "n_images_high_model_uncertainty": n_high_u,
            }
        )
    return out


def build_priority_tables(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    high_p = sorted(
        [r for r in rows if float(r["_p"]) >= HIGH_PROBABILITY_THRESHOLD],
        key=lambda r: (float(r["_p"]), float(r["_u"]), r["image_identifier"]),
        reverse=True,
    )
    high_u = sorted(
        [r for r in rows if float(r["_u"]) >= HIGH_UNCERTAINTY_THRESHOLD],
        key=lambda r: (float(r["_u"]), float(r["_p"]), r["image_identifier"]),
        reverse=True,
    )

    out: list[dict[str, Any]] = []
    for rank, r in enumerate(high_p, start=1):
        out.append(
            {
                "priority_basis": "high_model_estimated_artifact_probability",
                "rank": rank,
                "image_identifier": r["image_identifier"],
                "subject": r["subject"],
                "session": r["session"],
                "run": r["run"],
                "filename": r["filename"],
                "model_estimated_artifact_probability": r["model_estimated_artifact_probability"],
                "model_uncertainty": r["model_uncertainty"],
                "model_confidence": r["model_confidence"],
                "image_path": r["image_path"],
            }
        )
    for rank, r in enumerate(high_u, start=1):
        out.append(
            {
                "priority_basis": "high_model_uncertainty",
                "rank": rank,
                "image_identifier": r["image_identifier"],
                "subject": r["subject"],
                "session": r["session"],
                "run": r["run"],
                "filename": r["filename"],
                "model_estimated_artifact_probability": r["model_estimated_artifact_probability"],
                "model_uncertainty": r["model_uncertainty"],
                "model_confidence": r["model_confidence"],
                "image_path": r["image_path"],
            }
        )
    return out


def write_tsv(rows: list[dict[str, Any]], path: Path, columns: tuple[str, ...]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(columns), delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in columns})
    LOGGER.info("Wrote %s (%d data rows)", path, len(rows))


# ---------------------------------------------------------------------------
# Reproducibility metadata
# ---------------------------------------------------------------------------


def detect_slurm_array_job_id(log_dir: Path) -> str | None:
    """Infer the most relevant Pizarro array job id from log files.

    Preference order:
    1. Newest logs that mention T1-weighted-only execution
    2. Otherwise the job id with the newest log mtime
    """
    if not log_dir.is_dir():
        return None

    by_id: dict[str, list[Path]] = defaultdict(list)
    for p in log_dir.glob("pizarro_qc_*.out"):
        m = re.match(r"pizarro_qc_(\d+)_\d+\.out$", p.name)
        if m:
            by_id[m.group(1)].append(p)
    if not by_id:
        return None

    def newest_mtime(paths: list[Path]) -> float:
        return max(pp.stat().st_mtime for pp in paths)

    t1_only: list[tuple[float, str]] = []
    any_jobs: list[tuple[float, str]] = []
    for job_id, paths in by_id.items():
        mt = newest_mtime(paths)
        any_jobs.append((mt, job_id))
        # Probe a few logs for the T1w-only banner used by the revised array.
        sample = sorted(paths, key=lambda q: q.stat().st_mtime, reverse=True)[:3]
        for sp in sample:
            try:
                text = sp.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if "T1-weighted ONLY" in text or "Modalities:  T1w\n" in text:
                t1_only.append((mt, job_id))
                break

    if t1_only:
        return sorted(t1_only, reverse=True)[0][1]
    return sorted(any_jobs, reverse=True)[0][1]


def collect_runtime_versions() -> dict[str, str]:
    versions = {
        "python_version": sys.version.split()[0],
        "python_full": sys.version.replace("\n", " "),
        "onnxruntime_version": "unavailable",
    }
    try:
        import onnxruntime as ort  # type: ignore

        versions["onnxruntime_version"] = str(ort.__version__)
    except Exception:
        # Fall back to venv used for inference if present.
        venv_py = HOME / "scratch" / "venvs" / "pizarro_qc" / "bin" / "python"
        if venv_py.is_file():
            import subprocess

            try:
                out = subprocess.check_output(
                    [
                        str(venv_py),
                        "-c",
                        "import sys,onnxruntime as o; print(sys.version.split()[0]); print(o.__version__)",
                    ],
                    text=True,
                    timeout=30,
                ).strip().splitlines()
                if len(out) >= 2:
                    versions["python_version"] = out[0]
                    versions["onnxruntime_version"] = out[1]
                    versions["python_source"] = str(venv_py)
            except Exception as exc:  # noqa: BLE001
                versions["onnxruntime_note"] = f"could not query venv: {exc}"
    return versions


def build_model_metadata(
    *,
    model_path: Path,
    rows: list[dict[str, Any]],
    log_dir: Path,
    report_generated: str,
) -> dict[str, Any]:
    versions = collect_runtime_versions()
    inference_dates = sorted({str(r.get("inference_date") or "") for r in rows if r.get("inference_date")})
    slurm_id = detect_slurm_array_job_id(log_dir)
    checksum = sha256_file(model_path) if model_path.is_file() else None
    return {
        "model_name": MODEL_CITATION,
        "model_label": MODEL_LABEL,
        "model_file": MODEL_FILENAME,
        "model_path": str(model_path),
        "model_sha256": checksum,
        "inference_framework": "ONNX Runtime",
        "monte_carlo_dropout_runs": N_MC_RUNS,
        "random_seed": SEED,
        "python_version": versions.get("python_version"),
        "onnxruntime_version": versions.get("onnxruntime_version"),
        "execution_date": inference_dates[-1] if inference_dates else None,
        "execution_dates_observed": inference_dates,
        "report_generated": report_generated,
        "slurm_array_job_id": slurm_id,
        "role": "automated_qc_screening_and_prioritization",
        "not_used_as": "exclusion_classifier",
        "high_probability_threshold_percent": HIGH_PROBABILITY_THRESHOLD,
        "high_uncertainty_threshold_bits": HIGH_UNCERTAINTY_THRESHOLD,
        "required_statement": REQUIRED_STATEMENT,
        "mriqc_statement": MRIQC_STATEMENT,
        "runtime_notes": {
            k: v
            for k, v in versions.items()
            if k not in {"python_version", "onnxruntime_version"}
        },
    }


# ---------------------------------------------------------------------------
# Figures
# ---------------------------------------------------------------------------


def figure_workflow(out_path: Path) -> None:
    fig, ax = plt.subplots(figsize=(10.5, 2.8))
    ax.set_xlim(0, 10.5)
    ax.set_ylim(0, 2.2)
    ax.axis("off")

    boxes = [
        (0.3, 0.7, 2.2, 1.0, "BIDS T1w images\n(*_T1w.nii.gz)"),
        (3.0, 0.7, 2.2, 1.0, "Pizarro inference\n(ONNX, MC dropout)"),
        (5.7, 0.7, 2.2, 1.0, "Continuous QC metrics\n(probability, confidence,\nuncertainty)"),
        (8.4, 0.7, 1.9, 1.0, "Manual visual\nprioritization"),
    ]
    for x, y, w, h, text in boxes:
        patch = FancyBboxPatch(
            (x, y),
            w,
            h,
            boxstyle="round,pad=0.02,rounding_size=0.08",
            linewidth=1.2,
            edgecolor="#1f4e79",
            facecolor="#eef3f8",
        )
        ax.add_patch(patch)
        ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=9)

    for x0, x1 in ((2.5, 3.0), (5.2, 5.7), (7.9, 8.4)):
        ax.annotate(
            "",
            xy=(x1, 1.2),
            xytext=(x0, 1.2),
            arrowprops=dict(arrowstyle="->", color="#1f4e79", lw=1.4),
        )

    ax.set_title(
        "Automated QC screening workflow (Pizarro → visual prioritization)",
        fontsize=11,
        pad=8,
    )
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=220, bbox_inches="tight", facecolor="white")
    fig.savefig(out_path.with_suffix(".pdf"), bbox_inches="tight", facecolor="white")
    plt.close(fig)


def figure_probability_distribution(rows: list[dict[str, Any]], out_path: Path) -> None:
    vals = [float(r["_p"]) for r in rows]
    fig, ax = plt.subplots(figsize=(7.4, 4.6))
    ax.hist(vals, bins=np.linspace(0, 100, 21), color="#1f4e79", edgecolor="white", linewidth=0.6)
    ax.set_xlabel("Model-estimated artifact probability (%)")
    ax.set_ylabel("Number of T1w images")
    ax.set_title("Distribution of model-estimated artifact probability (T1w)")
    ax.set_xlim(0, 100)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=220, bbox_inches="tight", facecolor="white")
    fig.savefig(out_path.with_suffix(".pdf"), bbox_inches="tight", facecolor="white")
    plt.close(fig)


def figure_uncertainty_probability(rows: list[dict[str, Any]], out_path: Path) -> None:
    x = np.asarray([float(r["_u"]) for r in rows], dtype=float)
    y = np.asarray([float(r["_p"]) for r in rows], dtype=float)
    high_u = x >= HIGH_UNCERTAINTY_THRESHOLD

    fig, ax = plt.subplots(figsize=(7.4, 5.0))
    ax.scatter(x[~high_u], y[~high_u], s=28, alpha=0.65, c="#7a8a99", label="Other T1w images", edgecolors="none")
    ax.scatter(
        x[high_u],
        y[high_u],
        s=42,
        alpha=0.9,
        c="#c45c26",
        label=f"High uncertainty (≥ {HIGH_UNCERTAINTY_THRESHOLD:g} bit)",
        edgecolors="white",
        linewidths=0.4,
    )
    ax.axvline(HIGH_UNCERTAINTY_THRESHOLD, color="#c45c26", ls="--", lw=1.0, alpha=0.8)
    ax.set_xlabel("Model uncertainty (bits)")
    ax.set_ylabel("Model-estimated artifact probability (%)")
    ax.set_title("Model uncertainty vs model-estimated artifact probability")
    ax.set_xlim(-0.02, 1.05)
    ax.set_ylim(-2, 105)
    ax.legend(frameon=False, loc="best")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=220, bbox_inches="tight", facecolor="white")
    fig.savefig(out_path.with_suffix(".pdf"), bbox_inches="tight", facecolor="white")
    plt.close(fig)


def figure_subject_coverage(rows: list[dict[str, Any]], out_path: Path) -> None:
    counts = Counter(r["subject"] for r in rows)
    n_per_subject = list(counts.values())
    fig, ax = plt.subplots(figsize=(7.0, 4.4))
    bins = np.arange(min(n_per_subject) - 0.5, max(n_per_subject) + 1.5, 1)
    ax.hist(n_per_subject, bins=bins, color="#1f4e79", edgecolor="white", linewidth=0.6)
    ax.set_xlabel("Number of T1w scans per subject")
    ax.set_ylabel("Number of subjects")
    ax.set_title("Distribution of T1w scan counts per subject")
    ax.set_xticks(sorted(set(n_per_subject)))
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=220, bbox_inches="tight", facecolor="white")
    fig.savefig(out_path.with_suffix(".pdf"), bbox_inches="tight", facecolor="white")
    plt.close(fig)


# ---------------------------------------------------------------------------
# Report markdown
# ---------------------------------------------------------------------------


def format_priority_md_table(rows: list[dict[str, Any]], basis: str, limit: int | None = None) -> str:
    subset = [r for r in rows if r["priority_basis"] == basis]
    if limit is not None:
        subset = subset[:limit]
    if not subset:
        return "_None under current thresholds._\n"
    lines = [
        "| Rank | Image identifier | Model-estimated artifact probability | Uncertainty | Confidence |",
        "| ---: | --- | ---: | ---: | ---: |",
    ]
    for r in subset:
        lines.append(
            f"| {r['rank']} | `{r['image_identifier']}` | "
            f"{r['model_estimated_artifact_probability']} | "
            f"{r['model_uncertainty']} | {r['model_confidence']} |"
        )
    return "\n".join(lines) + "\n"


def write_report_md(
    path: Path,
    *,
    rows: list[dict[str, Any]],
    subjects: list[dict[str, Any]],
    priority: list[dict[str, Any]],
    meta: dict[str, Any],
    n_excluded: int,
    n_legacy_non_t1w: int,
    n_errors: int,
    source_dir: Path,
) -> None:
    n_images = len(rows)
    n_subjects = len(subjects)
    n_prio_images = sum(1 for r in rows if prioritize(r))
    n_high_p = sum(1 for r in rows if float(r["_p"]) >= HIGH_PROBABILITY_THRESHOLD)
    n_high_u = sum(1 for r in rows if float(r["_u"]) >= HIGH_UNCERTAINTY_THRESHOLD)
    n_subj_with_prio = sum(1 for s in subjects if int(s["n_images_prioritized_for_visual_review"]) > 0)

    high_p_table = format_priority_md_table(
        priority, "high_model_estimated_artifact_probability", limit=None
    )
    # Keep markdown readable: show first 25 in-report; full list in TSV.
    high_p_preview = format_priority_md_table(
        priority, "high_model_estimated_artifact_probability", limit=25
    )
    high_u_table = format_priority_md_table(priority, "high_model_uncertainty", limit=None)

    md = f"""# Pizarro automated QC screening report (Scientific Data)

**Dataset role:** automated structural MRI quality screening and prioritization  
**Modality scope:** `*_T1w.nii.gz` only  
**Report generated:** {meta.get("report_generated")}

## Statements for the Data Descriptor

> {MRIQC_STATEMENT}

> {REQUIRED_STATEMENT}

## Scope and exclusions

Only BIDS anatomical T1-weighted NIfTI files matching `*_T1w.nii.gz` were analysed.
FLAIR, T2-weighted, diffusion, functional, fieldmap, and all other modalities were
excluded from this package and must not enter the analysis tables or figures.

| Item | Count |
| --- | ---: |
| T1w images included in analysis | {n_images} |
| Non-T1w rows excluded from current subject TSVs | {n_excluded} |
| Legacy non-T1w rows in historical aggregate (informational) | {n_legacy_non_t1w} |
| T1w inference/load errors among scored inputs | {n_errors} |
| Subjects represented | {n_subjects} |

Validation: the analysis set is asserted to contain **T1w only**; presence of any
non-T1w modality raises an error at report generation time.

## Continuous screening metrics

For each T1w image the following continuous quantities are retained:

| Metric | Definition |
| --- | --- |
| Model-estimated artifact probability | Percentage of Monte Carlo (MC) dropout runs voting for the artifact class (0–100) |
| Model confidence | Majority-class agreement across MC runs (0–100) |
| Model uncertainty | Binary Shannon entropy (bits) of the MC artifact-vote fraction; maximal (1 bit) when votes are evenly split |

These quantities are **screening / prioritization indices** for manual visual
inspection. They are not automatic exclusion criteria.

### Prioritization thresholds used for review queues

| Criterion | Threshold | Interpretation |
| --- | --- | --- |
| High model-estimated artifact probability | ≥ {HIGH_PROBABILITY_THRESHOLD:g}% | Prioritize for visual review |
| High model uncertainty | ≥ {HIGH_UNCERTAINTY_THRESHOLD:g} bit | Prioritize for visual review regardless of majority vote |

Under these thresholds:

- T1w images prioritized for visual review: **{n_prio_images}**
- via high model-estimated artifact probability: **{n_high_p}**
- via high model uncertainty: **{n_high_u}**
- subjects prioritized for visual review (≥1 prioritized image): **{n_subj_with_prio}**

These counts describe **screening priority** for targeted manual inspection.
They are not pass/fail labels, exclusion tallies, or a dataset failure rate.

## Subject-level descriptive summary

Subject tables report:

- number of T1w images
- median model-estimated artifact probability
- interquartile range (IQR)
- number of images requiring prioritized review

Mean model-estimated artifact probability is intentionally **not** reported as a
cohort quality indicator.

## Images prioritized for visual inspection based on high model-estimated artifact probability

Full ranked list: `tables/pizarro_visual_review_priority.tsv`
(`priority_basis = high_model_estimated_artifact_probability`).

Preview (first 25):

{high_p_preview}

## Images prioritized for visual inspection based on high model uncertainty

Full ranked list: `tables/pizarro_visual_review_priority.tsv`
(`priority_basis = high_model_uncertainty`).

{high_u_table}

## Figures

| Figure | File | Description |
| --- | --- | --- |
| 1 | `figures/pizarro_workflow.png` | BIDS T1w → Pizarro inference → continuous metrics → manual visual prioritization |
| 2 | `figures/pizarro_probability_distribution.png` | Histogram of model-estimated artifact probability |
| 3 | `figures/pizarro_uncertainty_probability.png` | Uncertainty vs model-estimated artifact probability (high-uncertainty highlighted) |
| 4 | `figures/pizarro_subject_coverage.png` | Distribution of number of T1w scans per subject |

Pass/fail and artifact-rate figures are intentionally omitted.

## Reproducibility

| Item | Value |
| --- | --- |
| Model name | {meta.get("model_name")} |
| Model file | `{meta.get("model_file")}` |
| Model SHA256 | `{meta.get("model_sha256")}` |
| Inference framework | {meta.get("inference_framework")} |
| Monte Carlo dropout runs | {meta.get("monte_carlo_dropout_runs")} |
| Random seed | {meta.get("random_seed")} |
| Python version | {meta.get("python_version")} |
| ONNX Runtime version | {meta.get("onnxruntime_version")} |
| Execution date | {meta.get("execution_date")} |
| Slurm array job ID | {meta.get("slurm_array_job_id") or "not detected"} |
| Source predictions | `{source_dir}/subject_results/*_pizarro.tsv` |

Machine-readable copy: `metadata/model_metadata.json`.

## Deliverables

| Path | Description |
| --- | --- |
| `PIZARRO_QC_REPORT.md` | This Data Descriptor–oriented report |
| `tables/pizarro_image_level.tsv` | Continuous scores per T1w image |
| `tables/pizarro_subject_level.tsv` | Subject descriptive aggregates |
| `tables/pizarro_visual_review_priority.tsv` | Visual-review priority queues |
| `figures/` | Publication figures 1–4 |
| `metadata/model_metadata.json` | Reproducibility metadata |

## Citation

{MODEL_CITATION}. Deep learning detects MRI artifacts.
Model file: `{MODEL_FILENAME}`.
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(md, encoding="utf-8")
    LOGGER.info("Wrote %s", path)
    # silence unused if limit path unused
    _ = high_p_table


# ---------------------------------------------------------------------------
# Dry-run / orchestration
# ---------------------------------------------------------------------------


@dataclass
class Plan:
    source_dir: Path
    out_dir: Path
    model_path: Path
    log_dir: Path
    legacy_tsv: Path | None
    input_files: list[Path] = field(default_factory=list)
    output_files: list[Path] = field(default_factory=list)
    n_t1w: int = 0
    n_excluded_non_t1w: int = 0
    n_legacy_non_t1w: int = 0
    n_errors: int = 0
    n_subjects: int = 0


def planned_outputs(out_dir: Path) -> list[Path]:
    return [
        out_dir / "PIZARRO_QC_REPORT.md",
        out_dir / "tables" / "pizarro_image_level.tsv",
        out_dir / "tables" / "pizarro_subject_level.tsv",
        out_dir / "tables" / "pizarro_visual_review_priority.tsv",
        out_dir / "figures" / "pizarro_workflow.png",
        out_dir / "figures" / "pizarro_workflow.pdf",
        out_dir / "figures" / "pizarro_probability_distribution.png",
        out_dir / "figures" / "pizarro_probability_distribution.pdf",
        out_dir / "figures" / "pizarro_uncertainty_probability.png",
        out_dir / "figures" / "pizarro_uncertainty_probability.pdf",
        out_dir / "figures" / "pizarro_subject_coverage.png",
        out_dir / "figures" / "pizarro_subject_coverage.pdf",
        out_dir / "metadata" / "model_metadata.json",
    ]


def build_plan(args: argparse.Namespace) -> tuple[Plan, list[dict[str, Any]]]:
    source = Path(args.source_dir)
    out = Path(args.out_dir)
    model = Path(args.model_path)
    log_dir = Path(args.log_dir)
    legacy = Path(args.legacy_image_tsv) if args.legacy_image_tsv else None

    rows, excluded, n_errors = load_prediction_rows(source)
    input_files = sorted((source / "subject_results").glob("*_pizarro.tsv"))
    n_legacy = count_legacy_non_t1w(legacy)

    plan = Plan(
        source_dir=source,
        out_dir=out,
        model_path=model,
        log_dir=log_dir,
        legacy_tsv=legacy,
        input_files=input_files,
        output_files=planned_outputs(out),
        n_t1w=len(rows),
        n_excluded_non_t1w=len(excluded),
        n_legacy_non_t1w=n_legacy,
        n_errors=n_errors,
        n_subjects=len({r["subject"] for r in rows}),
    )
    return plan, rows


def print_dry_run(plan: Plan) -> None:
    print("=" * 72)
    print("Pizarro Scientific Data report — DRY RUN (no files written)")
    print("=" * 72)
    print(f"Source directory:     {plan.source_dir}")
    print(f"Output directory:     {plan.out_dir}")
    print(f"Model file:           {plan.model_path}")
    print(f"Log directory:        {plan.log_dir}")
    print(f"Legacy aggregate TSV: {plan.legacy_tsv}")
    print()
    print("Input files detected:")
    print(f"  subject TSVs: {len(plan.input_files)} under {plan.source_dir / 'subject_results'}")
    for p in plan.input_files[:5]:
        print(f"    - {p}")
    if len(plan.input_files) > 5:
        print(f"    ... ({len(plan.input_files) - 5} more)")
    if plan.model_path.is_file():
        print(f"  model: {plan.model_path}")
    else:
        print(f"  model: MISSING — {plan.model_path}")
    if plan.legacy_tsv and plan.legacy_tsv.is_file():
        print(f"  legacy aggregate (informational): {plan.legacy_tsv}")
    print()
    print("Inclusion / exclusion counts:")
    print(f"  T1w images included:                    {plan.n_t1w}")
    print(f"  Subjects:                               {plan.n_subjects}")
    print(f"  Non-T1w excluded from subject TSVs:     {plan.n_excluded_non_t1w}")
    print(f"  Legacy non-T1w in historical aggregate: {plan.n_legacy_non_t1w}")
    print(f"  T1w scored as error / unusable:         {plan.n_errors}")
    print()
    print("Output files that will be generated:")
    for p in plan.output_files:
        print(f"  - {p}")
    print("=" * 72)


def generate(plan: Plan, rows: list[dict[str, Any]]) -> None:
    assert_analysis_is_t1w_only(rows)
    out = plan.out_dir
    (out / "tables").mkdir(parents=True, exist_ok=True)
    (out / "figures").mkdir(parents=True, exist_ok=True)
    (out / "metadata").mkdir(parents=True, exist_ok=True)

    subjects = subject_summaries(rows)
    priority = build_priority_tables(rows)
    report_generated = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    meta = build_model_metadata(
        model_path=plan.model_path,
        rows=rows,
        log_dir=plan.log_dir,
        report_generated=report_generated,
    )

    # Tables
    write_tsv(
        [
            {
                **{k: r[k] for k in IMAGE_COLUMNS if k in r},
                "model_estimated_artifact_probability": r["model_estimated_artifact_probability"],
                "model_confidence": r["model_confidence"],
                "model_uncertainty": r["model_uncertainty"],
            }
            for r in rows
        ],
        out / "tables" / "pizarro_image_level.tsv",
        IMAGE_COLUMNS,
    )
    write_tsv(subjects, out / "tables" / "pizarro_subject_level.tsv", SUBJECT_COLUMNS)
    write_tsv(priority, out / "tables" / "pizarro_visual_review_priority.tsv", PRIORITY_COLUMNS)

    # Figures
    figure_workflow(out / "figures" / "pizarro_workflow.png")
    figure_probability_distribution(rows, out / "figures" / "pizarro_probability_distribution.png")
    figure_uncertainty_probability(rows, out / "figures" / "pizarro_uncertainty_probability.png")
    figure_subject_coverage(rows, out / "figures" / "pizarro_subject_coverage.png")

    # Metadata + report
    meta_path = out / "metadata" / "model_metadata.json"
    meta_path.write_text(json.dumps(meta, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    LOGGER.info("Wrote %s", meta_path)

    write_report_md(
        out / "PIZARRO_QC_REPORT.md",
        rows=rows,
        subjects=subjects,
        priority=priority,
        meta=meta,
        n_excluded=plan.n_excluded_non_t1w,
        n_legacy_non_t1w=plan.n_legacy_non_t1w,
        n_errors=plan.n_errors,
        source_dir=plan.source_dir,
    )

    # Small README pointer
    readme = out / "README.md"
    readme.write_text(
        "# Pizarro QC — Scientific Data package\n\n"
        "T1-weighted automated QC screening / visual-review prioritization only.\n\n"
        "See `PIZARRO_QC_REPORT.md`.\n",
        encoding="utf-8",
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--source-dir",
        type=Path,
        default=DEFAULT_SOURCE,
        help="Directory containing subject_results/*_pizarro.tsv",
    )
    p.add_argument(
        "--out-dir",
        type=Path,
        default=DEFAULT_OUT,
        help="Output package directory",
    )
    p.add_argument(
        "--model-path",
        type=Path,
        default=DEFAULT_MODEL,
        help="Path to model.FINAL.onnx (for SHA256; inference is not rerun)",
    )
    p.add_argument(
        "--log-dir",
        type=Path,
        default=DEFAULT_LOG_DIR,
        help="Slurm log directory used to recover array job ID",
    )
    p.add_argument(
        "--legacy-image-tsv",
        type=Path,
        default=DEFAULT_LEGACY_IMAGE_TSV,
        help="Optional legacy multi-modality aggregate TSV for informational exclusion counts",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Show inclusion counts and planned outputs without writing files",
    )
    p.add_argument("-v", "--verbose", action="store_true")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    _configure_logging(args.verbose)
    plan, rows = build_plan(args)
    print_dry_run(plan)
    if args.dry_run:
        LOGGER.info("Dry-run complete; no outputs written.")
        return 0
    LOGGER.info("Writing Scientific Data package to %s", plan.out_dir)
    generate(plan, rows)
    LOGGER.info("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
