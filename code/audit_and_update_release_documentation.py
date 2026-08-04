#!/usr/bin/env python3
"""Audit and (optionally) update release_dataset documentation for Scientific Data / OpenNeuro.

Default mode is AUDIT ONLY. Pass --update to create a timestamped backup and refresh
documentation from live metadata, QC outputs, and reports.

Never invents scientific values. Unavailable items are recorded as
"Not available in current release metadata".

Does not modify raw_original/ or original BIDS imaging data.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import pandas as pd
except ImportError as exc:  # pragma: no cover
    raise SystemExit("pandas is required (Python >= 3.11).") from exc

try:
    import yaml  # type: ignore
except ImportError:  # optional
    yaml = None  # type: ignore

NA = "Not available in current release metadata"
ROOT_DEFAULT = Path("/home/alexrees/scratch").resolve()

DOC_SUFFIXES = {".md", ".tsv", ".json", ".yml", ".yaml", ".txt"}
DOC_NAMES = {
    "readme",
    "readme.md",
    "license",
    "license.md",
    "license.txt",
    "changes",
    "changes.md",
    "dataset_description.json",
    "participants.tsv",
    "participants.json",
    ".bidsignore",
}

REQUIRED_OPEN_SCIENCE_DOCS = [
    ("README.md", "release_root"),
    ("dataset_description.json", "release_root"),
    ("CHANGES.md", "release_root_or_CHANGES"),
    ("LICENSE", "release_root"),
    ("participants.tsv", "release_root"),
    ("participants.json", "release_root"),
    ("acquisition_protocol.md", "docs"),
    ("quality_control.md", "docs"),
    ("data_dictionary.md", "docs"),
    ("task_descriptions.md", "docs"),
    ("physiology_methods.md", "docs"),
    ("limitations.md", "docs"),
    ("software_versions.md", "docs"),
    ("provenance.md", "docs"),
]

PHI_JSON_KEYS = {
    "PatientName",
    "PatientID",
    "PatientBirthDate",
    "PatientSex",
    "PatientAge",
    "PatientWeight",
    "ReferringPhysicianName",
    "InstitutionName",
    "InstitutionalDepartmentName",
    "DeviceSerialNumber",
    "StationName",
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_stamp() -> str:
    return utc_now().strftime("%Y%m%dT%H%M%SZ")


def utc_iso() -> str:
    return utc_now().strftime("%Y-%m-%dT%H:%M:%SZ")


def log(msg: str) -> None:
    print(msg, flush=True)


def rel_display(path: Path | str | None, project: Path) -> str:
    """Project-relative path for publication docs (never emit absolute host paths)."""
    if path is None or path == "" or path == NA:
        return NA
    p = Path(str(path))
    try:
        return str(p.resolve().relative_to(project.resolve()))
    except Exception:
        text = str(path)
        # Fallback: strip known absolute prefixes
        for prefix in (
            str(project.resolve()) + "/",
            "/home/alexrees/scratch/",
            "/lustre07/scratch/alexrees/",
        ):
            if text.startswith(prefix):
                return text[len(prefix) :]
        if text.startswith("/"):
            return NA
        return text


def scrub_abs_paths(text: str, project: Path) -> str:
    if not text or text == NA:
        return text
    out = text
    for prefix in (
        str(project.resolve()) + "/",
        "/home/alexrees/scratch/",
        "/lustre07/scratch/alexrees/",
    ):
        out = out.replace(prefix, "")
    # Any remaining absolute lustre/home paths → placeholder
    out = re.sub(r"(/lustre\d+/[^\s)`]+|/home/[^\s)`]+)", NA, out)
    return out


def fence_safe_excerpt(text: str, project: Path | None = None) -> str:
    """Neutralize markdown fences and absolute paths inside embedded excerpts."""
    if not text or text == NA:
        return text if text else NA
    out = text.replace("```", "'''")
    if project is not None:
        out = scrub_abs_paths(out, project)
    return out


def sha256_file(path: Path, max_bytes: int | None = 64 * 1024 * 1024) -> str:
    """SHA256 of file contents; large files hashed on first max_bytes with suffix note."""
    h = hashlib.sha256()
    size = path.stat().st_size
    with path.open("rb") as fh:
        if max_bytes is not None and size > max_bytes:
            remaining = max_bytes
            while remaining > 0:
                chunk = fh.read(min(1024 * 1024, remaining))
                if not chunk:
                    break
                h.update(chunk)
                remaining -= len(chunk)
            return f"{h.hexdigest()} (first_{max_bytes}_bytes_of_{size})"
        while True:
            chunk = fh.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def safe_read_text(path: Path, limit: int | None = None) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    if limit is not None:
        return text[:limit]
    return text


def load_json(path: Path) -> Any | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=False) + "\n", encoding="utf-8")


def write_tsv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, delimiter="\t", extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow({k: row.get(k, "") for k in fields})


def write_md(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not text.endswith("\n"):
        text += "\n"
    path.write_text(text, encoding="utf-8")


def run_find(root: Path, args: list[str]) -> list[str]:
    if not root.exists():
        return []
    proc = subprocess.run(
        ["find", str(root), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode not in (0, 1):
        return []
    return [ln for ln in proc.stdout.splitlines() if ln]


def detect_purpose(path: Path) -> str:
    name = path.name.lower()
    rel = str(path).lower()
    if name == "readme.md" or name == "readme":
        return "readme"
    if name.startswith("license"):
        return "license"
    if name.startswith("changes"):
        return "changelog"
    if name == "dataset_description.json":
        return "bids_dataset_description"
    if name == "participants.tsv":
        return "participants_table"
    if name == "participants.json":
        return "participants_dictionary"
    if "physio" in name:
        return "physiology"
    if "dwi" in name or "dmri" in name:
        return "diffusion_qc_or_data"
    if "mriqc" in rel:
        return "mriqc"
    if "protocol" in name or "/protocols/" in rel:
        return "acquisition_or_task_protocol"
    if name.endswith("_events.tsv") or "events" in name:
        return "events"
    if name.endswith(".md"):
        return "markdown_documentation"
    if name.endswith(".json"):
        return "json_metadata"
    if name.endswith(".tsv"):
        return "tabular_metadata"
    if name.endswith((".yml", ".yaml")):
        return "yaml_config_or_metadata"
    return "documentation_or_metadata"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Audit (and optionally update) release_dataset documentation."
    )
    p.add_argument("--release_dir", type=Path, default=ROOT_DEFAULT / "release_dataset")
    p.add_argument("--bids_dir", type=Path, default=ROOT_DEFAULT / "bids")
    p.add_argument("--derivatives_dir", type=Path, default=ROOT_DEFAULT / "derivatives")
    p.add_argument("--metadata_dir", type=Path, default=ROOT_DEFAULT / "metadata")
    p.add_argument("--reports_dir", type=Path, default=ROOT_DEFAULT / "reports")
    p.add_argument(
        "--output_dir",
        type=Path,
        default=ROOT_DEFAULT / "reports" / "release_documentation_audit",
    )
    p.add_argument(
        "--update",
        action="store_true",
        help="Backup then update release documentation from audited state.",
    )
    p.add_argument(
        "--project_root",
        type=Path,
        default=ROOT_DEFAULT,
        help="Workspace root (for docs/, code/, backups).",
    )
    p.add_argument(
        "--skip_bids_validator",
        action="store_true",
        help="Skip bids-validator invocation in phase 7.",
    )
    return p.parse_args()


# ---------------------------------------------------------------------------
# Phase 1 — Documentation inventory
# ---------------------------------------------------------------------------


def _should_inventory(path: Path, scan_root: Path, root_name: str) -> bool:
    name = path.name
    lower = name.lower()
    if lower in DOC_NAMES or name in DOC_NAMES:
        return True
    if path.suffix.lower() not in DOC_SUFFIXES:
        return False
    # Avoid hashing every subject sidecar under release/bids trees.
    if root_name in {"release_dataset", "bids"}:
        rel = path.relative_to(scan_root)
        parts = rel.parts
        if parts and parts[0].startswith("sub-"):
            # Keep only top-level-ish docs under subject trees that are clearly docs.
            if path.suffix.lower() == ".md":
                return True
            return False
        return True
    if root_name == "derivatives":
        # Keep pipeline-level reports, not every MRIQC subject JSON.
        rel = path.relative_to(scan_root)
        if len(rel.parts) <= 3:
            return True
        if any(
            k in name.lower()
            for k in ("report", "summary", "readme", "dataset_description", "inventory", "qc")
        ):
            return True
        if any(part.startswith("sub-") for part in rel.parts):
            return False
        return True
    if root_name == "code":
        if "__pycache__" in path.parts or path.suffix == ".pyc":
            return False
        return path.suffix.lower() in {".md", ".tsv", ".json", ".yml", ".yaml", ".txt"}
    return True


def phase1_inventory(paths: dict[str, Path], out_dir: Path) -> list[dict[str, Any]]:
    log("PHASE 1 — Documentation inventory")
    rows: list[dict[str, Any]] = []
    scan_map = {
        "release_dataset": paths["release"],
        "docs": paths["docs"],
        "metadata": paths["metadata"],
        "code": paths["code"],
        "derivatives": paths["derivatives"],
    }
    for root_name, root in scan_map.items():
        if not root.exists():
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            # prune heavy trees
            dirnames[:] = [
                d
                for d in dirnames
                if d not in {".git", "__pycache__", "node_modules", "work", ".npm-cache"}
                and not d.startswith("apptainer")
            ]
            for fn in filenames:
                p = Path(dirpath) / fn
                if not _should_inventory(p, root, root_name):
                    continue
                try:
                    st = p.stat()
                except OSError:
                    continue
                try:
                    digest = sha256_file(p)
                except OSError:
                    digest = NA
                rows.append(
                    {
                        "path": str(p),
                        "file_type": p.suffix.lower().lstrip(".") or p.name,
                        "size": st.st_size,
                        "last_modified": datetime.fromtimestamp(
                            st.st_mtime, tz=timezone.utc
                        ).strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "sha256": digest,
                        "purpose_detected": detect_purpose(p),
                    }
                )
    rows.sort(key=lambda r: r["path"])
    write_tsv(
        out_dir / "DOCUMENTATION_INVENTORY.tsv",
        rows,
        ["path", "file_type", "size", "last_modified", "sha256", "purpose_detected"],
    )
    log(f"  Inventoried {len(rows)} documentation/metadata files")
    return rows


# ---------------------------------------------------------------------------
# Phase 2 — Current dataset state
# ---------------------------------------------------------------------------


def _count_find(root: Path, name_pattern: str, extra: list[str] | None = None) -> int:
    args = ["-type", "f", "-name", name_pattern]
    if extra:
        args.extend(extra)
    return len(run_find(root, args))


def _modality_counts(root: Path) -> dict[str, int]:
    lines = run_find(root, ["-type", "f", "-name", "*.nii.gz"])
    counts: Counter[str] = Counter()
    for ln in lines:
        name = Path(ln).name
        if name.endswith(".nii.gz"):
            stem = name[: -len(".nii.gz")]
            suffix = stem.split("_")[-1]
            counts[suffix] += 1
    return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))


def _task_bold_counts(root: Path) -> dict[str, int]:
    lines = run_find(root, ["-type", "f", "-name", "*_bold.nii.gz"])
    counts: Counter[str] = Counter()
    for ln in lines:
        name = Path(ln).name
        if "part-phase" in name:
            continue
        m = re.search(r"task-([A-Za-z0-9]+)", name)
        if m:
            counts[m.group(1)] += 1
    return dict(sorted(counts.items()))


def _events_by_task(root: Path) -> dict[str, int]:
    lines = run_find(root, ["-type", "f", "-name", "*_events.tsv"])
    counts: Counter[str] = Counter()
    for ln in lines:
        m = re.search(r"task-([A-Za-z0-9]+)", Path(ln).name)
        if m:
            counts[m.group(1)] += 1
    return dict(sorted(counts.items()))


def _physio_by_recording(root: Path) -> dict[str, int]:
    lines = run_find(root, ["-type", "f", "-name", "*_physio.tsv.gz"])
    counts: Counter[str] = Counter()
    for ln in lines:
        m = re.search(r"recording-([A-Za-z0-9]+)", Path(ln).name)
        if m:
            counts[m.group(1)] += 1
        else:
            counts["unspecified"] += 1
    return dict(sorted(counts.items()))


def _session_coverage(root: Path) -> dict[str, int]:
    both = s1 = s2 = neither = 0
    subjects = [p for p in root.iterdir() if p.is_dir() and p.name.startswith("sub-")]
    for sub in subjects:
        ses = {p.name for p in sub.iterdir() if p.is_dir() and p.name.startswith("ses-")}
        if "ses-01" in ses and "ses-02" in ses:
            both += 1
        elif "ses-01" in ses:
            s1 += 1
        elif "ses-02" in ses:
            s2 += 1
        else:
            neither += 1
    return {
        "both_sessions": both,
        "ses-01_only": s1,
        "ses-02_only": s2,
        "neither": neither,
        "subject_session_dirs": len(run_find(root, ["-mindepth", "2", "-maxdepth", "2", "-type", "d", "-name", "ses-*"])),
    }


def _cohort_counts(participants_tsv: Path) -> dict[str, int]:
    if not participants_tsv.is_file():
        return {}
    df = pd.read_csv(participants_tsv, sep="\t", dtype=str)
    if "cohort" not in df.columns:
        return {}
    return {str(k): int(v) for k, v in df["cohort"].fillna("n/a").value_counts().items()}


def _read_report_snippet(path: Path, max_chars: int = 4000) -> str | None:
    if not path.is_file():
        return None
    return safe_read_text(path, limit=max_chars)


def _extract_acquisition_examples(release: Path) -> dict[str, Any]:
    """Pull representative parameters from sub-001 sidecars when present."""
    examples: dict[str, Any] = {}
    patterns = {
        "T1w_MPRAGE": "sub-001/ses-01/anat/*_T1w.json",
        "FLAIR": "sub-001/ses-01/anat/*_FLAIR.json",
        "rest_bold": "sub-001/ses-01/func/*task-rest*run-*_bold.json",
        "dwi": "sub-001/ses-01/dwi/*_dwi.json",
        "fmap_PA": "sub-001/ses-01/fmap/*dir-PA*_epi.json",
    }
    keys = [
        "Manufacturer",
        "ManufacturersModelName",
        "MagneticFieldStrength",
        "RepetitionTime",
        "EchoTime",
        "FlipAngle",
        "MultibandAccelerationFactor",
        "PhaseEncodingDirection",
        "ProtocolName",
        "ConversionSoftware",
        "ConversionSoftwareVersion",
        "PulseSequenceType",
        "ScanningSequence",
        "SequenceName",
    ]
    for label, pattern in patterns.items():
        hits = sorted(release.glob(pattern))
        # Prefer magnitude (no part-phase) when available.
        mag = [h for h in hits if "part-phase" not in h.name]
        chosen = (mag or hits)
        if not chosen:
            examples[label] = NA
            continue
        data = load_json(chosen[0]) or {}
        examples[label] = {
            "source_file": str(chosen[0].relative_to(release)),
            **{k: data[k] for k in keys if k in data},
        }
    return examples


def _load_physio_statistics(paths: dict[str, Path], release: Path) -> dict[str, Any]:
    stats: dict[str, Any] = {
        "physio_tsv_gz_in_release": _count_find(release, "*_physio.tsv.gz"),
        "physio_json_in_release": _count_find(release, "*_physio.json"),
        "by_recording": _physio_by_recording(release),
    }
    conv_summary = (
        paths["reports"]
        / "physiology_audit"
        / "final_bids_physio_readiness"
        / "conversion_run"
        / "CONVERSION_SUMMARY.md"
    )
    excl_readme = (
        paths["reports"]
        / "physiology_audit"
        / "final_bids_physio_readiness"
        / "EXCLUDED_physio_reasons_README.md"
    )
    readiness = (
        paths["reports"]
        / "physiology_audit"
        / "final_bids_physio_readiness"
        / "FINAL_PHYSIO_READINESS_REPORT.md"
    )
    qc_json = paths["derivatives"] / "physiology_qc" / "physiology_qc_summary.json"
    qc_md = paths["derivatives"] / "physiology_qc" / "PHYSIOLOGY_QC_REPORT.md"
    stats["conversion_summary_source"] = (
        rel_display(conv_summary, paths["project"]) if conv_summary.is_file() else NA
    )
    stats["exclusion_readme_source"] = (
        rel_display(excl_readme, paths["project"]) if excl_readme.is_file() else NA
    )
    stats["readiness_report_source"] = (
        rel_display(readiness, paths["project"]) if readiness.is_file() else NA
    )
    stats["conversion_summary_excerpt"] = scrub_abs_paths(
        _read_report_snippet(conv_summary, 2500) or NA, paths["project"]
    )
    stats["exclusion_readme_excerpt"] = scrub_abs_paths(
        _read_report_snippet(excl_readme, 2500) or NA, paths["project"]
    )
    if qc_json.is_file():
        stats["physiology_qc_summary"] = load_json(qc_json)
        stats["physiology_qc_summary_note"] = (
            "Derivative physiology_qc summary may reflect a subset/run scope; "
            "prefer live release physio file counts for inventory."
        )
    else:
        stats["physiology_qc_summary"] = NA
    stats["physiology_qc_report_excerpt"] = scrub_abs_paths(
        _read_report_snippet(qc_md, 2000) or NA, paths["project"]
    )
    excl_tsv = (
        paths["reports"]
        / "physiology_audit"
        / "final_bids_physio_readiness"
        / "EXCLUDED_physio_reasons.tsv"
    )
    if excl_tsv.is_file():
        try:
            edf = pd.read_csv(excl_tsv, sep="\t", dtype=str)
            col = None
            for c in ("exclusion_class", "reason", "FINAL_DECISION", "failure_reason"):
                if c in edf.columns:
                    col = c
                    break
            if col:
                stats["exclusion_reason_counts"] = {
                    str(k): int(v) for k, v in edf[col].fillna("n/a").value_counts().items()
                }
            else:
                stats["exclusion_reason_counts"] = {"rows": len(edf)}
        except Exception as exc:  # noqa: BLE001
            stats["exclusion_reason_counts"] = f"Failed to parse: {exc}"
    else:
        stats["exclusion_reason_counts"] = NA
    return stats


def _load_dwi_statistics(paths: dict[str, Path], release: Path) -> dict[str, Any]:
    stats: dict[str, Any] = {
        "dwi_nifti_in_release": _count_find(release, "*_dwi.nii.gz"),
    }
    report = paths["reports"] / "dwi_qc" / "DWI_QC_REPORT.md"
    inv = paths["reports"] / "dwi_qc" / "dwi_inventory.tsv"
    stats["dwi_qc_report_source"] = rel_display(report, paths["project"]) if report.is_file() else NA
    stats["dwi_qc_report_excerpt"] = scrub_abs_paths(
        _read_report_snippet(report, 3000) or NA, paths["project"]
    )
    if inv.is_file():
        try:
            df = pd.read_csv(inv, sep="\t", dtype=str)
            stats["dwi_inventory_rows"] = len(df)
        except Exception as exc:  # noqa: BLE001
            stats["dwi_inventory_rows"] = f"Failed to parse: {exc}"
    else:
        stats["dwi_inventory_rows"] = NA
    bval_summary = paths["reports"] / "dwi_qc" / "dwi_bvalue_summary.tsv"
    if bval_summary.is_file():
        try:
            bdf = pd.read_csv(bval_summary, sep="\t", dtype=str)
            stats["dwi_bvalue_summary_rows"] = len(bdf)
            # Attempt common column names
            for col in ("bvals", "bvalue_set", "scheme", "b_values"):
                if col in bdf.columns:
                    stats["bvalue_scheme_counts"] = {
                        str(k): int(v) for k, v in bdf[col].fillna("n/a").value_counts().items()
                    }
                    break
        except Exception as exc:  # noqa: BLE001
            stats["bvalue_parse_error"] = str(exc)
    return stats


def _load_qc_status(paths: dict[str, Path]) -> dict[str, Any]:
    status: dict[str, Any] = {}
    mriqc_dir = paths["derivatives"] / "mriqc"
    status["mriqc"] = {
        "t1w_json": _count_find(mriqc_dir, "*_T1w.json") if mriqc_dir.exists() else 0,
        "bold_json": _count_find(mriqc_dir, "*_bold.json") if mriqc_dir.exists() else 0,
        "container_present": (paths["project"] / "containers" / "mriqc-24.0.2.sif").is_file(),
        "report_sources": [],
    }
    for rel in [
        "mriqc/README.md",
        "mriqc_publication_audit/MRIQC_PUBLICATION_AUDIT.md",
        "scientific_data_docs/extracted_metrics.md",
    ]:
        p = paths["reports"] / rel
        if p.is_file():
            status["mriqc"]["report_sources"].append(rel_display(p, paths["project"]))

    pizarro = paths["reports"] / "pizarro_qc_scientific_data" / "PIZARRO_QC_REPORT.md"
    status["pizarro"] = {
        "report_present": pizarro.is_file(),
        "report_source": rel_display(pizarro, paths["project"]) if pizarro.is_file() else NA,
        "excerpt": scrub_abs_paths(_read_report_snippet(pizarro, 1500) or NA, paths["project"]),
    }
    deface = paths["reports"] / "defacing_audit"
    status["defacing"] = {
        "audit_dir_present": deface.is_dir(),
        "derivatives_present": (paths["derivatives"] / "defacing").is_dir(),
    }
    bids_val = paths["reports"] / "bids_validation_scientific_data"
    status["bids_validation"] = {
        "reports_dir_present": bids_val.is_dir(),
        "after_events_st": (bids_val / "VALIDATION_AFTER_EVENTS_ST.md").is_file(),
        "longitudinal_coverage": (bids_val / "LONGITUDINAL_COVERAGE.md").is_file(),
    }
    status["dwi_qc_report_present"] = (paths["reports"] / "dwi_qc" / "DWI_QC_REPORT.md").is_file()
    status["physiology_qc_present"] = (
        paths["derivatives"] / "physiology_qc" / "PHYSIOLOGY_QC_REPORT.md"
    ).is_file()
    return status


def _available_derivatives(derivatives: Path) -> list[str]:
    if not derivatives.is_dir():
        return []
    return sorted(
        p.name
        for p in derivatives.iterdir()
        if p.is_dir() and not p.name.startswith(".")
    )


def _runs_observed(root: Path) -> list[str]:
    lines = run_find(root, ["-type", "f", "-name", "*run-*_bold.nii.gz"])
    runs: set[str] = set()
    for ln in lines:
        m = re.search(r"run-(\d+)", Path(ln).name)
        if m:
            runs.add(m.group(1))
    return sorted(runs, key=lambda x: int(x))


def phase2_dataset_state(paths: dict[str, Path], out_dir: Path) -> dict[str, Any]:
    log("PHASE 2 — Detect current dataset state")
    release = paths["release"]
    participants = release / "participants.tsv"
    dd = load_json(release / "dataset_description.json") or {}
    n_subjects_tsv = 0
    if participants.is_file():
        pdf = pd.read_csv(participants, sep="\t", dtype=str)
        n_subjects_tsv = len(pdf)
    subjects_dirs = sorted(
        p.name for p in release.iterdir() if p.is_dir() and p.name.startswith("sub-")
    )
    state: dict[str, Any] = {
        "generated_at_utc": utc_iso(),
        "release_dir": str(release),
        "bids_dir": str(paths["bids"]),
        "number_of_subjects": {
            "subject_directories": len(subjects_dirs),
            "participants_tsv_rows": n_subjects_tsv,
        },
        "number_of_sessions": _session_coverage(release),
        "cohorts": _cohort_counts(participants),
        "modalities": _modality_counts(release),
        "tasks": {
            "magnitude_bold_by_task": _task_bold_counts(release),
            "events_tsv_by_task": _events_by_task(release),
        },
        "runs": _runs_observed(release),
        "available_derivatives": _available_derivatives(paths["derivatives"]),
        "physiology_statistics": _load_physio_statistics(paths, release),
        "dwi_statistics": _load_dwi_statistics(paths, release),
        "QC_status": _load_qc_status(paths),
        "dataset_description": dd,
        "acquisition_examples": _extract_acquisition_examples(release),
        "sources": {
            "participants_tsv": rel_display(participants, paths["project"])
            if participants.is_file()
            else NA,
            "dataset_description_json": rel_display(
                release / "dataset_description.json", paths["project"]
            ),
            "longitudinal_report": rel_display(
                paths["reports"]
                / "bids_validation_scientific_data"
                / "LONGITUDINAL_COVERAGE.md",
                paths["project"],
            ),
            "extracted_metrics": rel_display(
                paths["reports"] / "scientific_data_docs" / "extracted_metrics.md",
                paths["project"],
            ),
            "movie_events_generation": rel_display(
                paths["reports"]
                / "movie_events_generation"
                / "MOVIE_EVENTS_GENERATION_REPORT.md",
                paths["project"],
            ),
            "physio_conversion_summary": rel_display(
                paths["reports"]
                / "physiology_audit"
                / "final_bids_physio_readiness"
                / "conversion_run"
                / "CONVERSION_SUMMARY.md",
                paths["project"],
            ),
            "dwi_qc_report": rel_display(
                paths["reports"] / "dwi_qc" / "DWI_QC_REPORT.md", paths["project"]
            ),
        },
        "project_root": str(paths["project"]),
        "principle": "Counts are from live release_dataset inventory and cited reports only. No estimates.",
    }
    write_json(out_dir / "CURRENT_DATASET_STATE.json", state)
    log(
        f"  Subjects dirs={state['number_of_subjects']['subject_directories']} "
        f"participants.tsv={n_subjects_tsv} "
        f"physio_tsv.gz={state['physiology_statistics']['physio_tsv_gz_in_release']}"
    )
    return state


# ---------------------------------------------------------------------------
# Phase 3 — Documentation consistency
# ---------------------------------------------------------------------------


def _find_numbers_near(text: str, keywords: list[str]) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for kw in keywords:
        for m in re.finditer(
            rf"({re.escape(kw)}[^\n]{{0,80}}?)(\d{{1,5}})", text, flags=re.IGNORECASE
        ):
            found.append((kw, m.group(2)))
    return found


def phase3_consistency(
    paths: dict[str, Path], state: dict[str, Any], out_dir: Path
) -> list[dict[str, Any]]:
    log("PHASE 3 — Documentation consistency audit")
    rows: list[dict[str, Any]] = []
    release = paths["release"]
    readme = safe_read_text(release / "README.md")
    movie_md = safe_read_text(release / "docs" / "Protocols" / "Movie.md")
    extracted = safe_read_text(
        paths["reports"] / "scientific_data_docs" / "extracted_metrics.md"
    )

    def add(
        severity: str,
        check: str,
        documented: Any,
        actual: Any,
        location: str,
        detail: str = "",
    ) -> None:
        rows.append(
            {
                "severity": severity,
                "check": check,
                "documented_value": documented,
                "actual_value": actual,
                "location": location,
                "detail": detail,
            }
        )

    n_sub = state["number_of_subjects"]["subject_directories"]
    n_tsv = state["number_of_subjects"]["participants_tsv_rows"]
    if n_sub != n_tsv:
        add(
            "HIGH",
            "participant_numbers_mismatch_internal",
            n_tsv,
            n_sub,
            "participants.tsv vs sub-* dirs",
            "participants.tsv row count differs from subject directories",
        )

    # README subject count
    m = re.search(r"Subjects[^\n]*?\|\s*(\d+)\s*\|", readme)
    if m and int(m.group(1)) != n_sub:
        add(
            "HIGH",
            "participant_numbers_mismatch",
            m.group(1),
            n_sub,
            "release_dataset/README.md",
            "README subject count differs from live subject directories",
        )

    cov = state["number_of_sessions"]
    for label, key, pattern in [
        ("both sessions", "both_sessions", r"Both sessions present[^\n]*?\|\s*(\d+)"),
        ("ses-01 only", "ses-01_only", r"`ses-01` only[^\n]*?\|\s*(\d+)"),
        ("ses-02 only", "ses-02_only", r"`ses-02` only[^\n]*?\|\s*(\d+)"),
    ]:
        m = re.search(pattern, readme)
        if m and int(m.group(1)) != cov[key]:
            add(
                "HIGH",
                f"session_coverage_mismatch_{key}",
                m.group(1),
                cov[key],
                "release_dataset/README.md",
                f"README {label} count outdated relative to live tree",
            )

    # Cohort names in README vs participants
    cohorts = set(state["cohorts"].keys())
    for obsolete in ("TON", "ON", "HC", "healthy control"):
        if obsolete.lower() in readme.lower() and obsolete not in cohorts:
            # only flag if participants use different labels
            pass
    expected_cohorts = {"Control", "DataON", "DataTON", "Glaucoma"}
    missing_cohort_docs = expected_cohorts - set(
        c for c in expected_cohorts if c in readme or c in extracted
    )
    # Soft check: ensure README mentions each live cohort
    for c in sorted(cohorts):
        if c not in readme:
            add(
                "MEDIUM",
                "cohort_name_missing_in_readme",
                "not mentioned",
                c,
                "release_dataset/README.md",
                f"Cohort '{c}' present in participants.tsv but not named in README",
            )

    # Modality counts in README table
    mods = state["modalities"]
    modality_patterns = {
        "bold": r"Functional BOLD[^\n]*?\|\s*(\d+)",
        "sbref": r"sbref[^\n]*?\|\s*(\d+)",
        "epi": r"field maps[^\n]*?\|\s*(\d+)",
        "dwi": r"Diffusion[^\n]*?\|\s*(\d+)",
        "T1w": r"T1-weighted[^\n]*?\|\s*(\d+)",
        "TB1TFL": r"B1 mapping[^\n]*?\|\s*(\d+)",
        "FLAIR": r"FLAIR[^\n]*?\|\s*(\d+)",
    }
    for suffix, pat in modality_patterns.items():
        m = re.search(pat, readme, flags=re.IGNORECASE)
        actual = mods.get(suffix)
        if m and actual is not None and int(m.group(1)) != actual:
            add(
                "HIGH",
                f"modality_count_mismatch_{suffix}",
                m.group(1),
                actual,
                "release_dataset/README.md",
                "README modality inventory outdated",
            )

    # Task events
    events = state["tasks"]["events_tsv_by_task"]
    m = re.search(r"Event timing files are available for \*\*(\d+)\*\*", readme)
    if m:
        documented = int(m.group(1))
        actual_fmri = events.get("fmri", 0)
        if documented != actual_fmri:
            add(
                "HIGH",
                "task_fmri_events_count_mismatch",
                documented,
                actual_fmri,
                "release_dataset/README.md",
                "README task-fmri events count differs from live *_events.tsv",
            )

    # Movie events documentation
    movie_events = events.get("movie", 0)
    movie_claims_absent = bool(
        re.search(r"No.*\*_events\.tsv.*for this task", movie_md, flags=re.IGNORECASE)
        or re.search(
            r"task-movie[^\n]{0,80}(?:intentionally have no|no)\s+`?events\.tsv",
            readme,
            flags=re.IGNORECASE,
        )
    )
    movie_superseded = "<!-- documentation_audit_update_movie_events -->" in movie_md
    if movie_events > 0 and movie_claims_absent and not movie_superseded:
        add(
            "HIGH",
            "movie_events_docs_obsolete",
            "documents absence of movie events",
            f"{movie_events} task-movie events.tsv present",
            "docs/Protocols/Movie.md and/or README.md",
            "Movie events were generated; protocol docs still claim absence",
        )
    elif movie_events > 0 and movie_claims_absent and movie_superseded:
        add(
            "LOW",
            "movie_events_historical_wording_retained",
            "historical absence claim retained with update note",
            f"{movie_events} task-movie events.tsv present",
            "docs/Protocols/Movie.md",
            "Update note present; consider rewriting historical sections in a future editorial pass",
        )

    # Physiology outdated claims
    physio_n = state["physiology_statistics"]["physio_tsv_gz_in_release"]
    if physio_n > 0 and re.search(r"BIDS physiology sidecars[^\n]*\|\s*0\s*\|", extracted):
        add(
            "HIGH",
            "outdated_qc_numbers_physio_zero",
            "0",
            physio_n,
            "reports/scientific_data_docs/extracted_metrics.md",
            "Extracted metrics still report 0 physio sidecars",
        )
    if physio_n > 0 and "BIDS physiology files (none present)" in extracted:
        add(
            "MEDIUM",
            "outdated_missing_physio_claim",
            "none present",
            physio_n,
            "reports/scientific_data_docs/extracted_metrics.md",
            "Missing-items list still claims no BIDS physiology",
        )

    # DWI counts
    dwi_n = state["dwi_statistics"]["dwi_nifti_in_release"]
    if re.search(r"\b361\b", readme) and dwi_n != 361:
        add(
            "MEDIUM",
            "outdated_dwi_count_in_readme",
            "361",
            dwi_n,
            "release_dataset/README.md",
            "README still references 361 DWI scans",
        )

    # dataset_description completeness
    dd = state.get("dataset_description") or {}
    for field in [
        "Name",
        "BIDSVersion",
        "DatasetType",
        "Authors",
        "Acknowledgements",
        "HowToAcknowledge",
        "Funding",
        "ReferencesAndLinks",
        "License",
        "DatasetDOI",
    ]:
        if field not in dd or dd.get(field) in (None, "", [], {}):
            sev = "HIGH" if field in {"Name", "BIDSVersion", "Authors", "License"} else "MEDIUM"
            add(
                sev,
                f"dataset_description_missing_{field}",
                "missing",
                NA,
                "release_dataset/dataset_description.json",
                f"Required/recommended field '{field}' absent or empty",
            )
    authors = dd.get("Authors") or []
    if authors == ["Neuro BIDS Pipeline"]:
        add(
            "HIGH",
            "placeholder_authors",
            "Neuro BIDS Pipeline",
            "real author list required for publication",
            "release_dataset/dataset_description.json",
            "Authors still placeholder",
        )

    # Missing open-science docs (also reported in phase 4)
    docs_dir = release / "docs"
    for fname in [
        "acquisition_protocol.md",
        "quality_control.md",
        "data_dictionary.md",
        "task_descriptions.md",
        "physiology_methods.md",
        "limitations.md",
        "software_versions.md",
        "provenance.md",
    ]:
        if not (docs_dir / fname).is_file():
            add(
                "HIGH",
                f"missing_doc_{fname}",
                "absent",
                "required for Open Science release docs",
                f"release_dataset/docs/{fname}",
                "Required documentation file missing",
            )

    # LICENSE / CHANGES naming
    if not (release / "LICENSE").is_file():
        add("HIGH", "missing_license", "absent", "required", "release_dataset/LICENSE", "")
    if not (release / "CHANGES.md").is_file() and (release / "CHANGES").is_file():
        add(
            "LOW",
            "changes_filename",
            "CHANGES",
            "CHANGES.md preferred for OpenNeuro-style",
            "release_dataset/CHANGES",
            "CHANGES exists without .md suffix",
        )

    # Old task naming
    if "task-grating" in readme and "task-fmri" in state["tasks"]["magnitude_bold_by_task"]:
        # informational — grating may be glossary name
        pass
    bold_tasks = set(state["tasks"]["magnitude_bold_by_task"])
    for old in ("task-Task", "task-movie1", "task-resting"):
        if old in readme:
            add(
                "MEDIUM",
                "old_task_name",
                old,
                sorted(bold_tasks),
                "release_dataset/README.md",
                "Obsolete task label mentioned",
            )

    write_tsv(
        out_dir / "DOCUMENTATION_INCONSISTENCIES.tsv",
        rows,
        ["severity", "check", "documented_value", "actual_value", "location", "detail"],
    )
    log(f"  Inconsistencies: {len(rows)} "
        f"(HIGH={sum(1 for r in rows if r['severity']=='HIGH')})")
    return rows


# ---------------------------------------------------------------------------
# Phase 4 — Missing documentation
# ---------------------------------------------------------------------------


def phase4_missing_docs(paths: dict[str, Path], out_dir: Path) -> list[dict[str, Any]]:
    log("PHASE 4 — Required Open Science documentation audit")
    release = paths["release"]
    docs = release / "docs"
    rows: list[dict[str, Any]] = []

    def present(path: Path) -> bool:
        return path.is_file()

    checks = [
        ("README.md", release / "README.md", "critical"),
        ("dataset_description.json", release / "dataset_description.json", "critical"),
        ("CHANGES.md", release / "CHANGES.md", "recommended"),
        ("CHANGES (alternate)", release / "CHANGES", "critical_if_no_CHANGES.md"),
        ("LICENSE", release / "LICENSE", "critical"),
        ("participants.tsv", release / "participants.tsv", "critical"),
        ("participants.json", release / "participants.json", "critical"),
        ("acquisition_protocol.md", docs / "acquisition_protocol.md", "critical"),
        ("quality_control.md", docs / "quality_control.md", "critical"),
        ("data_dictionary.md", docs / "data_dictionary.md", "critical"),
        ("task_descriptions.md", docs / "task_descriptions.md", "critical"),
        ("physiology_methods.md", docs / "physiology_methods.md", "critical"),
        ("limitations.md", docs / "limitations.md", "critical"),
        ("software_versions.md", docs / "software_versions.md", "critical"),
        ("provenance.md", docs / "provenance.md", "critical"),
    ]
    changes_md = present(release / "CHANGES.md")
    changes_alt = present(release / "CHANGES")
    for name, path, criticality in checks:
        exists = present(path)
        status = "PRESENT" if exists else "MISSING"
        note = ""
        if name == "CHANGES (alternate)":
            if changes_md:
                status = "N/A"
                note = "CHANGES.md present"
            elif changes_alt:
                status = "PRESENT"
                note = "Acceptable alternate filename; prefer CHANGES.md"
            else:
                status = "MISSING"
                criticality = "critical"
        if name == "CHANGES.md" and not exists and changes_alt:
            status = "MISSING_PREFERRED_NAME"
            note = "CHANGES exists; CHANGES.md absent"
            criticality = "recommended"
        rows.append(
            {
                "document": name,
                "expected_path": str(path),
                "status": status,
                "criticality": criticality,
                "note": note,
            }
        )

    write_tsv(
        out_dir / "MISSING_DOCUMENTATION.tsv",
        rows,
        ["document", "expected_path", "status", "criticality", "note"],
    )
    missing_critical = [
        r
        for r in rows
        if r["status"] in {"MISSING", "MISSING_PREFERRED_NAME"}
        and r["criticality"] in {"critical", "critical_if_no_CHANGES.md"}
    ]
    # Recompute critical missing with CHANGES alternate logic
    missing_crit_names = []
    for r in rows:
        if r["document"] == "CHANGES.md":
            continue
        if r["document"] == "CHANGES (alternate)":
            if r["status"] == "MISSING":
                missing_crit_names.append("CHANGES/CHANGES.md")
            continue
        if r["status"] == "MISSING" and r["criticality"] == "critical":
            missing_crit_names.append(r["document"])
    log(f"  Missing critical docs: {missing_crit_names}")
    return rows


# ---------------------------------------------------------------------------
# Phase 5 — Scientific Data readiness
# ---------------------------------------------------------------------------


def _score_dimension(ok: bool, partial: bool = False) -> tuple[str, int]:
    if ok:
        return "READY", 2
    if partial:
        return "PARTIAL", 1
    return "NOT_READY", 0


def phase5_readiness(
    paths: dict[str, Path],
    state: dict[str, Any],
    inconsistencies: list[dict[str, Any]],
    missing_docs: list[dict[str, Any]],
    out_dir: Path,
) -> dict[str, Any]:
    log("PHASE 5 — Scientific Data readiness assessment")
    release = paths["release"]
    high = sum(1 for r in inconsistencies if r["severity"] == "HIGH")
    missing_critical = []
    for r in missing_docs:
        if r["document"] == "CHANGES.md":
            continue
        if r["document"] == "CHANGES (alternate)" and r["status"] == "MISSING":
            missing_critical.append("CHANGES")
        elif r["status"] == "MISSING" and r["criticality"] == "critical":
            missing_critical.append(r["document"])

    dims: list[dict[str, Any]] = []

    def dim(name: str, status: str, score: int, evidence: str, gaps: str) -> None:
        dims.append(
            {
                "dimension": name,
                "status": status,
                "score": score,
                "evidence": evidence,
                "gaps": gaps,
            }
        )

    dd = state.get("dataset_description") or {}
    authors_ok = bool(dd.get("Authors")) and dd.get("Authors") != ["Neuro BIDS Pipeline"]
    st, sc = _score_dimension(
        bool(dd.get("Name") and dd.get("BIDSVersion") and authors_ok and dd.get("License")),
        partial=bool(dd.get("Name") and dd.get("BIDSVersion")),
    )
    dim(
        "Dataset description",
        st,
        sc,
        f"Name={dd.get('Name')}; BIDSVersion={dd.get('BIDSVersion')}; Authors={dd.get('Authors')}",
        "Complete Authors/Funding/DOI/HowToAcknowledge if still placeholders",
    )

    acq_doc = (release / "docs" / "acquisition_protocol.md").is_file()
    acq_examples = state.get("acquisition_examples") or {}
    st, sc = _score_dimension(
        acq_doc and isinstance(acq_examples.get("T1w_MPRAGE"), dict),
        partial=isinstance(acq_examples.get("T1w_MPRAGE"), dict),
    )
    dim(
        "Acquisition documentation",
        st,
        sc,
        "Sidecar-derived examples available" + ("; docs/acquisition_protocol.md present" if acq_doc else ""),
        "Create docs/acquisition_protocol.md" if not acq_doc else "",
    )

    st, sc = _score_dimension(
        (paths["reports"] / "bids_validation_scientific_data" / "VALIDATION_AFTER_EVENTS_ST.md").is_file(),
        partial=True,
    )
    dim(
        "BIDS compliance",
        st,
        sc,
        "Prior validator reports under reports/bids_validation_scientific_data/",
        "Re-run bids-validator on current release_dataset for FINAL validation",
    )

    mriqc = state["QC_status"]["mriqc"]
    dwi_ok = state["QC_status"]["dwi_qc_report_present"]
    phys_ok = state["QC_status"]["physiology_qc_present"]
    st, sc = _score_dimension(
        mriqc["t1w_json"] > 0 and dwi_ok and phys_ok,
        partial=mriqc["t1w_json"] > 0 or dwi_ok or phys_ok,
    )
    dim(
        "Quality control",
        st,
        sc,
        f"MRIQC T1w JSON={mriqc['t1w_json']}, bold JSON={mriqc['bold_json']}; "
        f"DWI report={dwi_ok}; physio QC={phys_ok}",
        "Ensure QC narrative docs cite live counts; MRIQC may still be partial vs full cohort",
    )

    physio_n = state["physiology_statistics"]["physio_tsv_gz_in_release"]
    phys_methods = (release / "docs" / "physiology_methods.md").is_file()
    st, sc = _score_dimension(physio_n > 0 and phys_methods, partial=physio_n > 0)
    dim(
        "Physiology documentation",
        st,
        sc,
        f"Live physio.tsv.gz={physio_n}; methods doc={'yes' if phys_methods else 'no'}",
        "Write physiology_methods.md from conversion/exclusion reports" if not phys_methods else "",
    )

    dwi_n = state["dwi_statistics"]["dwi_nifti_in_release"]
    st, sc = _score_dimension(dwi_n > 0 and dwi_ok, partial=dwi_n > 0)
    dim(
        "Diffusion documentation",
        st,
        sc,
        f"DWI NIfTI={dwi_n}; DWI_QC_REPORT present={dwi_ok}",
        "Summarize DWI QC in quality_control.md / acquisition_protocol.md",
    )

    events = state["tasks"]["events_tsv_by_task"]
    tasks = state["tasks"]["magnitude_bold_by_task"]
    st, sc = _score_dimension(
        bool(tasks) and (events.get("fmri", 0) > 0 or events.get("movie", 0) > 0),
        partial=bool(tasks),
    )
    dim(
        "Functional validation",
        st,
        sc,
        f"Tasks={tasks}; events={events}",
        "Align task_descriptions.md with movie events timing policy",
    )

    code_present = (release / "code").is_dir() and any((release / "code").iterdir())
    st, sc = _score_dimension(code_present, partial=False)
    dim(
        "Code availability",
        st,
        sc,
        "release_dataset/code/ present with task protocol materials",
        "",
    )

    prov = (release / "docs" / "provenance.md").is_file()
    st, sc = _score_dimension(prov, partial=(release / "dataset_description.json").is_file())
    dim(
        "Provenance",
        st,
        sc,
        "dataset_description GeneratedBy + optional provenance.md",
        "Add docs/provenance.md" if not prov else "",
    )

    lim = (release / "docs" / "limitations.md").is_file()
    st, sc = _score_dimension(lim or ("Known limitations" in safe_read_text(release / "README.md")), partial=True)
    dim(
        "Limitations",
        st,
        sc,
        "README known limitations section and/or docs/limitations.md",
        "Create dedicated limitations.md" if not lim else "",
    )

    soft = (release / "docs" / "software_versions.md").is_file()
    st, sc = _score_dimension(soft, partial=True)
    dim(
        "Reproducibility",
        st,
        sc,
        "Software versions in README/reports; dedicated software_versions.md "
        + ("present" if soft else "missing"),
        "Create software_versions.md from verified sources only",
    )

    total = sum(d["score"] for d in dims)
    max_total = 2 * len(dims)
    pct = round(100.0 * total / max_total, 1) if max_total else 0.0

    lines = [
        "# Scientific Data readiness report",
        "",
        f"Generated: `{utc_iso()}`",
        "",
        "Assessment is based only on existing release metadata, QC outputs, and reports.",
        "No scientific claims were invented.",
        "",
        f"**Documentation readiness score:** {total}/{max_total} ({pct}%)",
        "",
        f"- HIGH inconsistencies: **{high}**",
        f"- Missing critical documents: **{len(missing_critical)}** ({', '.join(missing_critical) or 'none'})",
        "",
        "## Dimensions",
        "",
        "| Dimension | Status | Score | Evidence | Gaps |",
        "| --- | --- | ---: | --- | --- |",
    ]
    for d in dims:
        evid = d["evidence"].replace("|", "\\|").replace("\n", " ")
        gaps = (d["gaps"] or "").replace("|", "\\|").replace("\n", " ")
        lines.append(
            f"| {d['dimension']} | {d['status']} | {d['score']}/2 | {evid} | {gaps} |"
        )
    lines.extend(
        [
            "",
            "## Live dataset snapshot",
            "",
            f"- Subjects (directories): **{state['number_of_subjects']['subject_directories']}**",
            f"- participants.tsv rows: **{state['number_of_subjects']['participants_tsv_rows']}**",
            f"- Cohorts: `{json.dumps(state['cohorts'])}`",
            f"- Session coverage: `{json.dumps(state['number_of_sessions'])}`",
            f"- Modalities: `{json.dumps(state['modalities'])}`",
            f"- Magnitude BOLD by task: `{json.dumps(state['tasks']['magnitude_bold_by_task'])}`",
            f"- Events by task: `{json.dumps(state['tasks']['events_tsv_by_task'])}`",
            f"- Physio `*_physio.tsv.gz`: **{physio_n}**",
            f"- DWI NIfTI: **{dwi_n}**",
            f"- Derivatives available: {', '.join(state['available_derivatives']) or NA}",
            "",
            "## Publication blockers (from this audit)",
            "",
        ]
    )
    if missing_critical:
        for m in missing_critical:
            lines.append(f"- Missing critical documentation: `{m}`")
    else:
        lines.append("- No missing critical documentation filenames (content quality still requires review).")
    if high:
        lines.append(f"- Resolve **{high}** HIGH inconsistencies in `DOCUMENTATION_INCONSISTENCIES.tsv`.")
    if not authors_ok:
        lines.append("- Replace placeholder Authors in `dataset_description.json`.")
    if not dd.get("DatasetDOI"):
        lines.append("- DatasetDOI not set (use placeholder until OpenNeuro/Zenodo DOI assigned).")
    lines.extend(
        [
            "",
            "## Sources consulted",
            "",
        ]
    )
    for k, v in (state.get("sources") or {}).items():
        lines.append(f"- `{k}`: `{v}`")
    lines.append("")
    write_md(out_dir / "SCIENTIFIC_DATA_READINESS_REPORT.md", "\n".join(lines))
    summary = {
        "score_total": total,
        "score_max": max_total,
        "score_percent": pct,
        "dimensions": dims,
        "missing_critical": missing_critical,
        "high_inconsistencies": high,
    }
    write_json(out_dir / "SCIENTIFIC_DATA_READINESS_SUMMARY.json", summary)
    log(f"  Readiness score: {total}/{max_total} ({pct}%)")
    return summary


# ---------------------------------------------------------------------------
# Phase 6 — Update documentation
# ---------------------------------------------------------------------------


def _backup_release_docs(release: Path, project: Path) -> Path:
    stamp = utc_stamp()
    backup = project / f"release_dataset_backup_before_documentation_update_{stamp}"
    backup.mkdir(parents=True, exist_ok=False)
    # Copy documentation-related paths only (do not duplicate full imaging tree).
    targets = [
        "README.md",
        "dataset_description.json",
        "participants.tsv",
        "participants.json",
        "CHANGES",
        "CHANGES.md",
        "LICENSE",
        ".bidsignore",
        "docs",
        "code/README.md",
    ]
    manifest = []
    for rel in targets:
        src = release / rel
        if not src.exists():
            continue
        dst = backup / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            shutil.copytree(src, dst, dirs_exist_ok=True)
        else:
            shutil.copy2(src, dst)
        manifest.append(rel)
    write_json(
        backup / "BACKUP_MANIFEST.json",
        {
            "created_at_utc": utc_iso(),
            "source_release": str(release),
            "copied": manifest,
            "note": "Documentation/metadata backup only; imaging files not duplicated.",
        },
    )
    log(f"  Backup created: {backup}")
    return backup


def _fmt_table(headers: list[str], rows: list[list[Any]]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" if i else "---" for i, _ in enumerate(headers)).replace("---", "---", 1) + " |",
    ]
    # Fix alignment row properly
    lines[1] = "| " + " | ".join(["---"] * len(headers)) + " |"
    for row in rows:
        lines.append("| " + " | ".join(str(c) for c in row) + " |")
    return "\n".join(lines)


def _na(val: Any) -> str:
    if val is None or val == "" or val == {}:
        return NA
    return str(val)


def build_readme(state: dict[str, Any], paths: dict[str, Path]) -> str:
    n_sub = state["number_of_subjects"]["subject_directories"]
    n_tsv = state["number_of_subjects"]["participants_tsv_rows"]
    cov = state["number_of_sessions"]
    cohorts = state["cohorts"]
    mods = state["modalities"]
    tasks = state["tasks"]["magnitude_bold_by_task"]
    events = state["tasks"]["events_tsv_by_task"]
    phys = state["physiology_statistics"]
    dwi = state["dwi_statistics"]
    acq = state.get("acquisition_examples") or {}
    dd = state.get("dataset_description") or {}

    cohort_rows = [[k, v] for k, v in sorted(cohorts.items())]
    mod_rows = [[k, v] for k, v in mods.items()]
    task_rows = [[f"task-{k}", v, events.get(k, 0)] for k, v in tasks.items()]

    t1 = acq.get("T1w_MPRAGE") if isinstance(acq.get("T1w_MPRAGE"), dict) else {}
    fl = acq.get("FLAIR") if isinstance(acq.get("FLAIR"), dict) else {}
    rest = acq.get("rest_bold") if isinstance(acq.get("rest_bold"), dict) else {}
    dwi_ex = acq.get("dwi") if isinstance(acq.get("dwi"), dict) else {}
    fmap = acq.get("fmap_PA") if isinstance(acq.get("fmap_PA"), dict) else {}

    license_txt = safe_read_text(paths["release"] / "LICENSE", 500).splitlines()
    license_label = license_txt[0].lstrip("# ").strip() if license_txt else NA

    return f"""# Dataset overview

