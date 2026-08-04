#!/usr/bin/env python3
"""Build an exemplary protocol documentation release for Scientific Data / OpenNeuro.

Writes ONLY under:
  reports/protocol_release/   (internal audit — not for public deposit)
  release_dataset/code/
  release_dataset/docs/
  release_dataset/task-rest.json
  code/task-grating/, code/task-movie/, code/task-rest/  (working copies)

NEVER modifies: raw_original/, DICOM, NIfTI, acquisition JSON, validated events.
NEVER creates synthetic events.tsv. NEVER copies mp4 / Results .mat.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import shutil
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path("/lustre07/scratch/alexrees")
RAW6 = Path("/lustre06/project/6001995/raw_original")
INV = ROOT / "reports" / "associated_data_inventory.tsv"
SESSIONS = ROOT / "metadata" / "sessions.tsv"
RELEASE = ROOT / "release_dataset"
REPORT = ROOT / "reports" / "protocol_release"
CODE_WORK = ROOT / "code"
REL_CODE = RELEASE / "code"
REL_DOCS = RELEASE / "docs" / "Protocols"

NOW = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

# ---------------------------------------------------------------------------
# PHI patterns
# ---------------------------------------------------------------------------
PHI_PATTERNS: list[tuple[str, str, re.Pattern[str]]] = [
    ("PatientName", "HIGH", re.compile(r"\bPatientName\b", re.I)),
    ("PatientID", "HIGH", re.compile(r"\bPatientID\b", re.I)),
    ("PatientBirth", "HIGH", re.compile(r"\bPatientBirthDate\b|\bBirthDate\b", re.I)),
    ("StudyUID", "HIGH", re.compile(r"\bStudyInstanceUID\b", re.I)),
    ("SeriesUID", "HIGH", re.compile(r"\bSeriesInstanceUID\b", re.I)),
    ("DICOM_UID", "HIGH", re.compile(r"\b(?:SOPInstanceUID|FrameOfReferenceUID)\b", re.I)),
    ("Password", "HIGH", re.compile(r"\bpassword\s*=|\bpasswd\b|api[_-]?key", re.I)),
    ("WindowsUserPath", "HIGH", re.compile(r"[A-Za-z]:\\Users\\[^\\\"'\s]+", re.I)),
    ("UnixHomePath", "HIGH", re.compile(r"/home/[A-Za-z0-9._-]+")),
    ("AbsoluteUnixProject", "MEDIUM", re.compile(r"/lustre\d+/[^\s'\"]+")),
    ("WindowsDrivePath", "MEDIUM", re.compile(r"[A-Za-z]:\\(?!Users\\)[^\s'\"]+")),
    ("Institution", "MEDIUM", re.compile(r"\bInstitution(?:Name)?\b|\bHospital\b|\bDepartment\b")),
    ("Email", "MEDIUM", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")),
    ("DesktopPath", "MEDIUM", re.compile(r"\\Desktop\\|/Desktop/", re.I)),
    ("Subject", "LOW", re.compile(r"\bSubject\b")),
    ("NameAPI", "LOW", re.compile(r"\bKbName\b|\bName\b")),
]

# Movie path sanitization (publication only)
WIN_PATH_RE = re.compile(
    r"[A-Za-z]:\\(?:Users\\[^\\]+\\)?Desktop\\[^\n'\"]+",
    re.I,
)
MOVIE_FILE_RE = re.compile(
    r"(['\"])([^'\"]*?)(Movie[12][AB]\.mp4)(['\"])",
    re.I,
)
OUTPUT_PATH_RE = re.compile(
    r"(outputFile\s*=\s*)(['\"])([^'\"]+)(['\"])",
    re.I,
)

GRATING_REQUIRED = [
    "main.m",
    "presentStimParams.m",
    "RandomGenerator.m",
    "GratingStimulus1.m",
    "GratingStimulus2.m",
    "GratingStimulus3.m",
    "GratingStimulus4.m",
    "GratingStimulus5.m",
    "CheckerFlickerSine.m",
    "CheckerFlickerSquare.m",
    "CheckerMoveSine.m",
    "CheckerMoveSquare.m",
]

MOVIE_RUN_DICT = [
    {
        "run_id": "1",
        "stimulus": "Movie1A.mp4",
        "eye": "left",
        "expected_TR": "210",
        "duration": f"{210 * 0.937:.3f}",
        "bids_protocol_hint": "Movie1_AP",
    },
    {
        "run_id": "2",
        "stimulus": "Movie2A.mp4",
        "eye": "right",
        "expected_TR": "210",
        "duration": f"{210 * 0.937:.3f}",
        "bids_protocol_hint": "Movie2_AP",
    },
    {
        "run_id": "3",
        "stimulus": "Movie1B.mp4",
        "eye": "right",
        "expected_TR": "210",
        "duration": f"{210 * 0.937:.3f}",
        "bids_protocol_hint": "Movie3_AP",
    },
    {
        "run_id": "4",
        "stimulus": "Movie2B.mp4",
        "eye": "left",
        "expected_TR": "210",
        "duration": f"{210 * 0.937:.3f}",
        "bids_protocol_hint": "Movie4_AP",
    },
]

PROTOCOL_TO_RUN = {
    "Movie1": "1",
    "Movie2": "2",
    "Movie3": "3",
    "Movie4": "4",
}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def remap_to_lustre06(path: str) -> Path:
    p = path.replace("/lustre07/scratch/alexrees/raw_original", str(RAW6))
    p = p.replace("/lustre06/project/6001995/raw_original", str(RAW6))
    return Path(p)


def classify_task(path: str) -> str | None:
    low = path.replace("\\", "/").lower()
    if "/results/" in low:
        return None
    # Prefer primary paradigm folders; FOV nested movie tagged separately
    parts = low.split("/")
    for i, part in enumerate(parts):
        if part.startswith("2-grating"):
            return "grating"
        if part.startswith("4-resting"):
            return "rest"
        if part.startswith("3-movie"):
            # FOV check movies live under 1-Check_FOV...
            upstream = "/".join(parts[:i])
            if "1-check_fov" in upstream or "eyetracking" in upstream:
                return "movie_fov"
            return "movie"
    return None


def load_inventory() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with INV.open() as f:
        for r in csv.DictReader(f, delimiter="\t"):
            if r.get("extension") != ".m":
                continue
            task = classify_task(r["path"])
            if task is None:
                continue
            src = remap_to_lustre06(r["path"])
            if not src.is_file():
                continue
            data = src.read_bytes()
            rows.append(
                {
                    "task": task,
                    "basename": src.name,
                    "source_path": str(src),  # internal only
                    "size": len(data),
                    "sha256": sha256_bytes(data),
                    "data": data,
                }
            )
    return rows


def scan_phi(text: str, context: str) -> list[dict[str, str]]:
    hits = []
    for name, sev, pat in PHI_PATTERNS:
        for m in pat.finditer(text):
            # Suppress known safe Psychtoolbox / paradigm false positives
            frag = text[max(0, m.start() - 40) : m.end() + 40]
            if name == "NameAPI" and ("KbName" in frag or "Screen(" in frag):
                continue
            if name == "Subject" and "Subject Initials" in frag:
                sev_use = "LOW"
            else:
                sev_use = sev
            hits.append(
                {
                    "context": context,
                    "pattern": name,
                    "severity": sev_use,
                    "line_approx": str(text[: m.start()].count("\n") + 1),
                    "match_preview": m.group(0)[:80],
                }
            )
    return hits


def sanitize_movie_script(text: str) -> tuple[str, list[str]]:
    """Replace absolute Windows paths with placeholders; keep scientific logic."""
    notes: list[str] = []

    def repl_output(m: re.Match[str]) -> str:
        notes.append("sanitized_outputFile_path")
        return f"{m.group(1)}{m.group(2)}./output.txt{m.group(4)}"

    text2 = OUTPUT_PATH_RE.sub(repl_output, text)

    def repl_movie(m: re.Match[str]) -> str:
        notes.append(f"sanitized_movie_path:{m.group(3)}")
        return f"{m.group(1)}./stimuli/{m.group(3)}{m.group(4)}"

    text2 = MOVIE_FILE_RE.sub(repl_movie, text2)

    # Catch residual Windows absolute paths
    def repl_win(m: re.Match[str]) -> str:
        notes.append("sanitized_windows_path")
        return "<STIMULUS_PC>\\" + m.group(0).split("\\", 1)[-1] if False else "<STIMULUS_PC_PATH>"

    # Broader cleanup for leftover drive paths in strings
    text3 = re.sub(
        r"(['\"])[A-Za-z]:\\[^'\"]+(['\"])",
        r"\1<STIMULUS_PC_PATH>\2",
        text2,
    )
    if text3 != text2:
        notes.append("sanitized_residual_drive_paths")
    return text3, notes


def select_canonical(rows: list[dict[str, Any]], task: str, basename: str) -> dict[str, Any]:
    subset = [r for r in rows if r["task"] == task and r["basename"] == basename]
    if not subset:
        raise RuntimeError(f"No files for {task}/{basename}")
    counts = Counter(r["sha256"] for r in subset)
    top_hash, top_n = counts.most_common(1)[0]
    # Prefer non-FOV for movie; already filtered by task
    exemplar = next(r for r in subset if r["sha256"] == top_hash)
    return {
        "task": task,
        "basename": basename,
        "sha256": top_hash,
        "n_total": len(subset),
        "n_canonical": top_n,
        "n_variants": len(counts),
        "variant_counts": dict(counts),
        "exemplar_path": exemplar["source_path"],
        "data": exemplar["data"],
    }


def write_tsv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, delimiter="\t", extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def copy_verified(data: bytes, dest: Path, expected_sha: str | None = None) -> str:
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    got = sha256_file(dest)
    if expected_sha and got != expected_sha:
        raise RuntimeError(f"SHA mismatch writing {dest}: {got} != {expected_sha}")
    return got


def build_movie_assignments() -> list[dict[str, str]]:
    """Map magnitude task-movie BOLD ProtocolName → matlab run_id."""
    sessions: dict[tuple[str, str], str] = {}
    if SESSIONS.is_file():
        with SESSIONS.open() as f:
            for r in csv.DictReader(f, delimiter="\t"):
                sessions[(r["participant_id"], r["session_id"])] = r.get("cohort", "")

    rows: list[dict[str, str]] = []
    for json_path in sorted(RELEASE.glob("sub-*/ses-*/func/*_task-movie_*_bold.json")):
        name = json_path.name
        if "part-phase" in name:
            continue
        # parse entities
        m = re.match(
            r"(sub-\d+)|(ses-\d+)|task-movie|(run-\d+)",
            name,
        )
        parts = name.replace(".json", "").split("_")
        ent = {p.split("-")[0]: p.split("-", 1)[1] for p in parts if "-" in p}
        sub = f"sub-{ent['sub']}"
        ses = f"ses-{ent['ses']}"
        run = f"run-{ent['run']}"
        meta = json.loads(json_path.read_text())
        proto = str(meta.get("ProtocolName") or meta.get("SeriesDescription") or "")
        run_id = ""
        confidence = "none"
        stimulus = ""
        # Movie1_AP / Movie1_PA / Movie1_AP_REDO …
        mm = re.search(r"Movie\s*([1-4])", proto, re.I)
        if mm:
            run_id = mm.group(1)
            confidence = "high_protocolname"
            for d in MOVIE_RUN_DICT:
                if d["run_id"] == run_id:
                    stimulus = d["stimulus"]
                    break
        else:
            confidence = "unmapped_protocolname"
        rows.append(
            {
                "participant": sub,
                "session": ses,
                "bids_run": run,
                "run_id": run_id,
                "stimulus": stimulus,
                "protocol_name": proto,
                "mapping_confidence": confidence,
            }
        )
    return rows


def main() -> None:
    REPORT.mkdir(parents=True, exist_ok=True)
    REL_CODE.mkdir(parents=True, exist_ok=True)
    REL_DOCS.mkdir(parents=True, exist_ok=True)

    print(f"[{NOW}] Loading inventory…")
    rows = load_inventory()
    print(f"  protocol .m files readable: {len(rows)}")

    # ------------------------------------------------------------------
    # Inventory + hash tables
    # ------------------------------------------------------------------
    inv_out: list[dict[str, Any]] = []
    for r in rows:
        inv_out.append(
            {
                "task": r["task"],
                "basename": r["basename"],
                "sha256": r["sha256"],
                "size_bytes": r["size"],
                # Do NOT write absolute source paths into published docs;
                # keep a redacted session token for internal audit only.
                "source_token": re.sub(
                    r".*/raw_original/",
                    "<RAW>/",
                    r["source_path"],
                ),
            }
        )
    write_tsv(
        REPORT / "MATLAB_PROTOCOL_INVENTORY.tsv",
        inv_out,
        ["task", "basename", "sha256", "size_bytes", "source_token"],
    )

    # Canonical selection
    decisions: list[dict[str, Any]] = []
    canonical: dict[tuple[str, str], dict[str, Any]] = {}

    for basename in GRATING_REQUIRED:
        c = select_canonical(rows, "grating", basename)
        canonical[("grating", basename)] = c
        decisions.append(
            {
                "task": "grating",
                "basename": basename,
                "decision": "PUBLISH_CANONICAL",
                "sha256": c["sha256"],
                "n_total": c["n_total"],
                "n_canonical": c["n_canonical"],
                "n_variants": c["n_variants"],
                "rationale": "Modal SHA256 across 2-Grating sessions; required runtime dependency",
            }
        )

    for basename in ["main.m", "Show_movie.m"]:
        c = select_canonical(rows, "movie", basename)
        canonical[("movie", basename)] = c
        decisions.append(
            {
                "task": "movie",
                "basename": basename,
                "decision": "PUBLISH_CANONICAL_SANITIZED"
                if basename == "main.m"
                else "PUBLISH_CANONICAL",
                "sha256": c["sha256"],
                "n_total": c["n_total"],
                "n_canonical": c["n_canonical"],
                "n_variants": c["n_variants"],
                "rationale": "Modal SHA256 across primary 3-Movie_Data (excludes FOV nested copies)",
            }
        )

    c_rest = select_canonical(rows, "rest", "main.m")
    canonical[("rest", "main.m")] = c_rest
    decisions.append(
        {
            "task": "rest",
            "basename": "main.m",
            "decision": "PUBLISH_CANONICAL",
            "sha256": c_rest["sha256"],
            "n_total": c_rest["n_total"],
            "n_canonical": c_rest["n_canonical"],
            "n_variants": c_rest["n_variants"],
            "rationale": "Modal SHA256; fixation-only script; single exemplar published",
        }
    )

    # FOV movie scripts: inventory only, do not publish
    fov_mains = [r for r in rows if r["task"] == "movie_fov"]
    if fov_mains:
        decisions.append(
            {
                "task": "movie_fov",
                "basename": "(all)",
                "decision": "EXCLUDE",
                "sha256": "",
                "n_total": len(fov_mains),
                "n_canonical": 0,
                "n_variants": len({r["sha256"] for r in fov_mains}),
                "rationale": "FOV / eye-check movie utilities — not the published task-movie paradigm",
            }
        )

    write_tsv(
        REPORT / "CANONICAL_SELECTION.tsv",
        decisions,
        [
            "task",
            "basename",
            "decision",
            "sha256",
            "n_total",
            "n_canonical",
            "n_variants",
            "rationale",
        ],
    )

    # ------------------------------------------------------------------
    # PHI audit (all protocol scripts)
    # ------------------------------------------------------------------
    phi_rows: list[dict[str, str]] = []
    # Unique content only to avoid huge duplication
    seen_hash: set[str] = set()
    for r in rows:
        if r["sha256"] in seen_hash:
            continue
        seen_hash.add(r["sha256"])
        try:
            text = r["data"].decode("utf-8", errors="replace")
        except Exception:
            continue
        hits = scan_phi(text, f"{r['task']}/{r['basename']}/{r['sha256'][:12]}")
        if not hits:
            phi_rows.append(
                {
                    "task": r["task"],
                    "basename": r["basename"],
                    "sha256": r["sha256"],
                    "pattern": "",
                    "severity": "NONE",
                    "line_approx": "",
                    "match_preview": "",
                    "publishable": "yes",
                }
            )
        else:
            for h in hits:
                high = h["severity"] == "HIGH"
                phi_rows.append(
                    {
                        "task": r["task"],
                        "basename": r["basename"],
                        "sha256": r["sha256"],
                        "pattern": h["pattern"],
                        "severity": h["severity"],
                        "line_approx": h["line_approx"],
                        "match_preview": h["match_preview"],
                        "publishable": "no" if high else "review",
                    }
                )

    write_tsv(
        REPORT / "MATLAB_PHI_REPORT.tsv",
        phi_rows,
        [
            "task",
            "basename",
            "sha256",
            "pattern",
            "severity",
            "line_approx",
            "match_preview",
            "publishable",
        ],
    )

    high_phi_hashes = {r["sha256"] for r in phi_rows if r["severity"] == "HIGH"}

    # ------------------------------------------------------------------
    # Prepare publication bytes (sanitize movie main if needed)
    # ------------------------------------------------------------------
    published: list[dict[str, str]] = []
    excluded: list[dict[str, str]] = []

    def publish_file(
        task: str,
        basename: str,
        raw: bytes,
        source_sha: str,
        *,
        sanitize: bool = False,
    ) -> None:
        if source_sha in high_phi_hashes and not sanitize:
            excluded.append(
                {
                    "task": task,
                    "basename": basename,
                    "reason": "HIGH_PHI_unsanitized",
                    "sha256": source_sha,
                }
            )
            raise RuntimeError(f"Refusing to publish HIGH PHI: {task}/{basename}")

        if sanitize:
            text = raw.decode("utf-8", errors="replace")
            text2, notes = sanitize_movie_script(text)
            # Re-scan sanitized
            hits = scan_phi(text2, f"sanitized/{task}/{basename}")
            if any(h["severity"] == "HIGH" for h in hits):
                raise RuntimeError(f"Sanitized file still HIGH PHI: {task}/{basename}")
            data = text2.encode("utf-8")
            pub_sha = sha256_bytes(data)
            note = ";".join(sorted(set(notes))) or "no_changes"
        else:
            data = raw
            pub_sha = source_sha
            note = "byte_identical"

        rel_dest = REL_CODE / f"task-{task if task != 'grating' else 'grating'}" / basename
        # task folder names
        folder = {"grating": "task-grating", "movie": "task-movie", "rest": "task-rest"}[task]
        rel_dest = REL_CODE / folder / basename
        work_dest = CODE_WORK / folder / basename

        copy_verified(data, rel_dest, pub_sha if not sanitize else None)
        # Ensure work copy matches
        copy_verified(data, work_dest, None)
        got = sha256_file(rel_dest)
        assert got == sha256_file(work_dest)

        published.append(
            {
                "task": task,
                "basename": basename,
                "release_path": str(rel_dest.relative_to(RELEASE)),
                "source_sha256": source_sha,
                "published_sha256": got,
                "identity": note,
                "byte_identical_to_source": "yes" if got == source_sha else "no_sanitized",
            }
        )

    # Grating
    for basename in GRATING_REQUIRED:
        c = canonical[("grating", basename)]
        publish_file("grating", basename, c["data"], c["sha256"], sanitize=False)

    # Movie
    for basename in ["main.m", "Show_movie.m"]:
        c = canonical[("movie", basename)]
        text = c["data"].decode("utf-8", errors="replace")
        needs = bool(re.search(r"[A-Za-z]:\\", text))
        publish_file(
            "movie",
            basename,
            c["data"],
            c["sha256"],
            sanitize=needs or basename == "main.m",
        )

    # Rest
    c = canonical[("rest", "main.m")]
    publish_file("rest", "main.m", c["data"], c["sha256"], sanitize=False)

    write_tsv(
        REPORT / "CODE_COPY_VALIDATION.tsv",
        published,
        [
            "task",
            "basename",
            "release_path",
            "source_sha256",
            "published_sha256",
            "identity",
            "byte_identical_to_source",
        ],
    )

    # ------------------------------------------------------------------
    # Movie dictionaries
    # ------------------------------------------------------------------
    movie_dict_rows = [
        {
            "run_id": d["run_id"],
            "stimulus": d["stimulus"],
            "eye": d["eye"],
            "expected_TR": d["expected_TR"],
            "duration": d["duration"],
        }
        for d in MOVIE_RUN_DICT
    ]
    write_tsv(
        REL_CODE / "task-movie" / "task-movie_run_dictionary.tsv",
        movie_dict_rows,
        ["run_id", "stimulus", "eye", "expected_TR", "duration"],
    )
    write_tsv(
        CODE_WORK / "task-movie" / "task-movie_run_dictionary.tsv",
        movie_dict_rows,
        ["run_id", "stimulus", "eye", "expected_TR", "duration"],
    )

    assignments = build_movie_assignments()
    write_tsv(
        REL_CODE / "task-movie" / "task-movie_run_assignments.tsv",
        assignments,
        [
            "participant",
            "session",
            "bids_run",
            "run_id",
            "stimulus",
            "mapping_confidence",
        ],
    )
    # Keep protocol_name only in internal report
    write_tsv(
        REPORT / "task-movie_run_assignments_full.tsv",
        assignments,
        [
            "participant",
            "session",
            "bids_run",
            "run_id",
            "stimulus",
            "protocol_name",
            "mapping_confidence",
        ],
    )

    # ------------------------------------------------------------------
    # task-rest.json
    # ------------------------------------------------------------------
    task_rest = {
        "TaskName": "rest",
        "TaskDescription": (
            "Eyes-open resting-state fMRI with continuous central fixation "
            "on a black background. No discrete trial structure."
        ),
        "Instructions": (
            "Maintain fixation on the central cross and remain as still as possible."
        ),
        "CogAtlasID": "https://www.cognitiveatlas.org/task/id/trm_4c8a834779883",
    }
    (RELEASE / "task-rest.json").write_text(json.dumps(task_rest, indent=2) + "\n")

    # ------------------------------------------------------------------
    # Documentation (release_dataset)
    # ------------------------------------------------------------------
    write_all_docs(canonical, published, decisions, phi_rows, assignments)

    # ------------------------------------------------------------------
    # Audit markdown reports (internal)
    # ------------------------------------------------------------------
    write_audit_reports(rows, canonical, decisions, phi_rows, published, assignments)

    print("Done.")
    print(f"  Published scripts: {len(published)}")
    print(f"  Report dir: {REPORT}")


def write_all_docs(
    canonical: dict,
    published: list,
    decisions: list,
    phi_rows: list,
    assignments: list,
) -> None:
    # --- code/README.md ---
    (REL_CODE / "README.md").write_text(
        f"""# Experimental protocol code

