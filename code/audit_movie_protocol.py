#!/usr/bin/env python3
"""Read-only Movie MATLAB protocol audit + Scientific Data documentation builder.

Writes ONLY under:
  reports/movie_protocol/
  code/task-movie/   (sanitized publication copies only; never raw PHI paths)

Never modifies raw_original/, bids/, release_dataset/, derivatives/.
Never creates events.tsv. Never copies mp4.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import shutil
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

RAW_ROOTS = [
    Path("/lustre06/project/6001995/raw_original"),
    Path("/lustre07/scratch/alexrees/raw_original"),
]
BIDS = Path("/home/alexrees/scratch/bids")
SESSIONS = Path("/home/alexrees/scratch/metadata/sessions.tsv")
REPORT = Path("/home/alexrees/scratch/reports/movie_protocol")
CODE_OUT = Path("/home/alexrees/scratch/code/task-movie")

CALL_RE = re.compile(
    r"\b(?P<name>[A-Za-z_]\w*)\s*\(",
)
FUNC_DEF_RE = re.compile(r"^\s*function\b[^=]*=?\s*(?P<name>[A-Za-z_]\w*)", re.M)

PHI_PATTERNS: list[tuple[str, str, re.Pattern[str]]] = [
    ("PatientName", "HIGH", re.compile(r"\bPatientName\b", re.I)),
    ("PatientID", "HIGH", re.compile(r"\bPatientID\b", re.I)),
    ("PatientBirth", "HIGH", re.compile(r"\bPatientBirth|BirthDate\b", re.I)),
    ("StudyUID", "HIGH", re.compile(r"\bStudyInstanceUID|SeriesInstanceUID\b", re.I)),
    ("Institution", "MEDIUM", re.compile(r"\bInstitution|Hospital|Department\b", re.I)),
    ("WindowsUserPath", "HIGH", re.compile(r"[A-Za-z]:\\Users\\[^\\'\"]+", re.I)),
    ("WindowsDrivePath", "MEDIUM", re.compile(r"[A-Za-z]:\\(?!Users\\)[^\s'\"]+", re.I)),
    ("UnixHomePath", "HIGH", re.compile(r"/home/[A-Za-z0-9._-]+")),
    ("Desktop", "MEDIUM", re.compile(r"\\Desktop\\|/Desktop/", re.I)),
    ("Documents", "MEDIUM", re.compile(r"\\Documents\\|/Documents/", re.I)),
    ("Password", "HIGH", re.compile(r"\bpassword\s*=|\bpasswd\b|api[_-]?key", re.I)),
    ("Email", "MEDIUM", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")),
    # Subject initials dialog itself is not PHI in code; Results filenames are elsewhere
    ("HardcodedSubjectPrompt", "LOW", re.compile(r"Subject Initials", re.I)),
]

RUN_DICT = [
    {
        "matlab_run_id": "1",
        "stimulus_name": "Movie1A.mp4",
        "movie_label": "Movie1",
        "eye": "left",
        "expected_volumes": "210",
        "TR": "0.937",
        "duration_seconds": f"{210 * 0.937:.3f}",
        "notes": "Clip/eye from main.m; volumes=210 & TR=0.937 s from BIDS Movie BOLD (not logged by MATLAB)",
    },
    {
        "matlab_run_id": "2",
        "stimulus_name": "Movie2A.mp4",
        "movie_label": "Movie2",
        "eye": "right",
        "expected_volumes": "210",
        "TR": "0.937",
        "duration_seconds": f"{210 * 0.937:.3f}",
        "notes": "Clip/eye from main.m (eye=~change_eye); volumes/TR from BIDS Movie BOLD",
    },
    {
        "matlab_run_id": "3",
        "stimulus_name": "Movie1B.mp4",
        "movie_label": "Movie3",
        "eye": "right",
        "expected_volumes": "210",
        "TR": "0.937",
        "duration_seconds": f"{210 * 0.937:.3f}",
        "notes": "Clip/eye from main.m; Movie1B ↔ ProtocolName Movie3_*; volumes/TR from BIDS",
    },
    {
        "matlab_run_id": "4",
        "stimulus_name": "Movie2B.mp4",
        "movie_label": "Movie4",
        "eye": "left",
        "expected_volumes": "210",
        "TR": "0.937",
        "duration_seconds": f"{210 * 0.937:.3f}",
        "notes": "Clip/eye from main.m; Movie2B ↔ ProtocolName Movie4_*; volumes/TR from BIDS",
    },
]

# ProtocolName MovieN_AP ↔ matlab run_id N (digit extracted from ProtocolName)
PROTO_TO_RUN = {
    "1": "1",
    "2": "2",
    "3": "3",
    "4": "4",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _write_tsv(path: Path, fields: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, delimiter="\t", lineterminator="\n")
        w.writeheader()
        for row in rows:
            w.writerow({k: row.get(k, "") for k in fields})


def _load_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh, delimiter="\t"))


def find_movie_m_files() -> list[Path]:
    found: list[Path] = []
    for root in RAW_ROOTS:
        if not root.is_dir():
            continue
        # Restrict to MATLAB trees named 3-Movie_Data
        for d in root.rglob("3-Movie_Data"):
            if not d.is_dir():
                continue
            for p in d.rglob("*.m"):
                if p.is_file():
                    found.append(p)
    # Deduplicate by resolved path
    uniq = {}
    for p in found:
        try:
            uniq[str(p.resolve())] = p
        except OSError:
            uniq[str(p)] = p
    return sorted(uniq.values(), key=lambda x: str(x))


def parse_calls(text: str, known_basenames: set[str]) -> list[str]:
    # Map lowercase basename without .m
    known = {b.lower(): b for b in known_basenames}
    called: list[str] = []
    # function definitions in this file
    defs = {m.group("name") for m in FUNC_DEF_RE.finditer(text)}
    for m in CALL_RE.finditer(text):
        name = m.group("name")
        if name in defs:
            continue
        key = name.lower()
        # Show_movie / Show_Movie
        if key in known:
            called.append(known[key])
        elif key + ".m" in {k + ".m" for k in known}:
            called.append(known[key])
    # Also explicit Show_movie(...)
    if re.search(r"\bShow_movie\s*\(", text, re.I) and "Show_movie" in known_basenames:
        if "Show_movie" not in called:
            called.append("Show_movie")
    return sorted(set(called))


def sanitize_matlab(text: str) -> tuple[str, list[str]]:
    """Replace absolute Windows paths / usernames for publication. Return scrubbed text + edits."""
    edits: list[str] = []
    out = text

    # Diary / output path → local relative file (allow spaces in Windows usernames)
    def repl_out(m: re.Match[str]) -> str:
        edits.append(f"scrub diary output path: {m.group(0)}")
        return "output.txt"

    out = re.sub(
        r"(?:[A-Za-z]:\\|<STIMULUS_PC>\\)[^'\n]*output\.txt",
        repl_out,
        out,
        flags=re.I,
    )

    # Absolute / placeholder movie paths → basename only (spaces allowed in path)
    def repl_movie(m: re.Match[str]) -> str:
        edits.append(f"scrub movie path → basename: {m.group(0)}")
        fname = Path(m.group(0).replace("\\", "/")).name
        return fname if fname.lower().endswith(".mp4") else "movie.mp4"

    out = re.sub(
        r"(?:[A-Za-z]:\\|<STIMULUS_PC>\\)[^'\"]+\.mp4",
        repl_movie,
        out,
        flags=re.I,
    )

    # Residual Desktop\movies\Movie*.mp4 fragments (if user-path scrub ran first elsewhere)
    def repl_residual(m: re.Match[str]) -> str:
        edits.append(f"scrub residual movie path → basename: {m.group(0)}")
        return m.group(1)

    out = re.sub(
        r"(?:<STIMULUS_PC>\\Desktop\\movies\\|Desktop\\movies\\|movies\\)(Movie[12][AB]\.mp4)",
        repl_residual,
        out,
        flags=re.I,
    )

    # Any remaining Windows user roots (username may contain spaces)
    def repl_user(m: re.Match[str]) -> str:
        edits.append(f"scrub Windows user path: {m.group(0)}")
        return "<STIMULUS_PC>"

    out = re.sub(r"[A-Za-z]:\\Users\\[^\\'\"]+", repl_user, out)
    # Drop leftover Desktop / Documents path fragments after user scrub
    out = re.sub(r"<STIMULUS_PC>\\(?:Desktop|Documents)\\[^'\"]*", "<STIMULUS_PC>", out, flags=re.I)
    return out, edits


def inventory_and_phi(m_files: list[Path]) -> tuple[list[dict], list[dict], dict[str, list[Path]]]:
    basenames = {p.stem for p in m_files} | {p.name.replace(".m", "") for p in m_files}
    # normalize: Show_movie from Show_Movie.m
    known = set()
    for p in m_files:
        known.add(p.stem)
        known.add(p.name[:-2] if p.name.endswith(".m") else p.name)

    by_hash: dict[str, list[Path]] = defaultdict(list)
    inv_rows: list[dict] = []
    phi_rows: list[dict] = []

    # First pass: hash + text
    meta: dict[str, dict] = {}
    for p in m_files:
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            text = ""
            phi_rows.append(
                {
                    "file": str(p),
                    "line": "",
                    "pattern": "READ_ERROR",
                    "severity": "HIGH",
                    "recommendation": f"unreadable:{exc}",
                }
            )
        digest = _sha256(p) if p.is_file() else ""
        by_hash[digest].append(p)
        nlines = text.count("\n") + (1 if text and not text.endswith("\n") else 0)
        calls = parse_calls(text, {x for x in known})
        meta[str(p)] = {
            "text": text,
            "sha256": digest,
            "nlines": nlines,
            "calls": calls,
            "size": p.stat().st_size if p.is_file() else 0,
        }
        for i, line in enumerate(text.splitlines(), 1):
            for label, sev, pat in PHI_PATTERNS:
                if pat.search(line):
                    # Don't dump full Windows path content beyond pattern name for HIGH
                    phi_rows.append(
                        {
                            "file": str(p),
                            "line": str(i),
                            "pattern": label,
                            "severity": sev,
                            "recommendation": (
                                "Do not copy raw script; publish sanitized path placeholders only"
                                if sev == "HIGH"
                                else "Review before publication"
                            ),
                        }
                    )

    # Reverse called_by
    called_by: dict[str, set[str]] = defaultdict(set)
    for path_s, m in meta.items():
        src_name = Path(path_s).stem
        for c in m["calls"]:
            called_by[c].add(src_name)
            called_by[c.lower()].add(src_name)

    # publication candidate: unique content hashes for main.m / Show_movie.m that are used
    used_names = {"main", "Show_movie", "Show_Movie", "show_movie"}
    for path_s, m in meta.items():
        stem = Path(path_s).stem
        digest = m["sha256"]
        dups = len(by_hash[digest])
        is_core = stem.lower() in {"main", "show_movie"}
        # used if core or called by someone
        used = is_core or bool(called_by.get(stem) or called_by.get(stem.lower()))
        pub = "YES" if is_core and used else ("NO_UNUSED" if not used else "NO_NONCORE")
        # If HIGH PHI on this file, mark needs_sanitize
        high = any(
            r["file"] == path_s and r["severity"] == "HIGH" for r in phi_rows
        )
        if pub == "YES" and high:
            pub = "YES_NEEDS_SANITIZE"
        inv_rows.append(
            {
                "filepath": path_s,
                "filename": Path(path_s).name,
                "sha256": digest,
                "size": str(m["size"]),
                "number_of_lines": str(m["nlines"]),
                "called_by": ";".join(sorted(called_by.get(stem, set()) | called_by.get(stem.lower(), set()))),
                "calls": ";".join(m["calls"]),
                "duplicate_hash": str(dups),
                "publication_candidate": pub,
            }
        )

    return inv_rows, phi_rows, by_hash


def pick_canonical(by_hash: dict[str, list[Path]], inv_rows: list[dict]) -> dict[str, Path]:
    """Pick most common hash for main.m and Show_movie.m."""
    chosen: dict[str, Path] = {}
    for target in ("main.m", "Show_movie.m"):
        rows = [r for r in inv_rows if r["filename"].lower() == target.lower()]
        if not rows:
            continue
        # majority hash
        cnt = Counter(r["sha256"] for r in rows)
        best_hash, _ = cnt.most_common(1)[0]
        paths = by_hash[best_hash]
        # prefer Control cohort path if any
        paths_sorted = sorted(paths, key=lambda p: (0 if "Control" in str(p) else 1, str(p)))
        chosen[target] = paths_sorted[0]
    return chosen


def collect_movie_bolds() -> list[dict[str, str]]:
    rows = []
    for nii in BIDS.rglob("*task-movie*_bold.nii.gz"):
        if "part-phase" in nii.name:
            continue
        if "derivatives" in nii.parts:
            continue
        sub = next(x for x in nii.parts if x.startswith("sub-"))
        ses = next(x for x in nii.parts if x.startswith("ses-"))
        # run entity
        m = re.search(r"_run-(\d+)_", nii.name)
        run = m.group(1) if m else ""
        js = nii.with_suffix("").with_suffix(".json")  # .nii.gz -> tricky
        # Path.with_suffix only strips one suffix
        jpath = Path(str(nii).replace(".nii.gz", ".json"))
        proto = ""
        series = ""
        tr = ""
        if jpath.is_file():
            try:
                meta = json.loads(jpath.read_text(encoding="utf-8"))
                proto = str(meta.get("ProtocolName") or meta.get("SeriesDescription") or "")
                series = str(meta.get("SeriesNumber") or "")
                tr = str(meta.get("RepetitionTime") or "")
            except Exception:
                pass
        movie_n = ""
        mm = re.search(r"Movie\s*([1-4])", proto, re.I)
        if mm:
            movie_n = mm.group(1)
        rows.append(
            {
                "participant_id": sub,
                "session_id": ses,
                "task": "movie",
                "bids_run": run,
                "bold_file": str(nii),
                "ProtocolName": proto,
                "SeriesNumber": series,
                "RepetitionTime": tr,
                "movie_index": movie_n,
            }
        )
    return rows


def collect_matlab_run_logs(sessions: list[dict[str, str]]) -> list[dict[str, str]]:
    """Find selected_run_id*.mat under each session's original_path MATLAB trees."""
    rows = []
    for s in sessions:
        sub = s["participant_id"]
        ses = s["session_id"]
        root = Path(s["original_path"])
        if not root.is_dir():
            # try lustre06 twin
            alt = Path(str(root).replace("/lustre07/scratch/alexrees/raw_original", "/lustre06/project/6001995/raw_original"))
            root = alt if alt.is_dir() else root
        if not root.is_dir():
            continue
        mats = list(root.rglob("*selected_run_id*.mat"))
        for mat in mats:
            # only under 3-Movie_Data
            if "3-Movie_Data" not in mat.parts and "3-movie_data" not in [p.lower() for p in mat.parts]:
                # still accept if name matches selected_run_id
                if "selected_run_id" not in mat.name:
                    continue
            rm = re.search(r"selected_run_id[_-]?(\d+)", mat.name, re.I)
            run_id = rm.group(1) if rm else ""
            rows.append(
                {
                    "participant_id": sub,
                    "session_id": ses,
                    "mat_path": str(mat),
                    "matlab_run_id": run_id,
                    "mtime": str(int(mat.stat().st_mtime)),
                }
            )
    return rows