This repository contains a Brain Imaging Data Structure (BIDS) magnetic resonance imaging (MRI) dataset prepared for secondary analysis and for a *Scientific Data* Data Descriptor. The release focuses on organized raw imaging data, accompanying metadata, physiological recordings (where conversion gates were met), task events (where recoverable), and documented quality-control and privacy procedures. It does not present new biological findings.

Counts below were generated by `code/audit_and_update_release_documentation.py` from the live `release_dataset/` tree and cited reports on `{state['generated_at_utc']}`. Values not present in metadata are marked explicitly.

# Scientific motivation

The dataset supports multimodal neuroimaging methods development, quality-control benchmarking, physiology–BOLD analyses where recordings are available, and reproducible workflows that start from BIDS inputs. Longitudinal sessions (`ses-01`, `ses-02`) enable within-subject reuse when both visits exist.

# Cohorts and participants

{_fmt_table(['Item', 'Count'], [
    ['Subjects in release tree (`sub-*`)', n_sub],
    ['Rows in `participants.tsv`', n_tsv],
    ['Both sessions present', cov['both_sessions']],
    ['`ses-01` only', cov['ses-01_only']],
    ['`ses-02` only', cov['ses-02_only']],
    ['Subject×session directories', cov['subject_session_dirs']],
])}