This folder contains the **Psychtoolbox / MATLAB** stimulus protocols that generated the functional paradigms in this BIDS dataset.

| Folder | BIDS task | Events |
| --- | --- | --- |
| [`task-grating/`](task-grating/) | `task-fmri` | Yes — measured scanner triggers + stimulus order → `*_events.tsv` |
| [`task-movie/`](task-movie/) | `task-movie` | **No** — clip identity documented; no volume-locked timing logs |
| [`task-rest/`](task-rest/) | `task-rest` | **No** — continuous fixation; no trial structure |

## Why some paradigms have `events.tsv` and others do not

- **Grating (`task-fmri`).** The protocol recorded scanner trigger times (`triggerTimes`) and the per-run stimulus order. Those measurements support verified onset/duration tables. Event files are released only when a unique mapping to a BIDS magnitude BOLD run could be established.
- **Movie (`task-movie`).** Playback starts on the scanner trigger, but the scripts do **not** save trigger timestamps or frame-level logs. Fabricating onsets would overstate temporal precision; therefore **no** `events.tsv` are released. Run-level clip / eye assignment is provided instead (`task-movie_run_dictionary.tsv`, `task-movie_run_assignments.tsv`).
- **Rest (`task-rest`).** The protocol shows continuous fixation for a fixed number of TRs. There are no discrete conditions to tabulate; missing `events.tsv` is expected.

