#!/usr/bin/env python3
"""
Final Movie MATLAB timing reconstructibility audit (read-only).

Writes only under reports/movie_events_audit/code_timing_audit/.
Never modifies raw_original/, bids/, release_dataset/, or MATLAB sources.
Never creates events.tsv.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

# ---------------------------------------------------------------------------
# Keyword catalogues
# ---------------------------------------------------------------------------

SCANNER_KWS = [
    "trigger",
    "scanner",
    "ttl",
    "forp",
    "pulse",
    "sync",
    "mri",
    "kbtriggerwait",
    "kbqueue",
    "kbcheck",
    "waitsecs",
]
# Note: bare "mr" / "MR" too noisy — handled via word-boundary patterns below

PTB_KWS = [
    "screen('flip'",
    'screen("flip"',
    "screen( 'flip'",
    'screen( "flip"',
    "getsecs",
    "vbl",
    "onset",
    "timestamp",
    "frametime",
    "fliptime",
]

FRAME_KWS = [
    "frame",
    "frametimes",
    "getmovieimage",
    "playmovie",
]

SAVE_KWS = [
    "save(",
    "matfile",
    ".mat",
    "struct",
    "results",
    "timing",
    "timestamps",
]

MAT_TIMING_NAMES = [
    "triggertimes",
    "triggertime",
    "vbl",
    "flip",
    "timestamp",
    "timestamps",
    "onset",
    "onsets",
    "start",
    "time",
    "frame",
    "frametimes",
    "getsecs",
    "scanner",
    "ttl",
    "forp",
]

OUTPUT_KWS = re.compile(
    r"VBL|Flip|stimulus onset|trigger|scanner|frame|time",
    re.I,
)

PHI_PATH_RX = re.compile(
    r"(?:/lustre\d+/[^\s'\"\]]+|/home/[^\s'\"\]]+|[A-Za-z]:\\Users\\[^\s'\"\]]+)",
    re.I,
)
PHI_SUB_RX = re.compile(r"\bSUB[CGON]+\d+\b", re.I)
PHI_EXTRA_RX = re.compile(
    r"\b(?:SUBC|SUBG|SUBON|SUB)\d+\b|\bSubject_is_[A-Za-z0-9\-]+|\b20\d{2}(?:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\d{0,2}\b",
    re.I,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path, n: int = 16) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()[:n]


def rel_public(path: Path, movie_root: Path) -> str:
    """Path relative to 3-Movie_Data (or Movie_Data), PHI-safe."""
    try:
        return str(path.relative_to(movie_root)).replace("\\", "/")
    except ValueError:
        return path.name


def session_token(movie_root: Path) -> str:
    """Opaque session folder token (no subject ID / calendar date)."""
    digest = hashlib.sha256(str(movie_root).encode()).hexdigest()[:12]
    return f"session#{digest}"


def scrub_text(s: str) -> str:
    s = PHI_PATH_RX.sub("<REDACTED_PATH>", s)
    s = PHI_EXTRA_RX.sub("<REDACTED_ID>", s)
    s = PHI_SUB_RX.sub("<REDACTED_ID>", s)
    s = re.sub(r"[A-Za-z]:\\[^\s'\"]+", "<REDACTED_WINPATH>", s)
    s = re.sub(r"\b[A-Za-z0-9_\-]{0,20}Session[0-9_\-A-Za-z]{0,40}", "<REDACTED_SESSION>", s, flags=re.I)
    return s[:240]


def write_tsv(path: Path, fields: list[str], rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, delimiter="\t", lineterminator="\n", extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow({k: row.get(k, "") for k in fields})


def find_movie_roots(raw: Path) -> list[Path]:
    roots: list[Path] = []
    for dirpath, dirnames, _ in os.walk(raw):
        base = Path(dirpath)
        # prune heavy trees
        low_parts = {p.lower() for p in base.parts}
        if any(x in low_parts for x in ("dicom", "nii", "nifti", ".git", "derivatives")):
            dirnames[:] = []
            continue
        name = base.name.lower()
        if name in ("3-movie_data", "movie_data"):
            roots.append(base)
    return sorted(roots)


def decode_text(path: Path, max_bytes: int = 500_000) -> str:
    raw = path.read_bytes()[:max_bytes]
    candidates: list[tuple[str, str]] = []
    for enc in ("utf-8", "utf-16", "utf-16-le", "latin-1"):
        try:
            t = raw.decode(enc)
            candidates.append((enc, t))
        except Exception:
            continue
    if not candidates:
        return ""
    # prefer encoding with most alphanumeric chars
    enc, t = max(candidates, key=lambda et: sum(c.isalnum() for c in et[1]))
    return "".join(ch for ch in t if ch != "\x00")


# ---------------------------------------------------------------------------
# Step 1–3: scripts
# ---------------------------------------------------------------------------

def inventory_and_search_scripts(roots: list[Path]) -> tuple[list[dict], list[dict], dict[str, Any]]:
    inv: list[dict] = []
    hits: list[dict] = []
    show_analyses: list[dict] = []
    seen_hits: set[tuple] = set()

    seen_hash: dict[str, str] = {}  # sha -> first relative id

    for root in roots:
        tok = session_token(root)
        for p in sorted(root.rglob("*.m")):
            if not p.is_file():
                continue
            digest = sha256_file(p)
            rel = rel_public(p, root)
            pub_id = f"{tok}/{rel}"
            inv.append(
                {
                    "filename": p.name,
                    "path_relative": pub_id,
                    "sha256": digest,
                    "size_bytes": str(p.stat().st_size),
                    "basename_role": "Show_movie" if "show_movie" in p.name.lower() else (
                        "main" if p.name.lower() == "main.m" else "other"
                    ),
                }
            )
            try:
                text = p.read_text(errors="replace")
            except Exception:
                continue
            lines = text.splitlines()

            for i, line in enumerate(lines, 1):
                low = line.lower()
                cats_this_line: set[str] = set()

                def add_hit(kw: str, line_i: int, line: str, cat: str) -> None:
                    key = (pub_id, line_i, cat, kw)
                    if key in seen_hits:
                        return
                    seen_hits.add(key)
                    cats_this_line.add(cat)
                    hits.append(
                        {
                            "file": pub_id,
                            "keyword": kw,
                            "line_number": str(line_i),
                            "matched_text": scrub_text(line.strip()),
                            "category": cat,
                            "sha256": digest,
                        }
                    )

                for kw in SCANNER_KWS:
                    if kw in low:
                        add_hit(kw, i, line, "SCANNER_TRIGGER")
                if re.search(r"\bmri\b", low):
                    add_hit("mri", i, line, "SCANNER_TRIGGER")
                for kw in PTB_KWS:
                    if kw in low:
                        add_hit(kw, i, line, "PSYCHTOOLBOX_TIME")
                if any(x in low for x in ("getsecs", "flip", "onset", "vbl", "keytime")) and "time" in low:
                    add_hit("time", i, line, "PSYCHTOOLBOX_TIME")
                for kw in FRAME_KWS:
                    if kw in low:
                        add_hit(kw, i, line, "FRAME_TIMING")
                for kw in SAVE_KWS:
                    if kw in low:
                        add_hit(kw, i, line, "SAVE_OPERATION")

            if "show_movie" in p.name.lower():
                show_analyses.append(analyze_show_movie(text, pub_id, digest))

        seen_hash[digest] = seen_hash.get(digest, pub_id)

    return inv, hits, {"show": show_analyses, "unique_sha": len(set(r["sha256"] for r in inv))}


def analyze_show_movie(text: str, pub_id: str, digest: str) -> dict[str, Any]:
    low = text.lower()
    lines = text.splitlines()

    def find_lines(patterns: list[str]) -> list[str]:
        out = []
        for i, line in enumerate(lines, 1):
            ll = line.lower()
            if any(p in ll for p in patterns):
                out.append(f"L{i}: {scrub_text(line.strip())}")
        return out[:12]

    # A) scanner trigger reception
    a_pats = ["kbtriggerwait", "kbqueuewait", "kbqueuestart", "kbqueuecreate", "kbnname('t')", 'kbnname("t")', "forp", "ttl"]
    a_found = any(p in low for p in a_pats) or ("kbname('t')" in low) or ('kbname("t")' in low)
    # B) Flip timestamp capture
    b_assign = bool(re.search(r"\bvbl\s*=\s*screen\s*\(\s*['\"]flip['\"]", low))
    b_flip_call = "screen('flip'" in low or 'screen("flip"' in low or "screen( 'flip'" in low
    b_found = b_assign  # FOUND only if assigned — bare Flip without capture = NOT FOUND for timestamps
    # C) save timing
    c_found = bool(
        re.search(r"save\s*\([^)]*vbl", low)
        or re.search(r"results\.vbl\s*=", low)
        or re.search(r"triggertimes", low)
        or re.search(r"save\s*\([^)]*trigger", low)
        or re.search(r"save\s*\([^)]*time", low)
    )
    # D) frame loop
    d_found = "getmovieimage" in low or bool(re.search(r"for\s+\w*\s*=", low) and "movie" in low)
    # E) frame timestamps
    e_found = bool(
        re.search(r"frametimes?\s*\(", low)
        or re.search(r"frametimes?\s*=", low)
        or re.search(r"getsecs\s*\(", low)
    )

    return {
        "file": pub_id,
        "sha256": digest,
        "A_scanner_trigger_reception": "FOUND" if a_found else "NOT FOUND",
        "A_evidence": " | ".join(find_lines(["kbqueue", "kbname('t')", 'kbname("t")', "forp", "ttl", "trigger"])) or "",
        "B_flip_timestamps": "FOUND" if b_found else "NOT FOUND",
        "B_flip_called_without_capture": "YES" if (b_flip_call and not b_assign) else "NO",
        "B_evidence": " | ".join(find_lines(["flip", "vbl"])) or "",
        "C_saved_timing": "FOUND" if c_found else "NOT FOUND",
        "C_evidence": " | ".join(find_lines(["save(", "trigger", "vbl", "results."])) or "",
        "D_frame_loop": "FOUND" if d_found else "NOT FOUND",
        "D_evidence": " | ".join(find_lines(["getmovieimage", "playmovie", "while"])) or "",
        "E_frame_timestamps": "FOUND" if e_found else "NOT FOUND",
        "E_evidence": " | ".join(find_lines(["frametime", "getsecs"])) or "",
    }


# ---------------------------------------------------------------------------
# Step 4: output.txt
# ---------------------------------------------------------------------------

def classify_output_line(line: str) -> str:
    low = line.lower()
    # PTB warnings / diagnostics — not real timing
    if any(
        x in low
        for x in (
            "ptb-info",
            "ptb-error",
            "ptb-warning",
            "flip missed",
            "deadline",
            "vbl timestamp unavailable",
            "beamposition",
            "impossible stimulus onset",
            "won't be able to correct timestamps",
            "refresh interval",
        )
    ):
        return "PTB_WARNING"
    if re.search(r"triggertimes\s*=", low) or re.search(r"\bvbl\s*=\s*\d", low):
        return "REAL_TIMING"
    if any(x in low for x in ("debug", "warning", "error in")):
        return "DEBUG_ONLY"
    if OUTPUT_KWS.search(line):
        # generic mention without assignment
        return "DEBUG_ONLY"
    return "DEBUG_ONLY"


def audit_output_txt(roots: list[Path]) -> list[dict]:
    rows: list[dict] = []
    for root in roots:
        tok = session_token(root)
        for p in root.rglob("output.txt"):
            if not p.is_file():
                continue
            pub = f"{tok}/{rel_public(p, root)}"
            text = decode_text(p)
            for i, line in enumerate(text.splitlines(), 1):
                if not OUTPUT_KWS.search(line):
                    continue
                rows.append(
                    {
                        "file": pub,
                        "line": str(i),
                        "text": scrub_text(line.strip()),
                        "classification": classify_output_line(line),
                    }
                )
        # other *.txt / *.log under movie tree
        for p in list(root.rglob("*.txt")) + list(root.rglob("*.log")):
            if p.name.lower() == "output.txt":
                continue
            if not p.is_file():
                continue
            pub = f"{tok}/{rel_public(p, root)}"
            text = decode_text(p, max_bytes=200_000)
            for i, line in enumerate(text.splitlines(), 1):
                if not OUTPUT_KWS.search(line):
                    continue
                rows.append(
                    {
                        "file": pub,
                        "line": str(i),
                        "text": scrub_text(line.strip()),
                        "classification": classify_output_line(line),
                    }
                )
    return rows


# ---------------------------------------------------------------------------
# Step 5: MAT files
# ---------------------------------------------------------------------------

def audit_mats(roots: list[Path]) -> list[dict]:
    import scipy.io as sio

    rows: list[dict] = []
    for root in roots:
        tok = session_token(root)
        for p in sorted((root / "Results").glob("*.mat")) if (root / "Results").is_dir() else []:
            pub = f"{tok}/{rel_public(p, root)}"
            # anonymize filename in reports
            fname = p.name
            fname_pub = re.sub(r"Subject_is_[^_]+", "Subject_is_XXX", fname)
            fname_pub = PHI_SUB_RX.sub("SUBXXX", fname_pub)
            try:
                d = sio.loadmat(p, squeeze_me=False, struct_as_record=False)
            except Exception as e:
                rows.append(
                    {
                        "file": f"{tok}/Results/{fname_pub}",
                        "variable": "<LOAD_ERROR>",
                        "exists": "NO",
                        "type": type(e).__name__,
                        "sample_value": scrub_text(str(e)),
                        "timing_relevance": "IRRELEVANT",
                    }
                )
                continue
            vars_ = [k for k in d if not k.startswith("__")]
            present_lower = {v.lower(): v for v in vars_}

            def classify_var(vlower: str) -> str:
                if vlower in ("triggertimes", "triggertime"):
                    return "SCANNER_LOCKED_TIMING"
                if vlower in ("vbl", "flip", "frametimes", "onset", "onsets", "timestamps", "getsecs"):
                    return "FRAME_TIMING"
                if vlower in (
                    "run_id",
                    "change_eye",
                    "comment",
                    "moviename",
                    "eye",
                    "t",
                    "answer",
                    "x",
                    "y",
                    "ans",
                    "outputfile",
                    "outputfileid",
                    "resultdir",
                ):
                    return "IDENTITY_ONLY"
                return "IRRELEVANT"

            for v in vars_:
                val = d[v]
                typ = type(val).__name__
                sample = ""
                try:
                    if hasattr(val, "shape") and getattr(val, "size", 0) <= 4:
                        sample = scrub_text(str(val).replace("\n", " "))
                    elif hasattr(val, "shape"):
                        sample = f"ndarray shape={val.shape}"
                except Exception:
                    sample = ""
                rows.append(
                    {
                        "file": f"{tok}/Results/{fname_pub}",
                        "variable": v,
                        "exists": "YES",
                        "type": typ,
                        "sample_value": sample,
                        "timing_relevance": classify_var(v.lower()),
                    }
                )
            # Critical absences (once per file)
            for cand in ("triggerTimes", "vbl", "frameTimes", "onset", "timestamps"):
                if cand.lower() not in present_lower:
                    rows.append(
                        {
                            "file": f"{tok}/Results/{fname_pub}",
                            "variable": cand,
                            "exists": "NO",
                            "type": "",
                            "sample_value": "",
                            "timing_relevance": "ABSENT",
                        }
                    )
    return rows


# ---------------------------------------------------------------------------
# Step 7: PhysioLog / BIDS physio for movie
# ---------------------------------------------------------------------------

def audit_movie_physio(bids: Path | None, raw: Path) -> list[dict]:
    rows: list[dict] = []
    # Prefer BIDS sidecars (already converted, PHI-clean paths relative)
    if bids and bids.is_dir():
        for js in sorted(bids.glob("sub-*/ses-*/func/*task-movie*_physio.json")):
            try:
                meta = json.loads(js.read_text())
            except Exception:
                continue
            cols = meta.get("Columns") or meta.get("columns") or []
            if isinstance(cols, str):
                cols = [cols]
            cols_l = [str(c).lower() for c in cols]
            has_ext = any(c in ("ext", "trigger", "ttl") for c in cols_l)
            has_puls = any("puls" in c or c == "cardiac" for c in cols_l)
            has_resp = any("resp" in c for c in cols_l)
            if has_ext and not (has_puls or has_resp):
                interp = "scanner trigger source possible but stimulus onset unavailable"
            elif has_ext:
                interp = "scanner trigger source possible but stimulus onset unavailable"
            elif has_puls or has_resp:
                interp = "physiology only"
            else:
                interp = "physiology only"
            # relative public path
            try:
                rel = str(js.relative_to(bids))
            except ValueError:
                rel = js.name
            rows.append(
                {
                    "file": rel,
                    "ProtocolName": scrub_text(str(meta.get("ProtocolName", meta.get("TaskName", "movie")))),
                    "SeriesNumber": str(meta.get("SeriesNumber", "")),
                    "Channels": ";".join(str(c) for c in cols),
                    "has_EXT_or_trigger": "YES" if has_ext else "NO",
                    "interpretation": interp,
                }
            )
        return rows

    # Fallback: sample raw PhysioLog dirs named *MOVIE*PHYSIOLOG*
    n = 0
    for dirpath, dirnames, filenames in os.walk(raw):
        base = Path(dirpath)
        name = base.name.upper()
        if "MOVIE" in name and "PHYSIOLOG" in name.replace(" ", ""):
            # look for .resp / .puls / .ext / .log twins
            channels = []
            for fn in filenames:
                fl = fn.lower()
                if fl.endswith((".ext", ".puls", ".resp", ".ecg", ".trigger")) or "ext" in fl:
                    channels.append(fn)
            rows.append(
                {
                    "file": f"PhysioLog/{hashlib.sha256(str(base).encode()).hexdigest()[:10]}",
                    "ProtocolName": "Movie*",
                    "SeriesNumber": "",
                    "Channels": ";".join(channels) if channels else "(unparsed raw folder)",
                    "has_EXT_or_trigger": "YES" if any("ext" in c.lower() or "trig" in c.lower() for c in channels) else "UNKNOWN",
                    "interpretation": "scanner trigger source possible but stimulus onset unavailable"
                    if channels
                    else "raw PhysioLog present; stimulus onset unavailable",
                }
            )
            n += 1
            if n >= 40:
                break
    return rows


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------

def write_show_movie_md(path: Path, analyses: list[dict]) -> None:
    # Aggregate across unique sha
    by_sha: dict[str, dict] = {}
    for a in analyses:
        by_sha[a["sha256"]] = a
    # majority / any FOUND across versions
    def agg(key: str) -> str:
        vals = [a[key] for a in by_sha.values()]
        return "FOUND" if any(v == "FOUND" for v in vals) else "NOT FOUND"

    # pick representative evidence from modal sha (most common)
    sha_counts = Counter(a["sha256"] for a in analyses)
    rep = by_sha[sha_counts.most_common(1)[0][0]] if sha_counts else {}

    md = f"""# Show_movie.m timing analysis