Cohort composition (`participants.tsv`):

{_fmt_table(['Cohort', 'N'], cohort_rows)}

Columns in `participants.tsv`: `participant_id`, `cohort`, `sex` (see `participants.json`).

Missing sessions reflect incomplete participant follow-up, not omitted placeholders. Validator warnings such as `MISSING_SESSION` / `INCONSISTENT_SUBJECTS` are expected.

# MRI acquisition overview

Acquisition parameters are taken from converted BIDS JSON sidecars (representative example: `sub-001`, sources listed in each bullet).

- **Manufacturer / model:** {_na(t1.get('Manufacturer'))} {_na(t1.get('ManufacturersModelName'))}
- **Field strength:** {_na(t1.get('MagneticFieldStrength'))} T
- **Conversion software (sidecar):** {_na(t1.get('ConversionSoftware'))} {_na(t1.get('ConversionSoftwareVersion'))}

Representative parameters:

- **T1-weighted MPRAGE** (`{_na(t1.get('ProtocolName'))}`): TR {_na(t1.get('RepetitionTime'))} s, TE {_na(t1.get('EchoTime'))} s, flip angle {_na(t1.get('FlipAngle'))}°; source `{_na(t1.get('source_file'))}`
- **3D FLAIR** (`{_na(fl.get('ProtocolName'))}`): TR {_na(fl.get('RepetitionTime'))} s, TE {_na(fl.get('EchoTime'))} s, flip angle {_na(fl.get('FlipAngle'))}°; source `{_na(fl.get('source_file'))}`
- **Resting-state BOLD** (`{_na(rest.get('ProtocolName'))}`): TR {_na(rest.get('RepetitionTime'))} s, TE {_na(rest.get('EchoTime'))} s, flip angle {_na(rest.get('FlipAngle'))}°, multiband {_na(rest.get('MultibandAccelerationFactor'))}; source `{_na(rest.get('source_file'))}`
- **Diffusion example** (`{_na(dwi_ex.get('ProtocolName'))}`): TR {_na(dwi_ex.get('RepetitionTime'))} s, TE {_na(dwi_ex.get('EchoTime'))} s, multiband {_na(dwi_ex.get('MultibandAccelerationFactor'))}; source `{_na(dwi_ex.get('source_file'))}`
- **Spin-echo field map example** (`{_na(fmap.get('ProtocolName'))}`): TR {_na(fmap.get('RepetitionTime'))} s, TE {_na(fmap.get('EchoTime'))} s, PE `{_na(fmap.get('PhaseEncodingDirection'))}`; source `{_na(fmap.get('source_file'))}`

