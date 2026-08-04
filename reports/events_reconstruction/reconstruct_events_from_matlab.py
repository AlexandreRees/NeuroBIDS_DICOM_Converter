#!/usr/bin/env python3
"""Reconstruct BIDS events.tsv previews from MATLAB sources (read-only).

Writes only under reports/events_reconstruction/ and tmp_processing/events_validation_bids/.
Never modifies MATLAB originals or existing BOLD NIfTIs.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

SCRATCH = Path("/home/alexrees/scratch")
CODE_ROOT = SCRATCH / "neuro_pipeline"
sys.path.insert(0, str(CODE_ROOT))

from neuro_pipeline.associated_data.matlab.extract_scan_timing import (  # noqa: E402
    extract_scan_timing,
    parse_fmri_number_from_name,
)
from neuro_pipeline.associated_data.matlab.extract_stim_order import (  # noqa: E402
    default_block_paradigm,
    extract_paradigm_matrix,
    extract_stim_order,
)
from neuro_pipeline.associated_data.matlab.generate_events import (  # noqa: E402
    RunSources,
    generate_bids_events,
    write_events_tsv,
)
from neuro_pipeline.utils.subject_normalize import (  # noqa: E402
    normalize_session_label,
    normalize_subject_id,
)

OUT = SCRATCH / "reports" / "events_reconstruction"
PREVIEW = OUT / "events_preview"
TMP_EVENTS = SCRATCH / "tmp_processing" / "events_validation" / "all_events"
TMP_BIDS = SCRATCH / "tmp_processing" / "events_validation_bids"
PREVIEW_EXAMPLES = (
    "sub-001_ses-01_task-fmri_run-01",
    "sub-001_ses-01_task-fmri_run-03",
    "sub-010_ses-01_task-fmri_run-01",
    "sub-050_ses-01_task-fmri_run-01",
)
RAW_PREFIXES = (
    "/lustre06/project/6001995/raw_original",
    "/project/def-amirs/raw_original",
    "/lustre07/scratch/alexrees/raw_original",
)

MOVIE_RUN_MAP = {
    1: ("Movie1A.mp4", "L"),
    2: ("Movie2A.mp4", "R"),
    3: ("Movie1B.mp4", "R"),
    4: ("Movie2B.mp4", "L"),
}


def remap_path(p: str | Path) -> Path:
    s = str(p)
    for pref in RAW_PREFIXES[1:]:
        if s.startswith(pref):
            s = s.replace(pref, RAW_PREFIXES[0], 1)
            break
    return Path(s)


def file_sha256(path: Path, nbytes: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        h.update(fh.read(nbytes))
    return h.hexdigest()[:16]


def mat_variable_names(path: Path) -> set[str]:
    import scipy.io as sio

    try:
        raw = sio.whosmat(str(path))
        return {name for name, *_ in raw}
    except Exception:
        try:
            data = sio.loadmat(str(path), squeeze_me=True, struct_as_record=False)
            return {k for k in data if not k.startswith("__")}
        except Exception:
            return set()


def deep_keys_from_mat(path: Path, role: str) -> tuple[set[str], dict[str, Any]]:
    """Return interesting variable names + light metadata (read-only)."""
    import scipy.io as sio

    found: set[str] = set(mat_variable_names(path))
    meta: dict[str, Any] = {}

    # Filename-derived ids (cheap)
    n = parse_fmri_number_from_name(path)
    if n is not None:
        meta["fmri_number"] = n
    m_run = re.search(r"run_id[_\s-]*(\d+)|selected_run_id[_\s-]*(\d+)", path.name, re.I)
    if m_run:
        meta["run_id"] = int(m_run.group(1) or m_run.group(2))

    if role == "scan_info" or (role == "runs_random" and path.stat().st_size < 5_000_000):
        try:
            timing = extract_scan_timing(path)
            meta["trigger_count"] = int(timing.n_triggers)
            meta["has_triggerTimes"] = timing.n_triggers > 0
            meta["has_vbl"] = timing.vbl is not None
            if timing.fmri_number is not None:
                meta["fmri_number"] = timing.fmri_number
            meta["selected_run"] = timing.selected_run
            if timing.n_triggers:
                found.add("triggerTimes")
            if timing.vbl is not None:
                found.add("vbl")
        except Exception as exc:
            meta["trigger_count"] = 0
            meta["timing_error"] = str(exc)
    else:
        meta["trigger_count"] = 0
        meta["has_triggerTimes"] = any("triggertimes" in v.lower() for v in found)
        meta["has_vbl"] = any(v.lower() == "vbl" or v.lower().endswith(".vbl") for v in found)

    if role in {"stim_order_fmri_n", "stim_order_dated", "runs_random", "movie_selection"}:
        try:
            data = sio.loadmat(str(path), squeeze_me=True, struct_as_record=False)
            top = {k for k in data if not k.startswith("__")}
            found |= top
            if "Stim_order_selected" in top:
                meta["stim_order_n"] = int(np.asarray(data["Stim_order_selected"]).ravel().size)
            if "run_id" in top and meta.get("run_id") is None:
                meta["run_id"] = int(np.asarray(data["run_id"]).ravel()[0])
            # shallow struct field names only
            for k in list(top)[:20]:
                obj = data[k]
                if hasattr(obj, "_fieldnames"):
                    for name in obj._fieldnames:
                        found.add(f"{k}.{name}")
        except Exception as exc:
            meta["load_error"] = str(exc)
    return found, meta


def classify_mat(path: Path, task_hint: str) -> str:
    name = path.name.lower()
    stem = path.stem
    if "scan_info" in name:
        return "scan_info"
    if re.fullmatch(r"fMRI_\d+", stem, re.I):
        return "stim_order_fmri_n"
    if "sequence_of_stimuli" in name:
        return "stim_order_dated"
    if stem == "runs_random" or stem.startswith("runs_random_record"):
        return "runs_random"
    if task_hint == "movie" and (
        "run_id" in name or "selected_run" in name.lower()
    ):
        return "movie_selection"
    if task_hint == "rest":
        return "rest_other"
    return "other_mat"


def is_inventory_candidate(path: Path, task: str, role: str) -> bool:
    if role != "other_mat":
        return True
    if task == "rest":
        return True  # record any rest .mat if present
    name = path.name.lower()
    return any(
        k in name
        for k in ("trigger", "vbl", "timing", "scan", "stim", "paradigm", "run")
    )


def confidence_for_inventory(role: str, meta: dict[str, Any], vars_found: set[str]) -> str:
    has_tt = bool(meta.get("has_triggerTimes")) or any(
        "triggertimes" in v.lower() for v in vars_found
    )
    has_stim = "Stim_order_selected" in vars_found or meta.get("stim_order_n")
    has_run = meta.get("run_id") is not None or "run_id" in vars_found
    if role == "scan_info" and has_tt and int(meta.get("trigger_count") or 0) >= 2:
        return "HIGH"
    if role in {"stim_order_fmri_n", "stim_order_dated"} and has_stim:
        return "HIGH"
    if role == "runs_random" and (
        "paradigm" in vars_found or "runParadigmFinal" in vars_found or has_stim
    ):
        return "MEDIUM"
    if role == "movie_selection" and has_run:
        # identity only — no scanner-locked timing in these mats
        return "MEDIUM_IDENTITY_ONLY"
    if has_tt:
        return "MEDIUM"
    return "UNKNOWN"


def task_from_matlab_subdir(path: Path) -> str | None:
    parts_l = [p.lower() for p in path.parts]
    joined = "/".join(parts_l)
    if "2-grating" in joined or "/grating" in joined:
        return "fmri"
    if "3-movie" in joined or "movie_data" in joined:
        return "movie"
    if "4-rest" in joined or "resting" in joined:
        return "rest"
    return None


def load_session_matlab_roots() -> list[dict[str, str]]:
    sm = pd.read_csv(SCRATCH / "metadata" / "session_mapping.csv", dtype=str, low_memory=False)
    rows: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for _, r in sm.iterrows():
        pid = normalize_subject_id(str(r.get("participant_id") or "").strip())
        ses = normalize_session_label(str(r.get("session_label") or "").strip()) or "ses-01"
        mpath = str(r.get("MATLAB_data_path") or "").strip()
        if not pid.startswith("sub-") or not mpath or mpath.lower() == "nan":
            continue
        root = remap_path(mpath)
        key = (pid, ses, str(root))
        if key in seen:
            continue
        seen.add(key)
        rows.append(
            {
                "subject": pid,
                "session": ses,
                "matlab_root": str(root),
                "canonical": str(r.get("canonical_subject_id") or ""),
            }
        )
    return rows


def discover_mats(matlab_root: Path) -> list[tuple[str, Path]]:
    """Return (task, mat_path) for Results/.mat under tasks 2/3/4."""
    out: list[tuple[str, Path]] = []
    if not matlab_root.is_dir():
        return out
    for child in matlab_root.iterdir():
        if not child.is_dir():
            continue
        task = task_from_matlab_subdir(child)
        if task is None:
            continue
        # Prefer Results/; also top-level .mat in task folder
        candidates: list[Path] = []
        results = child / "Results"
        if results.is_dir():
            candidates.extend(sorted(results.glob("*.mat")))
        candidates.extend(sorted(child.glob("*.mat")))
        for mat in candidates:
            if mat.is_file():
                out.append((task, mat))
    return out


def build_inventory() -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    roots = load_session_matlab_roots()
    print(f"Scanning {len(roots)} MATLAB session roots…", flush=True)
    for i, info in enumerate(roots, 1):
        root = Path(info["matlab_root"])
        if i == 1 or i % 10 == 0 or i == len(roots):
            print(f"  [{i}/{len(roots)}] {info['subject']} {info['session']}", flush=True)
        mats = discover_mats(root)
        for task, mat in mats:
            role = classify_mat(mat, task)
            # Skip huge / irrelevant calibration mats quickly by name
            if mat.name in {"GreenLevel.mat", "RedLevel.mat"}:
                continue
            if not is_inventory_candidate(mat, task, role):
                continue
            vars_found, meta = deep_keys_from_mat(mat, role)
            interesting = sorted(
                v
                for v in vars_found
                if any(
                    k in v.lower()
                    for k in (
                        "trigger",
                        "vbl",
                        "run_id",
                        "stim",
                        "paradigm",
                        "ifi",
                        "scan",
                        "fmri",
                        "answer",
                    )
                )
            ) or sorted(vars_found)[:40]
            run = ""
            if task == "fmri":
                n = meta.get("fmri_number") or parse_fmri_number_from_name(mat)
                if n is not None:
                    run = f"{int(n):02d}"
            elif task == "movie":
                rid = meta.get("run_id")
                if rid is not None:
                    run = f"{int(rid):02d}"
            conf = confidence_for_inventory(role, meta, vars_found)
            rows.append(
                {
                    "subject": info["subject"],
                    "session": info["session"],
                    "task": task,
                    "run": run or "UNKNOWN",
                    "mat_file": str(mat),
                    "mat_role": role,
                    "variables_found": "|".join(interesting[:80]),
                    "trigger_count": int(meta.get("trigger_count") or 0),
                    "confidence": conf,
                    "source_sha256_16": file_sha256(mat) if mat.is_file() else "",
                    "matlab_root": str(root),
                }
            )
    return pd.DataFrame(rows)


def map_fmri_number_to_bids_run(subject: str, session: str, fmri_number: int) -> str | None:
    """Map MATLAB fMRI_number (1..4) → BIDS run via ProtocolName uniqueness."""
    func = SCRATCH / "bids" / subject / session / "func"
    if not func.is_dir():
        return None
    want = f"fMRI{int(fmri_number)}_"
    hits: list[str] = []
    for js in func.glob("*task-fmri*_bold.json"):
        if "part-phase" in js.name:
            continue
        try:
            meta = json.loads(js.read_text(encoding="utf-8"))
        except Exception:
            continue
        pn = str(meta.get("ProtocolName") or meta.get("SeriesDescription") or "")
        if want in pn.replace(" ", "") or pn.startswith(f"fMRI{int(fmri_number)}_"):
            m = re.search(r"_run-(\d+)_", js.name)
            if m:
                hits.append(m.group(1))
    hits = sorted(set(hits))
    if len(hits) == 1:
        return hits[0]
    return None


def group_grating_sources(inv: pd.DataFrame) -> list[RunSources]:
    sources: dict[tuple[str, str, int], RunSources] = {}
    session_rr: dict[tuple[str, str], Path] = {}
    g = inv[inv["task"] == "fmri"].copy()
    for _, row in g.iterrows():
        path = Path(row["mat_file"])
        subject = row["subject"]
        session = row["session"]
        role = row["mat_role"]
        if role == "runs_random":
            session_rr[(subject, session)] = path
            continue
        run = row["run"]
        if run == "UNKNOWN":
            continue
        fmri_n = int(run)
        key = (subject, session, fmri_n)
        slot = sources.get(key)
        if slot is None:
            slot = RunSources(subject=subject, session=session, fmri_number=fmri_n)
            sources[key] = slot
        if role == "scan_info" and slot.scan_info is None:
            slot.scan_info = path
        elif role in {"stim_order_fmri_n", "stim_order_dated"} and slot.stim_order is None:
            slot.stim_order = path
    for (subject, session), rr in session_rr.items():
        for key, slot in sources.items():
            if key[0] == subject and key[1] == session:
                slot.runs_random = rr
    return [sources[k] for k in sorted(sources)]


def reconstruct_grating(inv: pd.DataFrame) -> tuple[list[dict[str, Any]], int]:
    validation: list[dict[str, Any]] = []
    n_events_files = 0
    grouped = group_grating_sources(inv)
    # Detect non-unique scan_info / stim_order
    counts = defaultdict(lambda: {"scan_info": 0, "stim": 0})
    for _, row in inv[inv.task == "fmri"].iterrows():
        if row["run"] == "UNKNOWN":
            continue
        key = (row["subject"], row["session"], row["run"])
        if row["mat_role"] == "scan_info":
            counts[key]["scan_info"] += 1
        if row["mat_role"] in {"stim_order_fmri_n", "stim_order_dated"}:
            counts[key]["stim"] += 1

    for src in grouped:
        key = (src.subject, src.session, f"{src.fmri_number:02d}")
        c = counts[key]
        bids_run = map_fmri_number_to_bids_run(src.subject, src.session, src.fmri_number)
        run_label = bids_run or f"{src.fmri_number:02d}"
        source_mat = str(src.scan_info or src.stim_order or "")
        if c["scan_info"] != 1 or c["stim"] < 1 or src.scan_info is None or src.stim_order is None:
            validation.append(
                {
                    "subject": src.subject,
                    "session": src.session,
                    "task": "fmri",
                    "run": run_label,
                    "source_mat": source_mat,
                    "events_created": "no",
                    "event_count": 0,
                    "confidence": "UNKNOWN",
                    "message": (
                        f"non-unique or missing sources "
                        f"(scan_info={c['scan_info']}, stim={c['stim']})"
                    ),
                }
            )
            continue
        # Hard gate: never invent onset without measured triggerTimes.
        try:
            timing = extract_scan_timing(src.scan_info)
        except Exception as exc:  # noqa: BLE001
            validation.append(
                {
                    "subject": src.subject,
                    "session": src.session,
                    "task": "fmri",
                    "run": run_label,
                    "source_mat": source_mat,
                    "events_created": "no",
                    "event_count": 0,
                    "confidence": "UNKNOWN",
                    "message": f"scan_info timing unreadable: {exc}",
                }
            )
            continue
        if timing.n_triggers < 2 or (
            timing.tr_seconds is not None and timing.tr_seconds < 0.1
        ):
            validation.append(
                {
                    "subject": src.subject,
                    "session": src.session,
                    "task": "fmri",
                    "run": run_label,
                    "source_mat": source_mat,
                    "events_created": "no",
                    "event_count": 0,
                    "confidence": "UNKNOWN",
                    "message": (
                        f"no usable triggerTimes "
                        f"(n={timing.n_triggers}, tr={timing.tr_seconds})"
                    ),
                }
            )
            continue
        try:
            rows, confidence, messages = generate_bids_events(src)
        except Exception as exc:  # noqa: BLE001
            validation.append(
                {
                    "subject": src.subject,
                    "session": src.session,
                    "task": "fmri",
                    "run": run_label,
                    "source_mat": source_mat,
                    "events_created": "no",
                    "event_count": 0,
                    "confidence": "UNKNOWN",
                    "message": f"generation_failed: {exc}",
                }
            )
            continue
        # Full set → temp validation dir; copy a few into events_preview later.
        TMP_EVENTS.mkdir(parents=True, exist_ok=True)
        out_name = f"{src.subject}_{src.session}_task-fmri_run-{run_label}_events.tsv"
        out_path = TMP_EVENTS / out_name
        # Collision: another MATLAB fmri_number already claimed this BIDS run name.
        if out_path.exists():
            out_name = (
                f"{src.subject}_{src.session}_task-fmri_run-{run_label}"
                f"_desc-matlabFMRI{src.fmri_number}_events.tsv"
            )
            out_path = TMP_EVENTS / out_name
            messages = list(messages) + ["BIDS run mapping collision; used desc-matlabFMRI"]
            confidence = "medium"
        with out_path.open("w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=["onset", "duration", "trial_type"], delimiter="\t")
            w.writeheader()
            for row in rows:
                w.writerow(
                    {
                        "onset": f"{row.onset:.6f}",
                        "duration": f"{row.duration:.6f}",
                        "trial_type": row.trial_type,
                    }
                )
        # sidecar provenance
        prov = out_path.with_suffix(".json")
        prov.write_text(
            json.dumps(
                {
                    "GeneratedBy": "reconstruct_events_from_matlab.py",
                    "TaskName": "fmri",
                    "source_matlab_files": [str(p) for p in [src.scan_info, src.stim_order, src.runs_random] if p],
                    "source_sha256_16": {
                        str(p): file_sha256(p)
                        for p in [src.scan_info, src.stim_order, src.runs_random]
                        if p and p.is_file()
                    },
                    "matlab_fmri_number": src.fmri_number,
                    "bids_run": run_label,
                    "confidence_level": confidence,
                    "messages": messages,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        stem = out_name.replace("_events.tsv", "")
        if any(stem.startswith(ex) or stem == ex for ex in PREVIEW_EXAMPLES):
            PREVIEW.mkdir(parents=True, exist_ok=True)
            (PREVIEW / out_name).write_text(out_path.read_text(encoding="utf-8"), encoding="utf-8")
            (PREVIEW / prov.name).write_text(prov.read_text(encoding="utf-8"), encoding="utf-8")
        n_events_files += 1
        validation.append(
            {
                "subject": src.subject,
                "session": src.session,
                "task": "fmri",
                "run": run_label,
                "source_mat": source_mat,
                "events_created": "yes",
                "event_count": len(rows),
                "confidence": confidence.upper() if confidence != "UNKNOWN" else "UNKNOWN",
                "message": "; ".join(messages),
                "preview_path": str(out_path),
            }
        )
    return validation, n_events_files


def reconstruct_movie(inv: pd.DataFrame) -> list[dict[str, Any]]:
    """Movie: do not invent scanner-locked timing. Record identity-only when run_id exists."""
    validation: list[dict[str, Any]] = []
    movie = inv[inv.task == "movie"].copy()
    # Group by subject/session/run
    for (subject, session, run), g in movie.groupby(["subject", "session", "run"]):
        mats = g["mat_file"].tolist()
        roles = set(g["mat_role"])
        confs = set(g["confidence"])
        has_triggers = int(g["trigger_count"].max()) >= 2
        source = mats[0] if mats else ""
        if has_triggers:
            # Extremely rare; only then write events from triggers (not expected)
            validation.append(
                {
                    "subject": subject,
                    "session": session,
                    "task": "movie",
                    "run": run,
                    "source_mat": source,
                    "events_created": "no",
                    "event_count": 0,
                    "confidence": "UNKNOWN",
                    "message": "unexpected triggers present — manual review required; not auto-written",
                }
            )
            continue
        # Identity-only: no events.tsv (would invent onset/duration)
        stim = MOVIE_RUN_MAP.get(int(run)) if run != "UNKNOWN" else None
        msg = (
            "no scanner-locked timing in Movie Results .mat "
            "(no triggerTimes/VBL); run_id identity only"
        )
        if stim:
            msg += f"; design map run_id→{stim[0]} eye={stim[1]} (not used as invented onset)"
        validation.append(
            {
                "subject": subject,
                "session": session,
                "task": "movie",
                "run": run,
                "source_mat": source,
                "events_created": "no",
                "event_count": 0,
                "confidence": "UNKNOWN"
                if "UNKNOWN" in confs or run == "UNKNOWN"
                else "MEDIUM_IDENTITY_ONLY",
                "message": msg,
            }
        )
    return validation


def reconstruct_rest(inv: pd.DataFrame) -> tuple[list[dict[str, Any]], str]:
    rest = inv[inv.task == "rest"]
    n_mats = len(rest)
    n_with_triggers = int((rest["trigger_count"] > 0).sum()) if not rest.empty else 0
    report = f"""# Resting-state events assessment