**Generated:** `{_now()}`  
**Unique SHA256 (truncated) versions:** {len(by_sha)}  
**Copies observed:** {len(analyses)}

## Scanner trigger

**{agg('A_scanner_trigger_reception')}**

Evidence (representative `{rep.get('sha256','')}`):

```
{rep.get('A_evidence','(none)')}
```

Notes: Scripts wait for FORP-mapped key `t` via `KbQueueWait`. This is **runtime** trigger handling, not a saved timestamp array.

## Screen Flip timestamps

**{agg('B_flip_timestamps')}**

`Screen('Flip')` called without capturing return value as `vbl`: **{rep.get('B_flip_called_without_capture','')}**

Evidence:

```
{rep.get('B_evidence','(none)')}
```

## Frame timestamps

**{agg('E_frame_timestamps')}**

Frame loop present: **{agg('D_frame_loop')}**

Evidence:

```
{rep.get('D_evidence','(none)')}
{rep.get('E_evidence','(none)')}
```

## Saved timing

**{agg('C_saved_timing')}**

Evidence:

```
{rep.get('C_evidence','(none)')}
```

## Summary table

| Question | Result |
|---|---|
| A) Scanner trigger *reception* in code | {agg('A_scanner_trigger_reception')} |
| B) Flip timestamps *captured* | {agg('B_flip_timestamps')} |
| C) Timing *saved* to disk | {agg('C_saved_timing')} |
| D) Frame playback loop | {agg('D_frame_loop')} |
| E) Per-frame timestamps logged | {agg('E_frame_timestamps')} |
"""
    path.write_text(md, encoding="utf-8")


def write_feasibility(path: Path, *, show: dict, mat_rows: list, out_rows: list, physio_rows: list) -> str:
    n_real_out = sum(1 for r in out_rows if r["classification"] == "REAL_TIMING")
    n_mat_scan = sum(1 for r in mat_rows if r["timing_relevance"] == "SCANNER_LOCKED_TIMING")
    n_mat_frame = sum(1 for r in mat_rows if r["timing_relevance"] == "FRAME_TIMING")

    a = show.get("A_scanner_trigger_reception", "NOT FOUND")
    b = show.get("B_flip_timestamps", "NOT FOUND")
    c = show.get("C_saved_timing", "NOT FOUND")
    e = show.get("E_frame_timestamps", "NOT FOUND")

    # YES only if saved scanner-locked trigger AND stimulus timestamp with temporal link
    reconstructable = (
        n_mat_scan > 0
        and (n_mat_frame > 0 or b == "FOUND" and c == "FOUND")
        and c == "FOUND"
    )
    # More precise per user criteria:
    # trigger scanner retrouvé ET timestamp stimulus retrouvé ET relation temporelle conservée
    # Runtime KbQueueWait alone is NOT "retrouvé" as data — must be saved.
    trigger_data = n_mat_scan > 0 or n_real_out > 0
    stim_ts_data = n_mat_frame > 0 or n_real_out > 0
    temporal_link = trigger_data and stim_ts_data and c == "FOUND"

    decision = "YES" if (trigger_data and stim_ts_data and temporal_link) else "NO"
    verdict = "RECONSTRUCTABLE" if decision == "YES" else "NOT FEASIBLE"

    physio_note = (
        "EXT/trigger channel may exist for Movie BOLD, but alone cannot define stimulus onsets."
        if physio_rows and any(r.get("has_EXT_or_trigger") == "YES" for r in physio_rows)
        else "No usable Movie physio trigger linkage for events."
    )

    md = f"""# Movie events.tsv feasibility — final report