Full narrative: `docs/acquisition_protocol.md`.

# Available modalities

Live NIfTI suffix counts in `release_dataset/` (excluding derivatives):

{_fmt_table(['Suffix / type', 'NIfTI count'], mod_rows)}

# Functional MRI tasks

Magnitude BOLD runs (excluding `part-phase`) and available `*_events.tsv` counts:

{_fmt_table(['Task', 'Magnitude BOLD runs', 'events.tsv'], task_rows)}

Task glossary and limitations: `docs/task_descriptions.md`. Protocol materials: `code/task-*/` and `docs/Protocols/`.

- **`task-fmri`:** grating / visual stimulus paradigm; events present when unique protocol↔acquisition mapping was established.
- **`task-movie`:** naturalistic movie clips; events generated under a documented timing policy when applicable (see `docs/task_descriptions.md` and `reports/movie_events_generation/`).
- **`task-rest`:** continuous fixation / rest; no discrete trial events by design.
- **`task-control`:** control runs; trial timing not recovered for events distribution in current metadata.

# Physiological recordings

Siemens PhysioLog series that passed conversion gates are distributed as BIDS physiology sidecars (`*_recording-{{pulse,respiratory,trigger,ecg}}_physio.tsv.gz` + JSON).

| Item | Value |
| --- | ---: |
| `*_physio.tsv.gz` in release | {phys['physio_tsv_gz_in_release']} |
| `*_physio.json` in release | {phys['physio_json_in_release']} |