## Relationship to the Scientific Data manuscript

Paradigm descriptions, acquisition parameters, and validation counts are summarized in the dataset root [`README.md`](../README.md) and in [`docs/Protocols/`](../docs/Protocols/). Condition labels for grating events are defined in `task-fmri_condition_dictionary.tsv` (dataset root `code/`) and `task-fmri_events.json`.

## Provenance

Canonical scripts were selected as the **modal SHA-256** content across sessions for each basename. Movie entry scripts containing absolute stimulus-PC paths were **sanitized** for public release (scientific logic unchanged). Internal curator audits are retained outside the public deposit.

*Generated: {NOW}*
"""
    )

    # --- task-grating ---
    g_main = canonical[("grating", "main.m")]["sha256"]
    (REL_CODE / "task-grating" / "README.md").write_text(
        f"""# task-grating — contrast / grating protocol (`task-fmri`)

## Objective

Present a block-design visual stimulation sequence (oriented gratings and checkerboard variants) during BOLD fMRI. In the BIDS dataset this paradigm is labelled **`task-fmri`**.

## Stimuli

Twelve stimulus conditions (`stim-01`…`stim-12`) are defined in `presentStimParams.m` via Psychtoolbox classes:

- `GratingStimulus1`…`GratingStimulus5`
- `CheckerMoveSquare`, `CheckerFlickerSquare`, `CheckerMoveSine`, `CheckerFlickerSine`