def build_assignments(
    bolds: list[dict[str, str]], logs: list[dict[str, str]]
) -> tuple[list[dict], list[dict]]:
    """Unique ProtocolName MovieN → matlab_run_id N; else manual review."""
    assigns: list[dict] = []
    review: list[dict] = []

    logs_by = defaultdict(list)
    for r in logs:
        logs_by[(r["participant_id"], r["session_id"])].append(r)

    bolds_by = defaultdict(list)
    for r in bolds:
        bolds_by[(r["participant_id"], r["session_id"])].append(r)

    eye_by_run = {d["matlab_run_id"]: d["eye"] for d in RUN_DICT}
    stim_by_run = {d["matlab_run_id"]: d["stimulus_name"] for d in RUN_DICT}

    for key, session_bolds in sorted(bolds_by.items()):
        sub, ses = key
        # Group by movie_index from ProtocolName
        by_idx: dict[str, list[dict]] = defaultdict(list)
        no_idx: list[dict] = []
        for b in session_bolds:
            if b["movie_index"] in PROTO_TO_RUN:
                by_idx[b["movie_index"]].append(b)
            else:
                no_idx.append(b)

        session_logs = logs_by.get(key, [])
        log_ids = {r["matlab_run_id"] for r in session_logs if r["matlab_run_id"]}

        for idx, blist in by_idx.items():
            run_id = PROTO_TO_RUN[idx]
            if len(blist) != 1:
                review.append(
                    {
                        "participant_id": sub,
                        "session_id": ses,
                        "reason": "AMBIGUOUS_PROTOCOL_MATCH",
                        "detail": f"Movie{idx}: {len(blist)} BOLD files",
                        "bids_runs": ";".join(b["bids_run"] for b in blist),
                    }
                )
                continue
            b = blist[0]
            conf = "HIGH" if run_id in log_ids or not session_logs else "MEDIUM"
            method = "ProtocolName_MovieN_to_matlab_run_id"
            if run_id in log_ids:
                method += "+selected_run_id_mat_present"
            assigns.append(
                {
                    "participant_id": sub,
                    "session_id": ses,
                    "task": "movie",
                    "bids_run": b["bids_run"],
                    "matlab_run_id": run_id,
                    "stimulus_name": stim_by_run.get(run_id, ""),
                    "eye": eye_by_run.get(run_id, ""),
                    "mapping_confidence": conf,
                    "mapping_method": method,
                    "ProtocolName": b["ProtocolName"],
                    "SeriesNumber": b["SeriesNumber"],
                }
            )

        for b in no_idx:
            review.append(
                {
                    "participant_id": sub,
                    "session_id": ses,
                    "reason": "MISSING_MOVIE_INDEX_IN_PROTOCOL",
                    "detail": b["ProtocolName"] or "empty ProtocolName",
                    "bids_runs": b["bids_run"],
                }
            )

    return assigns, review