By recording type (live inventory): `{json.dumps(phys.get('by_recording', {}))}`

Conversion / exclusion evidence: `{phys.get('conversion_summary_source', NA)}` and `{phys.get('exclusion_readme_source', NA)}`. Methods: `docs/physiology_methods.md`.

# Diffusion MRI

| Item | Value |
| --- | --- |
| `*_dwi.nii.gz` in release | {dwi.get('dwi_nifti_in_release')} |
| DWI inventory rows (report) | {_na(dwi.get('dwi_inventory_rows'))} |
| QC report | `{dwi.get('dwi_qc_report_source', NA)}` |

See `docs/acquisition_protocol.md` and `docs/quality_control.md`. No gradient corrections were applied to the distributed dataset when stated in the DWI QC report.

# Quality control procedures

QC components documented from existing reports/derivatives (see `docs/quality_control.md`):

| Component | Live / report status |
| --- | --- |
| MRIQC derivatives | T1w JSON={state['QC_status']['mriqc']['t1w_json']}; bold JSON={state['QC_status']['mriqc']['bold_json']} |
| DWI QC report | {'present' if state['QC_status']['dwi_qc_report_present'] else 'absent'} |
| Physiology QC report | {'present' if state['QC_status']['physiology_qc_present'] else 'absent'} |
| Pizarro T1w screening | {_na(state['QC_status']['pizarro'].get('report_source'))} |
| Defacing derivatives | {'present' if state['QC_status']['defacing']['derivatives_present'] else 'absent'} |

Automated QC outputs describe and prioritize inspection; they are not automatic exclusion criteria unless a specific report states otherwise.

# Data organization

BIDSVersion (dataset_description): **{_na(dd.get('BIDSVersion'))}**. DatasetType: **{_na(dd.get('DatasetType'))}**.

```text
release_dataset/
├── dataset_description.json
├── participants.tsv
├── participants.json
├── README.md
├── CHANGES / CHANGES.md
├── LICENSE
├── docs/                 # acquisition, tasks, physio, QC, provenance, limitations
├── code/                 # paradigm code and dictionaries
└── sub-*/ses-*/{{anat,func,dwi,fmap}}/
```

Defaced anatomical derivatives used for public sharing are generated under `derivatives/defacing/` in the processing environment. Source DICOM under `raw_original/` must not be redistributed with the public package.

# Code availability

Release-facing paradigm code and dictionaries live under `release_dataset/code/`. Pipeline, QC, conversion, and audit scripts live under the project `code/` tree (examples: `convert_physiolog_to_bids.py`, `run_dwi_qc.py`, `clean_bids_metadata.py`, `audit_and_update_release_documentation.py`). Software versions: `docs/software_versions.md`.

# Known limitations

See `docs/limitations.md` for the curated list. Headline constraints:

1. Longitudinal coverage is incomplete (see session table above).
2. Not every functional run has `events.tsv` (mapping/recovery gates).
3. Movie timing may be inferred from acquisition/stimulus duration policy when Psychtoolbox frame-level logs are unavailable.
4. Physiology exclusions remain for EXT-only / missing StartTime / ambiguous mapping / missing sampling metadata (see physiology methods).
5. Movie stimulus video files are not redistributed (copyright); protocol/timing metadata are included.
6. `DatasetDOI`, full author list, and funding fields may still require manual completion in `dataset_description.json`.

# Data access and reuse

- **License:** {license_label}
- **How to acknowledge:** see `dataset_description.json` → `HowToAcknowledge` (complete before publication if still placeholder)
- **Dataset DOI:** {_na(dd.get('DatasetDOI'))}
- **Ethics / consent:** Confirm with study investigators that sharing conditions match consent and institutional approvals before redistribution.
"""


def build_dataset_description(existing: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    out = dict(existing) if existing else {}
    out.setdefault("Name", "Neuro BIDS Pipeline Dataset")
    out.setdefault("BIDSVersion", "1.9.0")
    out.setdefault("DatasetType", "raw")
    out.setdefault("Authors", ["Neuro BIDS Pipeline"])
    # Preserve existing GeneratedBy
    if "GeneratedBy" not in out:
        out["GeneratedBy"] = [
            {
                "Name": "neuro_pipeline",
                "Version": "2.1.0",
                "Description": "DICOM to BIDS conversion",
            }
        ]
    # Ensure recommended fields exist; do not invent content.
    out.setdefault(
        "Acknowledgements",
        NA,
    )
    out.setdefault(
        "HowToAcknowledge",
        "Please cite the forthcoming Scientific Data descriptor and the dataset DOI once assigned. "
        f"({NA} for final citation text.)",
    )
    out.setdefault("Funding", [NA])
    out.setdefault("ReferencesAndLinks", [NA])
    out.setdefault("DatasetDOI", NA)
    # License from LICENSE file if present
    lic_path = Path(state.get("release_dir", "")) / "LICENSE"
    if lic_path.is_file():
        head = safe_read_text(lic_path, 200)
        if "CC0" in head:
            out["License"] = "CC0-1.0"
        else:
            out.setdefault("License", NA)
    else:
        out.setdefault("License", NA)
    # Keep Authors as-is if real; leave placeholder but visible for manual review
    return out


def build_acquisition_protocol(state: dict[str, Any]) -> str:
    acq = state.get("acquisition_examples") or {}
    dwi = state.get("dwi_statistics") or {}
    mods = state.get("modalities") or {}

    def block(title: str, key: str) -> str:
        val = acq.get(key)
        if not isinstance(val, dict):
            return f"### {title}\n\n{NA}\n"
        lines = [f"### {title}", "", f"Source sidecar: `{val.get('source_file', NA)}`", ""]
        for k, v in val.items():
            if k == "source_file":
                continue
            lines.append(f"- **{k}:** {v}")
        lines.append("")
        return "\n".join(lines)

    return f"""# Acquisition protocol

Generated: `{utc_iso()}`

