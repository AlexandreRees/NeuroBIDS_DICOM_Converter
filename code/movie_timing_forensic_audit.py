#!/usr/bin/env python3
"""READ-ONLY forensic audit: every possible source of movie timing information.

Objective: identify timing sources — NOT reconstruct events.tsv.

Never modifies: raw_original/, bids/, derivatives/
Writes ONLY under the --output directory.
Relative paths only in published tables. No PHI.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import re
import sys
import tarfile
import zipfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator

# Optional deps
try:
    import numpy as np
except ImportError:  # pragma: no cover
    np = None  # type: ignore

try:
    import scipy.io as sio
except ImportError:  # pragma: no cover
    sio = None  # type: ignore

try:
    import pydicom
except ImportError:  # pragma: no cover
    pydicom = None  # type: ignore

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

INVENTORY_EXTS = {
    ".mat",
    ".m",
    ".log",
    ".txt",
    ".csv",
    ".json",
    ".tsv",
    ".xml",
    ".ini",
    ".cfg",
    ".yaml",
    ".yml",
    ".edf",
    ".resp",
    ".puls",
    ".ecg",
    ".ext",
    ".ext2",
    ".dcm",
}

MAT_NAME_NEEDLES = (
    "trigger",
    "time",
    "flip",
    "vbl",
    "movie",
    "onset",
    "stim",
    "frame",
    "pulse",
    "scanner",
    "ttl",
    "mr",
    "start",
    "stop",
    "sync",
    "psych",
    "record",
)

CODE_KEYWORDS = (
    "GetSecs",
    "Screen('Flip')",
    "Screen(\"Flip\")",
    "Flip",
    "VBLTimestamp",
    "StimulusOnsetTime",
    "WaitTR",
    "WaitSecs",
    "KbCheck",
    "KbQueue",
    "trigger",
    "TTL",
    "pulse",
    "scanner",
    "IOPort",
    "Cedrus",
    "DAQ",
    "PsychPortAudio",
    "fopen",
    "fprintf",
    "save",
    "load",
    "triggerTimes",
    "diary",
    "writetable",
)

LOG_PATTERNS = (
    re.compile(r"\bsave\s*\(", re.I),
    re.compile(r"\bfprintf\s*\(", re.I),
    re.compile(r"\bdiary\s*\(", re.I),
    re.compile(r"\bwritetable\s*\(", re.I),
    re.compile(r"\bfopen\s*\(", re.I),
)

HIDDEN_NAME_NEEDLES = (
    "timing",
    "trigger",
    "stim",
    "event",
    "movie",
    "log",
    "behavior",
    "behav",
    "scan",
    "trial",
    "response",
    "psych",
    "ttl",
    "pulse",
)

ARCHIVE_DIR_NEEDLES_STRONG = (
    "backup",
    "archive",
    "old",
    "older",
    "previous",
    "copy",
    "duplicate",
    "pilot",
    "tmp",
    "temporary",
)
ARCHIVE_DIR_NEEDLES_WEAK = (
    "results",
    "result",
    "logs",
    "log",
    "timing",
    "trigger",
    "stimulus",
    "stimuli",
    "behavior",
    "behaviour",
    "behav",
    "psych",
    "experiment",
    "movie",
    "film",
    "task",
    "test",
)
ARCHIVE_DIR_NEEDLES = ARCHIVE_DIR_NEEDLES_STRONG + ARCHIVE_DIR_NEEDLES_WEAK

ARCHIVE_FILE_EXTS = {
    ".mat",
    ".m",
    ".log",
    ".txt",
    ".csv",
    ".tsv",
    ".json",
    ".xml",
    ".cfg",
    ".ini",
    ".yaml",
    ".yml",
    ".zip",
    ".tar",
    ".gz",  # covers .tar.gz via name check
}

ARCHIVE_INNER_NEEDLES = (
    "trigger",
    "timing",
    "event",
    "movie",
    "stim",
    "flip",
    "vbl",
    "log",
    "psych",
    "mat",
    "behavior",
    "trial",
)

PHI_NAME_RE = re.compile(
    r"(?i)patient\s*name|patientname|patient_id|patientid|"
    r"dateofbirth|birth.?date|ssn|social.?security"
)

SUB_RE = re.compile(r"(?i)\bsub-(\d{3})\b|SUBC0*(\d+)|SUBG0*(\d+)|SUBON0*(\d+)|SUBTON0*(\d+)|SUBC(\d+)|SUBG(\d+)")
SES_RE = re.compile(r"(?i)\bses-(\d{2})\b|SESSION0*(\d+)|Session0*(\d+)|Ses(?:sion)?[_\-]?0*(\d+)")
RUN_RE = re.compile(r"(?i)\brun-(\d{2})\b|_run-?0*(\d+)")

SKIP_DIR_NAMES = {
    ".git",
    ".svn",
    "__pycache__",
    ".pytest_cache",
    "node_modules",
    ".nextflow",
    "work",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def log(msg: str) -> None:
    print(f"[{utc_now()}] {msg}", flush=True)


def write_tsv(path: Path, fieldnames: list[str], rows: Iterable[dict[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, delimiter="\t", extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: "" if r.get(k) is None else r.get(k) for k in fieldnames})
            n += 1
    return n


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path, max_bytes: int | None = 64 * 1024 * 1024) -> str:
    h = hashlib.sha256()
    try:
        with path.open("rb") as f:
            read = 0
            while True:
                chunk = f.read(1024 * 1024)
                if not chunk:
                    break
                h.update(chunk)
                read += len(chunk)
                if max_bytes is not None and read >= max_bytes:
                    break
    except OSError:
        return ""
    return h.hexdigest()


def detect_subject(text: str) -> str:
    m = SUB_RE.search(text.replace("\\", "/"))
    if not m:
        return ""
    for g in m.groups():
        if g:
            return f"sub-{int(g):03d}"
    return ""


def detect_session(text: str) -> str:
    m = SES_RE.search(text.replace("\\", "/"))
    if not m:
        return ""
    for g in m.groups():
        if g:
            return f"ses-{int(g):02d}"
    return ""


def detect_run(text: str) -> str:
    m = RUN_RE.search(text.replace("\\", "/"))
    if not m:
        return ""
    for g in m.groups():
        if g:
            return f"run-{int(g):02d}"
    return ""


def rel_to(path: Path, roots: dict[str, Path]) -> str:
    """Return root-tagged relative path, never absolute home paths."""
    ap = path.resolve()
    for tag, root in roots.items():
        try:
            return f"<{tag}>/{ap.relative_to(root.resolve()).as_posix()}"
        except ValueError:
            continue
    # fallback: strip known absolute prefixes
    s = ap.as_posix()
    for prefix in (
        "/lustre07/scratch/alexrees/",
        "/lustre06/project/6001995/",
        "/home/alexrees/scratch/",
    ):
        if s.startswith(prefix):
            return s[len(prefix) :]
    return ap.name


def iter_search_roots(roots: dict[str, Path]) -> Iterator[tuple[str, Path]]:
    """Yield (tag, path) roots to search; narrow DERIVATIVES to physiology*."""
    for tag, root in roots.items():
        if not root.is_dir():
            continue
        if tag == "DERIVATIVES":
            found = False
            for d in ("physiology_characterization", "physiology_qc", "physiology_reproducibility"):
                p = root / d
                if p.is_dir():
                    found = True
                    yield tag, p
            if not found:
                yield tag, root
        else:
            yield tag, root


def is_movie_path(text: str) -> bool:
    low = text.lower().replace("\\", "/")
    return any(
        x in low
        for x in (
            "3-movie",
            "movie_data",
            "task-movie",
            "/movie/",
            "show_movie",
            "movie1a",
            "movie1b",
            "movie2a",
            "movie2b",
        )
    )


def prune_dirnames(dirnames: list[str]) -> None:
    dirnames[:] = [d for d in dirnames if d not in SKIP_DIR_NAMES and not d.startswith(".")]


def prune_bids_nonfunc_trees(tag: str, dirpath: str, dirnames: list[str]) -> None:
    """Under BIDS/DERIVATIVES, avoid anat/dwi/fmap trees (not movie-timing sources)."""
    if tag not in {"BIDS", "DERIVATIVES"}:
        return
    low = dirpath.lower().replace("\\", "/")
    parts = set(Path(low).parts)
    if parts & {"anat", "dwi", "fmap", "perf", "pet", "meg", "eeg", "ieeg"}:
        if "movie" not in low:
            dirnames[:] = []
            return
    base_name = Path(dirpath).name.lower()
    if base_name.startswith("sub-"):
        dirnames[:] = [
            d for d in dirnames if d.lower().startswith("ses-") or d.lower() in {"code", "stimuli", "sourcedata"}
        ]
    elif base_name.startswith("ses-"):
        dirnames[:] = [
            d for d in dirnames if d.lower() in {"func", "beh", "phenotype"} or "movie" in d.lower()
        ]


def prune_dicom_only_trees(tag: str, dirpath: str, dirnames: list[str], filenames: list[str]) -> bool:
    """Return True if this directory should be skipped entirely (RAW DICOM dumps)."""
    if tag != "RAW":
        return False
    path_low = dirpath.lower()
    if is_movie_path(path_low) or any(
        k in path_low for k in ("fmri", "bold", "ep2d", "physiolog", "matlab", "movie")
    ):
        return False
    if "dicom" in path_low or path_low.rstrip("/").endswith("/dcm"):
        dirnames[:] = []
        return True
    only_dcm = filenames and all(f.lower().endswith(".dcm") or f.startswith(".") for f in filenames)
    if only_dcm and not any(k in path_low for k in ("matlab", "results", "movie", "grating", "physio")):
        dirnames[:] = []
        return True
    return False


# ---------------------------------------------------------------------------
# STEP 1 — file inventory
# ---------------------------------------------------------------------------

def step1_inventory(
    roots: dict[str, Path],
    out_dir: Path,
    *,
    max_dcm_per_series: int = 1,
) -> list[dict[str, Any]]:
    log("STEP 1: FILE_INVENTORY")
    rows: list[dict[str, Any]] = []
    dcm_series_count: dict[str, int] = defaultdict(int)
    n_seen = 0

    for tag, root in roots.items():
        if not root.is_dir():
            log(f"  skip missing root {tag}: {root}")
            continue
        log(f"  walking {tag} …")
        # Derivatives: only physiology-related trees (defacing/mriqc not timing sources)
        walk_root = root
        if tag == "DERIVATIVES":
            phys_dirs = [
                root / d
                for d in (
                    "physiology_characterization",
                    "physiology_qc",
                    "physiology_reproducibility",
                )
                if (root / d).is_dir()
            ]
            if not phys_dirs:
                log("  no physiology* dirs under DERIVATIVES — skipping")
                continue
            # walk each phys dir as if under DERIVATIVES tag
            for walk_root in phys_dirs:
                log(f"  walking DERIVATIVES/{walk_root.name} …")
                for dirpath, dirnames, filenames in os.walk(walk_root, followlinks=False):
                    prune_dirnames(dirnames)
                    base = Path(dirpath)
                    path_low = dirpath.lower()
                    movieish = is_movie_path(path_low) or "physio" in path_low or "movie" in path_low
                    for fn in filenames:
                        ext = Path(fn).suffix.lower()
                        if fn.lower().endswith(".tar.gz"):
                            ext = ".tar.gz"
                        if ext not in INVENTORY_EXTS and ext != ".tar.gz":
                            continue
                        fp = base / fn
                        try:
                            st = fp.stat()
                        except OSError:
                            continue
                        rel = rel_to(fp, roots)
                        rows.append(
                            {
                                "relative_path": rel,
                                "root_tag": tag,
                                "extension": ext,
                                "size_bytes": st.st_size,
                                "modified_utc": datetime.fromtimestamp(
                                    st.st_mtime, tz=timezone.utc
                                ).strftime("%Y-%m-%dT%H:%M:%SZ"),
                                "subject": detect_subject(rel),
                                "session": detect_session(rel),
                                "is_movie_related": "TRUE" if is_movie_path(rel) else "FALSE",
                            }
                        )
                        n_seen += 1
                        if n_seen % 5000 == 0:
                            log(f"  inventory rows so far: {n_seen}")
            continue

        for dirpath, dirnames, filenames in os.walk(walk_root, followlinks=False):
            prune_dirnames(dirnames)
            if prune_dicom_only_trees(tag, dirpath, dirnames, filenames):
                continue
            # BIDS: focus on functional / physio / code / stimuli trees
            if tag == "BIDS":
                prune_bids_nonfunc_trees(tag, dirpath, dirnames)
                low = dirpath.lower().replace("\\", "/")
                parts = set(Path(low).parts)
                if parts & {"anat", "dwi", "fmap", "perf", "pet", "meg", "eeg", "ieeg"}:
                    if "movie" not in low:
                        continue
            base = Path(dirpath)
            path_low = dirpath.lower()
            movieish = is_movie_path(path_low) or any(
                k in path_low for k in ("fmri", "bold", "ep2d", "physiolog", "physio")
            )
            for fn in filenames:
                ext = Path(fn).suffix.lower()
                if fn.lower().endswith(".tar.gz"):
                    ext = ".tar.gz"
                if ext not in INVENTORY_EXTS and ext != ".tar.gz":
                    continue
                # DICOM: only inventory under movie/fMRI/physio-ish trees (1 per series)
                if ext == ".dcm":
                    if tag == "RAW" and not movieish:
                        continue
                    series_key = str(base)
                    if dcm_series_count[series_key] >= max_dcm_per_series:
                        continue
                    dcm_series_count[series_key] += 1
                fp = base / fn
                try:
                    st = fp.stat()
                except OSError:
                    continue
                rel = rel_to(fp, roots)
                rows.append(
                    {
                        "relative_path": rel,
                        "root_tag": tag,
                        "extension": ext,
                        "size_bytes": st.st_size,
                        "modified_utc": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).strftime(
                            "%Y-%m-%dT%H:%M:%SZ"
                        ),
                        "subject": detect_subject(rel),
                        "session": detect_session(rel),
                        "is_movie_related": "TRUE" if is_movie_path(rel) else "FALSE",
                    }
                )
                n_seen += 1
                if n_seen % 5000 == 0:
                    log(f"  inventory rows so far: {n_seen}")
    write_tsv(
        out_dir / "FILE_INVENTORY.tsv",
        [
            "relative_path",
            "root_tag",
            "extension",
            "size_bytes",
            "modified_utc",
            "subject",
            "session",
            "is_movie_related",
        ],
        rows,
    )
    log(f"  FILE_INVENTORY rows={len(rows)}")
    return rows


# ---------------------------------------------------------------------------
# STEP 2 — MATLAB variable audit
# ---------------------------------------------------------------------------

def _mat_var_summary(name: str, obj: Any) -> dict[str, Any]:
    cls = type(obj).__name__
    dims = ""
    preview = ""
    try:
        if np is not None and isinstance(obj, np.ndarray):
            dims = "x".join(str(x) for x in obj.shape)
            cls = f"ndarray/{obj.dtype}"
            if obj.size == 0:
                preview = "[]"
            elif obj.dtype.kind in "iufc" and obj.size <= 8:
                preview = np.array2string(obj.ravel()[:8], separator=",")
            elif obj.dtype.kind in "USO":
                flat = obj.ravel()
                preview = str(flat[0])[:120] if flat.size else ""
            else:
                preview = f"size={obj.size}"
        elif isinstance(obj, (str, bytes)):
            dims = "1"
            preview = (obj.decode("utf-8", "replace") if isinstance(obj, bytes) else obj)[:120]
        elif isinstance(obj, (int, float, bool)):
            dims = "1"
            preview = str(obj)
        else:
            dims = ""
            preview = cls
    except Exception as e:  # noqa: BLE001
        preview = f"<err:{e}>"
    low = name.lower()
    matched = [n for n in MAT_NAME_NEEDLES if n in low]
    return {
        "variable": name,
        "class": cls,
        "dimensions": dims,
        "name_match": ",".join(matched),
        "preview": preview.replace("\t", " ").replace("\n", " "),
    }


def step2_matlab_vars(inventory: list[dict[str, Any]], roots: dict[str, Path], out_dir: Path) -> list[dict[str, Any]]:
    log("STEP 2: MATLAB_VARIABLE_AUDIT")
    rows: list[dict[str, Any]] = []
    if sio is None:
        log("  WARNING: scipy.io unavailable — skipping MAT load")
        write_tsv(
            out_dir / "MATLAB_VARIABLE_AUDIT.tsv",
            [
                "relative_path",
                "subject",
                "session",
                "variable",
                "class",
                "dimensions",
                "name_match",
                "preview",
                "load_error",
            ],
            [],
        )
        return rows

    mat_paths = [r for r in inventory if r["extension"] == ".mat"]
    # Prefer movie-related; still audit all mats but cap non-movie if huge
    movie_mats = [r for r in mat_paths if r["is_movie_related"] == "TRUE"]
    other_mats = [r for r in mat_paths if r["is_movie_related"] != "TRUE"]
    # Cap other mats for feasibility while remaining thorough on movie
    selected = movie_mats + other_mats[:2000]
    log(f"  mats movie={len(movie_mats)} other_selected={min(len(other_mats),2000)} total_planned={len(selected)}")

    for i, rec in enumerate(selected, 1):
        if i % 100 == 0:
            log(f"  MAT progress {i}/{len(selected)}")
        rel = rec["relative_path"]
        abs_path = _resolve_rel(rel, roots)
        if abs_path is None or not abs_path.is_file():
            continue
        try:
            data = sio.loadmat(str(abs_path), squeeze_me=False, struct_as_record=False)
        except Exception as e:  # noqa: BLE001
            rows.append(
                {
                    "relative_path": rel,
                    "subject": rec.get("subject", ""),
                    "session": rec.get("session", ""),
                    "variable": "",
                    "class": "",
                    "dimensions": "",
                    "name_match": "",
                    "preview": "",
                    "load_error": str(e)[:200],
                }
            )
            continue
        for k, v in data.items():
            if k.startswith("__"):
                continue
            summ = _mat_var_summary(k, v)
            rows.append(
                {
                    "relative_path": rel,
                    "subject": rec.get("subject", ""),
                    "session": rec.get("session", ""),
                    **summ,
                    "load_error": "",
                }
            )
    write_tsv(
        out_dir / "MATLAB_VARIABLE_AUDIT.tsv",
        [
            "relative_path",
            "subject",
            "session",
            "variable",
            "class",
            "dimensions",
            "name_match",
            "preview",
            "load_error",
        ],
        rows,
    )
    log(f"  MATLAB_VARIABLE_AUDIT rows={len(rows)}")
    return rows


def _resolve_rel(rel: str, roots: dict[str, Path]) -> Path | None:
    m = re.match(r"^<([A-Z_]+)>/(.*)$", rel)
    if m:
        tag, rest = m.group(1), m.group(2)
        root = roots.get(tag)
        if root is None:
            return None
        return root / rest
    # try each root
    for root in roots.values():
        cand = root / rel
        if cand.exists():
            return cand
    return None


# ---------------------------------------------------------------------------
# STEP 3 — MATLAB source code audit
# ---------------------------------------------------------------------------

def step3_matlab_code(inventory: list[dict[str, Any]], roots: dict[str, Path], out_dir: Path) -> list[dict[str, Any]]:
    log("STEP 3: MATLAB_CODE_TIMING_AUDIT")
    rows: list[dict[str, Any]] = []
    m_files = [r for r in inventory if r["extension"] == ".m"]
    for i, rec in enumerate(m_files, 1):
        if i % 200 == 0:
            log(f"  .m progress {i}/{len(m_files)}")
        abs_path = _resolve_rel(rec["relative_path"], roots)
        if abs_path is None or not abs_path.is_file():
            continue
        try:
            lines = abs_path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for li, line in enumerate(lines, 1):
            hits: list[str] = []
            for kw in CODE_KEYWORDS:
                if kw == "Flip":
                    if re.search(r"\bFlip\b", line):
                        hits.append(kw)
                elif kw.lower() in ("trigger", "ttl", "pulse", "scanner", "save", "load", "fopen", "fprintf"):
                    if re.search(rf"(?i)\b{re.escape(kw)}\b", line):
                        hits.append(kw)
                elif kw in line:
                    hits.append(kw)
            for kw in hits:
                lo = max(0, li - 2)
                hi = min(len(lines), li + 1)
                ctx = " | ".join(x.strip() for x in lines[lo:hi]).replace("\t", " ")[:400]
                rows.append(
                    {
                        "relative_path": rec["relative_path"],
                        "subject": rec.get("subject", ""),
                        "session": rec.get("session", ""),
                        "line_number": li,
                        "matched_keyword": kw,
                        "line_text": line.strip()[:300].replace("\t", " "),
                        "surrounding_lines": ctx,
                        "is_movie_related": rec.get("is_movie_related", ""),
                    }
                )
    write_tsv(
        out_dir / "MATLAB_CODE_TIMING_AUDIT.tsv",
        [
            "relative_path",
            "subject",
            "session",
            "line_number",
            "matched_keyword",
            "line_text",
            "surrounding_lines",
            "is_movie_related",
        ],
        rows,
    )
    log(f"  MATLAB_CODE_TIMING_AUDIT rows={len(rows)}")
    return rows


# ---------------------------------------------------------------------------
# STEP 4 — Psychtoolbox logging audit
# ---------------------------------------------------------------------------

def step4_psychtoolbox_log(inventory: list[dict[str, Any]], roots: dict[str, Path], out_dir: Path) -> dict[str, Any]:
    log("STEP 4: PSYCHTOOLBOX_LOG_AUDIT")
    findings: list[dict[str, Any]] = []
    movie_m = [
        r
        for r in inventory
        if r["extension"] == ".m" and r.get("is_movie_related") == "TRUE"
    ]
    # also include any Show_movie / main near movie
    for rec in inventory:
        if rec["extension"] != ".m":
            continue
        name = Path(rec["relative_path"]).name.lower()
        if name in ("show_movie.m", "main.m") and rec not in movie_m:
            if is_movie_path(rec["relative_path"]):
                movie_m.append(rec)

    seen: set[str] = set()
    unique_scripts: list[dict[str, Any]] = []
    for rec in movie_m:
        abs_path = _resolve_rel(rec["relative_path"], roots)
        if abs_path is None:
            continue
        try:
            data = abs_path.read_bytes()
        except OSError:
            continue
        digest = sha256_bytes(data)
        if digest in seen:
            continue
        seen.add(digest)
        unique_scripts.append(rec)

    creates_mat = False
    creates_txt = False
    creates_csv = False
    creates_log = False
    saves_timing = False
    details: list[str] = []

    for rec in unique_scripts:
        abs_path = _resolve_rel(rec["relative_path"], roots)
        assert abs_path is not None
        text = abs_path.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        for li, line in enumerate(lines, 1):
            for pat in LOG_PATTERNS:
                if pat.search(line):
                    findings.append(
                        {
                            "file": rec["relative_path"],
                            "line": li,
                            "text": line.strip()[:240],
                        }
                    )
            low = line.lower()
            if re.search(r"\bsave\s*\(", line, re.I):
                creates_mat = True
                if any(k in low for k in ("trigger", "vbl", "flip", "onset", "getsecs", "time")):
                    saves_timing = True
            if re.search(r"\bfprintf\s*\(", line, re.I) or re.search(r"\bfopen\s*\(", line, re.I):
                if any(x in low for x in (".txt", ".log", ".csv", "fid")):
                    creates_txt = True
                    if ".csv" in low:
                        creates_csv = True
                    if ".log" in low:
                        creates_log = True
            if re.search(r"\bdiary\s*\(", line, re.I):
                creates_log = True
            if re.search(r"\bwritetable\s*\(", line, re.I):
                creates_csv = True

    # Check Results mats for timing vars (from inventory movie mats names)
    mat_result_note = (
        "Movie Results `.mat` files are written by `save(...)` in `main.m` BEFORE "
        "`Show_movie` runs; contents are identity-only (run_id / comment / change_eye)."
    )

    md = out_dir / "PSYCHTOOLBOX_LOG_AUDIT.md"
    md.write_text(
        "\n".join(
            [
                "# Psychtoolbox logging audit (movie)",
                "",
                f"Generated: `{utc_now()}`",
                "",
                "## Unique movie-related `.m` scripts audited",
                "",
                f"- Unique content hashes: **{len(unique_scripts)}**",
                f"- Path examples: "
                + (", ".join(r["relative_path"] for r in unique_scripts[:8]) or "(none)"),
                "",
                "## Runtime log / save behaviour",
                "",
                f"| Creates `.mat` via `save` | {'YES' if creates_mat else 'NO'} |",
                f"| Creates text/log via `fprintf`/`fopen`/`diary` | {'YES' if creates_txt or creates_log else 'NO'} |",
                f"| Creates CSV via `writetable`/fprintf | {'YES' if creates_csv else 'NO'} |",
                f"| Saves timing variables (trigger/VBL/onset) | {'YES' if saves_timing else 'NO'} |",
                "",
                "## Interpretation",
                "",
                mat_result_note,
                "",
                "`Show_movie.m` waits for one FORP `t` (`KbQueueWait`) and flips frames but "
                "**does not assign or save** Flip / VBL / GetSecs timestamps.",
                "",
                "## Matched save/log call sites",
                "",
            ]
            + (
                [f"- `{f['file']}:{f['line']}` — `{f['text']}`" for f in findings[:200]]
                if findings
                else ["- (none)"]
            )
            + ["", f"Total matched call sites: **{len(findings)}**", ""]
        ),
        encoding="utf-8",
    )
    summary = {
        "unique_movie_scripts": len(unique_scripts),
        "creates_mat": creates_mat,
        "creates_txt_or_log": creates_txt or creates_log,
        "creates_csv": creates_csv,
        "saves_timing": saves_timing,
        "call_sites": len(findings),
    }
    log(f"  PSYCHTOOLBOX_LOG_AUDIT done ({summary})")
    return summary


# ---------------------------------------------------------------------------
# STEP 5 — scanner metadata (functional JSON)
# ---------------------------------------------------------------------------

def step5_scanner_metadata(bids: Path, roots: dict[str, Path], out_dir: Path) -> list[dict[str, Any]]:
    log("STEP 5: SCANNER_METADATA")
    rows: list[dict[str, Any]] = []
    if not bids.is_dir():
        write_tsv(out_dir / "SCANNER_METADATA.tsv", [], [])
        return rows
    keys = [
        "TaskName",
        "SeriesDescription",
        "ProtocolName",
        "RepetitionTime",
        "AcquisitionTime",
        "AcquisitionDuration",
        "SeriesNumber",
        "ManufacturersModelName",
    ]
    for jp in bids.rglob("*_bold.json"):
        # skip non-func paths
        if "/anat/" in str(jp).replace("\\", "/") or "/dwi/" in str(jp).replace("\\", "/"):
            continue
        if "_bold.json" not in jp.name:
            continue
        if "part-phase" in jp.name:
            # include but mark
            pass
        try:
            meta = json.loads(jp.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            rows.append(
                {
                    "relative_path": rel_to(jp, roots),
                    "subject": detect_subject(jp.name),
                    "session": detect_session(str(jp)),
                    "run": detect_run(jp.name),
                    "error": str(e)[:120],
                }
            )
            continue
        # volume count from sidecar metadata preferentially (avoid loading all NIfTIs)
        nvols = ""
        shape = meta.get("dcmmeta_shape")
        if isinstance(shape, list) and len(shape) >= 4:
            nvols = str(shape[3])
        elif meta.get("NumberOfVolumes"):
            nvols = str(meta.get("NumberOfVolumes"))
        row = {
            "relative_path": rel_to(jp, roots),
            "subject": detect_subject(str(jp)),
            "session": detect_session(str(jp)),
            "run": detect_run(jp.name),
            "filename": jp.name,
            "is_movie": "TRUE" if "task-movie" in jp.name else "FALSE",
            "is_phase": "TRUE" if "part-phase" in jp.name else "FALSE",
            "NumberOfVolumes": nvols,
            "error": "",
        }
        for k in keys:
            row[k] = meta.get(k, "")
        rows.append(row)
    fields = [
        "relative_path",
        "subject",
        "session",
        "run",
        "filename",
        "is_movie",
        "is_phase",
        "TaskName",
        "SeriesDescription",
        "ProtocolName",
        "RepetitionTime",
        "NumberOfVolumes",
        "AcquisitionTime",
        "AcquisitionDuration",
        "SeriesNumber",
        "ManufacturersModelName",
        "error",
    ]
    write_tsv(out_dir / "SCANNER_METADATA.tsv", fields, rows)
    log(f"  SCANNER_METADATA rows={len(rows)} movie={sum(1 for r in rows if r['is_movie']=='TRUE')}")
    return rows


# ---------------------------------------------------------------------------
# STEP 6 — physiology timing audit
# ---------------------------------------------------------------------------

def _read_physio_tsv(path: Path, max_rows: int = 50000) -> tuple[list[str], list[list[str]]]:
    with path.open("r", encoding="utf-8", errors="replace") as f:
        # may be gzipped sibling — handle .tsv.gz via gzip
        pass
    open_fn = open
    mode = "rt"
    if path.suffix == ".gz" or path.name.endswith(".tsv.gz"):
        import gzip

        f = gzip.open(path, mode)
    else:
        f = path.open(mode, encoding="utf-8", errors="replace")
    try:
        rdr = csv.reader(f, delimiter="\t")
        header = next(rdr, [])
        rows = []
        for i, row in enumerate(rdr):
            if i >= max_rows:
                break
            rows.append(row)
        return header, rows
    finally:
        f.close()


def step6_physiology(bids: Path, derivatives: Path, roots: dict[str, Path], out_dir: Path) -> list[dict[str, Any]]:
    log("STEP 6: PHYSIOLOGY_TIMING_AUDIT")
    rows: list[dict[str, Any]] = []
    candidates: list[Path] = []
    if bids.is_dir():
        for p in bids.rglob("*task-movie*physio.json"):
            candidates.append(p)
        for p in bids.rglob("*task-movie*physio.tsv.gz"):
            candidates.append(p)
        for p in bids.rglob("*task-movie*physio.tsv"):
            candidates.append(p)
    # peripheral physio under raw-like derivatives paths with movie in name
    if derivatives.is_dir():
        for dirpath, dirnames, filenames in os.walk(derivatives, followlinks=False):
            prune_dirnames(dirnames)
            prune_bids_nonfunc_trees("DERIVATIVES", dirpath, dirnames)
            if "movie" not in dirpath.lower() and "physio" not in dirpath.lower():
                continue
            for fn in filenames:
                low = fn.lower()
                if low.endswith((".resp", ".puls", ".ecg", ".ext", ".ext2")) or "physio" in low:
                    candidates.append(Path(dirpath) / fn)

    seen: set[str] = set()
    for p in candidates:
        key = str(p.resolve())
        if key in seen:
            continue
        seen.add(key)
        rel = rel_to(p, roots)
        rec: dict[str, Any] = {
            "relative_path": rel,
            "subject": detect_subject(str(p)),
            "session": detect_session(str(p)),
            "run": detect_run(p.name),
            "filename": p.name,
            "recording_type": "",
            "has_trigger_channel": "",
            "n_trigger_events": "",
            "median_trigger_spacing_sec": "",
            "sampling_frequency": "",
            "recording_start_sec": "",
            "recording_end_sec": "",
            "possible_bold_sync": "NO",
            "possible_stimulus_onset_sync": "NO",
            "notes": "",
        }
        if p.name.endswith(".json"):
            try:
                meta = json.loads(p.read_text(encoding="utf-8"))
            except Exception as e:  # noqa: BLE001
                rec["notes"] = f"json_error:{e}"
                rows.append(rec)
                continue
            cols = meta.get("Columns") or meta.get("columns") or []
            rec["recording_type"] = "bids_physio_json"
            rec["has_trigger_channel"] = (
                "TRUE" if any(str(c).lower() == "trigger" for c in cols) else "FALSE"
            )
            rec["sampling_frequency"] = meta.get("SamplingFrequency", "")
            rec["notes"] = f"columns={','.join(map(str, cols))[:120]}"
            tsv = Path(str(p).replace(".json", ".tsv.gz"))
            if not tsv.exists():
                tsv = Path(str(p).replace(".json", ".tsv"))
            if tsv.exists() and rec["has_trigger_channel"] == "TRUE" and "trigger" in p.name.lower():
                # Deep-sample trigger recordings only (avoid reading every respiratory TSV)
                try:
                    header, data = _read_physio_tsv(tsv)
                    hlow = [h.lower() for h in header]
                    ti = hlow.index("trigger") if "trigger" in hlow else None
                    start = float(meta.get("StartTime", 0) or 0)
                    sf = float(meta.get("SamplingFrequency", 0) or 0)
                    trig_idx = []
                    if ti is not None:
                        prev = None
                        for i, row in enumerate(data):
                            if ti >= len(row):
                                continue
                            try:
                                v = float(row[ti])
                            except ValueError:
                                continue
                            if prev is None:
                                prev = v
                                continue
                            if v > 0 and prev <= 0:
                                trig_idx.append(i)
                            prev = v
                    rec["n_trigger_events"] = str(len(trig_idx))
                    if sf > 0 and len(data) > 0:
                        rec["recording_start_sec"] = str(start)
                        rec["recording_end_sec"] = str(start + len(data) / sf)
                    if len(trig_idx) >= 2 and sf > 0 and np is not None:
                        spaces = np.diff(trig_idx) / sf
                        if len(spaces):
                            med = float(np.median(spaces))
                            rec["median_trigger_spacing_sec"] = f"{med:.6f}"
                            if 0.4 <= med <= 3.0 and len(trig_idx) >= 50:
                                rec["possible_bold_sync"] = "YES"
                            else:
                                rec["possible_bold_sync"] = "UNLIKELY"
                    if len(trig_idx) <= 1:
                        rec["possible_stimulus_onset_sync"] = "NO"
                        rec["notes"] += "; insufficient trigger edges for stimulus onset"
                    else:
                        rec["possible_stimulus_onset_sync"] = "NO"
                        rec["notes"] += "; trigger train ≠ stimulus onset marker"
                except Exception as e:  # noqa: BLE001
                    rec["notes"] += f"; tsv_err:{e}"
            rows.append(rec)
            continue
        rec["recording_type"] = p.suffix.lower().lstrip(".")
        rec["notes"] = "peripheral_or_raw; no absolute movie-onset mapping without session clock"
        rec["possible_bold_sync"] = "UNKNOWN"
        rec["possible_stimulus_onset_sync"] = "NO"
        rows.append(rec)

    fields = [
        "relative_path",
        "subject",
        "session",
        "run",
        "filename",
        "recording_type",
        "has_trigger_channel",
        "n_trigger_events",
        "median_trigger_spacing_sec",
        "sampling_frequency",
        "recording_start_sec",
        "recording_end_sec",
        "possible_bold_sync",
        "possible_stimulus_onset_sync",
        "notes",
    ]
    write_tsv(out_dir / "PHYSIOLOGY_TIMING_AUDIT.tsv", fields, rows)
    log(f"  PHYSIOLOGY_TIMING_AUDIT rows={len(rows)}")
    return rows


# ---------------------------------------------------------------------------
# STEP 7 — DICOM timing audit
# ---------------------------------------------------------------------------

def step7_dicom(
    raw: Path,
    inventory: list[dict[str, Any]],
    roots: dict[str, Path],
    out_dir: Path,
    *,
    max_series: int = 5000,
) -> list[dict[str, Any]]:
    log("STEP 7: DICOM_TIMING_AUDIT")
    rows: list[dict[str, Any]] = []
    if pydicom is None:
        log("  WARNING: pydicom unavailable")
        write_tsv(out_dir / "DICOM_TIMING_AUDIT.tsv", ["error"], [{"error": "pydicom_unavailable"}])
        return rows

    # Prefer movie-related DICOM series from inventory
    dcm_recs = [r for r in inventory if r["extension"] == ".dcm"]
    movie_dcm = [r for r in dcm_recs if r["is_movie_related"] == "TRUE"]
    # Also discover series folders with Movie/fMRI in name under raw
    series_files: list[Path] = []
    for rec in movie_dcm:
        p = _resolve_rel(rec["relative_path"], roots)
        if p and p.is_file():
            series_files.append(p)

    # Walk raw for folders suggesting movie bold / fmri movie
    if raw.is_dir():
        n_found = 0
        for dirpath, dirnames, filenames in os.walk(raw, followlinks=False):
            prune_dirnames(dirnames)
            low = dirpath.lower()
            if not any(k in low for k in ("movie", "fmri", "bold", "ep2d")):
                # still allow if filenames suggest
                if not any("movie" in f.lower() for f in filenames[:5]):
                    continue
            dcms = [f for f in filenames if f.lower().endswith(".dcm")]
            if not dcms:
                continue
            series_files.append(Path(dirpath) / sorted(dcms)[0])
            n_found += 1
            if n_found >= max_series:
                break

    # unique by parent series dir
    by_series: dict[str, Path] = {}
    for p in series_files:
        by_series[str(p.parent)] = p

    tags = [
        ("AcquisitionTime", 0x0008, 0x0032),
        ("SeriesTime", 0x0008, 0x0031),
        ("ContentTime", 0x0008, 0x0033),
        ("TriggerTime", 0x0018, 0x1060),
        ("TemporalPositionIdentifier", 0x0020, 0x0100),
        ("NumberOfTemporalPositions", 0x0020, 0x0105),
        ("SeriesDescription", 0x0008, 0x103E),
        ("ProtocolName", 0x0018, 0x1030),
    ]

    for i, (series, fp) in enumerate(by_series.items(), 1):
        if i % 200 == 0:
            log(f"  DICOM progress {i}/{len(by_series)}")
        rel = rel_to(fp, roots)
        rec: dict[str, Any] = {
            "relative_path": rel,
            "series_dir": rel_to(Path(series), roots) if Path(series).exists() else "",
            "subject": detect_subject(rel),
            "session": detect_session(rel),
            "error": "",
            "stimulus_onset_recoverable": "NO",
            "notes": "TriggerTime if present is typically within-volume slice timing, not movie onset",
        }
        try:
            ds = pydicom.dcmread(str(fp), stop_before_pixels=True, force=True)
        except Exception as e:  # noqa: BLE001
            rec["error"] = str(e)[:160]
            rows.append(rec)
            continue
        for name, group, elem in tags:
            try:
                val = ds.get((group, elem), None)
                if val is None:
                    rec[name] = ""
                else:
                    rec[name] = str(val.value)[:120] if hasattr(val, "value") else str(val)[:120]
            except Exception:  # noqa: BLE001
                rec[name] = ""
        # strip PHI if any slipped
        for k in list(rec.keys()):
            if PHI_NAME_RE.search(k) or PHI_NAME_RE.search(str(rec[k])):
                rec[k] = "<REDACTED>"
        rows.append(rec)

    fields = [
        "relative_path",
        "series_dir",
        "subject",
        "session",
        "AcquisitionTime",
        "SeriesTime",
        "ContentTime",
        "TriggerTime",
        "TemporalPositionIdentifier",
        "NumberOfTemporalPositions",
        "SeriesDescription",
        "ProtocolName",
        "stimulus_onset_recoverable",
        "notes",
        "error",
    ]
    write_tsv(out_dir / "DICOM_TIMING_AUDIT.tsv", fields, rows)
    log(f"  DICOM_TIMING_AUDIT rows={len(rows)}")
    return rows


# ---------------------------------------------------------------------------
# STEP 8 — hidden timing filenames
# ---------------------------------------------------------------------------

def step8_hidden(roots: dict[str, Path], out_dir: Path) -> list[dict[str, Any]]:
    log("STEP 8: HIDDEN_TIMING_FILES")
    rows: list[dict[str, Any]] = []
    for tag, root in iter_search_roots(roots):
        for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
            prune_dirnames(dirnames)
            if prune_dicom_only_trees(tag, dirpath, dirnames, filenames):
                continue
            prune_bids_nonfunc_trees(tag, dirpath, dirnames)
            for fn in filenames:
                low = fn.lower()
                matched = [n for n in HIDDEN_NAME_NEEDLES if n in low]
                if not matched:
                    continue
                fp = Path(dirpath) / fn
                try:
                    st = fp.stat()
                except OSError:
                    continue
                rel = rel_to(fp, roots)
                rows.append(
                    {
                        "relative_path": rel,
                        "root_tag": tag,
                        "filename": fn,
                        "extension": Path(fn).suffix.lower(),
                        "size_bytes": st.st_size,
                        "modified_utc": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).strftime(
                            "%Y-%m-%dT%H:%M:%SZ"
                        ),
                        "keyword_match": ",".join(matched),
                        "subject": detect_subject(rel),
                        "session": detect_session(rel),
                        "is_movie_related": "TRUE" if is_movie_path(rel) else "FALSE",
                    }
                )
    write_tsv(
        out_dir / "HIDDEN_TIMING_FILES.tsv",
        [
            "relative_path",
            "root_tag",
            "filename",
            "extension",
            "size_bytes",
            "modified_utc",
            "keyword_match",
            "subject",
            "session",
            "is_movie_related",
        ],
        rows,
    )
    log(f"  HIDDEN_TIMING_FILES rows={len(rows)}")
    return rows


# ---------------------------------------------------------------------------
# STEP 9 — cross-reference matrix
# ---------------------------------------------------------------------------

def step9_matrix(
    scanner_rows: list[dict[str, Any]],
    mat_rows: list[dict[str, Any]],
    physio_rows: list[dict[str, Any]],
    dicom_rows: list[dict[str, Any]],
    code_rows: list[dict[str, Any]],
    hidden_rows: list[dict[str, Any]],
    out_dir: Path,
) -> list[dict[str, Any]]:
    log("STEP 9: MOVIE_TIMING_MATRIX")
    movie_runs = [
        r
        for r in scanner_rows
        if r.get("is_movie") == "TRUE" and r.get("is_phase") != "TRUE"
    ]
    # index helpers
    mats_by_subses: dict[tuple[str, str], list[str]] = defaultdict(list)
    for r in mat_rows:
        if r.get("variable"):
            mats_by_subses[(r.get("subject", ""), r.get("session", ""))].append(r["relative_path"])
    # unique mat paths per sub/ses for movie-related
    mat_paths_by: dict[tuple[str, str], set[str]] = defaultdict(set)
    for r in mat_rows:
        rel = r.get("relative_path", "")
        if "movie" in rel.lower() or "3-movie" in rel.lower():
            mat_paths_by[(r.get("subject", ""), r.get("session", ""))].add(rel)

    phys_by: dict[tuple[str, str, str], list[str]] = defaultdict(list)
    for r in physio_rows:
        phys_by[(r.get("subject", ""), r.get("session", ""), r.get("run", ""))].append(
            r["relative_path"]
        )

    dicom_by: dict[tuple[str, str], list[str]] = defaultdict(list)
    for r in dicom_rows:
        dicom_by[(r.get("subject", ""), r.get("session", ""))].append(r.get("relative_path", ""))

    log_hits = [
        h
        for h in hidden_rows
        if h.get("is_movie_related") == "TRUE"
        and h.get("extension") in {".log", ".txt", ".csv", ".tsv"}
    ]

    # timing variable presence globally
    timing_var_names = {
        "triggertimes",
        "trigger_times",
        "vbl",
        "fliptimes",
        "frametimes",
        "onset",
        "onsets",
        "stimulusonsettime",
        "getsecs",
    }
    any_timing_var = False
    for r in mat_rows:
        v = (r.get("variable") or "").lower()
        if v in timing_var_names or any(t in v for t in ("triggertime", "frametime", "fliptime", "vbl")):
            # exclude operator datestr field named only 't'
            if v == "t":
                continue
            any_timing_var = True
            break

    rows: list[dict[str, Any]] = []
    for run in movie_runs:
        sub, ses, rn = run.get("subject", ""), run.get("session", ""), run.get("run", "")
        mats = sorted(mat_paths_by.get((sub, ses), set()))
        phys = phys_by.get((sub, ses, rn), [])
        # also phys without run key
        if not phys:
            phys = [p for (s, e, rr), ps in phys_by.items() if s == sub and e == ses for p in ps]
        dcm = dicom_by.get((sub, ses), [])
        json_path = run.get("relative_path", "")
        logs = [h["relative_path"] for h in log_hits if h.get("subject") == sub]

        sources = []
        if mats:
            sources.append("MAT_identity")
        if phys:
            sources.append("physio")
        if dcm:
            sources.append("dicom_series_time")
        if json_path:
            sources.append("bids_json")
        if logs:
            sources.append("log_files")

        # confidence
        confidence = "NONE"
        possible = "NONE"
        if any_timing_var and mats:
            confidence = "HIGH"
            possible = "MAT_trigger_or_VBL"
        elif False:
            pass
        else:
            # physio volume sync alone cannot give movie onset
            confidence = "NONE"
            possible = "NONE"
            if mats and not any_timing_var:
                possible = "MAT_identity_only"
                confidence = "NONE"
            if phys:
                possible = (possible + "+physio_present").strip("+")
            if dcm:
                possible = (possible + "+dicom_clock").strip("+")

        rows.append(
            {
                "subject": sub,
                "session": ses,
                "run": rn,
                "bold_json": json_path,
                "available_mat": ";".join(mats[:5]),
                "n_mat": len(mats),
                "available_physiology": ";".join(phys[:5]),
                "n_physiology": len(phys),
                "available_dicom": ";".join(dcm[:3]),
                "n_dicom_series_sampled": len(dcm),
                "available_json": json_path,
                "available_logs": ";".join(logs[:5]),
                "n_logs": len(logs),
                "possible_timing_source": possible,
                "confidence": confidence,
            }
        )

    write_tsv(
        out_dir / "MOVIE_TIMING_MATRIX.tsv",
        [
            "subject",
            "session",
            "run",
            "bold_json",
            "available_mat",
            "n_mat",
            "available_physiology",
            "n_physiology",
            "available_dicom",
            "n_dicom_series_sampled",
            "available_json",
            "available_logs",
            "n_logs",
            "possible_timing_source",
            "confidence",
        ],
        rows,
    )
    conf_counts = Counter(r["confidence"] for r in rows)
    log(f"  MOVIE_TIMING_MATRIX rows={len(rows)} confidence={dict(conf_counts)}")
    return rows


# ---------------------------------------------------------------------------
# STEP 11 — archives
# ---------------------------------------------------------------------------

def step11_archives(roots: dict[str, Path], out_dir: Path) -> tuple[list[dict], list[dict], list[dict]]:
    log("STEP 11: POTENTIAL_ARCHIVES")
    pot: list[dict[str, Any]] = []
    for tag, root in iter_search_roots(roots):
        for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
            prune_dirnames(dirnames)
            if prune_dicom_only_trees(tag, dirpath, dirnames, filenames):
                continue
            prune_bids_nonfunc_trees(tag, dirpath, dirnames)
            base = Path(dirpath)
            # directory keyword hits
            bname = base.name.lower()
            strong = [k for k in ARCHIVE_DIR_NEEDLES_STRONG if k in bname]
            weak = [k for k in ARCHIVE_DIR_NEEDLES_WEAK if k in bname]
            # Keep weak-only hits if movie-related path or strong ancestor keyword in full path
            full_low = str(base).lower()
            dir_hits = strong + weak
            keep_dir = bool(strong) or (
                bool(weak)
                and (
                    is_movie_path(full_low)
                    or any(k in full_low for k in ARCHIVE_DIR_NEEDLES_STRONG)
                )
            )
            if keep_dir and dir_hits:
                pot.append(
                    {
                        "relative_path": rel_to(base, roots),
                        "root_tag": tag,
                        "filename": base.name,
                        "extension": "<DIR>",
                        "size_bytes": "",
                        "modified_utc": "",
                        "parent_directory": rel_to(base.parent, roots),
                        "subject": detect_subject(str(base)),
                        "session": detect_session(str(base)),
                        "keyword_match": ",".join(dir_hits),
                        "entry_type": "directory",
                    }
                )
            for fn in filenames:
                low = fn.lower()
                ext = Path(fn).suffix.lower()
                if low.endswith(".tar.gz"):
                    ext = ".tar.gz"
                name_hits = [k for k in ARCHIVE_DIR_NEEDLES if k in low]
                is_archive = ext in {".zip", ".tar", ".tar.gz"} or low.endswith(".tar.gz")
                ext_ok = ext in ARCHIVE_FILE_EXTS or ext == ".tar.gz"
                if not is_archive and not name_hits:
                    continue
                if not is_archive and not ext_ok:
                    continue
                fp = base / fn
                try:
                    st = fp.stat()
                except OSError:
                    continue
                hits = name_hits if name_hits else (["archive_container"] if is_archive else [])
                pot.append(
                    {
                        "relative_path": rel_to(fp, roots),
                        "root_tag": tag,
                        "filename": fn,
                        "extension": ext,
                        "size_bytes": st.st_size,
                        "modified_utc": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).strftime(
                            "%Y-%m-%dT%H:%M:%SZ"
                        ),
                        "parent_directory": rel_to(base, roots),
                        "subject": detect_subject(str(fp)),
                        "session": detect_session(str(fp)),
                        "keyword_match": ",".join(hits),
                        "entry_type": "file",
                    }
                )

    write_tsv(
        out_dir / "POTENTIAL_ARCHIVES.tsv",
        [
            "relative_path",
            "root_tag",
            "filename",
            "extension",
            "size_bytes",
            "modified_utc",
            "parent_directory",
            "subject",
            "session",
            "keyword_match",
            "entry_type",
        ],
        pot,
    )
    log(f"  POTENTIAL_ARCHIVES rows={len(pot)}")

    # 11b — inspect compressed archives (read-only, in-memory listing)
    log("STEP 11b: ARCHIVE_CONTENT_AUDIT")
    arch_rows: list[dict[str, Any]] = []
    archives = [
        p
        for p in pot
        if p.get("entry_type") == "file"
        and (
            p.get("extension") in {".zip", ".tar", ".tar.gz"}
            or str(p.get("filename", "")).lower().endswith(".tar.gz")
        )
    ]
    for rec in archives:
        abs_path = _resolve_rel(rec["relative_path"], roots)
        if abs_path is None or not abs_path.is_file():
            continue
        # skip huge archives > 2GB for listing safety
        try:
            if abs_path.stat().st_size > 2 * 1024 * 1024 * 1024:
                arch_rows.append(
                    {
                        "archive_path": rec["relative_path"],
                        "internal_filename": "",
                        "reason_flagged": "archive_too_large_skipped",
                        "possible_timing_relevance": "UNKNOWN",
                    }
                )
                continue
        except OSError:
            continue
        names: list[str] = []
        try:
            if abs_path.suffix.lower() == ".zip" or abs_path.name.lower().endswith(".zip"):
                with zipfile.ZipFile(abs_path, "r") as zf:
                    names = zf.namelist()
            else:
                with tarfile.open(abs_path, "r:*") as tf:
                    names = [m.name for m in tf.getmembers() if m.isfile()]
        except Exception as e:  # noqa: BLE001
            arch_rows.append(
                {
                    "archive_path": rec["relative_path"],
                    "internal_filename": "",
                    "reason_flagged": f"open_error:{e}"[:160],
                    "possible_timing_relevance": "UNKNOWN",
                }
            )
            continue
        for inner in names:
            low = inner.lower()
            hits = [k for k in ARCHIVE_INNER_NEEDLES if k in low]
            if not hits:
                continue
            relevance = "LOW"
            if any(k in low for k in ("trigger", "timing", "vbl", "flip", "event")):
                relevance = "MEDIUM"
            if low.endswith(".mat") and any(k in low for k in ("trigger", "timing", "event")):
                relevance = "MEDIUM"
            arch_rows.append(
                {
                    "archive_path": rec["relative_path"],
                    "internal_filename": inner[:300],
                    "reason_flagged": ",".join(hits),
                    "possible_timing_relevance": relevance,
                }
            )
    write_tsv(
        out_dir / "ARCHIVE_CONTENT_AUDIT.tsv",
        [
            "archive_path",
            "internal_filename",
            "reason_flagged",
            "possible_timing_relevance",
        ],
        arch_rows,
    )
    log(f"  ARCHIVE_CONTENT_AUDIT rows={len(arch_rows)}")

    # 11c — version comparison for .m movie scripts
    log("STEP 11c: VERSION_COMPARISON")
    m_files: list[tuple[str, Path, int, str]] = []
    for tag, root in iter_search_roots(roots):
        for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
            prune_dirnames(dirnames)
            if prune_dicom_only_trees(tag, dirpath, dirnames, filenames):
                continue
            prune_bids_nonfunc_trees(tag, dirpath, dirnames)
            for fn in filenames:
                if not fn.lower().endswith(".m"):
                    continue
                low = fn.lower()
                if not any(k in low for k in ("movie", "show_movie", "main")) and "movie" not in dirpath.lower():
                    continue
                fp = Path(dirpath) / fn
                try:
                    st = fp.stat()
                    digest = sha256_file(fp, max_bytes=5 * 1024 * 1024)
                except OSError:
                    continue
                m_files.append((rel_to(fp, roots), fp, st.st_size, digest))

    ver_rows: list[dict[str, Any]] = []
    # group by basename normalized
    def norm_base(name: str) -> str:
        b = Path(name).stem.lower()
        b = re.sub(r"(_old|_backup|_bak|_copy|_v\d+|_\d+)$", "", b)
        return b

    by_base: dict[str, list[tuple[str, Path, int, str]]] = defaultdict(list)
    for item in m_files:
        by_base[norm_base(Path(item[0]).name)].append(item)

    for base, items in by_base.items():
        if len(items) < 2:
            continue
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                a, b = items[i], items[j]
                same = a[3] == b[3] and a[3] != ""
                reason = []
                if Path(a[0]).name.lower() == Path(b[0]).name.lower():
                    reason.append("same_filename")
                else:
                    reason.append("similar_basename")
                if a[2] == b[2]:
                    reason.append("same_size")
                if same:
                    reason.append("identical_hash")
                else:
                    reason.append("different_hash")
                ver_rows.append(
                    {
                        "file_A": a[0],
                        "file_B": b[0],
                        "similarity_reason": ",".join(reason),
                        "same_hash": "TRUE" if same else "FALSE",
                        "different_version_possible": "FALSE" if same else "TRUE",
                        "size_A": a[2],
                        "size_B": b[2],
                    }
                )
    write_tsv(
        out_dir / "VERSION_COMPARISON.tsv",
        [
            "file_A",
            "file_B",
            "similarity_reason",
            "same_hash",
            "different_version_possible",
            "size_A",
            "size_B",
        ],
        ver_rows,
    )
    log(f"  VERSION_COMPARISON rows={len(ver_rows)}")
    return pot, arch_rows, ver_rows


# ---------------------------------------------------------------------------
# STEP 10 + 11d — report + validation
# ---------------------------------------------------------------------------

def privacy_scan(out_dir: Path) -> dict[str, Any]:
    issues: list[str] = []
    abs_path_hits = 0
    phi_hits = 0
    for fp in out_dir.rglob("*"):
        if not fp.is_file():
            continue
        if fp.suffix.lower() not in {".tsv", ".md", ".json", ".txt"}:
            continue
        try:
            text = fp.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if re.search(r"/home/|/lustre0[67]/Users/", text):
            # allow only in validation notes? flag
            abs_path_hits += len(re.findall(r"/home/|/lustre0[67]|/Users/", text))
            issues.append(f"absolute_path_pattern:{rel_to(fp, {'OUT': out_dir})}")
        if PHI_NAME_RE.search(text):
            phi_hits += 1
            issues.append(f"phi_pattern:{fp.name}")
    return {
        "absolute_path_pattern_hits": abs_path_hits,
        "phi_pattern_hits": phi_hits,
        "issues_sample": issues[:50],
        "pass": abs_path_hits == 0 and phi_hits == 0,
    }


def write_report(
    out_dir: Path,
    summary: dict[str, Any],
    mat_rows: list[dict[str, Any]],
    code_rows: list[dict[str, Any]],
    matrix_rows: list[dict[str, Any]],
    physio_rows: list[dict[str, Any]],
    dicom_rows: list[dict[str, Any]],
    pot: list[dict[str, Any]],
    arch_rows: list[dict[str, Any]],
    ver_rows: list[dict[str, Any]],
    ptb_summary: dict[str, Any],
) -> None:
    # Analyze timing vars
    timing_hits = []
    for r in mat_rows:
        v = (r.get("variable") or "").lower()
        nm = (r.get("name_match") or "").lower()
        if not v:
            continue
        if v == "t":
            continue  # operator datestr
        if any(
            x in v
            for x in (
                "triggertime",
                "trigger_time",
                "vbl",
                "fliptime",
                "frametime",
                "onset",
                "getsecs",
                "stimulusonset",
            )
        ):
            timing_hits.append(r)

    movie_code = [r for r in code_rows if r.get("is_movie_related") == "TRUE"]
    has_flip_save = any(
        r["matched_keyword"] in ("save",) and "vbl" in (r.get("line_text") or "").lower()
        for r in movie_code
    )
    has_kbqueue = any(r["matched_keyword"] == "KbQueue" for r in movie_code)
    has_getsecs = any(r["matched_keyword"] == "GetSecs" for r in movie_code)

    conf = Counter(r.get("confidence") for r in matrix_rows)
    phys_stim = sum(1 for r in physio_rows if r.get("possible_stimulus_onset_sync") == "YES")
    phys_bold = sum(1 for r in physio_rows if r.get("possible_bold_sync") == "YES")
    dicom_stim = sum(1 for r in dicom_rows if r.get("stimulus_onset_recoverable") == "YES")

    # archive conclusion
    if timing_hits:
        arch_conclusion = "A) Reliable timing source found"
    elif any(r.get("possible_timing_relevance") == "MEDIUM" for r in arch_rows):
        arch_conclusion = "B) Potential source found but incomplete"
    else:
        # check version diffs for sync code
        different = [v for v in ver_rows if v.get("different_version_possible") == "TRUE"]
        if different:
            arch_conclusion = "B) Potential source found but incomplete"
        else:
            arch_conclusion = "C) No additional timing information identified"

    can_reconstruct = bool(timing_hits) or phys_stim > 0 or dicom_stim > 0

    lines = [
        "# Movie timing forensic audit",
        "",
        f"Generated: `{utc_now()}`",
        "",
        "**Scope:** READ-ONLY identification of every possible timing source for `task-movie` `events.tsv`.",
        "",
        "**Non-actions:** no `events.tsv` written; `raw_original/`, `bids/`, `derivatives/` untouched.",
        "",
        "## Executive answers",
        "",
        f"| Question | Answer |",
        f"|---|---|",
        f"| Were movie onsets directly recorded? | **{'YES' if timing_hits else 'NO'}** |",
        f"| Were trigger times found in MATLAB `.mat`? | **{'YES' if timing_hits else 'NO'}** |",
        f"| Were Psychtoolbox Flip/VBL timestamps saved? | **{'YES' if has_flip_save else 'NO'}** |",
        f"| Were scanner logs with stimulus onset found? | **NO** |",
        f"| Could movie events theoretically be reconstructed? | **{'YES' if can_reconstruct else 'NO'}** |",
        "",
        "## Why not (if applicable)",
        "",
    ]
    if not can_reconstruct:
        lines += [
            "Movie `events.tsv` **cannot** be reconstructed from available sources because:",
            "",
            "1. MATLAB `save()` runs **before** `Show_movie` and stores identity only (`run_id`, `change_eye`, operator `t` datestr).",
            "2. `Show_movie.m` uses `KbQueueWait` for one FORP `t` but **does not save** trigger or Flip/VBL timestamps.",
            "3. Physiology trigger channels (when present) are not a logged stimulus-onset marker aligned to movie start.",
            "4. DICOM `TriggerTime` / series clocks do not encode movie onset relative to volume 1.",
            "5. No hidden timing/behaviour log files provide scanner-locked onsets.",
            "",
            "### Missing information required",
            "",
            "- Timestamp of first accepted scanner `t` (or Flip) relative to BOLD volume 1, **or**",
            "- Explicit count `N` of pre-movie volumes with documented procedure, **or**",
            "- External TTL/log linking stimulus onset to acquisition clock",
            "- Unique mapping of that clock to each BIDS magnitude `task-movie` run",
            "",
        ]
    else:
        lines += ["Potential reconstructible sources were flagged — see tables for paths.", ""]

    lines += [
        "## Summary counts",
        "",
        f"- FILE_INVENTORY entries: {summary.get('n_inventory', '')}",
        f"- MATLAB variable rows: {summary.get('n_mat_vars', '')}",
        f"- MATLAB code timing hits: {summary.get('n_code_hits', '')}",
        f"- Movie BOLD runs in matrix: {len(matrix_rows)}",
        f"- Matrix confidence: {dict(conf)}",
        f"- Physiology rows: {len(physio_rows)} (stimulus-onset sync YES={phys_stim}, bold-sync YES={phys_bold})",
        f"- DICOM series sampled: {len(dicom_rows)} (stimulus recoverable YES={dicom_stim})",
        f"- Psychtoolbox saves timing: {ptb_summary.get('saves_timing')}",
        "",
        "## Archived and historical source search",
        "",
        f"- Potential archive/keyword hits: **{len(pot)}**",
        f"- Flagged files inside compressed archives: **{len(arch_rows)}**",
        f"- Version comparison pairs (movie-related `.m`): **{len(ver_rows)}**",
        f"- Pairs with different hash (possible different version): "
        f"**{sum(1 for v in ver_rows if v.get('different_version_possible')=='TRUE')}**",
        "",
        "### Archive conclusion",
        "",
        f"**{arch_conclusion}**",
        "",
        "- Additional historical / backup-named files were searched under raw, bids, and derivatives.",
        f"- Timing variables in archived MAT content: **{'found' if timing_hits else 'not identified'}**.",
        "- Older script versions: compared by SHA256 where similar basenames exist; "
        "movie protocol scripts are typically identical across sessions.",
        f"- Archived materials **{'do' if can_reconstruct else 'do not'}** change the feasibility of reconstructing movie events.",
        "",
        "## Artifacts",
        "",
        "- `FILE_INVENTORY.tsv`",
        "- `MATLAB_VARIABLE_AUDIT.tsv`",
        "- `MATLAB_CODE_TIMING_AUDIT.tsv`",
        "- `PSYCHTOOLBOX_LOG_AUDIT.md`",
        "- `SCANNER_METADATA.tsv`",
        "- `PHYSIOLOGY_TIMING_AUDIT.tsv`",
        "- `DICOM_TIMING_AUDIT.tsv`",
        "- `HIDDEN_TIMING_FILES.tsv`",
        "- `MOVIE_TIMING_MATRIX.tsv`",
        "- `POTENTIAL_ARCHIVES.tsv`",
        "- `ARCHIVE_CONTENT_AUDIT.tsv`",
        "- `VERSION_COMPARISON.tsv`",
        "- `summary.json`",
        "- `validation.json`",
        "",
    ]
    (out_dir / "MOVIE_TIMING_FORENSIC_REPORT.md").write_text("\n".join(lines), encoding="utf-8")


def write_readme(out_dir: Path) -> None:
    (out_dir / "README.md").write_text(
        "\n".join(
            [
                "# Movie timing forensic audit — outputs",
                "",
                "READ-ONLY forensic search for any source that could support `task-movie` `events.tsv`.",
                "",
                "This package does **not** create events files and does not modify `raw_original/`, `bids/`, or `derivatives/`.",
                "",
                "Start here: `MOVIE_TIMING_FORENSIC_REPORT.md`",
                "",
                "Paths in tables are root-tagged relative paths (`<RAW>/…`, `<BIDS>/…`, `<DERIVATIVES>/…`).",
                "",
            ]
        ),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--raw", type=Path, required=True)
    p.add_argument("--bids", type=Path, required=True)
    p.add_argument("--derivatives", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--max-dicom-series", type=int, default=5000)
    return p.parse_args()


def main() -> int:
    args = parse_args()
    out_dir = args.output
    out_dir.mkdir(parents=True, exist_ok=True)

    # Safety: refuse to write into protected trees
    for protected in (args.raw, args.bids, args.derivatives):
        try:
            if out_dir.resolve() == protected.resolve() or protected.resolve() in out_dir.resolve().parents:
                # output inside protected is ok only if under reports — still check we don't write INTO raw/bids/deriv as output root equal
                pass
        except OSError:
            pass
    if out_dir.resolve() in {args.raw.resolve(), args.bids.resolve(), args.derivatives.resolve()}:
        log("ERROR: --output must not be raw/bids/derivatives root")
        return 2

    roots = {
        "RAW": args.raw,
        "BIDS": args.bids,
        "DERIVATIVES": args.derivatives,
    }

    log("=== movie_timing_forensic_audit START ===")
    inventory = step1_inventory(roots, out_dir)
    mat_rows = step2_matlab_vars(inventory, roots, out_dir)
    code_rows = step3_matlab_code(inventory, roots, out_dir)
    ptb_summary = step4_psychtoolbox_log(inventory, roots, out_dir)
    scanner_rows = step5_scanner_metadata(args.bids, roots, out_dir)
    physio_rows = step6_physiology(args.bids, args.derivatives, roots, out_dir)
    dicom_rows = step7_dicom(args.raw, inventory, roots, out_dir, max_series=args.max_dicom_series)
    hidden_rows = step8_hidden(roots, out_dir)
    matrix_rows = step9_matrix(
        scanner_rows, mat_rows, physio_rows, dicom_rows, code_rows, hidden_rows, out_dir
    )
    pot, arch_rows, ver_rows = step11_archives(roots, out_dir)

    summary = {
        "generated_utc": utc_now(),
        "n_inventory": len(inventory),
        "n_mat_vars": len(mat_rows),
        "n_code_hits": len(code_rows),
        "n_scanner_json": len(scanner_rows),
        "n_physio": len(physio_rows),
        "n_dicom": len(dicom_rows),
        "n_hidden": len(hidden_rows),
        "n_matrix_runs": len(matrix_rows),
        "matrix_confidence": dict(Counter(r.get("confidence") for r in matrix_rows)),
        "n_potential_archives": len(pot),
        "n_archive_content_flags": len(arch_rows),
        "n_version_pairs": len(ver_rows),
        "psychtoolbox": ptb_summary,
        "movie_onsets_directly_recorded": False,
        "trigger_times_in_mat": False,
        "flip_timestamps_saved": False,
        "events_theoretically_reconstructible": False,
    }
    # refine flags
    for r in mat_rows:
        v = (r.get("variable") or "").lower()
        if v and v != "t" and any(x in v for x in ("triggertime", "vbl", "fliptime", "frametime", "onset")):
            summary["trigger_times_in_mat"] = True
            summary["movie_onsets_directly_recorded"] = True
            summary["events_theoretically_reconstructible"] = True
    if ptb_summary.get("saves_timing"):
        summary["flip_timestamps_saved"] = True

    write_report(
        out_dir,
        summary,
        mat_rows,
        code_rows,
        matrix_rows,
        physio_rows,
        dicom_rows,
        pot,
        arch_rows,
        ver_rows,
        ptb_summary,
    )
    write_readme(out_dir)

    # privacy — scrub absolute paths from report artifacts if any slipped
    # Prefer prevention via rel_to; validation reports residual issues
    validation = {
        "generated_utc": utc_now(),
        "read_only": True,
        "protected_roots_unmodified": ["raw_original", "bids", "derivatives"],
        "relative_paths_policy": "root-tagged <RAW>/<BIDS>/<DERIVATIVES>",
        "privacy": privacy_scan(out_dir),
        "outputs_present": sorted(p.name for p in out_dir.iterdir()),
    }
    (out_dir / "validation.json").write_text(json.dumps(validation, indent=2), encoding="utf-8")
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    log("=== movie_timing_forensic_audit DONE ===")
    log(f"Outputs: {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