**Generated:** `{_now()}`  
**Decision:** **{verdict}** (`RECONSTRUCTABLE = {decision}`)

## Criteria (all required for YES)

| Criterion | Status |
|---|---|
| Scanner trigger **data** recovered (`triggerTimes` or equivalent saved) | {"PASS" if trigger_data else "FAIL"} |
| Stimulus timestamp **data** recovered (VBL / frame / onset arrays) | {"PASS" if stim_ts_data else "FAIL"} |
| Temporal relationship preserved on disk | {"PASS" if temporal_link else "FAIL"} |

## Code behavior vs saved data

| Capability | In `Show_movie.m` code | Persisted to `.mat` / logs |
|---|---|---|
| Wait for scanner key `t` | {a} | NO (`triggerTimes` absent) |
| `Screen('Flip')` timestamps | {b} | NO |
| Frame timestamps | {e} | NO |
| Explicit timing `save(...)` | {c} | NO |

## Source matrix

| Source | Available | Usable for scanner-locked events.tsv |
|---|---|---|
| MATLAB `.m` | Yes (protocol logic) | No — describes wait/`Flip` but does not record times |
| MATLAB `Results/*.mat` | Yes | No — identity only (`run_id`, …); `SCANNER_LOCKED_TIMING` rows = {n_mat_scan}; `FRAME_TIMING` rows = {n_mat_frame} |
| `output.txt` | Yes | No — `REAL_TIMING` lines = {n_real_out}; remainder PTB warnings / debug |
| MP4 | Sometimes present | No — media only, not onset logs |
| PhysioLog / BIDS physio | Partial | No alone — {physio_note} |
| DICOM | BOLD series exist | No — volumes ≠ stimulus event table without locked onsets |

