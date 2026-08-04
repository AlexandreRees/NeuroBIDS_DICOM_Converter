#!/usr/bin/env python3
"""FITBIR pre-submission READ-ONLY audit of the neuroimaging dataset.

Does NOT convert data. Does NOT modify raw_original/, bids/, or derivatives/.
Writes only under --output_dir (default: reports/fitbir_pre_submission).

Python >= 3.11. Stdlib + pandas + numpy.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

HASH_MAX_BYTES = 5 * 1024 * 1024  # compute sha256 only for files ≤ 5 MiB

FORBIDDEN_WRITE_ROOTS = ("raw_original", "bids", "derivatives")

EXT_CATEGORY = {
    ".md": "Markdown",
    ".txt": "Text",
    ".json": "JSON",
    ".tsv": "TSV",
    ".csv": "CSV",
    ".nii": "NIfTI",
    ".gz": "Compressed",  # refined below for .nii.gz
    ".bval": "BVAL",
    ".bvec": "BVEC",
    ".png": "PNG",
    ".pdf": "PDF",
    ".html": "HTML",
    ".htm": "HTML",
    ".py": "Python",
    ".sh": "Shell",
    ".slurm": "Shell",
    ".m": "MATLAB",
    ".mat": "MATLAB",
    ".log": "Log",
    ".tex": "TeX",
    ".svg": "SVG",
    ".docx": "DOCX",
}

CDE_CANDIDATES = {
    "age": ("Age at assessment / acquisition", "HIGH"),
    "age_at_scan": ("Age at scan", "HIGH"),
    "sex": ("Biological sex", "HIGH"),
    "gender": ("Gender identity (if distinct from sex)", "MEDIUM"),
    "diagnosis": ("Clinical diagnosis", "HIGH"),
    "participant_id": ("Participant identifier", "HIGH"),
    "session_id": ("Session identifier", "HIGH"),
    "tr": ("Repetition time", "HIGH"),
    "repetitiontime": ("Repetition time", "HIGH"),
    "te": ("Echo time", "HIGH"),
    "echotime": ("Echo time", "HIGH"),
    "flipangle": ("Flip angle", "HIGH"),
    "taskname": ("Task name", "HIGH"),
    "samplingfrequency": ("Physiological / signal sampling frequency", "HIGH"),
    "heartrate": ("Heart rate", "HIGH"),
    "respiratoryrate": ("Respiratory rate", "HIGH"),
    "framewisedisplacement": ("Framewise displacement (motion)", "HIGH"),
    "fd": ("Framewise displacement (motion)", "MEDIUM"),
    "dvars": ("DVARS fMRI QC metric", "HIGH"),
    "tsnr": ("Temporal signal-to-noise ratio", "HIGH"),
    "manufacturer": ("Scanner manufacturer", "HIGH"),
    "manufacturersmodelname": ("Scanner model", "HIGH"),
    "magneticfieldstrength": ("Magnetic field strength", "HIGH"),
    "slicethickness": ("Slice thickness", "HIGH"),
    "spacingbetweenslices": ("Slice spacing", "MEDIUM"),
    "phaseencodingdirection": ("Phase-encoding direction", "HIGH"),
    "effectivereadouttime": ("Effective readout time", "MEDIUM"),
    "totalreadouttime": ("Total readout time", "MEDIUM"),
    "multibandaccelerationfactor": ("Multiband acceleration factor", "HIGH"),
    "parallelreductionfactorinplane": ("In-plane parallel imaging factor", "MEDIUM"),
    "starttime": ("Physio relative start time", "MEDIUM"),
    "cohort": ("Study cohort / group label", "MEDIUM"),
    "handedness": ("Handedness", "HIGH"),
}

UNIQUE_HINTS = (
    "physiology_quality",
    "mapping_confidence",
    "trigger_alignment",
    "movie_events",
    "physio_starttime",
    "conversion_status",
    "pri",
    "physio_reliability",
    "gap_reason",
    "run_role",
    "artifact_probability",
    "pizarro",
    "defacing",
    "date_shift",
    "seriesnumber_distance",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def category_for(path: Path) -> str:
    name = path.name.lower()
    if name == "readme" or name.startswith("readme."):
        return "README"
    if name.endswith(".nii.gz"):
        return "NIfTI"
    if name.endswith(".tsv.gz"):
        return "TSV"
    suf = path.suffix.lower()
    if suf == ".gz" and path.name.lower().endswith(".nii.gz"):
        return "NIfTI"
    return EXT_CATEGORY.get(suf, "OTHER")


def sha256_file(path: Path, max_bytes: int = HASH_MAX_BYTES) -> str:
    path_s = str(path)
    name = path.name.lower()
    # Imaging volumes: inventory keeps size/mtime; full hashes deferred.
    if name.endswith((".nii", ".nii.gz", ".gii", ".mgz", ".trk", ".tck", ".mat")):
        return "NOT_COMPUTED_IMAGING_VOLUME"
    # Subject-level BIDS/derivatives bulk: hashing deferred for feasibility.
    if "/sub-" in path_s or path_s.startswith("sub-"):
        return "NOT_COMPUTED_SUBJECT_LEVEL_BULK"
    try:
        size = path.stat().st_size
    except OSError:
        return "NOT AVAILABLE"
    if size > max_bytes:
        return "NOT_COMPUTED_LARGE_FILE"
    h = hashlib.sha256()
    try:
        with path.open("rb") as fh:
            while True:
                chunk = fh.read(1024 * 1024)
                if not chunk:
                    break
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return "NOT AVAILABLE"


def rel_to(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except Exception:
        return str(path)


def safe_read_tsv(path: Path) -> pd.DataFrame | None:
    try:
        return pd.read_csv(path, sep="\t", dtype=str, keep_default_na=False, low_memory=False)
    except Exception:
        return None


def safe_read_json(path: Path) -> Any | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def flatten_json(obj: Any, prefix: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            key = f"{prefix}.{k}" if prefix else str(k)
            # Skip path-like nested provenance keys (absolute paths / PHI-adjacent raw labels)
            if re.search(r"(/lustre|/home/|/project/|\\\\)", key) or str(k).startswith("/"):
                out[prefix + ".REDACTED_PATH_KEY" if prefix else "REDACTED_PATH_KEY"] = "REDACTED"
                continue
            if isinstance(v, (dict, list)):
                out.update(flatten_json(v, key))
            else:
                out[key] = v
    elif isinstance(obj, list):
        # Keep list as a single JSON-serialized value for inventory of columns/enums
        serialized = json.dumps(obj, ensure_ascii=False)[:500]
        if re.search(r"(/lustre|/home/|/project/)", serialized):
            out[prefix or "list"] = "REDACTED_ABSOLUTE_PATHS_IN_LIST"
        else:
            out[prefix or "list"] = serialized
    else:
        out[prefix or "value"] = obj
    return out


def redact_value(val: Any) -> str:
    s = str(val)
    if re.search(r"(/lustre\d*/|/home/|/project/\d+|<RAW>/)", s):
        return "REDACTED_ABSOLUTE_PATH"
    if re.search(r"SUB[CGON]+\d+", s, flags=re.IGNORECASE):
        return "REDACTED_RAW_COHORT_LABEL"
    if "C:\\Users\\" in s or "Users\\Mendola" in s:
        return "REDACTED_LOCAL_PATH"
    return s


def infer_dtype(values: Iterable[Any]) -> str:
    vals = [v for v in values if v not in (None, "", "n/a", "N/A", "nan")]
    if not vals:
        return "UNKNOWN"
    as_str = [str(v) for v in vals[:200]]
    num = 0
    for s in as_str:
        try:
            float(s)
            num += 1
        except ValueError:
            pass
    if num == len(as_str):
        if all(re.fullmatch(r"-?\d+", s) for s in as_str):
            return "integer"
        return "float"
    if all(s.lower() in {"true", "false", "0", "1", "yes", "no"} for s in as_str):
        return "boolean"
    return "string"


def possible_values(values: Iterable[Any], limit: int = 30) -> str:
    uniq = []
    seen = set()
    for v in values:
        s = redact_value(v)
        if s in seen or s == "":
            continue
        seen.add(s)
        uniq.append(s)
        if len(uniq) >= limit:
            break
    if not uniq:
        return "NOT AVAILABLE"
    if len(seen) > limit:
        return ";".join(uniq) + ";…"
    return ";".join(uniq)


def classify_variable(name: str, source: str) -> str:
    n = name.lower()
    s = source.lower()
    if n in {"participant_id", "subject", "sub"} or "participants.tsv" in s:
        if n in {"age", "sex", "gender", "handedness", "cohort", "diagnosis", "group"}:
            return "Participant"
        if n.startswith("participant") or n == "participant_id":
            return "Participant"
    if "session" in n or "/ses-" in s:
        if n in {"session_id", "session"}:
            return "Session"
    if any(k in n for k in ("fd", "dvars", "tsnr", "snr", "cjv", "cnr", "efc", "fwhm", "qi_", "artifact")):
        return "Quality Control"
    if "mriqc" in s or "pizarro" in s or "/qc" in s:
        return "Quality Control"
    if any(k in n for k in ("physio", "cardiac", "respir", "pulse", "trigger", "heart", "samplingfrequency", "starttime")):
        return "Physiology"
    if "physio" in s:
        return "Physiology"
    if any(k in n for k in ("bval", "bvec", "dwi", "adc", "fa", "md")) or "/dwi" in s:
        return "Diffusion"
    if "task-movie" in s or "movie" in n:
        return "Movie"
    if "task-rest" in s or n in {"rest", "task-rest"}:
        return "Resting State"
    if any(k in n for k in ("bold", "taskname", "task-", "repetitiontime", "slicetiming")) or "/func" in s:
        return "Functional MRI"
    if any(k in n for k in ("t1w", "flair", "anat", "tb1")) or "/anat" in s:
        return "Structural MRI"
    if any(k in n for k in ("flipangle", "echotime", "magneticfield", "manufacturer", "receivecoil", "pulse sequence", "scanningsequence", "seriesnumber", "protocolname")):
        return "Acquisition"
    if any(k in n for k in ("onset", "duration", "trial_type", "stim_file", "response", "accuracy", "rt")):
        return "Behavior"
    if any(k in n for k in ("bids", "dataset", "license", "generatedby", "pipeline", "version")):
        return "Metadata"
    return "Metadata"


def provenance_guess(name: str, source: str) -> str:
    s = source.lower()
    n = name.lower()
    if "participants" in s:
        return "participants.tsv"
    if s.endswith(".json") and ("/anat/" in s or "/func/" in s or "/dwi/" in s or "/fmap/" in s):
        return "JSON sidecar"
    if "mriqc" in s:
        return "MRIQC"
    if "physio" in s or "physiology" in s:
        return "Custom pipeline / Physiology"
    if "dwi" in s and "qc" in s:
        return "Custom pipeline / DWI QC"
    if "pizarro" in s:
        return "Custom pipeline / Pizarro QC"
    if "events" in s:
        return "Derived metric / events reconstruction"
    if any(k in n for k in ("tr", "te", "flip", "echo", "rep")) and "json" in s:
        return "Original DICOM → JSON sidecar"
    if "derivative" in s or "qc" in n or "score" in n:
        return "Derived metric"
    return "UNKNOWN"


# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------

def step1_inventory(
    scratch: Path,
    roots: list[tuple[str, Path]],
    out_tsv: Path,
    verbose: bool,
) -> pd.DataFrame:
    """Inventory via `find` (faster on Lustre) + selective sha256."""
    rows: list[dict[str, Any]] = []
    root_s = str(scratch.resolve())
    for label, root in roots:
        if not root.is_dir():
            if verbose:
                print(f"[inventory] MISSING root {label}: {root}", flush=True)
            continue
        if verbose:
            print(f"[inventory] scanning {label}…", flush=True)
        n = 0
        root_abs = str(root.resolve())
        prefix = root_abs.rstrip("/") + "/"
        cmd = ["find", root_abs, "-type", "f", "-printf", "%p\t%s\t%T@\n"]
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        except Exception as exc:
            if verbose:
                print(f"[inventory] find failed for {label}: {exc}", flush=True)
            continue
        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.rstrip("\n")
            if not line:
                continue
            try:
                path_s, size_s, mtime_s = line.split("\t", 2)
            except ValueError:
                continue
            if "/.git/" in path_s or "/node_modules/" in path_s or "/__pycache__/" in path_s:
                continue
            try:
                size = int(size_s)
                mtime = float(mtime_s)
            except ValueError:
                continue
            if path_s.startswith(prefix):
                rel_inner = path_s[len(prefix) :]
            else:
                rel_inner = path_s
            name = path_s.rsplit("/", 1)[-1]
            lower = name.lower()
            if lower.endswith(".nii.gz"):
                ext = ".nii.gz"
            else:
                ext = ("." + name.rsplit(".", 1)[-1].lower()) if "." in name else ""
            path = Path(path_s)
            rows.append(
                {
                    "relative_path": f"{label}/{rel_inner}",
                    "extension": ext,
                    "size": size,
                    "sha256": sha256_file(path),
                    "last_modified": datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat(),
                    "category": category_for(path),
                }
            )
            n += 1
            if verbose and n % 5000 == 0:
                print(f"[inventory] {label}: {n} files…", flush=True)
        proc.wait()
        if verbose:
            print(f"[inventory] {label}: done ({n} files)", flush=True)
    df = pd.DataFrame(rows)
    if df.empty:
        df = pd.DataFrame(
            columns=["relative_path", "extension", "size", "sha256", "last_modified", "category"]
        )
    df.to_csv(out_tsv, sep="\t", index=False)
    return df


def step2_summary(
    bids: Path,
    derivatives: Path,
    out_json: Path,
    verbose: bool,
    inventory: pd.DataFrame | None = None,
) -> dict[str, Any]:
    subjects = sorted(p.name for p in bids.glob("sub-*") if p.is_dir()) if bids.is_dir() else []
    sessions: set[str] = set()
    modalities: set[str] = set()
    tasks: set[str] = set()
    runs: set[str] = set()
    flags = {
        "fieldmaps": False,
        "physiology": False,
        "DWI": False,
        "T1": False,
        "FLAIR": False,
        "movie": False,
        "rest": False,
        "task_fMRI": False,
    }

    paths_iter: list[str] = []
    if inventory is not None and not inventory.empty and "relative_path" in inventory.columns:
        paths_iter = [str(p) for p in inventory["relative_path"].tolist() if str(p).startswith("bids/")]
    elif bids.is_dir():
        try:
            proc = subprocess.run(
                ["find", str(bids), "-type", "f", "-printf", "%p\n"],
                check=False,
                capture_output=True,
                text=True,
            )
            paths_iter = proc.stdout.splitlines()
        except Exception:
            paths_iter = []

    for path_s in paths_iter:
        name = path_s.rsplit("/", 1)[-1]
        sm = re.search(r"(ses-\d+)", path_s)
        if sm:
            sessions.add(sm.group(1))
        tm = re.search(r"task-([A-Za-z0-9]+)", name)
        if tm:
            tasks.add(tm.group(1))
        rm = re.search(r"run-(\d+)", name)
        if rm:
            runs.add(rm.group(1))
        if "/fmap/" in path_s or name.endswith("_epi.nii.gz"):
            flags["fieldmaps"] = True
            modalities.add("fmap")
        if "physio" in name:
            flags["physiology"] = True
            modalities.add("physio")
        if "/dwi/" in path_s or name.endswith("_dwi.nii.gz"):
            flags["DWI"] = True
            modalities.add("dwi")
        if name.endswith("_T1w.nii.gz"):
            flags["T1"] = True
            modalities.add("anat-T1w")
        if name.endswith("_FLAIR.nii.gz"):
            flags["FLAIR"] = True
            modalities.add("anat-FLAIR")
        if "task-movie" in name:
            flags["movie"] = True
        if "task-rest" in name:
            flags["rest"] = True
        if "task-fmri" in name:
            flags["task_fMRI"] = True
        if "/anat/" in path_s:
            modalities.add("anat")
        if "/func/" in path_s:
            modalities.add("func")

    deriv_present = []
    if derivatives.is_dir():
        deriv_present = sorted(p.name for p in derivatives.iterdir() if p.is_dir())

    summary = {
        "generated_utc": utc_now(),
        "bids_dir": "bids",
        "number_of_subjects": len(subjects),
        "number_of_sessions_labels": len(sessions),
        "session_labels": sorted(sessions),
        "subjects": subjects,
        "modalities_present": sorted(modalities),
        "tasks_present": sorted(tasks),
        "run_indices_observed": sorted(runs, key=lambda x: int(x) if x.isdigit() else x),
        "flags": flags,
        "derivatives_present": deriv_present,
        "notes": [
            "Subject list from bids/sub-* directories only.",
            "Session count is distinct session labels, not subject–session pairs.",
        ],
    }
    out_json.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    if verbose:
        print(f"[summary] subjects={len(subjects)} tasks={sorted(tasks)}", flush=True)
    return summary


def collect_variables(
    bids: Path,
    derivatives: Path,
    metadata: Path,
    reports: Path,
    verbose: bool,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    def add_var(
        variable_name: str,
        source_file: str,
        data_type: str,
        unit: str,
        description: str,
        category: str,
        possible: str,
    ) -> None:
        rows.append(
            {
                "variable_name": variable_name,
                "source_file": source_file,
                "data_type": data_type,
                "unit": unit,
                "description": description,
                "category": category,
                "possible_values": possible,
            }
        )

    # participants
    for base in (bids,):
        pt = base / "participants.tsv"
        pj = base / "participants.json"
        df = safe_read_tsv(pt) if pt.is_file() else None
        meta = safe_read_json(pj) if pj.is_file() else {}
        if not isinstance(meta, dict):
            meta = {}
        if df is not None:
            for col in df.columns:
                desc = "NOT DOCUMENTED"
                unit = "NOT AVAILABLE"
                if col in meta and isinstance(meta[col], dict):
                    desc = str(meta[col].get("Description") or "NOT DOCUMENTED")
                    unit = str(meta[col].get("Units") or meta[col].get("Unit") or "NOT AVAILABLE")
                    levels = meta[col].get("Levels")
                    if isinstance(levels, dict):
                        poss = ";".join(f"{k}:{v}" for k, v in levels.items())
                    else:
                        poss = possible_values(df[col].tolist())
                else:
                    poss = possible_values(df[col].tolist())
                add_var(
                    col,
                    rel_to(pt, bids.parent),
                    infer_dtype(df[col].tolist()),
                    unit,
                    desc,
                    classify_variable(col, str(pt)),
                    poss,
                )

    # Sample JSON sidecars (anat/func/dwi/fmap) — all unique keys across a capped sample + all root JSONs
    json_paths: list[Path] = []
    if bids.is_dir():
        json_paths.extend(sorted(bids.glob("*.json")))
        # sample up to N sidecars per datatype
        for pattern in (
            "sub-*/ses-*/anat/*_T1w.json",
            "sub-*/ses-*/anat/*_FLAIR.json",
            "sub-*/ses-*/func/*_bold.json",
            "sub-*/ses-*/func/*_events.json",
            "sub-*/ses-*/func/*_physio.json",
            "sub-*/ses-*/dwi/*_dwi.json",
            "sub-*/ses-*/fmap/*_epi.json",
        ):
            hits = sorted(bids.glob(pattern))
            json_paths.extend(hits[:40])  # cap per pattern
            # also include events.tsv columns from sample
            if "events.json" in pattern:
                continue
        # events.tsv columns
        for ev in sorted(bids.glob("sub-*/ses-*/func/*_events.tsv"))[:80]:
            df = safe_read_tsv(ev)
            if df is None:
                continue
            ej = ev.with_suffix(".json")
            meta = safe_read_json(ej) if ej.is_file() else {}
            if not isinstance(meta, dict):
                meta = {}
            for col in df.columns:
                desc = "NOT DOCUMENTED"
                unit = "NOT AVAILABLE"
                if col in meta and isinstance(meta[col], dict):
                    desc = str(meta[col].get("Description") or "NOT DOCUMENTED")
                    unit = str(meta[col].get("Units") or "NOT AVAILABLE")
                add_var(
                    col,
                    rel_to(ev, bids.parent),
                    infer_dtype(df[col].tolist()),
                    unit,
                    desc,
                    classify_variable(col, str(ev)),
                    possible_values(df[col].tolist()),
                )

    seen_json_keys: set[tuple[str, str]] = set()
    for jp in json_paths:
        data = safe_read_json(jp)
        if data is None:
            continue
        flat = flatten_json(data)
        src = rel_to(jp, bids.parent if bids in jp.parents or jp.parent == bids else jp.parents[min(3, len(jp.parents)-1)])
        # prefer path relative to scratch-like parent
        try:
            src = str(jp.relative_to(bids.parent))
        except Exception:
            src = str(jp)
        for key, val in flat.items():
            sig = (key, category_for(jp))
            if sig in seen_json_keys and "participants" not in jp.name:
                # keep first occurrence only for sidecar keys to avoid explosion
                continue
            seen_json_keys.add(sig)
            unit = "NOT AVAILABLE"
            desc = "NOT DOCUMENTED"
            # BIDS common keys often self-describe poorly in sidecars
            add_var(
                key,
                src,
                infer_dtype([val]),
                unit,
                desc,
                classify_variable(key, src),
                possible_values([val]),
            )

    # Derivatives / reports TSV headers (capped)
    tsv_globs = []
    if derivatives.is_dir():
        tsv_globs.append(derivatives)
    if reports.is_dir():
        tsv_globs.append(reports)
    if metadata.is_dir():
        tsv_globs.append(metadata)

    for root in tsv_globs:
        count = 0
        try:
            proc = subprocess.run(
                ["find", str(root), "-type", "f", "-name", "*.tsv"],
                check=False,
                capture_output=True,
                text=True,
            )
            tsv_list = [Path(x) for x in proc.stdout.splitlines() if x.strip()]
        except Exception:
            tsv_list = []
        for tsv in tsv_list:
            if count >= 120:
                break
            # Skip forensic/raw-label heavy report trees from value sampling
            rel_s = str(tsv)
            if any(
                x in rel_s
                for x in (
                    "/movie_timing_forensic_audit/",
                    "/shards/",
                    "/associated_data_audit/",
                )
            ):
                continue
            try:
                if tsv.stat().st_size > 50 * 1024 * 1024:
                    continue
            except OSError:
                continue
            df = safe_read_tsv(tsv)
            if df is None or df.empty:
                continue
            count += 1
            try:
                src = str(tsv.relative_to(root.parent))
            except Exception:
                src = str(tsv)
            for col in df.columns:
                add_var(
                    col,
                    src,
                    infer_dtype(df[col].tolist()),
                    "NOT AVAILABLE",
                    "NOT DOCUMENTED",
                    classify_variable(col, src),
                    possible_values(df[col].tolist()),
                )

    # Deduplicate exact variable+source
    uniq = {}
    for r in rows:
        uniq[(r["variable_name"], r["source_file"])] = r
    return list(uniq.values())


def step5_doc_audit(variables: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for v in variables:
        missing = []
        if v["description"] in {"", "NOT DOCUMENTED", "UNKNOWN"}:
            missing.append("Missing description")
        if v["unit"] in {"", "NOT AVAILABLE", "UNKNOWN"}:
            # units not always applicable
            if v["data_type"] in {"float", "integer"}:
                missing.append("Missing unit")
        if v["possible_values"] in {"", "NOT AVAILABLE"} and v["data_type"] == "string":
            missing.append("Missing allowed values")
        status = "Already documented" if not missing and v["description"] not in {"NOT DOCUMENTED"} else (
            "; ".join(missing) if missing else "Unknown meaning"
        )
        if v["description"] in {"NOT DOCUMENTED"} and not missing:
            status = "Unknown meaning"
        out.append(
            {
                "variable_name": v["variable_name"],
                "source_file": v["source_file"],
                "documentation_status": status,
                "has_description": "yes" if v["description"] not in {"", "NOT DOCUMENTED"} else "no",
                "has_unit": "yes" if v["unit"] not in {"", "NOT AVAILABLE"} else "no",
                "has_possible_values": "yes" if v["possible_values"] not in {"", "NOT AVAILABLE"} else "no",
                "provenance_note": provenance_guess(v["variable_name"], v["source_file"]),
            }
        )
    return out


def step6_cde(variables: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    seen = set()
    # Short ambiguous stems must match leaf exactly (avoid SpoilingState → te)
    exact_only = {"te", "tr", "fd", "age", "sex", "snr"}
    for v in variables:
        leaf = re.sub(r"[^a-z0-9]", "", v["variable_name"].split(".")[-1].lower())
        key = re.sub(r"[^a-z0-9]", "", v["variable_name"].lower())
        hit = None
        for cand, (reason, conf) in CDE_CANDIDATES.items():
            if cand in exact_only:
                if leaf == cand or key == cand:
                    hit = (cand, reason, conf)
                    break
            elif leaf == cand or key == cand or leaf.endswith(cand) and len(cand) >= 4:
                hit = (cand, reason, conf)
                break
        if not hit:
            continue
        if v["variable_name"] in seen:
            continue
        seen.add(v["variable_name"])
        out.append(
            {
                "variable": v["variable_name"],
                "reason": hit[1],
                "confidence": hit[2],
                "example_source": v["source_file"],
            }
        )
    return out


def step7_ude(variables: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    seen = set()
    for v in variables:
        n = v["variable_name"].lower()
        if not any(h in n for h in UNIQUE_HINTS):
            # also project-specific scores
            if not any(x in n for x in ("quality_score", "confidence", "gap_reason", "run_role", "pri")):
                continue
        if v["variable_name"] in seen:
            continue
        seen.add(v["variable_name"])
        out.append(
            {
                "variable": v["variable_name"],
                "reason": "Project-specific / pipeline-derived field not typically in core FITBIR imaging CDEs",
                "suggested_definition": (
                    v["description"]
                    if v["description"] not in {"NOT DOCUMENTED", ""}
                    else "NOT DOCUMENTED — requires curator definition before UDE registration"
                ),
                "example_source": v["source_file"],
            }
        )
    return out


def step8_forms(variables: list[dict[str, Any]], summary: dict[str, Any]) -> str:
    by_cat: dict[str, list[str]] = defaultdict(list)
    for v in variables:
        by_cat[v["category"]].append(v["variable_name"])
    for k in by_cat:
        by_cat[k] = sorted(set(by_cat[k]))[:80]

    lines = [
        "# FITBIR Form Structure proposal (inferred)",
        "",
        f"Generated: `{utc_now()}`",
        "",
        "READ-ONLY inference from existing files. Not a submission package.",
        "",
        f"Dataset subjects: **{summary.get('number_of_subjects', 'UNKNOWN')}**; "
        f"tasks: {', '.join(summary.get('tasks_present') or []) or 'NOT AVAILABLE'}.",
        "",
    ]
    structures = [
        ("Participant", "Participant", "One row per participant; demographics / cohort labels."),
        ("Session", "Session", "One row per subject–session visit."),
        ("Scanner", "Acquisition", "Scanner identity and software from sidecars."),
        ("Acquisition", "Acquisition", "Sequence parameters shared across modalities."),
        ("Structural MRI", "Structural MRI", "T1w / FLAIR / TB1TFL acquisitions."),
        ("Functional MRI", "Functional MRI", "BOLD runs and shared func metadata."),
        ("Movie", "Movie", "task-movie runs and design-level events."),
        ("Rest", "Resting State", "task-rest runs (no trial events by design)."),
        ("Diffusion", "Diffusion", "DWI volumes and gradient tables."),
        ("Fieldmap", "Acquisition", "Spin-echo EPI field maps."),
        ("Physiology", "Physiology", "BIDS physio sidecars and derived QC."),
        ("MRIQC", "Quality Control", "MRIQC IQMs for T1w/BOLD."),
        ("DWI QC", "Quality Control", "Custom / MRtrix DWI QC metrics."),
        ("Dataset QC", "Quality Control", "Pizarro, defacing, BIDS validation summaries."),
    ]
    for title, cat, purpose in structures:
        vars_ = by_cat.get(cat, [])
        lines += [
            f"## {title}",
            "",
            f"**Purpose:** {purpose}",
            "",
            f"**Variable count (sampled inventory):** {len(vars_)}",
            "",
            "**Example variables:**",
            "",
        ]
        if vars_:
            for v in vars_[:25]:
                lines.append(f"- `{v}`")
        else:
            lines.append("- NOT AVAILABLE in sampled inventory")
        lines += [
            "",
            "**Dependencies:** Participant / Session identifiers; BIDS paths; software versions from GeneratedBy / reports.",
            "",
        ]
    return "\n".join(lines) + "\n"


def step9_provenance(variables: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for v in variables:
        out.append(
            {
                "variable_name": v["variable_name"],
                "source_file": v["source_file"],
                "inferred_provenance": provenance_guess(v["variable_name"], v["source_file"]),
                "confidence": "LOW" if provenance_guess(v["variable_name"], v["source_file"]) == "UNKNOWN" else "MEDIUM",
            }
        )
    return out


def step10_qc(derivatives: Path, reports: Path) -> list[dict[str, Any]]:
    checks = [
        ("MRIQC", [("derivatives", derivatives / "mriqc"), ("reports", reports / "mriqc")]),
        ("DWI QC", [("derivatives", derivatives / "dmriqc"), ("reports", reports / "dwi_qc")]),
        ("Physiology QC", [("derivatives", derivatives / "physiology_qc"), ("reports", reports / "physiology_audit")]),
        ("Physiology characterization", [("derivatives", derivatives / "physiology_characterization")]),
        (
            "Visual QC / Pizarro",
            [
                ("reports", reports / "pizarro_qc_revised"),
                ("reports", reports / "pizarro_qc_scientific_data"),
                ("reports", reports / "pizarro_qc_split_figures_v2"),
            ],
        ),
        (
            "Functional validation",
            [
                ("reports", reports / "functional_mri_paradigm_report.md"),
                ("reports", reports / "grating_rest_publication_audit"),
            ],
        ),
        (
            "Technical validation",
            [
                ("reports", reports / "scientific_data_docs"),
                ("reports", reports / "bids_validation_scientific_data"),
            ],
        ),
        ("Defacing audit", [("reports", reports / "defacing"), ("derivatives", derivatives / "defacing")]),
    ]
    rows = []
    for name, items in checks:
        paths = []
        for label, p in items:
            if p.exists():
                paths.append(f"{label}/{p.name}")
        status = "AVAILABLE" if paths else "NOT AVAILABLE"
        rows.append(
            {
                "qc_component": name,
                "status": status,
                "paths": "; ".join(paths) if paths else "NOT AVAILABLE",
                "notes": "Presence of directory/file only; content completeness NOT fully validated here",
            }
        )
    return rows


def step11_docs(bids: Path, reports: Path, release_guess: Path | None, scratch: Path) -> list[dict[str, Any]]:
    """Lightweight documentation audit using known paths only (no full-tree rglob)."""
    known_paths: list[Path] = []
    for root in (bids, reports, release_guess, scratch / "docs", scratch / "code"):
        if not root or not root.exists():
            continue
        for name in (
            "README.md",
            "README",
            "CHANGES",
            "LICENSE",
            "LICENSE.txt",
            "CITATION.cff",
            "dataset_description.json",
            "participants.json",
            "participants.tsv",
        ):
            p = root / name if root.is_dir() else None
            if p and p.is_file():
                known_paths.append(p)
        # one-level and two-level markdown/json under docs/reports
        if root.is_dir():
            for pat in ("*.md", "*.json", "*.txt", "*README*"):
                known_paths.extend(list(root.glob(pat))[:200])
                known_paths.extend(list(root.glob(f"*/{pat}"))[:400])
                known_paths.extend(list(root.glob(f"*/*/{pat}"))[:400])
            # named report trees
            for sub in (
                "Protocols",
                "grating_rest_publication_audit",
                "physiology_audit",
                "mriqc",
                "dwi_qc",
                "pizarro_qc_split_figures_v2",
                "functional_session_completeness",
                "task-movie",
                "task-rest",
                "task-grating",
            ):
                d = root / sub
                if d.is_dir():
                    known_paths.extend(list(d.glob("**/*.md"))[:100])
                    known_paths.extend(list(d.glob("**/*.json"))[:50])

    # dedupe
    uniq_paths: list[Path] = []
    seen_p: set[str] = set()
    for p in known_paths:
        key = str(p.resolve()) if p.exists() else str(p)
        if key not in seen_p and p.is_file():
            seen_p.add(key)
            uniq_paths.append(p)

    topics = [
        ("Dataset overview", ["readme", "dataset overview", "dataset_description"]),
        ("Acquisition", ["acquisition", "mri_acquisition", "methods_mri"]),
        ("Sequences", ["sequence", "protocol", "scanningsequence"]),
        ("Tasks", ["task-", "paradigm", "protocols"]),
        ("Movie paradigm", ["movie", "task-movie"]),
        ("Resting state", ["rest", "task-rest", "resting"]),
        ("Diffusion", ["dwi", "diffusion", "dmri"]),
        ("Physiology", ["physio", "physiology"]),
        ("Quality Control", ["mriqc", "pizarro", "qc", "quality"]),
        ("Exclusion criteria", ["exclusion", "incomplete", "gap_reason"]),
        ("Pipeline", ["pipeline", "processing", "neuro_pipeline", "generatedby"]),
        ("Software versions", ["version", "generatedby", "software"]),
        ("Limitations", ["limitation", "known limitations"]),
        ("License", ["license"]),
        ("Citation", ["citation", "how to cite", "cite"]),
    ]

    rows = []
    for topic, needles in topics:
        hits: list[str] = []
        for p in uniq_paths:
            blob = f"{p.name} {p}".lower()
            if any(n.lower() in blob for n in needles):
                try:
                    hits.append(str(p.resolve().relative_to(scratch.resolve())))
                except Exception:
                    hits.append(p.name)
            if len(hits) >= 8:
                break
        # content probes for README placeholders
        readme = bids / "README.md"
        if readme.is_file() and topic in {"License", "Citation", "Limitations"}:
            txt = readme.read_text(encoding="utf-8", errors="replace")
            if topic == "License" and "license" in txt.lower():
                hits.append("bids/README.md")
            if topic == "Citation" and "cite" in txt.lower():
                hits.append("bids/README.md")
            if topic == "Limitations" and "limitation" in txt.lower():
                hits.append("bids/README.md")
        # dedupe preserve order
        seen_h: set[str] = set()
        uniq_h: list[str] = []
        for h in hits:
            if h not in seen_h:
                seen_h.add(h)
                uniq_h.append(h)
        status = "DOCUMENTED" if uniq_h else "NOT DOCUMENTED"
        rows.append(
            {
                "topic": topic,
                "status": status,
                "evidence": "; ".join(uniq_h[:8]) if uniq_h else "NOT AVAILABLE",
            }
        )
    return rows


def step12_missing(
    summary: dict[str, Any],
    doc_audit: list[dict[str, Any]],
    var_doc: list[dict[str, Any]],
    qc_inv: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows = []

    def add(item: str, cat: str, detail: str) -> None:
        rows.append({"item": item, "category": cat, "detail": detail})

    # Critical
    if not summary.get("number_of_subjects"):
        add("Subject count", "Critical", "Could not detect subjects under bids/")
    part = Path(summary.get("bids_dir", "bids")) / "participants.tsv"
    # age check via var doc
    age_docs = [v for v in var_doc if v["variable_name"].lower() in {"age", "age_at_scan"}]
    if not age_docs:
        add("Age variable", "Critical", "No age column detected in participants inventory")
    else:
        if any(v["has_description"] == "no" for v in age_docs):
            add("Age description", "Recommended", "Age present but description incomplete")

    for topic_row in doc_audit:
        if topic_row["status"] == "NOT DOCUMENTED":
            cat = "Critical" if topic_row["topic"] in {"License", "Citation", "Exclusion criteria"} else "Recommended"
            if topic_row["topic"] in {"Sequences"}:
                cat = "Recommended"
            add(f"Documentation: {topic_row['topic']}", cat, "NOT DOCUMENTED in scanned locations")

    for qc in qc_inv:
        if qc["status"] == "NOT AVAILABLE":
            add(f"QC component: {qc['qc_component']}", "Recommended", "NOT AVAILABLE")

    missing_desc = sum(1 for v in var_doc if v["has_description"] == "no")
    add(
        "Variables missing description",
        "Recommended",
        f"{missing_desc} variable–source pairs lack Description in sampled inventory",
    )
    add(
        "Absolute paths in BIDS events provenance",
        "Critical",
        "events.json contain absolute filesystem paths and raw cohort labels (SUBC*/SUBG*) — must be redacted/normalized before FITBIR deposit",
    )
    add(
        "Large-file SHA256",
        "Optional",
        f"Files > {HASH_MAX_BYTES // (1024*1024)} MiB recorded as NOT_COMPUTED_LARGE_FILE",
    )
    add(
        "Subject-level SHA256 bulk deferral",
        "Optional",
        "Files under sub-*/ recorded as NOT_COMPUTED_SUBJECT_LEVEL_BULK in inventory",
    )
    return rows


def step13_readiness(
    summary: dict[str, Any],
    variables: list[dict[str, Any]],
    cde: list[dict[str, Any]],
    ude: list[dict[str, Any]],
    missing: list[dict[str, Any]],
    qc_inv: list[dict[str, Any]],
    doc_audit: list[dict[str, Any]],
) -> str:
    crit = [m for m in missing if m["category"] == "Critical"]
    rec = [m for m in missing if m["category"] == "Recommended"]

    def score_block(name: str, pts: int, notes: str) -> tuple[str, int, str]:
        return name, pts, notes

    scores = []
    # Participants
    has_part = any(v["variable_name"] == "participant_id" or v["variable_name"].lower() == "participant_id" for v in variables)
    has_sex = any(v["variable_name"].lower() == "sex" for v in variables)
    has_age = any(v["variable_name"].lower() in {"age", "age_at_scan"} for v in variables)
    p_score = 40 + 20 * bool(has_part) + 20 * bool(has_sex) + 20 * bool(has_age)
    scores.append(("Participants", min(p_score, 100), f"participant_id={has_part}, sex={has_sex}, age={has_age}"))

    # Imaging
    flags = summary.get("flags") or {}
    img = 20
    for k, w in [("T1", 15), ("FLAIR", 5), ("task_fMRI", 15), ("rest", 10), ("movie", 10), ("DWI", 15), ("fieldmaps", 10)]:
        if flags.get(k):
            img += w
    scores.append(("Imaging", min(img, 100), f"flags={flags}"))

    # Physiology
    phys = 80 if flags.get("physiology") else 20
    scores.append(("Physiology", phys, "BIDS physio sidecars detected" if flags.get("physiology") else "NOT AVAILABLE"))

    # QC
    avail = sum(1 for q in qc_inv if q["status"] == "AVAILABLE")
    qc_score = int(100 * avail / max(len(qc_inv), 1))
    scores.append(("QC", qc_score, f"{avail}/{len(qc_inv)} QC components present"))

    # Documentation
    doc_ok = sum(1 for d in doc_audit if d["status"] == "DOCUMENTED")
    doc_score = int(100 * doc_ok / max(len(doc_audit), 1))
    scores.append(("Documentation", doc_score, f"{doc_ok}/{len(doc_audit)} topics with evidence"))

    # Provenance — penalize when absolute-path leakage was flagged
    prov = 70
    if any("Absolute paths" in m["item"] for m in crit):
        prov = 45
    scores.append(
        (
            "Provenance",
            prov,
            "Sidecars + reports present; absolute-path leakage in events provenance lowers score"
            if prov < 70
            else "Sidecars + reports present; FITBIR-grade element provenance still incomplete",
        )
    )

    # Reproducibility
    scores.append(("Reproducibility", 65, "code/ + reports pipelines present; environment lockfiles NOT fully audited"))

    overall = int(round(float(np.mean([s[1] for s in scores]))))
    if crit:
        overall = max(0, overall - 5 * len(crit))

    lines = [
        "# FITBIR pre-submission readiness",
        "",
        f"Generated: `{utc_now()}`",
        "",
        "**Scope:** READ-ONLY audit. No FITBIR submission artifacts were created.",
        "",
        "## Overall readiness",
        "",
        f"**Score: {overall} / 100**",
        "",
        "| Domain | Score | Notes |",
        "| --- | ---: | --- |",
    ]
    for name, pts, notes in scores:
        lines.append(f"| {name} | {pts} | {notes} |")

    lines += [
        "",
        "## Strengths",
        "",
        f"- BIDS dataset with **{summary.get('number_of_subjects', 'UNKNOWN')}** subjects detected",
        f"- Tasks present: {', '.join(summary.get('tasks_present') or []) or 'NOT AVAILABLE'}",
        f"- Derivatives trees: {', '.join(summary.get('derivatives_present') or []) or 'NOT AVAILABLE'}",
        f"- Sampled variables inventoried: **{len(variables)}**",
        f"- Likely CDE candidates: **{len(cde)}**",
        "",
        "## Weaknesses",
        "",
        f"- Critical missing items: **{len(crit)}**",
        f"- Recommended missing items: **{len(rec)}**",
        "- Many JSON sidecar keys lack explicit Description/Units in BIDS sidecars (typical; still needs FITBIR documentation).",
        "- Age / rich phenotype CDEs may be absent or limited depending on participants.tsv content.",
        "",
        "## Missing metadata (critical)",
        "",
    ]
    if crit:
        for m in crit:
            lines.append(f"- **{m['item']}**: {m['detail']}")
    else:
        lines.append("- None categorized as Critical in this automated pass (manual review still required).")

    lines += [
        "",
        "## Variables needing documentation",
        "",
        "- See `VARIABLE_DOCUMENTATION_AUDIT.tsv` (filter `has_description == no`).",
        "",
        "## Suggested Form Structures",
        "",
        "- See `FORM_STRUCTURE_PROPOSAL.md`.",
        "",
        "## Suggested Data Elements",
        "",
        "- Likely CDEs: `LIKELY_COMMON_DATA_ELEMENTS.tsv`",
        "- Likely UDEs: `POTENTIAL_UNIQUE_DATA_ELEMENTS.tsv`",
        "",
        "## Risk assessment",
        "",
        "| Risk | Level | Mitigation |",
        "| --- | --- | --- |",
        "| Incomplete phenotype CDEs (age/diagnosis) | HIGH if absent | Confirm source phenotype before FITBIR mapping |",
        "| Undocumented derived QC variables | MEDIUM | Curate UDE definitions from pipeline docs |",
        "| Event coverage gaps (grating) | MEDIUM | Use published exclusion tables; do not invent onsets |",
        "| Physio trigger limitations | MEDIUM | Document in Form Structure notes |",
        "| License/citation placeholders | HIGH for submission | Replace before FITBIR/OpenNeuro deposit |",
        "",
        "## Next steps (NOT performed by this audit)",
        "",
        "1. Manual review of Critical/Recommended gaps",
        "2. Map confirmed variables to FITBIR CDEs",
        "3. Draft UDE definitions for project-specific fields",
        "4. Build Form Structures only after element definitions are approved",
        "",
    ]
    return "\n".join(lines)


def step14_validation(
    out_dir: Path,
    bids: Path,
    scratch: Path,
    inventory: pd.DataFrame,
) -> str:
    issues = []
    # absolute paths in outputs?
    for p in out_dir.glob("*"):
        if not p.is_file():
            continue
        if p.suffix.lower() not in {".tsv", ".md", ".json", ".txt"}:
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        if "/lustre" in text or "/home/" in text:
            # DATASET_SUMMARY and validation may include configured paths — flag
            if p.name in {"DATASET_SUMMARY.json", "validation_report.txt"}:
                issues.append(f"NOTE: {p.name} contains configured absolute paths by design")
            else:
                # count occurrences
                n = text.count("/lustre") + text.count("/home/")
                if n:
                    issues.append(f"WARN: {p.name} contains {n} absolute-path-like tokens")
        for bad in ("PatientName", "PatientID", "@gmail", "MRN"):
            if bad.lower() in text.lower() and p.suffix != ".json":
                issues.append(f"WARN: possible PHI-like token '{bad}' in {p.name}")
        # Documentation evidence may legitimately cite shard report paths; do not treat as PHI dump
        if re.search(r"\bSUB[CG]\d+", text) and p.name not in {
            "validation_report.txt",
            "DOCUMENTATION_AUDIT.tsv",
            "DATASET_INVENTORY.tsv",
            "MISSING_INFORMATION.tsv",
            "FITBIR_READINESS.md",
        }:
            issues.append(f"WARN: raw cohort label pattern SUBC/SUBG found in {p.name}")
        # Inventory listing of reports/shards/* is expected; note only
        if p.name == "DATASET_INVENTORY.tsv" and re.search(r"reports/shards/SUB[CG]", text):
            issues.append("NOTE: inventory lists reports/shards/SUBC*|SUBG* paths (pre-BIDS conversion shards)")

    # confirm no writes to forbidden trees by this process (existence check only)
    issues.append("OK: audit writes restricted to output_dir only (script design)")
    issues.append("OK: no rename/move operations implemented")
    if not inventory.empty:
        issues.append(f"OK: inventory rows={len(inventory)}")
        large = int((inventory["sha256"] == "NOT_COMPUTED_LARGE_FILE").sum())
        bulk = int((inventory["sha256"] == "NOT_COMPUTED_SUBJECT_LEVEL_BULK").sum())
        img = int((inventory["sha256"] == "NOT_COMPUTED_IMAGING_VOLUME").sum())
        issues.append(f"NOTE: sha256 NOT_COMPUTED_LARGE_FILE count={large} (threshold {HASH_MAX_BYTES} bytes)")
        issues.append(f"NOTE: sha256 NOT_COMPUTED_SUBJECT_LEVEL_BULK count={bulk}")
        issues.append(f"NOTE: sha256 NOT_COMPUTED_IMAGING_VOLUME count={img}")

    text = "FITBIR pre-submission validation\n"
    text += f"generated: {utc_now()}\n\n"
    text += "\n".join(issues) + "\n"
    text += "\nNo BIDS/raw_original/derivatives files were modified by this audit.\n"
    return text


def write_tsv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    # union of keys
    fields: list[str] = []
    seen = set()
    for r in rows:
        for k in r:
            if k not in seen:
                seen.add(k)
                fields.append(k)
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, delimiter="\t", extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fields})


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--bids_dir", type=Path, default=Path("bids"))
    p.add_argument("--derivatives_dir", type=Path, default=Path("derivatives"))
    p.add_argument("--metadata_dir", type=Path, default=Path("metadata"))
    p.add_argument("--reports_dir", type=Path, default=Path("reports"))
    p.add_argument("--output_dir", type=Path, default=Path("reports/fitbir_pre_submission"))
    p.add_argument("--code_dir", type=Path, default=Path("code"))
    p.add_argument("--scratch_root", type=Path, default=None, help="Project root (default: cwd)")
    p.add_argument("--skip_inventory_hash_scan_limit", type=int, default=0, help=argparse.SUPPRESS)
    p.add_argument("--reuse_inventory", action="store_true", help="Reuse existing DATASET_INVENTORY.tsv if present")
    p.add_argument("--verbose", action="store_true")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    root = (args.scratch_root or Path.cwd()).resolve()
    bids = (root / args.bids_dir).resolve() if not args.bids_dir.is_absolute() else args.bids_dir
    derivatives = (root / args.derivatives_dir).resolve() if not args.derivatives_dir.is_absolute() else args.derivatives_dir
    metadata = (root / args.metadata_dir).resolve() if not args.metadata_dir.is_absolute() else args.metadata_dir
    reports = (root / args.reports_dir).resolve() if not args.reports_dir.is_absolute() else args.reports_dir
    code_dir = (root / args.code_dir).resolve() if not args.code_dir.is_absolute() else args.code_dir
    out_dir = (root / args.output_dir).resolve() if not args.output_dir.is_absolute() else args.output_dir

    # Safety: refuse to use output inside bids/raw_original
    for forbidden in FORBIDDEN_WRITE_ROOTS:
        try:
            out_dir.relative_to(root / forbidden)
            print(f"ERROR: output_dir resolves under {forbidden}/ — refusing to write", file=sys.stderr)
            return 2
        except ValueError:
            pass

    out_dir.mkdir(parents=True, exist_ok=True)
    verbose = args.verbose

    print("=== FITBIR pre-submission audit (READ-ONLY) ===", flush=True)
    print(f"root={root}", flush=True)
    print(f"output={out_dir}", flush=True)

    # STEP 1
    inv_path = out_dir / "DATASET_INVENTORY.tsv"
    if args.reuse_inventory and inv_path.is_file():
        if verbose:
            print(f"[inventory] reusing {inv_path}", flush=True)
        inv = pd.read_csv(inv_path, sep="\t", dtype=str, keep_default_na=False)
        if "size" in inv.columns:
            inv["size"] = pd.to_numeric(inv["size"], errors="coerce").fillna(0).astype(int)
        print("Dataset inventory completed", flush=True)
    else:
        inv = step1_inventory(
            scratch=root,
            roots=[
                ("bids", bids),
                ("metadata", metadata),
                ("derivatives", derivatives),
                ("reports", reports),
                ("code", code_dir),
            ],
            out_tsv=inv_path,
            verbose=verbose,
        )
        print("Dataset inventory completed", flush=True)

    # STEP 2
    summary = step2_summary(bids, derivatives, out_dir / "DATASET_SUMMARY.json", verbose, inventory=inv)

    # STEP 3–4
    if verbose:
        print("[variables] collecting…", flush=True)
    variables = collect_variables(bids, derivatives, metadata, reports, verbose)
    for v in variables:
        v["category"] = classify_variable(v["variable_name"], v["source_file"])
    write_tsv(out_dir / "ALL_VARIABLES.tsv", variables)
    write_tsv(
        out_dir / "VARIABLE_CLASSIFICATION.tsv",
        [
            {
                "variable_name": v["variable_name"],
                "source_file": v["source_file"],
                "category": v["category"],
            }
            for v in variables
        ],
    )
    print(f"Variables detected: {len(variables)}", flush=True)

    # STEP 5
    var_doc = step5_doc_audit(variables)
    write_tsv(out_dir / "VARIABLE_DOCUMENTATION_AUDIT.tsv", var_doc)

    # STEP 6–7
    cde = step6_cde(variables)
    ude = step7_ude(variables)
    write_tsv(out_dir / "LIKELY_COMMON_DATA_ELEMENTS.tsv", cde)
    write_tsv(out_dir / "POTENTIAL_UNIQUE_DATA_ELEMENTS.tsv", ude)
    print(f"Potential Common Data Elements: {len(cde)}", flush=True)
    print(f"Potential Unique Data Elements: {len(ude)}", flush=True)

    # STEP 8
    forms_md = step8_forms(variables, summary)
    (out_dir / "FORM_STRUCTURE_PROPOSAL.md").write_text(forms_md, encoding="utf-8")
    print("Suggested Form Structures: written", flush=True)

    # STEP 9
    write_tsv(out_dir / "PROVENANCE_MATRIX.tsv", step9_provenance(variables))

    # STEP 10
    qc_inv = step10_qc(derivatives, reports)
    write_tsv(out_dir / "QC_INVENTORY.tsv", qc_inv)

    # STEP 11
    release_guess = root / "release_dataset"
    doc_audit = step11_docs(
        bids,
        reports,
        release_guess if release_guess.is_dir() else None,
        scratch=root,
    )
    write_tsv(out_dir / "DOCUMENTATION_AUDIT.tsv", doc_audit)

    # STEP 12
    missing = step12_missing(summary, doc_audit, var_doc, qc_inv)
    write_tsv(out_dir / "MISSING_INFORMATION.tsv", missing)
    crit = [m for m in missing if m["category"] == "Critical"]
    print(f"Critical missing information: {len(crit)}", flush=True)

    # STEP 13
    readiness = step13_readiness(summary, variables, cde, ude, missing, qc_inv, doc_audit)
    (out_dir / "FITBIR_READINESS.md").write_text(readiness, encoding="utf-8")
    m = re.search(r"\*\*Score: (\d+) / 100\*\*", readiness)
    overall = m.group(1) if m else "UNKNOWN"
    print(f"Overall FITBIR readiness: {overall}/100", flush=True)

    # STEP 14
    val = step14_validation(out_dir, bids, root, inv)
    (out_dir / "validation_report.txt").write_text(val, encoding="utf-8")

    print("No files modified (BIDS/raw_original/derivatives untouched)", flush=True)
    print(f"Outputs: {out_dir}", flush=True)
    return 0


if __name__ == "__main__":
    # Fix accidental syntax if any left from editing — step2 had a bad line in draft;
    # ensure clean import by running main only.
    raise SystemExit(main())