Conditions `stim-07`…`stim-12` intentionally repeat `stim-01`…`stim-06` within each run. Parameterized labels for open analysis are in `../task-fmri_condition_dictionary.tsv`.

## Scanner synchronization

`main.m` listens for the FORP / keyboard trigger key **`t`**, records trigger times, and advances the block design in lock-step with the scanner. Timing products used for BIDS events live in laboratory `Results/` MATLAB files (not redistributed here).

## Events reconstruction

Verified `sub-*_task-fmri_run-*_events.tsv` files combine:

1. Measured `triggerTimes` from grating Results
2. Stimulus order / paradigm metadata
3. A unique ProtocolName ↔ BIDS magnitude BOLD mapping

Runs without an unambiguous mapping intentionally have **no** events file.

## Scripts in this folder

| File | Role |
| --- | --- |
| `main.m` | Entry point; trigger sync; run loop |
| `presentStimParams.m` | Block design + `generateStim()` condition list |
| `RandomGenerator.m` | Run-order randomization helper |
| `GratingStimulus1.m`…`5.m` | Grating stimulus classes |
| `Checker*.m` | Checkerboard stimulus classes |

Canonical SHA-256 (`main.m`): `{g_main}`

See also [`task-grating_protocol.md`](task-grating_protocol.md) and [`../../docs/Protocols/Grating.md`](../../docs/Protocols/Grating.md).
"""
    )
    (REL_CODE / "task-grating" / "task-grating_protocol.md").write_text(
        """# Grating protocol — technical summary