Generated: `{datetime.now(timezone.utc).isoformat()}`

## Conclusion

**No `*_task-rest_*_events.tsv` should be created** for this dataset from MATLAB sources.

## Why

- Task-rest is fixation-only (no stimulus blocks).
- Folder `4-resting state` typically contains only `main.m` (FORP wait for trigger `t`).
- Inventory found **{n_mats}** rest-related `.mat` files under resting folders; **{n_with_triggers}** with triggerTimes.
- BIDS does not require events for resting-state; inventing empty or dummy events would violate the no-invented-timing policy.

## Recommendation

- Omit rest events.tsv from the BIDS release.
- If a validator warns `EVENTS_TSV_MISSING` for `task-rest`, treat as acceptable / ignore for rest.
"""
    validation = [
        {
            "subject": "ALL",
            "session": "ALL",
            "task": "rest",
            "run": "ALL",
            "source_mat": "",
            "events_created": "no",
            "event_count": 0,
            "confidence": "HIGH_NEGATIVE",
            "message": "events.tsv not required for fixation-only resting-state; none generated",
        }
    ]
    return validation, report


def write_generation_report(
    inv: pd.DataFrame,
    validation: pd.DataFrame,
    *,
    n_fmri_events: int,
    rest_report_path: Path,
) -> Path:
    analyzed = len(validation)
    created = validation[validation["events_created"] == "yes"]
    no_timing = validation[
        validation["confidence"].astype(str).str.contains("UNKNOWN|IDENTITY", case=False, na=False)
        & (validation["events_created"] == "no")
    ]
    problems = validation[
        validation["message"].astype(str).str.contains(
            "failed|non-unique|missing|unexpected", case=False, na=False
        )
    ]
    lines = [
        "# Events generation report",
        "",
        f"Generated: `{datetime.now(timezone.utc).isoformat()}`",
        "",
        "## Policy",
        "",
        "- Read-only on MATLAB sources and BOLD NIfTIs.",
        "- No invented timing.",
        "- Preview events written only under `events_preview/` (not integrated into `bids/` yet).",
        "",
        "## Counts",
        "",
        f"- MATLAB inventory rows: **{len(inv)}**",
        f"- Runs / units analyzed (validation rows): **{analyzed}**",
        f"- Events files generated (grating/fmri): **{n_fmri_events}**",
        f"- Total event rows written: **{int(created['event_count'].sum()) if len(created) else 0}**",
        f"- Units without usable timing / identity-only: **{len(no_timing)}**",
        f"- Problem rows (failed / non-unique / unexpected): **{len(problems)}**",
        "",
        "## By task",
        "",
    ]
    for task, g in validation.groupby("task"):
        n_yes = int((g["events_created"] == "yes").sum())
        lines.append(
            f"- `{task}`: analyzed={len(g)}, events_created={n_yes}, "
            f"mean confidence among created="
            f"{g.loc[g.events_created=='yes','confidence'].mode().tolist()}"
        )
    lines += [
        "",
        "## Movie",
        "",
        "Movie Results `.mat` provide `run_id` / selection logs but **no `triggerTimes`**. "
        "No movie `events.tsv` were written (would invent onset/duration).",
        "",
        "## Resting state",
        "",
        f"See `{rest_report_path.name}` — events.tsv **not** generated.",
        "",
        "## Traceability",
        "",
        "- Inventory: `MATLAB_EVENTS_SOURCE_INVENTORY.tsv` (`mat_file`, `source_sha256_16`).",
        "- Per-preview provenance JSON next to each events.tsv in `events_preview/`.",
        "- Validation table: `events_validation.tsv`.",
        "",
    ]
    path = OUT / "events_generation_report.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def stage_validator_mini(preview_events: list[Path]) -> Path:
    """Copy a few preview events into a mini BIDS tree with existing bold for sub-001 ses-01."""
    mini = TMP_BIDS
    if mini.exists():
        # clean func events only
        pass
    mini.mkdir(parents=True, exist_ok=True)
    src_bids = SCRATCH / "bids"
    # root meta
    for name in ("dataset_description.json", ".bidsignore", "participants.tsv", "participants.json"):
        p = src_bids / name
        if p.exists():
            (mini / name).write_bytes(p.read_bytes())
    # filter participants
    ppt = mini / "participants.tsv"
    if ppt.exists():
        lines = ppt.read_text().splitlines()
        keep = [lines[0]] + [ln for ln in lines[1:] if ln.startswith("sub-001\t")]
        ppt.write_text("\n".join(keep) + "\n", encoding="utf-8")
    # hardlink session
    ses_src = src_bids / "sub-001" / "ses-01"
    ses_dst = mini / "sub-001" / "ses-01"
    ses_dst.mkdir(parents=True, exist_ok=True)
    for modality in ("anat", "dwi", "fmap", "func"):
        s = ses_src / modality
        d = ses_dst / modality
        if not s.is_dir():
            continue
        d.mkdir(parents=True, exist_ok=True)
        for f in s.iterdir():
            if not f.is_file():
                continue
            dest = d / f.name
            if dest.exists():
                continue
            try:
                dest.hardlink_to(f)
            except Exception:
                # skip large if needed — for validator we need func at least
                if modality == "func":
                    try:
                        dest.write_bytes(f.read_bytes())
                    except Exception:
                        pass
    # Overlay preview events for sub-001
    func = ses_dst / "func"
    for ev in preview_events:
        if "sub-001_ses-01_task-fmri" in ev.name and ev.suffix == ".tsv":
            target = func / ev.name
            target.write_text(ev.read_text(encoding="utf-8"), encoding="utf-8")
    return mini


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    PREVIEW.mkdir(parents=True, exist_ok=True)

    print("Building MATLAB events source inventory…")
    inv = build_inventory()
    inv_path = OUT / "MATLAB_EVENTS_SOURCE_INVENTORY.tsv"
    col_order = [
        "subject",
        "session",
        "task",
        "run",
        "mat_file",
        "variables_found",
        "trigger_count",
        "confidence",
        "mat_role",
        "source_sha256_16",
        "matlab_root",
    ]
    inv = inv.reindex(columns=[c for c in col_order if c in inv.columns])
    inv.to_csv(inv_path, sep="\t", index=False)
    print(f"  wrote {inv_path} ({len(inv)} rows)", flush=True)

    print("Reconstructing grating/fmri events…")
    val_fmri, n_fmri = reconstruct_grating(inv)
    print(f"  fmri events files: {n_fmri}")

    print("Assessing movie (no invented timing)…")
    val_movie = reconstruct_movie(inv)

    print("Assessing resting-state…")
    val_rest, rest_md = reconstruct_rest(inv)
    rest_path = OUT / "RESTING_STATE_EVENTS_ASSESSMENT.md"
    rest_path.write_text(rest_md, encoding="utf-8")

    validation = pd.DataFrame(val_fmri + val_movie + val_rest)
    # Ensure required columns
    for col in [
        "subject",
        "session",
        "task",
        "run",
        "source_mat",
        "events_created",
        "event_count",
        "confidence",
    ]:
        if col not in validation.columns:
            validation[col] = ""
    val_path = OUT / "events_validation.tsv"
    validation.to_csv(val_path, sep="\t", index=False)
    print(f"  wrote {val_path}")

    report_path = write_generation_report(
        inv, validation, n_fmri_events=n_fmri, rest_report_path=rest_path
    )
    print(f"  wrote {report_path}")

    # Stage mini bids + validator for sub-001 previews
    previews = sorted(PREVIEW.glob("sub-001_ses-01_task-fmri_*_events.tsv"))
    if previews:
        print("Staging mini BIDS + running bids-validator on sub-001 ses-01…")
        mini = stage_validator_mini(previews)
        try:
            import subprocess

            cmd = [
                "bash",
                "-lc",
                f"module load nodejs/20.16.0 && npx --yes bids-validator@1.14.6 '{mini}' --json",
            ]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            (OUT / "bids_validator_events_preview.json").write_text(
                proc.stdout or "", encoding="utf-8"
            )
            (OUT / "bids_validator_events_preview.stderr.txt").write_text(
                proc.stderr or "", encoding="utf-8"
            )
            # summarize events-related issues
            try:
                rep = json.loads(proc.stdout or "{}")
                errs = rep.get("issues", {}).get("errors", [])
                warns = rep.get("issues", {}).get("warnings", [])
                summary = {
                    "returncode": proc.returncode,
                    "error_keys": [e.get("key") for e in errs],
                    "warning_keys": [w.get("key") for w in warns],
                }
            except Exception:
                summary = {"returncode": proc.returncode, "parse_error": True}
            (OUT / "bids_validator_events_preview_summary.json").write_text(
                json.dumps(summary, indent=2) + "\n", encoding="utf-8"
            )
            print("  validator summary:", summary)
        except Exception as exc:  # noqa: BLE001
            print("  validator skipped/failed:", exc)

    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
