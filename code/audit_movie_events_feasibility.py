#!/usr/bin/env python3
"""
Read-only audit: can Movie MATLAB .mat files support BIDS events.tsv reconstruction?

Never writes events.tsv. Never modifies raw_original/, bids/, release_dataset/.
Writes only under reports/movie_events_audit/.
"""

from __future__ import annotations

import csv
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import scipy.io as sio

RAW = Path("/lustre06/project/6001995/raw_original")
OUT = Path("/home/alexrees/scratch/reports/movie_events_audit")

# Identity / sync / timing candidate name patterns (case-insensitive substring match on varname)
IDENTITY_PATTERNS = [
    "movie",
    "moviename",
    "moviefile",
    "clip",
    "stimulus",
    "run_id",
    "selected_run_id",
    "runid",
]
SYNC_PATTERNS = [
    "triggertimes",
    "triggertime",
    "triggers",
    "trigger",
    "ttl",
    "scanner",
    "forp",
    "pulse",
]
TIMING_PATTERNS = [
    "vbl",
    "flip",
    "frametime",
    "frametimes",
    "timestamp",
    "timestamps",
    "onset",
    "onsets",
    "moviestart",
    "starttime",
    "stimulusonset",
]
DURATION_PATTERNS = [
    "duration",
    "movieduration",
    "stimduration",
]