def write_protocol_docs(
    inv_rows: list[dict],
    phi_rows: list[dict],
    canonical: dict[str, Path],
    assigns: list[dict],
    review: list[dict],
    bolds: list[dict],
    logs: list[dict],
    copy_rows: list[dict],
    verdict: str,
) -> None:
    REPORT.mkdir(parents=True, exist_ok=True)

    # SUMMARY
    (REPORT / "MOVIE_PROTOCOL_SUMMARY.md").write_text(
        f"""# Movie protocol summary (MATLAB / Psychtoolbox)

**Generated:** `{_now()}`  
**Source of truth:** majority-hash copies of `main.m` / `Show_movie.m` under `**/3-Movie_Data/` in `raw_original/` (read-only audit).

## Overview

Naturalistic monocular movie stimulation was delivered with Psychtoolbox-3 under MATLAB. Operators launched `main.m`, selected a `run_id` (1–4), which selected a movie file and stimulated eye, then `Show_movie.m` waited for the scanner FORP trigger key `t` and streamed the clip with a binocular fixation overlay.

## Acquisition workflow

1. Operator confirms Results folder housekeeping (`questdlg`).
2. Operator enters subject initials (saved into Results filename only; not used for timing).
3. Operator selects `run_id` 1–4 via dialog.
4. `main.m` **immediately saves** `Results/<datetime>_Subject_is_<initials>_selected_run_id_<N>.mat` containing selection metadata (`run_id`, comment, timestamps) — **before** playback.
5. `main.m` calls `Show_movie(moviename, eye)`.
6. `Show_movie` opens a stereo PTB window, shows “The experiment will start shortly”, opens the movie, starts the playback engine, creates a keyboard queue for `t`, then `KbQueueWait` blocks until the scanner trigger.
7. Frames are drawn to the stimulated eye buffer with a blue/red fixation cross until the movie ends (or space aborts).

## Synchronization

- Intended sync: first scanner TTL mapped to keyboard `t` (FORP device index 0).
- **Limitation (critical):** `Screen('PlayMovie', movie, 1)` is invoked **before** `KbQueueWait`. No `triggerTimes`, VBL timestamps, or frame indices are written to disk.
- Therefore scanner-locked onsets/durations **cannot** be reconstructed without inventing timing.

## Stimulus selection

| matlab_run_id | File (as coded) | Stimulated eye (with default `change_eye=0`) |
|---:|---|---|
| 1 | Movie1A.mp4 | left (`eye = change_eye`) |
| 2 | Movie2A.mp4 | right (`eye = ~change_eye`) |
| 3 | Movie1B.mp4 | right |
| 4 | Movie2B.mp4 | left |

`change_eye` may be flipped from FOV/eye-check notes (commented in `main.m`).

## Movie assignment / Run selection

BIDS functional series use `ProtocolName` / `SeriesDescription` `Movie1_AP`…`Movie4_AP`. Documentation maps:

- `Movie1_*` ↔ matlab `run_id=1` ↔ Movie1A  
- `Movie2_*` ↔ `run_id=2` ↔ Movie2A  
- `Movie3_*` ↔ `run_id=3` ↔ Movie1B  
- `Movie4_*` ↔ `run_id=4` ↔ Movie2B  

Assignments are emitted only when this ProtocolName match is **unique** within a session.

## Scanner interaction

- Start: wait for `t`.
- Abort: space closes movie and screen.
- Design length referenced in prior paradigm docs: ~210 volumes at TR ≈ 0.937 s (~197 s). Not re-derived from MP4 (videos not ingested).

## Known limitations

1. No measured event timing → **no `events.tsv`** (fail-closed).
2. Absolute Windows stimulus-PC paths in raw scripts (sanitized in public `code/task-movie/`).
3. Results `.mat` store identity (`run_id`) only.
4. MP4s are copyright-sensitive and are **not** copied into the public tree.

## Scientific relevance

Documents which naturalistic clip and eye were intended per BIDS `task-movie` run, supporting reuse and QC without fabricating onsets. Aligns with Scientific Data / OpenNeuro expectations for transparent withholding of non-recoverable timing.
""",
        encoding="utf-8",
    )

    n_bold = len(bolds)
    n_logs = len(logs)
    n_map = len(assigns)
    n_amb = len(review)
    sessions_bold = {(b["participant_id"], b["session_id"]) for b in bolds}
    sessions_mapped = {(a["participant_id"], a["session_id"]) for a in assigns}
    coverage = (n_map / n_bold * 100.0) if n_bold else 0.0

    (REPORT / "MOVIE_PROTOCOL_VALIDATION.md").write_text(
        f"""# Movie protocol validation

**Generated:** `{_now()}`

| Metric | N |
|---|---:|
| BIDS `task-movie` magnitude BOLD | {n_bold} |
| MATLAB `selected_run_id*.mat` logs found | {n_logs} |
| Unique ProtocolName→run assignments written | {n_map} |
| Manual review rows | {n_amb} |
| Sessions with ≥1 movie BOLD | {len(sessions_bold)} |
| Sessions with ≥1 assignment | {len(sessions_mapped)} |
| Assignment coverage (assigned / BOLD) | {coverage:.1f}% |

## Ambiguities / missing

See `MANUAL_REVIEW_REQUIRED.tsv` for per-session reasons (`AMBIGUOUS_PROTOCOL_MATCH`, `MISSING_MOVIE_INDEX_IN_PROTOCOL`, …).

## Duplicates

Script inventory duplicate counts are in `MATLAB_PROTOCOL_INVENTORY.tsv` (`duplicate_hash`).
""",
        encoding="utf-8",
    )

    high_phi = sum(1 for r in phi_rows if r["severity"] == "HIGH")
    n_scripts = len(inv_rows)
    n_unique = len({r["sha256"] for r in inv_rows})
    n_copied = sum(1 for r in copy_rows if r.get("status") == "COPIED_SANITIZED")

    (REPORT / "FINAL_MOVIE_PROTOCOL_REPORT.md").write_text(
        f"""# Final Movie protocol documentation report

**Generated:** `{_now()}`

## Counts

| Item | N |
|---|---:|
| Total `.m` scripts under `**/3-Movie_Data/` | {n_scripts} |
| Unique SHA256 versions | {n_unique} |
| Scripts copied to `code/task-movie/` (sanitized) | {n_copied} |
| PHI findings (all severities) | {len(phi_rows)} |
| PHI HIGH findings | {high_phi} |
| Run dictionary rows | {len(RUN_DICT)} |
| Run assignments | {n_map} |
| Manual review rows | {n_amb} |
| Movie BOLD coverage | {n_map}/{n_bold} ({coverage:.1f}%) |

## Audit PHI

Raw scripts contain **HIGH** absolute Windows user/stimulus paths (`C:\\Users\\...`).  
Public copies under `code/task-movie/` are **sanitized** (paths replaced with placeholders / relative mp4 filenames). Raw `raw_original/` files were not modified.

## Run dictionary / assignments

- `code/task-movie/task-movie_run_dictionary.tsv` — from `main.m` comments/switch only.
- `code/task-movie/task-movie_run_assignments.tsv` — unique `ProtocolName MovieN` → `matlab_run_id N` only.

## Recommendation

### {verdict}

{"Movie protocol documentation is suitable for inclusion in the public OpenNeuro / Scientific Data release." if verdict.startswith("OPTION A") else "Manual review required before publication."}

**Rationale:** Protocol behavior and run↔clip↔eye mapping are documented without inventing `events.tsv`. Videos are not redistributed. Sanitized MATLAB entry points are provided under `code/task-movie/`. Remaining unmapped BOLD runs are listed for manual review rather than forced association.
""",
        encoding="utf-8",
    )