Parameters below are copied from representative BIDS JSON sidecars in the release tree.
No values were estimated. Missing fields are omitted or marked unavailable.

Live modality NIfTI counts: `{json.dumps(mods)}`

## Structural MRI

{block("T1 MPRAGE", "T1w_MPRAGE")}
{block("FLAIR", "FLAIR")}

## Functional MRI

{block("Resting-state BOLD", "rest_bold")}

### Task fMRI (`task-fmri`)

See `docs/task_descriptions.md` and `code/task-grating/` (grating paradigm materials).
Acquisition parameters vary by run; consult per-run `*_bold.json` sidecars.

### Movie fMRI (`task-movie`)

See `docs/task_descriptions.md` and `code/task-movie/`.
Acquisition parameters: consult per-run `*_bold.json` sidecars.

## Diffusion MRI

{block("DWI (example series)", "dwi")}

- Live `*_dwi.nii.gz` count: **{dwi.get('dwi_nifti_in_release', NA)}**
- DWI QC report: `{dwi.get('dwi_qc_report_source', NA)}`
- b-value / direction summaries: see `reports/dwi_qc/` (`dwi_bvalue_summary.tsv`, `DWI_QC_REPORT.md`).
- RESOLVE / protocol naming: use `ProtocolName` / `SeriesDescription` in sidecars; do not assume a single scheme for all scans.
- Report excerpt (truncated):

```
{dwi.get('dwi_qc_report_excerpt', NA)}
```

## Fieldmaps

{block("SpinEcho field map (PA example)", "fmap_PA")}

Opposing phase-encode SpinEcho EPI field maps (AP/PA) are present as `*_epi.nii.gz` under `fmap/`. Exact PE directions are recorded per sidecar (`PhaseEncodingDirection` / `dir-AP`/`dir-PA` entities).
"""


def build_task_descriptions(state: dict[str, Any], paths: dict[str, Path]) -> str:
    project = paths["project"]
    tasks = state["tasks"]["magnitude_bold_by_task"]
    events = state["tasks"]["events_tsv_by_task"]
    movie_report = (
        paths["reports"] / "movie_events_generation" / "MOVIE_EVENTS_GENERATION_REPORT.md"
    )
    movie_excerpt = fence_safe_excerpt(
        _read_report_snippet(movie_report, 2000) or NA, project
    )
    grating_readme = fence_safe_excerpt(
        safe_read_text(paths["release"] / "code" / "task-grating" / "README.md", 2500),
        project,
    )
    rest_readme = fence_safe_excerpt(
        safe_read_text(paths["release"] / "code" / "task-rest" / "README.md", 2500),
        project,
    )
    movie_readme = fence_safe_excerpt(
        safe_read_text(paths["release"] / "code" / "task-movie" / "README.md", 2500),
        project,
    )

    sections = [
        "# Task descriptions",
        "",
        f"Generated: `{utc_iso()}`",
        "",
        "Live magnitude BOLD and events counts are from the release tree inventory.",
        "",
        _fmt_table(
            ["Task", "Magnitude BOLD", "events.tsv"],
            [[f"task-{k}", tasks.get(k, 0), events.get(k, 0)] for k in sorted(set(tasks) | set(events))],
        ),
        "",
    ]

    # task-rest
    sections.extend(
        [
            "## task-rest",
            "",
            f"- **Purpose:** Resting-state / continuous fixation BOLD.",
            f"- **Stimulus:** Fixation / rest (see `code/task-rest/`).",
            f"- **Timing source:** Continuous run; no discrete trial schedule.",
            f"- **Events availability:** {events.get('rest', 0)} `*_events.tsv` (expected 0 by design).",
            f"- **Known limitations:** No trial-level events; use run-level models.",
            "",
            "Code README excerpt:",
            "",
            "```",
            rest_readme or NA,
            "```",
            "",
        ]
    )

    # task-fmri (grating)
    sections.extend(
        [
            "## task-fmri (grating)",
            "",
            f"- **Purpose:** Visual grating / stimulus paradigm (release entity `task-fmri`).",
            f"- **Stimulus:** Parametric gratings / related stimuli (`code/task-grating/`, condition dictionary under `code/`).",
            f"- **Timing source:** Experimental logs + scanner triggers when uniquely mappable.",
            f"- **Events availability:** {events.get('fmri', 0)} `*_events.tsv` for {tasks.get('fmri', 0)} magnitude BOLD runs.",
            f"- **Known limitations:** Runs without unambiguous protocol↔BOLD mapping intentionally lack events.",
            "",
            "Code README excerpt:",
            "",
            "```",
            grating_readme or NA,
            "```",
            "",
        ]
    )

    # task-movie
    sections.extend(
        [
            "## task-movie",
            "",
            f"- **Purpose:** Naturalistic movie watching.",
            f"- **Stimulus:** Short movie clips; video files are **not** redistributed (copyright).",
            f"- **Timing source:** When Psychtoolbox frame-level timestamps are unavailable, movie timing was inferred when applicable from acquisition duration matching stimulus duration (see generation report).",
            f"- **Events availability:** {events.get('movie', 0)} `*_events.tsv` for {tasks.get('movie', 0)} magnitude BOLD runs.",
            f"- **Known limitations:** Exact frame-level timestamps are unavailable unless recorded by Psychtoolbox logs. Inferred onsets are not millisecond-precise TTL measurements; suitable for run-level / continuous-movie models, not frame-locked analyses.",
            "",
            "Code README excerpt:",
            "",
            "```",
            movie_readme or NA,
            "```",
            "",
            f"Generation report source: `{rel_display(movie_report, project) if movie_report.is_file() else NA}`",
            "",
            "```",
            movie_excerpt,
            "```",
            "",
        ]
    )

    # task-control
    sections.extend(
        [
            "## task-control",
            "",
            f"- **Purpose:** Control functional runs.",
            f"- **Stimulus:** {_na('See protocol materials if present; otherwise ' + NA)}",
            f"- **Timing source:** {NA} for recoverable trial timing in current release metadata.",
            f"- **Events availability:** {events.get('control', 0)} `*_events.tsv`.",
            f"- **Known limitations:** Trial-level events generally unavailable.",
            "",
        ]
    )
    return "\n".join(sections)


def build_physiology_methods(state: dict[str, Any]) -> str:
    phys = state.get("physiology_statistics") or {}
    return f"""# Physiology methods

Generated: `{utc_iso()}`

## Conversion pipeline

Siemens PhysioLog DICOM objects (CSA non-image payloads) were evaluated and, when gates passed, converted to BIDS physiology sidecars using `code/convert_physiolog_to_bids.py`.

Evidence sources:

- Readiness: `{phys.get('readiness_report_source', NA)}`
- Conversion summary: `{phys.get('conversion_summary_source', NA)}`
- Exclusions: `{phys.get('exclusion_readme_source', NA)}`

Conversion summary excerpt:

```
{phys.get('conversion_summary_excerpt', NA)}
```

## BIDS physio format

Distributed products:

- `*_recording-pulse_physio.tsv.gz` + `.json`
- `*_recording-respiratory_physio.tsv.gz` + `.json`
- `*_recording-trigger_physio.tsv.gz` + `.json`
- `*_recording-ecg_physio.tsv.gz` + `.json` (when present)

Live release inventory:

| Item | N |
| --- | ---: |
| physio.tsv.gz | {phys.get('physio_tsv_gz_in_release', NA)} |
| physio.json | {phys.get('physio_json_in_release', NA)} |

By recording: `{json.dumps(phys.get('by_recording', {}))}`

## Channels

- **Cardiac:** typically pulse (`recording-pulse`; Siemens PULS) and rare ECG (`recording-ecg`)
- **Respiratory:** `recording-respiratory` (Siemens RESP)
- **Trigger:** `recording-trigger` (EXT / volume trigger channels when present)

## Sampling frequency

Sampling frequency is taken from converter JSON (`SamplingFrequency`), typically derived from CSA `SampleTime` as \(1000 / \\mathrm{{SampleTime}}\) ms when accepted by the conversion gates. Values that rely only on undocumented defaults are not treated as valid in the readiness policy.

## Quality criteria

Physiology QC derivatives (may be a scoped subset relative to full inventory): `{paths_note(phys)}`

QC summary object: see `CURRENT_DATASET_STATE.json` → `physiology_statistics.physiology_qc_summary`.

QC report excerpt:

```
{phys.get('physiology_qc_report_excerpt', NA)}
```

## Converted vs excluded recordings

Exclusion readme excerpt:

```
{phys.get('exclusion_readme_excerpt', NA)}
```

Exclusion reason counts (from exclusion TSV when parseable): `{json.dumps(phys.get('exclusion_reason_counts', NA))}`

Documented exclusion classes in project reports include:

- EXT-only / missing StartTime (`EXT_ONLY_NO_STARTTIME`)
- missing StartTime with physio channels
- ambiguous mapping (`MAPPING_AMBIGUOUS`)
- missing sampling metadata (`NO_SAMPLETIME_AND_NO_STARTTIME`)

Peripheral PMU session-wide vendor logs (`.ecg` / `.resp` / `.puls`) remain excluded under the fail-closed policy when they lack validated ADC sampling frequency and unique run linkage.
"""


def paths_note(phys: dict[str, Any]) -> str:
    return phys.get(
        "physiology_qc_summary_note",
        "Prefer live release physio counts for inventory; QC tables may be scoped.",
    )


def build_quality_control(state: dict[str, Any], paths: dict[str, Path]) -> str:
    qc = state.get("QC_status") or {}
    mriqc = qc.get("mriqc") or {}
    dwi = state.get("dwi_statistics") or {}
    return f"""# Quality control procedures

Generated: `{utc_iso()}`

## MRIQC

- Derivatives directory: `derivatives/mriqc/`
- Live counts: T1w JSON={mriqc.get('t1w_json', NA)}; bold JSON={mriqc.get('bold_json', NA)}
- Container present: {mriqc.get('container_present', NA)} (`containers/mriqc-24.0.2.sif` when available)
- Report sources: {mriqc.get('report_sources', [])}

MRIQC IQMs are descriptive. Do not treat incomplete cohort coverage as full-cohort QC without checking derivative coverage.

## Physiology QC

- Report present: {qc.get('physiology_qc_present')}
- Live physio.tsv.gz: {state.get('physiology_statistics', {}).get('physio_tsv_gz_in_release', NA)}
- See `docs/physiology_methods.md` and `derivatives/physiology_qc/`.

## DWI QC

- Report: `{dwi.get('dwi_qc_report_source', NA)}`
- Live DWI NIfTI: {dwi.get('dwi_nifti_in_release', NA)}
- Inventory rows: {_na(dwi.get('dwi_inventory_rows'))}

Excerpt:

```
{dwi.get('dwi_qc_report_excerpt', NA)}
```

## Visual inspection

- Pizarro T1w screening report: `{_na((qc.get('pizarro') or {}).get('report_source'))}`
- Role (from existing reports): prioritization for manual review, not automatic exclusion, unless a specific report states otherwise.

Pizarro excerpt:

```
{(qc.get('pizarro') or {}).get('excerpt', NA)}
```

## Defacing

- Derivatives present: {(qc.get('defacing') or {}).get('derivatives_present')}
- Audit dir present: {(qc.get('defacing') or {}).get('audit_dir_present')}

## Exclusion criteria

No global automated exclusion list is asserted here beyond what individual QC/conversion reports document (physiology conversion gates, event mapping gates, and any explicit exclusions TSVs under `docs/Protocols/` or reports). Users should consult:

- `docs/Protocols/grating_events_exclusions.tsv` (if present)
- physiology exclusion TSVs under `reports/physiology_audit/`
- DWI QC REVIEW/FAIL labels (report-only; corrections not applied when stated)
"""


def build_data_dictionary(state: dict[str, Any], paths: dict[str, Path]) -> str:
    pj = load_json(paths["release"] / "participants.json") or {}
    return f"""# Data dictionary

Generated: `{utc_iso()}`

## participants.tsv

File: `participants.tsv`  
Sidecar dictionary: `participants.json`

```json
{json.dumps(pj, indent=2)}
```

Cohort counts (live): `{json.dumps(state.get('cohorts', {}))}`

## events.tsv

Task events files use BIDS column conventions (`onset`, `duration`, and task-specific columns such as `trial_type` when present). Column definitions may appear in:

- `task-fmri_events.json` / related task JSON at release root (when present)
- `task-movie_events.json` (when present)
- per-run `*_events.json` sidecars

Live events counts by task: `{json.dumps(state['tasks']['events_tsv_by_task'])}`

## JSON sidecars

Imaging sidecars (`*_bold.json`, `*_T1w.json`, `*_dwi.json`, `*_epi.json`, …) carry acquisition parameters from dcm2niix conversion and post-conversion cleaning. Physiology JSON use an allowlist of keys (see physiology conversion summary).