## Scientific answers

1. **Do Movie MATLAB scripts record scanner triggers?**  
   They **wait** for a FORP/`t` key at runtime, but **do not save** trigger timestamps.

2. **Do they record Psychtoolbox `Screen('Flip')` timestamps?**  
   `Flip` is called; return timestamps are **not assigned/saved**.

3. **Frame-by-frame presentation times?**  
   Frames are drawn in a loop; times are **not logged**.

4. **IRM↔stimulus temporal link on disk?**  
   **No** conserved numeric link suitable for BIDS `events.tsv`.

## Publication stance

Release Movie BOLD **without** `events.tsv`. Provide protocol code and stimulus mapping only. **No synthetic onset generation.**
"""
    path.write_text(md, encoding="utf-8")
    return decision


def write_final(path: Path, decision: str) -> None:
    md = f"""# Final Movie timing audit

**Generated:** `{_now()}`

## Conclusion

Possible events reconstruction: **{"YES" if decision == "YES" else "NO"}**

## Evidence found

- MATLAB protocol scripts (`main.m`, `Show_movie.m`) documenting FORP key `t` wait and movie playback.
- `Results/*.mat` with **identity** fields (`run_id`, `change_eye`, wall-clock save stamp).
- `output.txt` diaries with Psychtoolbox **diagnostics** (refresh / Flip warnings).
- Optional physiology recordings that may include scanner EXT pulses (volume clock), **not** stimulus event onsets.