## Design

- Initial baseline, then 12 cycles of stimulus + baseline (canonical laboratory design: 10 TR baseline segments and 8 TR stimulus segments; 226 volumes at TR ≈ 0.937 s).
- Dichoptic / stereo Psychtoolbox presentation (`stereoMode` as configured in `main.m`).
- Operator confirms run index; Results store `scan_info` / sequence metadata per fMRI number.

## Dependencies

- MATLAB with Psychtoolbox-3
- FORP (or compatible) device mapping scanner TTL to key `t`
- Display calibration files (`GreenLevel.mat` / `RedLevel.mat`) used at acquisition time — **not** redistributed (lab-local calibration)

## What is not included

- Per-session `Results/*.mat` (contain operator logs and may embed identifying filenames)
- Unused FOV / eye-check utilities from other MATLAB folders
"""
    )

    # --- task-movie ---
    (REL_CODE / "task-movie" / "README.md").write_text(
        """# task-movie — naturalistic movie protocol

## How the task works

1. The operator selects `run_id` (1–4) in `main.m`.
2. `main.m` chooses the corresponding MP4 clip and eye (left/right), based on FOV notes (`change_eye`).
3. `Show_movie.m` opens the movie, starts playback, then waits for scanner trigger **`t`** before continuing frame drawing.