Representative acquisition examples are in `CURRENT_DATASET_STATE.json` → `acquisition_examples`.

## Derivative outputs

Available derivative top-level datasets: `{json.dumps(state.get('available_derivatives', []))}`

These may include MRIQC IQMs, defacing outputs, DWI QC / dmriqc products, and physiology QC/characterization tables. Derivative-specific dictionaries are documented in each derivative's report/README when available.
"""


def build_provenance(state: dict[str, Any], paths: dict[str, Path]) -> str:
    dd = state.get("dataset_description") or {}
    return f"""# Provenance

Generated: `{utc_iso()}`

## Raw data preservation

- Source DICOM / associated files remain under private `raw_original/` (not part of the public release package).
- This documentation update does **not** modify `raw_original/` or overwrite original imaging NIfTI as part of documentation generation.

## Conversion tools

- Primary conversion pipeline recorded in `dataset_description.json` → `GeneratedBy`: `{json.dumps(dd.get('GeneratedBy', NA))}`
- Sidecar conversion software example: see acquisition examples (`dcm2niix` version from JSON when present).

## Versioning

- BIDSVersion: `{_na(dd.get('BIDSVersion'))}`
- DatasetType: `{_na(dd.get('DatasetType'))}`
- Changelog: `CHANGES` / `CHANGES.md`

## Containers

- MRIQC Apptainer/Singularity image expected at `containers/mriqc-24.0.2.sif` (present={state['QC_status']['mriqc'].get('container_present')}).
- Additional containers: inspect `containers/` in the processing environment.

## Pipeline history

Documented processing stages in existing README/methods materials include DICOM inventory/mapping, PS3.15-oriented de-identification, dcm2niix conversion, BIDS organization via neuro_pipeline, sidecar cleaning, defacing derivatives, physiology conversion (gated), events integration, and QC (MRIQC / DWI / physiology / privacy).

## SHA256 tracking

- Documentation inventory hashes: `reports/release_documentation_audit/DOCUMENTATION_INVENTORY.tsv`
- De-identification / processing manifests under `metadata/` (e.g. `deidentify_manifest.json`, `processing_manifest.csv`) when present — treat as sensitive/internal as appropriate.
"""


def build_limitations(state: dict[str, Any]) -> str:
    cov = state["number_of_sessions"]
    events = state["tasks"]["events_tsv_by_task"]
    tasks = state["tasks"]["magnitude_bold_by_task"]
    phys = state["physiology_statistics"]
    return f"""# Known limitations

Generated: `{utc_iso()}`

## Missing events

Not all functional runs have `*_events.tsv`. Live magnitude BOLD vs events:

`{json.dumps({"bold": tasks, "events": events})}`

Runs without unambiguous mapping intentionally remain without events.

## Movie timing assumptions

Movie timing was inferred when applicable from acquisition duration matching stimulus duration.
Exact frame-level timestamps are unavailable unless recorded by Psychtoolbox logs.
See `docs/task_descriptions.md` and `reports/movie_events_generation/`.

## Physiology exclusions

Converted physio.tsv.gz in release: **{phys.get('physio_tsv_gz_in_release', NA)}**

Excluded recordings and reasons are documented in physiology readiness/exclusion reports, including classes such as EXT-only, missing StartTime, ambiguous mapping, and missing sampling metadata. See `docs/physiology_methods.md`.

## Incomplete runs / longitudinal coverage

Session coverage: `{json.dumps(cov)}`

Missing sessions are real absences (participant follow-up), not empty placeholders.

## Copyright restricted stimuli

Movie stimulus video files are not redistributed with this dataset because of third-party copyright restrictions. Protocol code and timing metadata are included (`LICENSE` note).

## Unavailable source files

Some associated source logs (eye-tracking, peripheral PMU, failed-gate PhysioLogs, unrecovered stimulus timing) remain source-only and are not in the public BIDS tree. Details appear in associated-data and physiology audit reports under `reports/`.

## Metadata placeholders

Fields such as final Dataset DOI, complete author list, and funding may still require manual completion before journal/OpenNeuro submission (`dataset_description.json`).
"""


def build_software_versions(paths: dict[str, Path], state: dict[str, Any]) -> str:
    """Extract versions only from existing files / runtime — never invent."""
    project = paths["project"]
    rows: list[list[str]] = []

    def add(name: str, version: str, source: str) -> None:
        rows.append([name, version, rel_display(source, project) if source != "sys.version" else source])

    add("Python (audit runtime)", sys.version.split()[0], "sys.version")

    # dcm2niix from sidecar example
    acq = state.get("acquisition_examples") or {}
    t1 = acq.get("T1w_MPRAGE") if isinstance(acq.get("T1w_MPRAGE"), dict) else {}
    if t1.get("ConversionSoftwareVersion"):
        add(
            t1.get("ConversionSoftware", "dcm2niix"),
            str(t1.get("ConversionSoftwareVersion")),
            str(t1.get("source_file")),
        )
    else:
        add("dcm2niix", NA, "sidecar ConversionSoftwareVersion")

    # bids-validator from reports
    val_md = paths["reports"] / "bids_validation_scientific_data" / "VALIDATION_AFTER_EVENTS_ST.md"
    val_txt = safe_read_text(val_md, 2000)
    m = re.search(r"bids-validator[^\n]*?(\d+\.\d+\.\d+)", val_txt)
    if m:
        add("bids-validator", m.group(1), str(val_md))
    else:
        add("bids-validator", NA, str(val_md))

    # MRIQC
    mriqc_readme = paths["reports"] / "mriqc" / "README.md"
    mt = safe_read_text(mriqc_readme, 3000)
    m = re.search(r"(24\.[^\s]+)", mt)
    if m:
        add("MRIQC (derivatives metadata / README)", m.group(1), str(mriqc_readme))
    else:
        add("MRIQC", NA, str(mriqc_readme))
    add(
        "MRIQC container file",
        "mriqc-24.0.2.sif" if (project / "containers" / "mriqc-24.0.2.sif").is_file() else NA,
        "containers/mriqc-24.0.2.sif",
    )

    # fMRIPrep
    fmriprep_hits = list((paths["derivatives"]).glob("*fmriprep*")) + list(
        (project / "containers").glob("*fmriprep*")
    )
    if fmriprep_hits:
        add("fMRIPrep", f"path present: {fmriprep_hits[0].name}", str(fmriprep_hits[0]))
    else:
        add("fMRIPrep", NA, "no fmriprep derivative/container detected")

    # MRtrix — mentioned in DWI report
    dwi_md = paths["reports"] / "dwi_qc" / "DWI_QC_REPORT.md"
    dwi_txt = safe_read_text(dwi_md, 2000)
    if "dwigradcheck" in dwi_txt or "MRtrix" in dwi_txt:
        add(
            "MRtrix3 tools",
            "dwigradcheck / dwi2mask used in DWI QC (exact version string not in report excerpt)",
            str(dwi_md),
        )
    else:
        add("MRtrix3", NA, str(dwi_md))

    # Nextflow
    nf = project / "software" / "nextflow-22.10.8"
    if nf.exists():
        add("Nextflow", "22.10.8", str(nf))
    else:
        add("Nextflow", NA, "software/nextflow-*")

    # Apptainer
    apptainer = shutil.which("apptainer") or shutil.which("singularity")
    if apptainer:
        try:
            proc = subprocess.run(
                [apptainer, "--version"], capture_output=True, text=True, check=False
            )
            ver = proc.stdout.strip() or proc.stderr.strip() or NA
            add("Apptainer/Singularity", ver, "runtime which(apptainer|singularity)")
        except OSError:
            add("Apptainer/Singularity", NA, "runtime which(apptainer|singularity)")
    else:
        add("Apptainer/Singularity", NA, "not on PATH in audit environment")

    # neuro_pipeline from dataset_description
    dd = state.get("dataset_description") or {}
    for gb in dd.get("GeneratedBy") or []:
        if isinstance(gb, dict):
            add(gb.get("Name", "GeneratedBy"), str(gb.get("Version", NA)), "dataset_description.json")

    # pydeface from extracted metrics / manuscript if present
    em_path = paths["reports"] / "scientific_data_docs" / "extracted_metrics.md"
    em = safe_read_text(em_path, 5000)
    m = re.search(r"pydeface[^\n]*?(\d+\.\d+\.\d+[^\s|]*)", em, flags=re.IGNORECASE)
    if m:
        add("pydeface", m.group(1), str(em_path))
    else:
        tv_path = project / "manuscript" / "technical_validation.md"
        tv = safe_read_text(tv_path, 5000)
        m = re.search(r"pydeface[^\n]*?(\d+\.\d+\.\d+[^\s|]*)", tv, flags=re.IGNORECASE)
        if m:
            add("pydeface", m.group(1), str(tv_path))
        else:
            add("pydeface", NA, "not found as explicit version string in consulted reports")

    table = _fmt_table(["Software", "Version", "Source"], rows)
    return f"""# Software versions

Generated: `{utc_iso()}`

Versions below were extracted from existing sidecars, reports, containers, or the audit runtime.
Entries marked `{NA}` were not found as explicit version strings in consulted sources.
Source paths are relative to the project root.

{table}
"""


def build_changes_md(release: Path) -> str:
    existing = ""
    if (release / "CHANGES.md").is_file():
        existing = safe_read_text(release / "CHANGES.md")
    elif (release / "CHANGES").is_file():
        existing = safe_read_text(release / "CHANGES")
    stamp = utc_now().strftime("%Y-%m-%d")
    entry = (
        f"{stamp}\n"
        "  - Documentation audit/update via `code/audit_and_update_release_documentation.py`.\n"
        "  - Refreshed README and docs/* from live release metadata and QC reports.\n"
        "  - Ensured Open Science documentation set under `docs/`.\n"
    )
    if entry.split("\n", 1)[0] in existing:
        return existing if existing.endswith("\n") else existing + "\n"
    if existing.strip():
        return entry + "\n" + existing.lstrip()
    return entry


def update_movie_protocol_note(release: Path, state: dict[str, Any]) -> list[str]:
    """Preserve prior Movie.md text and add a clear superseding current-state section."""
    updated: list[str] = []
    movie_md = release / "docs" / "Protocols" / "Movie.md"
    n_events = state["tasks"]["events_tsv_by_task"].get("movie", 0)
    n_bold = state["tasks"]["magnitude_bold_by_task"].get("movie", 0)
    if not movie_md.is_file():
        return updated
    text = safe_read_text(movie_md)
    marker = "<!-- documentation_audit_update_movie_events -->"
    # Preserve original body once under a historical heading if not already archived.
    hist_marker = "<!-- documentation_audit_historical_movie_body -->"
    if hist_marker not in text and n_events > 0:
        # Split off any prior update note
        body = re.split(r"<!-- documentation_audit_update_movie_events -->", text, maxsplit=1)[0].rstrip()
        text = f"""# Naturalistic movie paradigm (`task-movie`)

## Current release status ({utc_iso()})

- Magnitude BOLD runs (`task-movie`, excluding phase): **{n_bold}**
- `*_events.tsv` present: **{n_events}**
- Timing policy: Movie timing was inferred when applicable from acquisition duration matching stimulus duration.
- Exact frame-level timestamps are unavailable unless recorded by Psychtoolbox logs.
- Movie video files are **not** redistributed (copyright). Protocol code and run-identity tables remain under `code/task-movie/`.
- Details: `docs/task_descriptions.md`, `reports/movie_events_generation/MOVIE_EVENTS_GENERATION_REPORT.md`

{marker}

## Historical protocol note (preserved)

{hist_marker}