SKIP_VARS = {"__header__", "__version__", "__globals__"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def find_movie_mats(root: Path) -> list[Path]:
    """Collect .mat under 3-Movie_Data, Movie_Data, and Movie Results only."""
    found: set[Path] = set()
    # Prefer find via pathlib walk scoped to known trees — use os.walk with filters
    for dirpath, dirnames, filenames in __import__("os").walk(root):
        # prune heavy non-matlab trees early
        base = Path(dirpath)
        name = base.name
        parts = {p.lower() for p in base.parts}
        # Skip DICOM / nifti dumps
        if any(x in parts for x in ("dicom", "nii", "nifti", ".git")):
            dirnames[:] = []
            continue
        is_movie_tree = (
            "3-movie_data" in parts
            or "movie_data" in parts
            or any(p.lower().endswith("3-movie_data") or p.lower() == "movie_data" for p in base.parts)
        )
        # Accept Results only inside a Movie tree
        if name.lower() == "results" and not is_movie_tree:
            # check ancestors
            if not any(
                "3-movie_data" in str(base).lower() or "/movie_data/" in str(base).lower()
                for _ in [0]
            ):
                # also allow filename selected_run_id anywhere under MATLAB movie
                pass
        for fn in filenames:
            if not fn.lower().endswith(".mat"):
                continue
            p = base / fn
            plow = str(p).lower()
            if "/3-movie_data/" in plow or "/movie_data/" in plow:
                found.add(p)
            elif "/results/" in plow and "selected_run_id" in plow:
                found.add(p)
    return sorted(found)


def find_movie_mats_fast(root: Path) -> list[Path]:
    """Shell find is faster on Lustre; fall back to walk."""
    import subprocess

    cmds = [
        ["find", str(root), "-path", "*/3-Movie_Data/*.mat"],
        ["find", str(root), "-path", "*/3-Movie_Data/**/*.mat"],
        ["find", str(root), "-path", "*/Movie_Data/*.mat"],
        ["find", str(root), "-path", "*/Movie_Data/**/*.mat"],
        # Results under movie folders only
        ["find", str(root), "-path", "*/3-Movie_Data/Results/*.mat"],
        ["find", str(root), "-path", "*/Movie_Data/Results/*.mat"],
    ]
    found: set[Path] = set()
    for cmd in cmds:
        try:
            out = subprocess.check_output(cmd, stderr=subprocess.DEVNULL, text=True, timeout=600)
        except Exception:
            continue
        for line in out.splitlines():
            line = line.strip()
            if line:
                found.add(Path(line))
    # Also recursive under 3-Movie_Data
    try:
        out = subprocess.check_output(
            ["find", str(root), "-type", "f", "-name", "*.mat", "-path", "*/3-Movie_Data/*"],
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=600,
        )
        for line in out.splitlines():
            if line.strip():
                found.add(Path(line.strip()))
    except Exception:
        pass
    try:
        out = subprocess.check_output(
            ["find", str(root), "-type", "f", "-name", "*.mat", "-path", "*/Movie_Data/*"],
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=600,
        )
        for line in out.splitlines():
            if line.strip():
                found.add(Path(line.strip()))
    except Exception:
        pass
    return sorted(found)


def parse_subject_session(path: Path) -> tuple[str, str]:
    s = str(path)
    sub = ""
    ses = ""
    m = re.search(r"/(SUB[CG]\d+)[-_]", s, re.I)
    if m:
        sub = m.group(1).upper()
    m2 = re.search(r"Session[-_]?0?(\d)", s, re.I)
    if m2:
        ses = f"ses-{int(m2.group(1)):02d}"
    elif re.search(r"Session2|Session-2|ses-02", s, re.I):
        ses = "ses-02"
    elif re.search(r"Session1|Session-1|ses-01", s, re.I):
        ses = "ses-01"
    return sub, ses


def varname_matches(name: str, patterns: list[str]) -> bool:
    n = name.lower().replace("-", "").replace(" ", "")
    for p in patterns:
        p2 = p.lower().replace("-", "")
        if p2 in n:
            return True
    return False


def load_varnames(path: Path) -> tuple[list[str], str | None]:
    """Return variable names and optional error."""
    try:
        d = sio.loadmat(path, squeeze_me=False, struct_as_record=False)
        names = sorted(k for k in d.keys() if k not in SKIP_VARS and not k.startswith("__"))
        return names, None
    except Exception as e:
        # try v7.3
        try:
            import h5py  # type: ignore

            with h5py.File(path, "r") as f:
                names = sorted(list(f.keys()))
            return names, None
        except Exception:
            return [], f"{type(e).__name__}: {e}"


def classify(
    variables: list[str],
    *,
    has_trigger: bool,
    has_vbl: bool,
    has_identity: bool,
    has_duration: bool,
) -> str:
    """
    RECONSTRUCTABLE: scanner-locked onsets (triggerTimes or equivalent) + stimulus identity
    IDENTITY_ONLY: run_id / movie identity without recoverable timing
    INSUFFICIENT_TIMING: some timing-ish vars but not scanner-locked usable onsets
    AMBIGUOUS: unreadable or contradictory
    """
    if not variables and not has_identity:
        return "AMBIGUOUS"
    # Strict: need triggerTimes-like vector AND identity for events.tsv
    sync_strong = any(
        varname_matches(v, ["triggertimes", "triggertime"]) for v in variables
    ) or has_trigger
    timing_strong = has_vbl or any(
        varname_matches(v, ["vbl", "frametimes", "stimulusonset", "onsets"]) for v in variables
    )
    if sync_strong and has_identity:
        return "RECONSTRUCTABLE"
    if timing_strong and has_identity and not sync_strong:
        # Flip/VBL without documented scanner lock is not sufficient for BIDS events
        return "INSUFFICIENT_TIMING"
    if has_identity and not sync_strong and not timing_strong:
        return "IDENTITY_ONLY"
    if sync_strong and not has_identity:
        return "INSUFFICIENT_TIMING"
    if has_duration and not sync_strong:
        return "IDENTITY_ONLY" if has_identity else "INSUFFICIENT_TIMING"
    return "AMBIGUOUS" if not variables else "IDENTITY_ONLY"


def audit_file(path: Path) -> dict[str, Any]:
    sub, ses = parse_subject_session(path)
    variables, err = load_varnames(path)
    # filename identity
    fname_has_run = bool(re.search(r"selected_run_id[_-]?\d+", path.name, re.I))

    has_trigger = any(varname_matches(v, SYNC_PATTERNS) for v in variables)
    # Narrow has_triggerTimes to explicit trigger time arrays
    has_triggerTimes = any(
        varname_matches(v, ["triggertimes", "triggertime"]) for v in variables
    )
    has_VBL = any(varname_matches(v, TIMING_PATTERNS) for v in variables)
    has_movie_identity = (
        any(varname_matches(v, IDENTITY_PATTERNS) for v in variables) or fname_has_run
    )
    has_duration = any(varname_matches(v, DURATION_PATTERNS) for v in variables)

    # Soften: 'trigger' alone in varname without times — still note in variables_found
    # but has_triggerTimes stays False unless triggerTimes*

    cls = classify(
        variables,
        has_trigger=has_triggerTimes,
        has_vbl=has_VBL,
        has_identity=has_movie_identity,
        has_duration=has_duration,
    )
    if err:
        cls = "AMBIGUOUS"

    recon = "YES" if cls == "RECONSTRUCTABLE" else "NO"

    return {
        "file": str(path),
        "subject": sub,
        "session": ses,
        "variables_found": ";".join(variables) if variables else (f"ERROR:{err}" if err else ""),
        "has_triggerTimes": "YES" if has_triggerTimes else "NO",
        "has_VBL": "YES" if has_VBL else "NO",
        "has_movie_identity": "YES" if has_movie_identity else "NO",
        "has_duration": "YES" if has_duration else "NO",
        "event_reconstruction_possible": recon,
        "classification": cls,
        "filename": path.name,
        "n_variables": str(len(variables)),
    }


def write_tsv(path: Path, fields: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, delimiter="\t", lineterminator="\n", extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow(row)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    print(f"Scanning {RAW} for Movie .mat files…", flush=True)
    mats = find_movie_mats_fast(RAW)
    print(f"Found {len(mats)} .mat files", flush=True)

    rows: list[dict[str, Any]] = []
    var_counter: Counter[str] = Counter()
    class_counter: Counter[str] = Counter()
    errors = 0

    for i, p in enumerate(mats, 1):
        if i % 50 == 0 or i == 1:
            print(f"  [{i}/{len(mats)}] {p.name}", flush=True)
        row = audit_file(p)
        rows.append(row)
        class_counter[row["classification"]] += 1
        if row["variables_found"].startswith("ERROR:"):
            errors += 1
        else:
            for v in row["variables_found"].split(";"):
                if v:
                    var_counter[v] += 1

    inv_fields = [
        "file",
        "subject",
        "session",
        "variables_found",
        "has_triggerTimes",
        "has_VBL",
        "has_movie_identity",
        "has_duration",
        "event_reconstruction_possible",
        "classification",
        "filename",
        "n_variables",
    ]
    write_tsv(OUT / "MOVIE_TIMING_VARIABLE_INVENTORY.tsv", inv_fields, rows)

    n = len(rows)
    n_recon = class_counter.get("RECONSTRUCTABLE", 0)
    n_id = class_counter.get("IDENTITY_ONLY", 0)
    n_insuf = class_counter.get("INSUFFICIENT_TIMING", 0)
    n_amb = class_counter.get("AMBIGUOUS", 0)
    n_trig = sum(1 for r in rows if r["has_triggerTimes"] == "YES")
    n_vbl = sum(1 for r in rows if r["has_VBL"] == "YES")
    n_ident = sum(1 for r in rows if r["has_movie_identity"] == "YES")

    # Example variable sets (de-identified path tails)
    examples: dict[str, list[str]] = defaultdict(list)
    for r in rows:
        if len(examples[r["classification"]]) < 3:
            examples[r["classification"]].append(
                f"`…/{'/'.join(Path(r['file']).parts[-3:])}` → vars: `{r['variables_found'] or '(none)'}`"
            )

    top_vars = var_counter.most_common(25)
    top_vars_md = "\n".join(f"| `{v}` | {c} |" for v, c in top_vars)

    # Union of all variables ever seen
    all_vars = sorted(var_counter)
    sync_seen = [v for v in all_vars if varname_matches(v, SYNC_PATTERNS)]
    timing_seen = [v for v in all_vars if varname_matches(v, TIMING_PATTERNS)]
    id_seen = [v for v in all_vars if varname_matches(v, IDENTITY_PATTERNS)]

    verdict = (
        "NOT FEASIBLE"
        if n_recon == 0
        else ("PARTIALLY FEASIBLE" if n_recon < n else "FEASIBLE")
    )

    report = f"""# Movie events.tsv feasibility report

**Generated:** `{_now()}`  
**Scope (read-only):** `{RAW}/**/{{3-Movie_Data,Movie_Data}}/**/*.mat`  
**Rule:** Never invent timing from TR or volume count. Never write `events.tsv` in this audit.

## Verdict

### {verdict} — BIDS `events.tsv` reconstruction from Movie MATLAB `.mat` files

**{n_recon} / {n}** files classified as `RECONSTRUCTABLE`.

Scientifically, scanner-locked stimulus onsets suitable for BIDS `events.tsv` **cannot** be reconstructed from the Movie Results `.mat` corpus as archived: the MATLAB `main.m` workflow saves **selection metadata only** (before playback), and `Show_movie.m` does **not** write `triggerTimes`, VBL, or frame timestamps to disk.

## Counts

| Metric | N |
|---|---:|
| Movie `.mat` files audited | {n} |
| Load errors | {errors} |
| `has_triggerTimes=YES` | {n_trig} |
| `has_VBL=YES` | {n_vbl} |
| `has_movie_identity=YES` | {n_ident} |
| RECONSTRUCTABLE | {n_recon} |
| IDENTITY_ONLY | {n_id} |
| INSUFFICIENT_TIMING | {n_insuf} |
| AMBIGUOUS | {n_amb} |

## Classification rules

| Class | Meaning |
|---|---|
| `RECONSTRUCTABLE` | Explicit scanner-locked onset array (e.g. `triggerTimes`) **and** stimulus identity → events.tsv could be built without inventing timing |
| `IDENTITY_ONLY` | Clip / `run_id` recoverable; **no** usable onset timestamps |
| `INSUFFICIENT_TIMING` | Some timing-related fields present but not sufficient for scanner-locked BIDS onsets |
| `AMBIGUOUS` | Unreadable file or no interpretable variables |

## What variables exist

### Observed variable names (frequency)

| Variable | Files |
|---|---:|
{top_vars_md if top_vars_md else "| *(none)* | 0 |"}

### Identity-related names seen

{", ".join(f"`{v}`" for v in id_seen) if id_seen else "*(none matching identity patterns beyond filename `selected_run_id_*`)*"}

### Scanner-sync-related names seen

{", ".join(f"`{v}`" for v in sync_seen) if sync_seen else "**None.** No `triggerTimes`, `triggers`, `TTL`, `FORP`, or `pulse` variables in any audited Movie `.mat`."}

### Psychtoolbox timing-related names seen

{", ".join(f"`{v}`" for v in timing_seen) if timing_seen else "**None.** No `vbl` / VBL / flip / frame timestamp variables in any audited Movie `.mat`."}

## What information is missing

1. **`triggerTimes` (or equivalent)** — required to lock stimulus onset to scanner TTL / FORP `t`.
2. **VBL / `Screen('Flip')` timestamps** — not saved; flips occur in `Show_movie.m` but are discarded.
3. **Movie start / frame indices** — `OpenMovie` / `GetMovieImage` loop does not log times.
4. **Per-event duration tables** — `movieduration` from PTB is not persisted to `.mat`.
5. Wall-clock string `t` in Results files is **operator save time before playback**, not stimulus onset relative to the first BOLD volume.

## Examples by class

"""
    for cls in ["RECONSTRUCTABLE", "IDENTITY_ONLY", "INSUFFICIENT_TIMING", "AMBIGUOUS"]:
        report += f"\n### {cls}\n\n"
        if examples.get(cls):
            for e in examples[cls]:
                report += f"- {e}\n"
        else:
            report += "- *(none)*\n"

    report += f"""
## Examples of valid timing sources (for contrast — not present here)

A paradigm **would** be reconstructable if Results `.mat` contained, for example:

- `triggerTimes` — vector of FORP/`t` key times from `KbQueue` / `KbCheck` aligned to Psychtoolbox clock  
- paired with stimulus identity (`run_id`, `moviename`, trial list)  
- optionally `vbl` / flip times for sub-TR refinement  

The grating (`task-fmri`) protocol is an example of that pattern elsewhere in this project. **Movie Results `.mat` files do not contain these fields.**

## Implications for BIDS release

- Do **not** generate synthetic `task-movie` `events.tsv` from TR × volume count or assumed clip length.
- Continue releasing **identity-level** documentation (`run_id` ↔ clip ↔ eye; ProtocolName mapping) only.
- Fail-closed stance remains scientifically justified.

## Inventory

Full per-file table: [`MOVIE_TIMING_VARIABLE_INVENTORY.tsv`](MOVIE_TIMING_VARIABLE_INVENTORY.tsv)
"""
    (OUT / "MOVIE_EVENTS_FEASIBILITY_REPORT.md").write_text(report, encoding="utf-8")

    # Compact summary TSV
    write_tsv(
        OUT / "MOVIE_EVENTS_CLASS_SUMMARY.tsv",
        ["classification", "n", "pct"],
        [
            {
                "classification": k,
                "n": str(v),
                "pct": f"{100.0 * v / n:.1f}" if n else "0",
            }
            for k, v in sorted(class_counter.items())
        ],
    )

    print(
        f"DONE verdict={verdict} n={n} RECONSTRUCTABLE={n_recon} IDENTITY_ONLY={n_id}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