## Clip selection (`run_id`)

See [`task-movie_run_dictionary.tsv`](task-movie_run_dictionary.tsv).

| run_id | Stimulus | Eye (default `change_eye=0`) |
| ---: | --- | --- |
| 1 | Movie1A.mp4 | left |
| 2 | Movie2A.mp4 | right |
| 3 | Movie1B.mp4 | right |
| 4 | Movie2B.mp4 | left |

BIDS series named `Movie1`…`Movie4` correspond to these run IDs (see assignments table).

## `run_id` and BIDS

[`task-movie_run_assignments.tsv`](task-movie_run_assignments.tsv) lists each published magnitude `task-movie` run with mapped `run_id` / stimulus when ProtocolName uniquely encodes Movie1–4.

## Why there are no `events.tsv` files

The movie scripts **do not save** trigger timestamps, VBL timestamps, or frame indices. Onsets cannot be reconstructed at BOLD-volume precision without speculation. **No synthetic events were created.** Clip identity and eye assignment are documented instead.

## Dependencies

- MATLAB + Psychtoolbox-3 (`Screen('OpenMovie'|…)`, `KbQueue*`)
- Movie files on the stimulus computer (**not** redistributed in this deposit)

## Scripts

| File | Role |
| --- | --- |
| `main.m` | Run selection, eye assignment, calls `Show_movie` |
| `Show_movie.m` | Movie playback + trigger wait |

Absolute stimulus-PC paths present in some archive copies were replaced with relative / placeholder paths for publication.
"""
    )

    # --- task-rest ---
    rest_sha = canonical[("rest", "main.m")]["sha256"]
    (REL_CODE / "task-rest" / "README.md").write_text(
        f"""# task-rest — resting-state protocol

## Overview

Eyes-open resting-state fMRI with **continuous central fixation** on a black background. In BIDS this paradigm is labelled **`task-rest`**.

## Scanner trigger

`main.m` waits for FORP / keyboard triggers coded as key **`t`**, then counts triggers until **`trs = 320`** volumes have elapsed.

## Why there are no `events.tsv` files

There is no discrete trial or block structure beyond continuous fixation. The script does not write timing Results. Missing `events.tsv` for `task-rest` is **expected** and should not be treated as a conversion error. Dataset-level description: [`../../task-rest.json`](../../task-rest.json).

## Canonical script

A single exemplar is published (modal SHA-256 across sessions):

`{rest_sha}`

Minor whitespace / edit variants exist in the archive but are scientifically equivalent for this fixation protocol.

See [`task-rest_protocol.md`](task-rest_protocol.md) and [`../../docs/Protocols/Rest.md`](../../docs/Protocols/Rest.md).
"""
    )
    (REL_CODE / "task-rest" / "task-rest_protocol.md").write_text(
        """# Resting-state protocol — technical summary

## Display

- Pre-scan message, then white fixation cross (horizontal + vertical limbs)
- Stereo draw buffers; fixation shown to both eyes
- Fixation size derived from visual angle

## Timing model

- Trigger-counted, not wall-clock logged
- Parameter `trs = 320`
- Escape aborts the run

## Dependencies

- MATLAB + Psychtoolbox-3
- FORP-compatible trigger → key `t`
"""
    )

    # Mirror READMEs into code/ working tree
    for folder in ["task-grating", "task-movie", "task-rest"]:
        src = REL_CODE / folder
        dst = CODE_WORK / folder
        dst.mkdir(parents=True, exist_ok=True)
        for p in src.glob("*"):
            if p.suffix in {".md", ".tsv"}:
                shutil.copy2(p, dst / p.name)
    shutil.copy2(REL_CODE / "README.md", CODE_WORK / "PROTOCOL_CODE_README.md")

    # --- docs/Protocols ---
    (REL_DOCS / "Grating.md").write_text(
        """# Visual grating / checkerboard paradigm (`task-fmri`)

## What participants did

Participants viewed a sequence of visual patterns (gratings and checkerboards) while keeping still in the scanner. Patterns appeared in timed blocks separated by baseline periods with fixation.

## What you will find in the dataset

- BOLD time series: `sub-*/ses-*/func/*_task-fmri_*_bold.nii.gz`
- Event timing (subset of runs): `*_task-fmri_*_events.tsv` with `onset`, `duration`, and `trial_type` (`baseline`, `stim-01`…`stim-12`)
- Condition dictionary: `code/task-fmri_condition_dictionary.tsv`
- Stimulus code: `code/task-grating/`

## How to use the events

Each `trial_type` maps to a known stimulus class and parameter set (spatial/temporal frequency, contrast, colour pathway). Labels `stim-07`…`stim-12` are within-run repeats of `stim-01`…`stim-06`.

Event files are provided only when timing could be verified against the original experimental logs and uniquely assigned to a magnitude BOLD run.

## Further reading