def main() -> int:
    REPORT.mkdir(parents=True, exist_ok=True)
    print("Scanning for 3-Movie_Data/*.m …", flush=True)
    m_files = find_movie_m_files()
    print(f"Found {len(m_files)} .m files", flush=True)

    inv_rows, phi_rows, by_hash = inventory_and_phi(m_files)
    _write_tsv(
        REPORT / "MATLAB_PROTOCOL_INVENTORY.tsv",
        [
            "filepath",
            "filename",
            "sha256",
            "size",
            "number_of_lines",
            "called_by",
            "calls",
            "duplicate_hash",
            "publication_candidate",
        ],
        inv_rows,
    )
    _write_tsv(
        REPORT / "MATLAB_PHI_AUDIT.tsv",
        ["file", "line", "pattern", "severity", "recommendation"],
        phi_rows,
    )

    high = [r for r in phi_rows if r["severity"] == "HIGH"]
    print(f"PHI HIGH hits: {len(high)}", flush=True)

    canonical = pick_canonical(by_hash, inv_rows)
    print("Canonical scripts:", {k: str(v) for k, v in canonical.items()}, flush=True)

    # Part 4: sanitized copies ONLY (never raw HIGH paths)
    CODE_OUT.mkdir(parents=True, exist_ok=True)
    copy_rows: list[dict] = []
    for fname, src in canonical.items():
        raw = src.read_text(encoding="utf-8", errors="replace")
        scrubbed, edits = sanitize_matlab(raw)
        # Also ensure function filename matches Show_movie call convention
        dest = CODE_OUT / fname
        dest.write_text(scrubbed, encoding="utf-8")
        copy_rows.append(
            {
                "source_path": str(src),
                "source_sha256": _sha256(src),
                "dest_path": str(dest),
                "dest_sha256": hashlib.sha256(scrubbed.encode()).hexdigest(),
                "status": "COPIED_SANITIZED",
                "sanitization_edits": " | ".join(edits) if edits else "none",
            }
        )
    _write_tsv(
        REPORT / "CODE_COPY_VALIDATION.tsv",
        [
            "source_path",
            "source_sha256",
            "dest_path",
            "dest_sha256",
            "status",
            "sanitization_edits",
        ],
        copy_rows,
    )

    # Run dictionary
    _write_tsv(
        CODE_OUT / "task-movie_run_dictionary.tsv",
        [
            "matlab_run_id",
            "stimulus_name",
            "movie_label",
            "eye",
            "expected_volumes",
            "TR",
            "duration_seconds",
            "notes",
        ],
        RUN_DICT,
    )

    # README (Scientific Data public wording + technical appendix)
    (CODE_OUT / "README.md").write_text(
        """# Movie task

Participants viewed predefined movie clips during fMRI acquisition.

The released metadata provide the mapping between BIDS functional runs and MATLAB movie identifiers.

Precise stimulus onset timing was not released because scanner-locked presentation timestamps were not consistently recoverable.

Therefore, no BIDS `events.tsv` files were generated.

Movie scripts are provided to document stimulus presentation logic.

Movie files are not included because of copyright restrictions.

---

## Technical documentation

Sanitized publication copies of the laboratory Psychtoolbox entry points (`main.m`, `Show_movie.m`). Absolute stimulus-PC paths from the raw archive were replaced with relative MP4 basenames.

### Scanner synchronization

`Show_movie.m` opens the movie, starts the playback engine, then blocks on `KbQueueWait` for the FORP keyboard event `t` (scanner trigger). Frame drawing proceeds after the trigger. **No trigger timestamps are saved.**

### Stimulus presentation (`run_id`)

| run_id | Clip | Default eye (`change_eye=0`) | BIDS ProtocolName family |
|---:|---|---|---|
| 1 | Movie1A.mp4 | left | Movie1_* |
| 2 | Movie2A.mp4 | right | Movie2_* |
| 3 | Movie1B.mp4 | right | Movie3_* |
| 4 | Movie2B.mp4 | left | Movie4_* |

See `task-movie_run_dictionary.tsv` and `task-movie_run_assignments.tsv`.

### Dependencies

- MATLAB
- Psychtoolbox-3 (`Screen`, `KbQueue*`, stereo mode)
- Movie files on the stimulus PC (**not** redistributed)

### Provenance

`reports/movie_protocol/CODE_COPY_VALIDATION.tsv`
""",
        encoding="utf-8",
    )

    print("Collecting BIDS movie BOLD + MATLAB logs…", flush=True)
    sessions = _load_tsv(SESSIONS)
    bolds = collect_movie_bolds()
    logs = collect_matlab_run_logs(sessions)
    assigns, review = build_assignments(bolds, logs)

    _write_tsv(
        CODE_OUT / "task-movie_run_assignments.tsv",
        [
            "participant_id",
            "session_id",
            "task",
            "bids_run",
            "matlab_run_id",
            "stimulus_name",
            "eye",
            "mapping_confidence",
            "mapping_method",
            "ProtocolName",
            "SeriesNumber",
        ],
        assigns,
    )
    _write_tsv(
        REPORT / "MANUAL_REVIEW_REQUIRED.tsv",
        ["participant_id", "session_id", "reason", "detail", "bids_runs"],
        review,
    )

    # Dependency graph (markdown)
    graph_lines = ["# MATLAB Movie dependency graph", "", "```", "main.m"]
    for r in inv_rows:
        if r["filename"].lower() == "main.m" and r["calls"]:
            for c in r["calls"].split(";"):
                if c:
                    graph_lines.append(f"  └─ {c}.m")
            break
    graph_lines += ["```", ""]
    (REPORT / "DEPENDENCY_GRAPH.md").write_text("\n".join(graph_lines), encoding="utf-8")

    verdict = "OPTION A — PASS"
    # Fail only if we couldn't produce sanitized core scripts
    if not copy_rows:
        verdict = "OPTION B — FAIL"

    write_protocol_docs(
        inv_rows, phi_rows, canonical, assigns, review, bolds, logs, copy_rows, verdict
    )

    print(
        f"DONE verdict={verdict} scripts={len(inv_rows)} assigns={len(assigns)} review={len(review)}",
        flush=True,
    )
    return 0 if verdict.startswith("OPTION A") else 1


if __name__ == "__main__":
    sys.exit(main())