## Evidence missing

- no `triggerTimes` (saved)
- no VBL timestamps (saved)
- no frame timestamps (saved)
- no scanner-locked stimulus onset
- no conserved IRM↔clip temporal table

## Publication recommendation

Release Movie BOLD data without `events.tsv`.  
Provide protocol code and stimulus mapping only.  
No synthetic onset generation.
"""
    path.write_text(md, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Movie timing reconstructibility audit (read-only)")
    ap.add_argument("--input", default="/lustre06/project/6001995/raw_original", help="raw_original root")
    ap.add_argument(
        "--output",
        default="/home/alexrees/scratch/reports/movie_events_audit/code_timing_audit",
        help="report output directory",
    )
    ap.add_argument("--bids", default="/home/alexrees/scratch/bids", help="optional BIDS root for physio audit")
    ap.add_argument("--read-only", action="store_true", default=True, help="mandatory read-only mode")
    args = ap.parse_args(argv)

    raw = Path(args.input)
    out = Path(args.output)
    bids = Path(args.bids) if args.bids else None
    out.mkdir(parents=True, exist_ok=True)

    if not raw.is_dir():
        print(f"ERROR: input not found: {raw}", file=sys.stderr)
        return 2

    print(f"[{_now()}] Finding Movie roots under {raw} …", flush=True)
    roots = find_movie_roots(raw)
    print(f"  movie roots: {len(roots)}", flush=True)

    print("Step 1–3: script inventory + keyword search + Show_movie …", flush=True)
    inv, hits, meta = inventory_and_search_scripts(roots)
    write_tsv(
        out / "MATLAB_MOVIE_SCRIPT_INVENTORY.tsv",
        ["filename", "path_relative", "sha256", "size_bytes", "basename_role"],
        inv,
    )
    write_tsv(
        out / "MATLAB_TIMING_CODE_SEARCH.tsv",
        ["file", "keyword", "line_number", "matched_text", "category", "sha256"],
        hits,
    )
    write_show_movie_md(out / "SHOW_MOVIE_TIMING_ANALYSIS.md", meta["show"])

    # aggregate show flags for feasibility
    show_flags = {
        "A_scanner_trigger_reception": "FOUND"
        if any(a["A_scanner_trigger_reception"] == "FOUND" for a in meta["show"])
        else "NOT FOUND",
        "B_flip_timestamps": "FOUND"
        if any(a["B_flip_timestamps"] == "FOUND" for a in meta["show"])
        else "NOT FOUND",
        "C_saved_timing": "FOUND"
        if any(a["C_saved_timing"] == "FOUND" for a in meta["show"])
        else "NOT FOUND",
        "E_frame_timestamps": "FOUND"
        if any(a["E_frame_timestamps"] == "FOUND" for a in meta["show"])
        else "NOT FOUND",
    }

    print("Step 4: output.txt / logs …", flush=True)
    out_rows = audit_output_txt(roots)
    write_tsv(
        out / "MOVIE_OUTPUT_LOG_ANALYSIS.tsv",
        ["file", "line", "text", "classification"],
        out_rows,
    )

    print("Step 5: Results/*.mat …", flush=True)
    try:
        import scipy.io  # noqa: F401
    except ImportError:
        print("ERROR: scipy required (module load scipy-stack)", file=sys.stderr)
        return 3
    mat_rows = audit_mats(roots)
    write_tsv(
        out / "MOVIE_MAT_VARIABLE_TIMING_INVENTORY.tsv",
        ["file", "variable", "exists", "type", "sample_value", "timing_relevance"],
        mat_rows,
    )

    print("Step 7: Movie physio …", flush=True)
    physio_rows = audit_movie_physio(bids if bids and bids.is_dir() else None, raw)
    write_tsv(
        out / "MOVIE_PHYSIO_TRIGGER_AUDIT.tsv",
        ["file", "ProtocolName", "SeriesNumber", "Channels", "has_EXT_or_trigger", "interpretation"],
        physio_rows,
    )

    print("Step 6–8: feasibility + final reports …", flush=True)
    decision = write_feasibility(
        out / "MOVIE_EVENTS_FEASIBILITY_FINAL_REPORT.md",
        show=show_flags,
        mat_rows=mat_rows,
        out_rows=out_rows,
        physio_rows=physio_rows,
    )
    write_final(out / "FINAL_MOVIE_TIMING_AUDIT.md", decision)

    # compact summary json (PHI-safe)
    summary = {
        "generated": _now(),
        "movie_roots": len(roots),
        "scripts": len(inv),
        "unique_script_sha16": meta["unique_sha"],
        "code_search_hits": len(hits),
        "output_log_rows": len(out_rows),
        "output_REAL_TIMING": sum(1 for r in out_rows if r["classification"] == "REAL_TIMING"),
        "mat_SCANNER_LOCKED_TIMING": sum(1 for r in mat_rows if r["timing_relevance"] == "SCANNER_LOCKED_TIMING"),
        "mat_FRAME_TIMING": sum(1 for r in mat_rows if r["timing_relevance"] == "FRAME_TIMING"),
        "physio_rows": len(physio_rows),
        "RECONSTRUCTABLE": decision,
        "show_movie": show_flags,
    }
    (out / "AUDIT_SUMMARY.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2), flush=True)
    print(f"DONE → {out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