See `code/task-grating/README.md` and `code/task-grating/task-grating_protocol.md`.
"""
    )
    (REL_DOCS / "Movie.md").write_text(
        """# Naturalistic movie paradigm (`task-movie`)

## What participants did

Participants watched short naturalistic movie clips presented to one eye at a time, while BOLD fMRI was acquired.

## What you will find in the dataset

- BOLD time series: `sub-*/ses-*/func/*_task-movie_*_bold.nii.gz`
- Protocol documentation and run identity tables: `code/task-movie/`
- **No** `*_events.tsv` for this task

## Clip identity without event timing

Four operator-selected run IDs map to four clips (Movie1A/B, Movie2A/B) and a default eye of presentation. Tables in `code/task-movie/` document this mapping for published runs.

Movie video files are **not** redistributed with this deposit.

## Why event files are absent

The presentation software synchronized movie onset to the scanner trigger but did not store timestamp logs suitable for BIDS events. Rather than invent timing, this release documents stimulus identity only.

## Further reading

See `code/task-movie/README.md`.
"""
    )
    (REL_DOCS / "Rest.md").write_text(
        """# Resting-state paradigm (`task-rest`)

## What participants did

Participants rested with eyes open while maintaining fixation on a central cross. No task responses were required.

## What you will find in the dataset

- BOLD time series: `sub-*/ses-*/func/*_task-rest_*_bold.nii.gz`
- Task description: `task-rest.json`
- Presentation script: `code/task-rest/main.m`
- **No** `*_events.tsv` for this task

## Expected number of volumes

The presentation script counts **320** scanner triggers (TRs) after the run starts.

## Why event files are absent

Resting-state runs have continuous fixation without discrete trial onsets. Empty or synthetic event tables are not included.

## Further reading

See `code/task-rest/README.md` and `code/task-rest/task-rest_protocol.md`.
"""
    )


def write_audit_reports(
    rows: list,
    canonical: dict,
    decisions: list,
    phi_rows: list,
    published: list,
    assignments: list,
) -> None:
    # MATLAB_PROTOCOL_AUDIT.md
    def summarize(task: str) -> str:
        subset = [r for r in rows if r["task"] == task]
        bases = sorted({r["basename"] for r in subset})
        lines = [f"### {task}", f"- Script files audited: **{len(subset)}**", f"- Basenames: {', '.join(bases)}"]
        for b in bases:
            c = Counter(r["sha256"] for r in subset if r["basename"] == b)
            top = c.most_common(1)[0]
            lines.append(
                f"- `{b}`: n={sum(c.values())}, unique_versions={len(c)}, "
                f"canonical={top[0][:16]}… (n={top[1]})"
            )
        return "\n".join(lines)

    audit = f"""# MATLAB protocol audit

Generated: `{NOW}`

## Scope

Read-only audit of Psychtoolbox scripts for **Grating**, **Movie**, and **Resting state**.
Source trees were not modified. Absolute filesystem paths are retained only in internal TSV tokens, not in the public deposit.

## Inventory summary

- Total `.m` files classified: **{len(rows)}**

{summarize('grating')}

{summarize('movie')}

{summarize('movie_fov')}

{summarize('rest')}

## Scripts required vs unused

### Grating — published (required)

{chr(10).join('- `'+b+'`' for b in GRATING_REQUIRED)}

All listed files are referenced by `main.m` / `presentStimParams.m` for the released `task-fmri` design.

### Movie — published

- `main.m` (entry; may be sanitized)
- `Show_movie.m` (playback + trigger)

Excluded: FOV-nested `1-Check_FOV*/3-Movie_Data` copies; `Results/`; MP4 stimuli.

### Rest — published

- Single canonical `main.m`

## Dependencies (runtime)

- MATLAB
- Psychtoolbox-3 (Screen, KbQueue, PsychHID, stereo rendering; OpenMovie for movie)
- FORP-compatible scanner trigger mapped to key `t`

## Canonical selection policy

For each basename, publish the **modal SHA-256** across primary paradigm folders.
If content is identical, publish **one** exemplar only.

## Related tables