{body}
"""
    elif marker in text:
        text = re.sub(
            rf"{re.escape(marker)}.*?(?=\n## Historical|\Z)",
            f"{marker}\n\n_Current events inventory: {n_events}. See Current release status above._\n\n",
            text,
            count=1,
            flags=re.DOTALL,
        )
    else:
        text = text.rstrip() + f"\n\n{marker}\n\nCurrent events inventory: **{n_events}**.\n"
    write_md(movie_md, text)
    updated.append(str(movie_md))
    return updated


def phase6_update(
    paths: dict[str, Path], state: dict[str, Any], out_dir: Path
) -> dict[str, Any]:
    log("PHASE 6 — Update documentation")
    release = paths["release"]
    backup = _backup_release_docs(release, paths["project"])
    docs = release / "docs"
    docs.mkdir(parents=True, exist_ok=True)

    updated: list[str] = []
    manual_review: list[str] = []

    # README
    write_md(release / "README.md", build_readme(state, paths))
    updated.append(str(release / "README.md"))

    # dataset_description.json
    existing_dd = load_json(release / "dataset_description.json") or {}
    new_dd = build_dataset_description(existing_dd, state)
    write_json(release / "dataset_description.json", new_dd)
    updated.append(str(release / "dataset_description.json"))
    if new_dd.get("Authors") == ["Neuro BIDS Pipeline"] or new_dd.get("DatasetDOI") == NA:
        manual_review.append(
            "release_dataset/dataset_description.json (Authors/Funding/DOI/Acknowledgements)"
        )

    # docs
    doc_builders = {
        "acquisition_protocol.md": lambda: build_acquisition_protocol(state),
        "task_descriptions.md": lambda: build_task_descriptions(state, paths),
        "physiology_methods.md": lambda: build_physiology_methods(state),
        "quality_control.md": lambda: build_quality_control(state, paths),
        "data_dictionary.md": lambda: build_data_dictionary(state, paths),
        "provenance.md": lambda: build_provenance(state, paths),
        "limitations.md": lambda: build_limitations(state),
        "software_versions.md": lambda: build_software_versions(paths, state),
    }
    for name, builder in doc_builders.items():
        path = docs / name
        write_md(path, builder())
        updated.append(str(path))

    # CHANGES.md (preserve CHANGES content)
    changes_md = build_changes_md(release)
    write_md(release / "CHANGES.md", changes_md)
    updated.append(str(release / "CHANGES.md"))
    # Keep legacy CHANGES in sync without deleting it
    if (release / "CHANGES").is_file():
        write_md(release / "CHANGES", changes_md)
        updated.append(str(release / "CHANGES"))

    updated.extend(update_movie_protocol_note(release, state))

    # LICENSE: do not overwrite if present
    if not (release / "LICENSE").is_file():
        manual_review.append("LICENSE missing — must be added manually (not invented by audit script)")
    else:
        manual_review.append("Confirm LICENSE matches investigator intent (existing file preserved)")

    result = {
        "backup_dir": str(backup),
        "updated_files": updated,
        "manual_review": manual_review,
    }
    write_json(out_dir / "DOCUMENTATION_UPDATE_MANIFEST.json", result)
    log(f"  Updated {len(updated)} files")
    return result


# ---------------------------------------------------------------------------
# Phase 7 — Final validation
# ---------------------------------------------------------------------------


def _scan_absolute_paths(release: Path) -> list[str]:
    hits: list[str] = []
    roots = [release / "README.md", release / "docs", release / "dataset_description.json"]
    abs_re = re.compile(r"(/lustre\d+/|/home/|/Users/|/mnt/)")
    for root in roots:
        if root.is_file():
            files = [root]
        elif root.is_dir():
            files = [p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in {".md", ".json", ".tsv", ".txt"}]
        else:
            continue
        for p in files:
            text = safe_read_text(p, 200_000)
            if abs_re.search(text):
                hits.append(str(p))
    return sorted(set(hits))


def _sample_phi_scan(release: Path, limit: int = 50) -> list[str]:
    """Sample sidecars for forbidden PHI keys (documentation validation aid)."""
    json_files = run_find(release, ["-type", "f", "-name", "*_bold.json"])[:limit]
    json_files += run_find(release, ["-type", "f", "-name", "*_T1w.json"])[:limit]
    offenders: list[str] = []
    for fp in json_files:
        data = load_json(Path(fp))
        if not isinstance(data, dict):
            continue
        bad = [k for k in PHI_JSON_KEYS if k in data and data[k] not in (None, "", "n/a")]
        # InstitutionalDepartmentName often residual — flag if present
        if bad:
            offenders.append(f"{fp}: {','.join(bad)}")
    return offenders[:30]


def phase7_validation(
    paths: dict[str, Path],
    state: dict[str, Any],
    update_result: dict[str, Any] | None,
    skip_validator: bool,
    out_dir: Path,
) -> dict[str, Any]:
    log("PHASE 7 — Final documentation validation")
    release = paths["release"]
    checks: list[dict[str, str]] = []

    def add(name: str, status: str, detail: str = "") -> None:
        checks.append({"check": name, "status": status, "detail": detail})

    add("README_exists", "PASS" if (release / "README.md").is_file() else "FAIL")
    dd = load_json(release / "dataset_description.json")
    add("dataset_description_json_valid", "PASS" if isinstance(dd, dict) else "FAIL")
    try:
        pd.read_csv(release / "participants.tsv", sep="\t")
        add("participants_tsv_readable", "PASS")
    except Exception as exc:  # noqa: BLE001
        add("participants_tsv_readable", "FAIL", str(exc))

    for doc in [
        "acquisition_protocol.md",
        "task_descriptions.md",
        "physiology_methods.md",
        "quality_control.md",
        "data_dictionary.md",
        "provenance.md",
        "limitations.md",
        "software_versions.md",
    ]:
        add(f"docs_{doc}", "PASS" if (release / "docs" / doc).is_file() else "FAIL")

    add(
        "LICENSE_exists",
        "PASS" if (release / "LICENSE").is_file() else "FAIL",
    )
    add(
        "CHANGES_exists",
        "PASS"
        if (release / "CHANGES.md").is_file() or (release / "CHANGES").is_file()
        else "FAIL",
    )

    abs_hits = _scan_absolute_paths(release)
    add(
        "no_absolute_paths_in_docs",
        "PASS" if not abs_hits else "WARN",
        f"{len(abs_hits)} files: " + "; ".join(abs_hits[:10]),
    )

    phi_hits = _sample_phi_scan(release)
    add(
        "phi_sample_sidecars",
        "PASS" if not phi_hits else "WARN",
        f"{len(phi_hits)} sampled sidecars with sensitive keys",
    )

    validator_out = out_dir / "bids_validator_release_dataset.txt"
    validator_status = "SKIPPED"
    validator_detail = ""
    if skip_validator:
        validator_detail = "--skip_bids_validator set"
    else:
        # Prefer npx bids-validator if available
        cmd = None
        if shutil.which("bids-validator"):
            cmd = ["bids-validator", str(release)]
        elif shutil.which("npx"):
            cmd = ["npx", "--yes", "bids-validator@1.15.0", str(release)]
        if cmd is None:
            validator_status = "SKIPPED"
            validator_detail = "bids-validator / npx not available"
        else:
            log(f"  Running: {' '.join(cmd)}")
            try:
                proc = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=7200,
                )
                validator_out.write_text(
                    (proc.stdout or "") + "\n" + (proc.stderr or ""), encoding="utf-8"
                )
                # bids-validator exits non-zero on errors; warnings may still exit 0 depending on version/flags
                if proc.returncode == 0:
                    validator_status = "PASS"
                else:
                    validator_status = "WARN"
                validator_detail = f"exit={proc.returncode}; output={validator_out}"
            except subprocess.TimeoutExpired:
                validator_status = "WARN"
                validator_detail = "bids-validator timed out"
            except OSError as exc:
                validator_status = "SKIPPED"
                validator_detail = str(exc)
    add("bids_validator", validator_status, validator_detail)

    lines = [
        "# Final documentation validation",
        "",
        f"Generated: `{utc_iso()}`",
        "",
        f"Release dir: `{release}`",
        "",
        "## Checks",
        "",
        "| Check | Status | Detail |",
        "| --- | --- | --- |",
    ]
    for c in checks:
        detail = (c.get("detail") or "").replace("|", "\\|").replace("\n", " ")
        lines.append(f"| {c['check']} | {c['status']} | {detail} |")

    lines.extend(
        [
            "",
            "## Live counts (post-audit)",
            "",
            f"- Subjects: {state['number_of_subjects']}",
            f"- Modalities: `{json.dumps(state['modalities'])}`",
            f"- Tasks: `{json.dumps(state['tasks'])}`",
            f"- Physio tsv.gz: {state['physiology_statistics'].get('physio_tsv_gz_in_release')}",
            "",
        ]
    )
    if update_result:
        lines.extend(
            [
                "## Update manifest",
                "",
                f"- Backup: `{update_result.get('backup_dir')}`",
                f"- Updated files: {len(update_result.get('updated_files') or [])}",
                "",
            ]
        )
        for fp in update_result.get("updated_files") or []:
            lines.append(f"  - `{fp}`")
        lines.append("")
        lines.append("### Manual review")
        lines.append("")
        for item in update_result.get("manual_review") or []:
            lines.append(f"- {item}")
        lines.append("")

    fail_n = sum(1 for c in checks if c["status"] == "FAIL")
    warn_n = sum(1 for c in checks if c["status"] == "WARN")
    lines.extend(
        [
            "## Summary",
            "",
            f"- FAIL: **{fail_n}**",
            f"- WARN: **{warn_n}**",
            f"- PASS/SKIPPED: **{len(checks) - fail_n - warn_n}**",
            "",
        ]
    )
    write_md(out_dir / "FINAL_DOCUMENTATION_VALIDATION.md", "\n".join(lines))
    summary = {"checks": checks, "fail": fail_n, "warn": warn_n}
    write_json(out_dir / "FINAL_DOCUMENTATION_VALIDATION.json", summary)
    log(f"  Validation FAIL={fail_n} WARN={warn_n}")
    return summary


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def print_final_summary(
    readiness: dict[str, Any],
    missing_docs: list[dict[str, Any]],
    update_result: dict[str, Any] | None,
) -> None:
    missing_critical = readiness.get("missing_critical") or []
    # Recompute after update if files now exist — caller should pass refreshed list
    print("", flush=True)
    print("Current documentation score:", flush=True)
    print(
        f"  {readiness.get('score_total')}/{readiness.get('score_max')} "
        f"({readiness.get('score_percent')}%)",
        flush=True,
    )
    print("Missing critical items:", flush=True)
    if missing_critical:
        for item in missing_critical:
            print(f"  - {item}", flush=True)
    else:
        print("  - none", flush=True)
    print("Updated files:", flush=True)
    if update_result and update_result.get("updated_files"):
        for fp in update_result["updated_files"]:
            print(f"  - {fp}", flush=True)
    else:
        print("  - none (audit-only mode)" if not update_result else "  - none", flush=True)
    print("Files requiring manual review:", flush=True)
    manual = (update_result or {}).get("manual_review") or [
        "dataset_description.json Authors/Funding/DOI",
        "Confirm Scientific Data manuscript alignment with live counts",
    ]
    for item in manual:
        print(f"  - {item}", flush=True)


def main() -> int:
    args = parse_args()
    project = args.project_root.resolve()
    paths = {
        "project": project,
        "release": args.release_dir.resolve(),
        "bids": args.bids_dir.resolve(),
        "derivatives": args.derivatives_dir.resolve(),
        "metadata": args.metadata_dir.resolve(),
        "reports": args.reports_dir.resolve(),
        "docs": (project / "docs"),
        "code": (project / "code"),
    }
    out_dir = args.output_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    if not paths["release"].is_dir():
        log(f"ERROR: release_dir not found: {paths['release']}")
        return 1

    log(f"Release documentation audit @ {utc_iso()}")
    log(f"  release_dir = {paths['release']}")
    log(f"  output_dir  = {out_dir}")
    log(f"  mode        = {'UPDATE' if args.update else 'AUDIT ONLY'}")

    phase1_inventory(paths, out_dir)
    state = phase2_dataset_state(paths, out_dir)
    inconsistencies = phase3_consistency(paths, state, out_dir)
    missing_docs = phase4_missing_docs(paths, out_dir)
    readiness = phase5_readiness(paths, state, inconsistencies, missing_docs, out_dir)

    update_result = None
    if args.update:
        update_result = phase6_update(paths, state, out_dir)
        # Refresh state-dependent readiness missing list after update
        missing_docs_after = phase4_missing_docs(paths, out_dir)
        readiness = phase5_readiness(
            paths, state, inconsistencies, missing_docs_after, out_dir
        )
        # Re-run consistency on updated README against same live state
        inconsistencies = phase3_consistency(paths, state, out_dir)

    phase7_validation(
        paths, state, update_result, args.skip_bids_validator, out_dir
    )

    # Final missing critical from latest missing_docs file
    latest_missing = list(pd.read_csv(out_dir / "MISSING_DOCUMENTATION.tsv", sep="\t").to_dict("records"))
    missing_critical = []
    for r in latest_missing:
        if r["document"] == "CHANGES.md":
            continue
        if r["document"] == "CHANGES (alternate)" and r["status"] == "MISSING":
            missing_critical.append("CHANGES")
        elif r["status"] == "MISSING" and r["criticality"] == "critical":
            missing_critical.append(r["document"])
    readiness["missing_critical"] = missing_critical

    print_final_summary(readiness, latest_missing, update_result)
    write_json(
        out_dir / "RUN_SUMMARY.json",
        {
            "generated_at_utc": utc_iso(),
            "mode": "update" if args.update else "audit",
            "readiness": readiness,
            "update": update_result,
            "output_dir": str(out_dir),
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