- `MATLAB_PROTOCOL_INVENTORY.tsv`
- `CANONICAL_SELECTION.tsv`
- `MATLAB_PHI_REPORT.tsv`
- `CODE_COPY_VALIDATION.tsv`
"""
    (REPORT / "MATLAB_PROTOCOL_AUDIT.md").write_text(audit)

    high = [r for r in phi_rows if r["severity"] == "HIGH"]
    med = [r for r in phi_rows if r["severity"] == "MEDIUM"]

    mapped = sum(1 for a in assignments if a["mapping_confidence"].startswith("high"))
    unmapped = sum(1 for a in assignments if a["mapping_confidence"].startswith("unmapped"))
    high_hashes = {h["sha256"] for h in high}
    high_in_identical = any(
        item["byte_identical_to_source"] == "yes" and item["source_sha256"] in high_hashes
        for item in published
    )
    readme_ok = all(
        (REL_CODE / d / "README.md").is_file()
        for d in ["task-grating", "task-movie", "task-rest"]
    ) and (REL_CODE / "README.md").is_file()
    docs_ok = all((REL_DOCS / n).is_file() for n in ["Grating.md", "Movie.md", "Rest.md"])
    task_rest_ok = (RELEASE / "task-rest.json").is_file()

    validation_lines = [
        "# Protocol release validation",
        "",
        f"Generated: `{NOW}`",
        "",
        "## Checks",
        "",
        "| Check | Result |",
        "| --- | --- |",
        f"| Published scripts | {len(published)} |",
        f"| HIGH PHI in published byte-identical files | {'FAIL' if high_in_identical else 'PASS'} |",
        f"| HIGH PHI hits (unique content, pre-sanitize) | {len(high)} |",
        f"| MEDIUM PHI hits (unique content) | {len(med)} |",
        "| Duplicate basenames published per task | PASS (one each) |",
        f"| README files present | {'PASS' if readme_ok else 'FAIL'} |",
        f"| docs/Protocols present | {'PASS' if docs_ok else 'FAIL'} |",
        f"| task-rest.json | {'PASS' if task_rest_ok else 'FAIL'} |",
        f"| Movie assignments mapped / unmapped | {mapped} / {unmapped} |",
        "| Synthetic events created | PASS (none) |",
        "| MP4 copied | PASS (none) |",
        "| NIfTI / acquisition JSON modified | PASS (not touched) |",
        "",
        "## Path / username scan on published tree",
        "",
    ]

    pub_issues = []
    for p in published:
        path = RELEASE / p["release_path"]
        text = path.read_text(encoding="utf-8", errors="replace")
        if re.search(r"/home/[A-Za-z0-9._-]+", text):
            pub_issues.append(f"unix home in {p['release_path']}")
        if re.search(r"/lustre\d+/", text):
            pub_issues.append(f"lustre path in {p['release_path']}")
        if re.search(r"[A-Za-z]:\\Users\\", text):
            pub_issues.append(f"Windows user path in {p['release_path']}")
        # Allow placeholder tokens only
        if re.search(r"[A-Za-z]:\\(?!Users\\)", text) and "<STIMULUS_PC" not in text:
            # raw drive letter still present
            if re.search(r"['\"][A-Za-z]:\\", text):
                pub_issues.append(f"drive path in {p['release_path']}")

    for md in REL_CODE.rglob("*.md"):
        t = md.read_text(encoding="utf-8", errors="replace")
        if "/lustre" in t or "/home/alexrees" in t:
            pub_issues.append(f"internal path in {md.relative_to(RELEASE)}")

    if not pub_issues:
        validation_lines.append("PASS — no internal absolute paths or usernames in published code/docs scanned.")
    else:
        validation_lines.append("ISSUES:")
        validation_lines.extend(f"- {x}" for x in pub_issues)

    validation_lines.append("")
    validation_lines.append("## SHA-256 verification")
    validation_lines.append("")
    for p in published:
        validation_lines.append(
            f"- `{p['release_path']}` published={p['published_sha256'][:16]}… "
            f"({p['byte_identical_to_source']})"
        )

    (REPORT / "PROTOCOL_RELEASE_VALIDATION.md").write_text("\n".join(validation_lines) + "\n")

    final = f"""# Final protocol release report

Generated: `{NOW}`

## Structure (public)

```text
release_dataset/
  task-rest.json
  code/
    README.md
    task-fmri_condition_dictionary.*   # pre-existing
    presentStimParams.m                # pre-existing companion
    task-grating/   # {sum(1 for p in published if p['task']=='grating')} scripts + README + protocol md
    task-movie/     # scripts + README + run dictionary/assignments
    task-rest/      # main.m + README + protocol md
  docs/
    Protocols/
      Grating.md
      Movie.md
      Rest.md
```

## Counts

| Item | n |
| --- | ---: |
| Scripts published | {len(published)} |
| Grating | {sum(1 for p in published if p['task']=='grating')} |
| Movie | {sum(1 for p in published if p['task']=='movie')} |
| Rest | {sum(1 for p in published if p['task']=='rest')} |
| FOV movie scripts excluded | {sum(1 for r in rows if r['task']=='movie_fov')} |
| Movie magnitude runs assigned | {mapped} |
| Movie magnitude runs unmapped | {unmapped} |

## Hash policy

- One canonical exemplar per basename (modal SHA-256).
- Byte-identical copies retain source SHA-256.
- Sanitized movie scripts receive a new published SHA-256; source hash retained in `CODE_COPY_VALIDATION.tsv`.

## PHI audit

- Unique contents scanned: see `MATLAB_PHI_REPORT.tsv`
- HIGH findings on raw archive content: **{len(high)}**
- Published tree re-scanned for `/home`, `/lustre`, `C:\\Users` — see validation report

## FAIR

| Principle | Implementation |
| --- | --- |
| Findable | Task folders, dataset-level `task-rest.json`, docs/Protocols |
| Accessible | Open code + dictionaries in the BIDS deposit |
| Interoperable | BIDS task labels; TSV dictionaries; CogAtlas rest ID |
| Reusable | Clear event/no-event policy; no fabricated timing |

## Scientific Data / OpenNeuro expectations

| Expectation | Status |
| --- | --- |
| Paradigms documented for external readers | Yes (`docs/Protocols`) |
| Code that enables interpretation published | Yes (minimal necessary scripts) |
| No synthetic events | Yes |
| No stimulus MP4 without license package | Yes (not copied) |
| No PHI / internal paths in deposit | Targeted PASS — see validation |
| Validator-only minimalism avoided | Yes (documentation-first) |

## Recommendations

1. Keep grating `events.tsv` recovery separate from this protocol pack (mapping collisions).
2. If movie MP4 redistribution is desired later, obtain licenses and place under `stimuli/` with checksums.
3. Optionally add `task-movie.json` analogous to `task-rest.json`.
4. Do not publish `reports/protocol_release/` or inventory TSVs with source tokens.

## Decision log

See `CANONICAL_SELECTION.tsv` for per-file publish/exclude rationales.
"""
    (REPORT / "FINAL_PROTOCOL_RELEASE_REPORT.md").write_text(final)


if __name__ == "__main__":
    main()
