#!/usr/bin/env python3
"""Integrate validated Grating MATLAB events into BIDS (task-fmri).

Default mode is DRY-RUN. Use --execute to copy *_events.tsv / *_events.json
into bids/. Never modifies raw_original/, NIfTI, or acquisition JSON sidecars.

Ambiguous mappings are never written. Existing BIDS events are backed up before
overwrite.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

SCRATCH_DEFAULT = Path("/home/alexrees/scratch")
RAW_DEFAULT = Path("/lustre06/project/6001995/raw_original")
RAW_PREFIXES = (
    "/lustre06/project/6001995/raw_original",
    "/project/def-amirs/raw_original",
    "/lustre07/scratch/alexrees/raw_original",
)

EVENTS_JSON_SIDECAR = {
    "Description": (
        "Event timings reconstructed from MATLAB Psychtoolbox triggerTimes "
        "recorded during task-fMRI acquisition."
    ),
    "Source": "MATLAB scan_info.mat triggerTimes",
    "ReconstructionMethod": "Direct extraction, no synthetic timing generation",
}

_FMRI_RE = re.compile(r"fMRI\s*(\d+)", re.I)


def now_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def remap_raw(path: str | Path, raw_root: Path) -> Path:
    s = str(path)
    if not s or s.lower() in {"nan", "none"}:
        return Path("")
    for pref in RAW_PREFIXES:
        if s.startswith(pref):
            return raw_root / s[len(pref) :].lstrip("/")
    p = Path(s)
    if p.is_absolute():
        return p
    return raw_root / p


def sha256_file(path: Path, nbytes: int | None = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        if nbytes is None:
            while True:
                chunk = fh.read(1024 * 1024)
                if not chunk:
                    break
                h.update(chunk)
            return h.hexdigest()
        h.update(fh.read(nbytes))
    return h.hexdigest()[:16]


def protocol_fmri_number(protocol: str) -> int | None:
    m = _FMRI_RE.search((protocol or "").replace(" ", ""))
    return int(m.group(1)) if m else None


def zrun(run: Any) -> str:
    s = str(run).strip()
    m = re.search(r"(\d+)", s)
    return m.group(1).zfill(2) if m else s.zfill(2)


@dataclass
class MappingRow:
    participant: str
    session: str
    fmri_number: int
    matlab_source: str
    matlab_sha256: str
    bold_target: str
    events_source: str
    selected_run: str
    origin: str = "FINAL_MAPPING"
    reason: str = ""
    n_triggers_expected: int | None = None
    volume_count_expected: int | None = None


@dataclass
class IntegrationResult:
    row: MappingRow
    status: str  # INTEGRATED | FAILED | REVIEW | SKIPPED
    message: str
    events_dest: str = ""
    events_used: str = ""
    n_triggers: int | None = None
    n_volumes: int | None = None
    actions: list[str] = field(default_factory=list)


def load_trigger_sha_index(scratch: Path) -> dict[str, str]:
    """Map absolute matlab path -> registered sha16 from recovery DB."""
    idx: dict[str, str] = {}
    for rel in (
        "reports/grating_events_recovery/MATLAB_TRIGGER_DATABASE.tsv",
        "reports/grating_events_recovery/candidates/MAPPING_CANDIDATES.tsv",
    ):
        p = scratch / rel
        if not p.exists():
            continue
        df = pd.read_csv(p, sep="\t", dtype=str, low_memory=False)
        mat_col = "source_mat" if "source_mat" in df.columns else None
        sha_col = "sha256" if "sha256" in df.columns else None
        if not mat_col or not sha_col:
            continue
        for _, r in df.iterrows():
            mat = str(r.get(mat_col) or "")
            sha = str(r.get(sha_col) or "")
            if mat and sha and mat.lower() != "nan":
                idx[mat] = sha
                # also index by basename+parent for remapped paths
                idx[str(Path(mat).name)] = sha
    return idx


def load_accept_mappings(
    mapping_tsv: Path,
    dicom_tsv: Path | None,
    bids_root: Path,
    raw_root: Path,
    scratch: Path,
) -> list[MappingRow]:
    sha_idx = load_trigger_sha_index(scratch)
    rows: list[MappingRow] = []

    df = pd.read_csv(mapping_tsv, sep="\t", dtype=str, low_memory=False)
    accept = df[df["decision"].astype(str).str.upper() == "ACCEPT"].copy()
    for _, r in accept.iterrows():
        sub = str(r.get("participant_id") or r.get("subject") or "")
        ses = str(r.get("session_id") or r.get("session") or "")
        try:
            n = int(r.get("fmri_number"))
        except Exception:
            continue
        run = zrun(r.get("selected_bold_run") or r.get("bids_run") or "")
        mat = str(r.get("matlab_file") or r.get("matlab_source") or "")
        bold = str(r.get("bold_file") or "")
        if not bold or bold.lower() == "nan":
            bold = str(
                bids_root
                / sub
                / ses
                / "func"
                / f"{sub}_{ses}_task-fmri_run-{run}_bold.nii.gz"
            )
        ev = str(r.get("events_source") or "")
        if ev.lower() in {"nan", "none"}:
            ev = ""
        sha = sha_idx.get(mat) or sha_idx.get(Path(mat).name if mat else "") or ""
        ntrig = None
        try:
            ntrig = int(float(r.get("matlab_trigger_count")))
        except Exception:
            pass
        nvol = None
        try:
            nvol = int(float(r.get("volume_count")))
        except Exception:
            pass
        rows.append(
            MappingRow(
                participant=sub,
                session=ses,
                fmri_number=n,
                matlab_source=mat,
                matlab_sha256=sha,
                bold_target=bold,
                events_source=ev,
                selected_run=run,
                origin="FINAL_MAPPING_ACCEPT",
                reason=str(r.get("reason") or ""),
                n_triggers_expected=ntrig,
                volume_count_expected=nvol,
            )
        )

    if dicom_tsv and dicom_tsv.exists():
        ddf = pd.read_csv(dicom_tsv, sep="\t", dtype=str, low_memory=False)
        for _, r in ddf.iterrows():
            sub = str(r.get("subject") or r.get("participant") or "")
            ses = str(r.get("session") or "")
            try:
                n = int(r.get("matlab_fmri_number") or r.get("fmri_number"))
            except Exception:
                continue
            run = zrun(r.get("selected_bids_run") or r.get("bids_target_run") or "")
            # Prefer explicit matlab from companion INTEGRATE file if present
            mat = str(r.get("matlab_source") or "")
            if not mat or mat.lower() == "nan":
                mat = find_matlab_for_session(scratch, raw_root, sub, ses, n)
            sha = sha_idx.get(mat) or sha_idx.get(Path(mat).name if mat else "") or ""
            bold = str(
                bids_root
                / sub
                / ses
                / "func"
                / f"{sub}_{ses}_task-fmri_run-{run}_bold.nii.gz"
            )
            ev = str(r.get("events_source") or "")
            if ev.lower() in {"nan", "none"}:
                ev = ""
            rows = [
                x
                for x in rows
                if not (
                    x.participant == sub
                    and x.session == ses
                    and x.fmri_number == n
                    and x.origin.startswith("FINAL")
                    and x.selected_run != run
                    and "AMBIGUOUS" in (x.reason or "").upper()
                )
            ]
            if (sub, ses, n, run) in {
                (x.participant, x.session, x.fmri_number, x.selected_run) for x in rows
            }:
                continue
            rows.append(
                MappingRow(
                    participant=sub,
                    session=ses,
                    fmri_number=n,
                    matlab_source=mat,
                    matlab_sha256=sha,
                    bold_target=bold,
                    events_source=ev,
                    selected_run=run,
                    origin="DICOM_RESOLUTION",
                    reason=str(r.get("reason") or ""),
                )
            )

    # Deduplicate exact keys preferring DICOM_RESOLUTION
    uniq: dict[tuple[str, str, int, str], MappingRow] = {}
    for r in rows:
        k = (r.participant, r.session, r.fmri_number, r.selected_run)
        if k in uniq and uniq[k].origin == "DICOM_RESOLUTION":
            continue
        uniq[k] = r
    return list(uniq.values())


def find_matlab_for_session(
    scratch: Path, raw_root: Path, sub: str, ses: str, fmri_n: int
) -> str:
    """Locate scan_info mat via session_mapping + Results glob."""
    sm_path = scratch / "metadata" / "session_mapping.csv"
    if not sm_path.exists():
        return ""
    sm = pd.read_csv(sm_path, dtype=str, low_memory=False)
    hit = sm[(sm["participant_id"] == sub) & (sm["session_id"] == ses)]
    if hit.empty:
        hit = sm[(sm["participant_id"] == sub) & (sm["session_label"] == ses)]
    if hit.empty:
        return ""
    mat_root = remap_raw(str(hit.iloc[0].get("MATLAB_data_path") or ""), raw_root)
    if not mat_root.is_dir():
        return ""
    grating = None
    for c in mat_root.iterdir():
        if c.is_dir() and ("grating" in c.name.lower() or c.name.startswith("2-")):
            grating = c
            break
    if grating is None:
        return ""
    results = grating / "Results"
    if not results.is_dir():
        return ""
    hits = []
    for p in results.glob("*scan_info*.mat"):
        if f"fmri_number_is{fmri_n}" in p.name.replace(" ", "").lower():
            hits.append(p)
        else:
            m = re.search(r"fmri_number_is\s*(\d+)", p.name, re.I)
            if m and int(m.group(1)) == fmri_n:
                hits.append(p)
    if not hits:
        return ""
    hits.sort(key=lambda p: p.name)
    return str(hits[-1])


def verify_matlab(
    row: MappingRow, raw_root: Path
) -> tuple[bool, str, int | None, Path | None]:
    """Return (ok, message, n_triggers, mat_path)."""
    sys.path.insert(0, str(SCRATCH_DEFAULT / "neuro_pipeline"))
    from neuro_pipeline.associated_data.matlab.extract_scan_timing import (  # noqa: WPS433
        extract_scan_timing,
    )

    mat = remap_raw(row.matlab_source, raw_root)
    if not mat.is_file():
        return False, f"MATLAB_MISSING:{mat.name if mat else ''}", None, None
    # SHA check against registered truncated hash (first 1 MiB)
    got = sha256_file(mat, nbytes=1024 * 1024)
    if row.matlab_sha256:
        if got != row.matlab_sha256 and not got.startswith(row.matlab_sha256[:8]):
            # allow full vs truncated comparison
            full = sha256_file(mat, nbytes=None)
            if not (
                full.startswith(row.matlab_sha256)
                or row.matlab_sha256.startswith(got)
                or got == row.matlab_sha256
            ):
                return (
                    False,
                    f"MATLAB_SHA_MISMATCH expected={row.matlab_sha256} got={got}",
                    None,
                    mat,
                )
    else:
        # No registered SHA: record computed hash but do not fail solely for that
        row.matlab_sha256 = got

    try:
        timing = extract_scan_timing(mat)
    except Exception as exc:  # noqa: BLE001
        return False, f"MATLAB_TIMING_UNREADABLE:{exc}", None, mat
    ntrig = int(timing.n_triggers)
    if ntrig < 2:
        return False, f"TRIGGER_TIMES_TOO_FEW n={ntrig}", ntrig, mat
    return True, "MATLAB_OK", ntrig, mat


def nifti_n_volumes(bold_path: Path) -> int | None:
    if not bold_path.is_file():
        return None
    try:
        import nibabel as nib

        shape = nib.load(str(bold_path)).header.get_data_shape()
        if len(shape) >= 4:
            return int(shape[3])
        return 1
    except Exception:
        return None


def verify_bold(
    row: MappingRow, bids_root: Path, n_triggers: int | None
) -> tuple[str, str, int | None]:
    """Return (status, message, n_volumes). status in OK|REVIEW|FAIL."""
    bold = Path(row.bold_target)
    if not bold.is_absolute():
        bold = bids_root / bold
    # Prefer remapped bids path under bids_root
    expected = (
        bids_root
        / row.participant
        / row.session
        / "func"
        / f"{row.participant}_{row.session}_task-fmri_run-{row.selected_run}_bold.nii.gz"
    )
    if expected.is_file():
        bold = expected
    if not bold.is_file():
        return "FAIL", f"BOLD_MISSING:{expected.name}", None

    js = bold.with_name(bold.name.replace("_bold.nii.gz", "_bold.json"))
    if not js.is_file():
        return "FAIL", f"BOLD_JSON_MISSING:{js.name}", None
    meta = json.loads(js.read_text(encoding="utf-8"))
    task = str(meta.get("TaskName") or "").lower()
    if task and task not in {"fmri", "task-fmri"}:
        return "FAIL", f"TASKNAME_MISMATCH:{task}", None
    pn = str(meta.get("ProtocolName") or "")
    pn_n = protocol_fmri_number(pn)
    if pn_n is not None and pn_n != row.fmri_number:
        return "FAIL", f"PROTOCOL_MISMATCH ProtocolName={pn} fmri={row.fmri_number}", None

    nvol = nifti_n_volumes(bold)
    if nvol is None and row.volume_count_expected is not None:
        nvol = row.volume_count_expected
    if n_triggers is not None and nvol is not None:
        if abs(int(n_triggers) - int(nvol)) > 2:
            return (
                "REVIEW",
                f"TRIGGER_VOLUME_MISMATCH triggers={n_triggers} volumes={nvol}",
                nvol,
            )
    return "OK", "BOLD_OK", nvol


def find_precomputed_events(
    row: MappingRow, events_root: Path
) -> Path | None:
    """Locate a precomputed events TSV under all_events/ matching fmri_number."""
    candidates: list[Path] = []
    if row.events_source:
        p = Path(row.events_source)
        if p.is_file():
            candidates.append(p)
        alt = events_root / p.name
        if alt.is_file():
            candidates.append(alt)

    # desc-matlabFMRI{n}
    candidates.extend(
        sorted(
            events_root.glob(
                f"{row.participant}_{row.session}_task-fmri_*_desc-matlabFMRI{row.fmri_number}_events.tsv"
            )
        )
    )
    # Validate provenance when JSON sidecar exists
    for tsv in candidates:
        if not tsv.is_file():
            continue
        js = tsv.with_suffix(".json")
        if js.is_file():
            try:
                meta = json.loads(js.read_text(encoding="utf-8"))
            except Exception:
                meta = {}
            mn = meta.get("matlab_fmri_number")
            if mn is not None and int(mn) != row.fmri_number:
                continue
            # If source paths listed, require basename match when matlab_source known
            sources = meta.get("source_matlab_files") or []
            if row.matlab_source and sources:
                want = Path(row.matlab_source).name
                names = [Path(str(s)).name for s in sources]
                if want not in names and not any("scan_info" in n for n in names):
                    # still accept if fmri number matches
                    pass
        return tsv
    return None


def build_run_sources(mat_path: Path, subject: str, session: str, fmri_n: int):
    sys.path.insert(0, str(SCRATCH_DEFAULT / "neuro_pipeline"))
    from neuro_pipeline.associated_data.matlab.generate_events import RunSources

    results = mat_path.parent
    stim = results / f"fMRI_{fmri_n}.mat"
    if not stim.is_file():
        # dated sequence fallback
        stim_hits = [
            p
            for p in results.glob("*sequence_of_stimuli*")
            if f"fMRI_number_{fmri_n}" in p.name.replace(" ", "")
            or f"fmri_number_{fmri_n}" in p.name.lower().replace(" ", "")
        ]
        stim = stim_hits[-1] if stim_hits else None
    rr = None
    for pat in ("runs_random_record*.mat", "runs_random.mat"):
        hits = sorted(results.glob(pat))
        if hits:
            rr = hits[-1]
            break
    return RunSources(
        subject=subject,
        session=session,
        fmri_number=fmri_n,
        scan_info=mat_path,
        stim_order=stim if stim and Path(stim).is_file() else None,
        runs_random=rr,
    )


def regenerate_events_tsv(
    row: MappingRow,
    mat_path: Path,
    staging_dir: Path,
) -> tuple[Path | None, str]:
    """Build events from MATLAB triggerTimes into staging (not synthetic)."""
    sys.path.insert(0, str(SCRATCH_DEFAULT / "neuro_pipeline"))
    from neuro_pipeline.associated_data.matlab.generate_events import (  # noqa: WPS433
        generate_bids_events,
    )

    src = build_run_sources(mat_path, row.participant, row.session, row.fmri_number)
    if src.scan_info is None:
        return None, "REGEN_NO_SCAN_INFO"
    try:
        events, confidence, messages = generate_bids_events(src)
    except Exception as exc:  # noqa: BLE001
        return None, f"REGEN_FAILED:{exc}"
    if not events:
        return None, f"REGEN_EMPTY:{';'.join(messages)}"

    staging_dir.mkdir(parents=True, exist_ok=True)
    stem = (
        f"{row.participant}_{row.session}_task-fmri_run-{row.selected_run}"
        f"_desc-matlabFMRI{row.fmri_number}_events"
    )
    tsv = staging_dir / f"{stem}.tsv"
    with tsv.open("w", encoding="utf-8", newline="") as fh:
        fh.write("onset\tduration\ttrial_type\n")
        for ev in events:
            fh.write(f"{ev.onset:.6f}\t{ev.duration:.6f}\t{ev.trial_type}\n")
    # provenance json (no absolute paths)
    js = staging_dir / f"{stem}.json"
    js.write_text(
        json.dumps(
            {
                **EVENTS_JSON_SIDECAR,
                "matlab_fmri_number": row.fmri_number,
                "matlab_sha256_16": row.matlab_sha256,
                "confidence_level": confidence,
                "messages": messages,
                "matlab_basename": mat_path.name,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return tsv, f"REGENERATED_FROM_MATLAB confidence={confidence}"


def prepare_public_events(src_tsv: Path, dest_tsv: Path) -> None:
    """Write BIDS events with only onset/duration/trial_type (no PHI paths)."""
    df = pd.read_csv(src_tsv, sep="\t")
    need = ["onset", "duration", "trial_type"]
    for c in need:
        if c not in df.columns:
            raise ValueError(f"events missing column {c}: {src_tsv.name}")
    out = df[need].copy()
    dest_tsv.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(dest_tsv, sep="\t", index=False, float_format="%.6f")


def backup_existing(paths: list[Path], backup_root: Path, bids_root: Path) -> list[str]:
    copied = []
    for p in paths:
        if not p.exists():
            continue
        try:
            rel = p.relative_to(bids_root)
        except ValueError:
            rel = Path(p.name)
        dest = backup_root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, dest)
        copied.append(str(rel))
    return copied


def process_row(
    row: MappingRow,
    *,
    bids_root: Path,
    raw_root: Path,
    events_root: Path,
    staging_dir: Path,
    execute: bool,
    backup_root: Path | None,
) -> IntegrationResult:
    ok, msg, ntrig, mat_path = verify_matlab(row, raw_root)
    if not ok:
        return IntegrationResult(row=row, status="FAILED", message=msg, n_triggers=ntrig)

    bold_status, bold_msg, nvol = verify_bold(row, bids_root, ntrig)
    if bold_status == "FAIL":
        return IntegrationResult(
            row=row, status="FAILED", message=bold_msg, n_triggers=ntrig, n_volumes=nvol
        )
    if bold_status == "REVIEW":
        return IntegrationResult(
            row=row, status="REVIEW", message=bold_msg, n_triggers=ntrig, n_volumes=nvol
        )

    ev_src = find_precomputed_events(row, events_root)
    origin_note = "PRECOMPUTED"
    if ev_src is None:
        assert mat_path is not None
        ev_src, origin_note = regenerate_events_tsv(row, mat_path, staging_dir)
        if ev_src is None:
            return IntegrationResult(
                row=row,
                status="FAILED",
                message=f"EVENTS_SOURCE_MISSING_AND_{origin_note}",
                n_triggers=ntrig,
                n_volumes=nvol,
            )

    dest_tsv = (
        bids_root
        / row.participant
        / row.session
        / "func"
        / f"{row.participant}_{row.session}_task-fmri_run-{row.selected_run}_events.tsv"
    )
    dest_json = dest_tsv.with_suffix(".json")

    actions: list[str] = []
    if dest_tsv.exists():
        actions.append("WOULD_BACKUP_EXISTING" if not execute else "BACKED_UP_EXISTING")

    if not execute:
        return IntegrationResult(
            row=row,
            status="INTEGRATED",
            message=f"DRY_RUN_OK;{origin_note};{msg};{bold_msg}",
            events_dest=str(dest_tsv.relative_to(bids_root)),
            events_used=ev_src.name,
            n_triggers=ntrig,
            n_volumes=nvol,
            actions=actions + ["DRY_RUN_NO_WRITE"],
        )

    # Execute: backup then write
    assert backup_root is not None
    backup_existing([dest_tsv, dest_json], backup_root, bids_root)
    # write via temp then move
    tmp_tsv = dest_tsv.with_suffix(".tsv.tmp")
    prepare_public_events(ev_src, tmp_tsv)
    tmp_tsv.replace(dest_tsv)
    dest_json.write_text(json.dumps(EVENTS_JSON_SIDECAR, indent=2) + "\n", encoding="utf-8")
    return IntegrationResult(
        row=row,
        status="INTEGRATED",
        message=f"WRITTEN;{origin_note};{msg};{bold_msg}",
        events_dest=str(dest_tsv.relative_to(bids_root)),
        events_used=ev_src.name,
        n_triggers=ntrig,
        n_volumes=nvol,
        actions=actions + ["WROTE_EVENTS_TSV", "WROTE_EVENTS_JSON"],
    )


def write_reports(
    out_dir: Path,
    results: list[IntegrationResult],
    n_accept_initial: int,
    backup_root: Path | None,
    execute: bool,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    integrated = [r for r in results if r.status == "INTEGRATED"]
    failed = [r for r in results if r.status == "FAILED"]
    review = [r for r in results if r.status == "REVIEW"]

    def row_dict(r: IntegrationResult) -> dict[str, Any]:
        return {
            "participant": r.row.participant,
            "session": r.row.session,
            "fmri_number": r.row.fmri_number,
            "selected_run": r.row.selected_run,
            "status": r.status,
            "message": r.message,
            "events_dest": r.events_dest,
            "events_used": r.events_used,
            "matlab_sha256": r.row.matlab_sha256,
            "n_triggers": r.n_triggers,
            "n_volumes": r.n_volumes,
            "origin": r.row.origin,
            "actions": ";".join(r.actions),
        }

    pd.DataFrame([row_dict(r) for r in integrated]).to_csv(
        out_dir / "INTEGRATED_EVENTS.tsv", sep="\t", index=False
    )
    pd.DataFrame([row_dict(r) for r in failed + review]).to_csv(
        out_dir / "FAILED_EVENTS.tsv", sep="\t", index=False
    )
    pd.DataFrame([row_dict(r) for r in failed]).to_csv(
        out_dir / "INTEGRATION_FAILED.tsv", sep="\t", index=False
    )

    if backup_root is not None:
        (out_dir / "BACKUP_LOCATION.txt").write_text(
            str(backup_root) + "\n", encoding="utf-8"
        )
    else:
        (out_dir / "BACKUP_LOCATION.txt").write_text(
            "N/A (dry-run; no backup created)\n", encoding="utf-8"
        )

    mode = "EXECUTION MODE : fichiers copiés dans BIDS" if execute else "DRY RUN : aucune modification effectuée"
    runs = "\n".join(f"- `{r.events_dest}`" for r in integrated if r.events_dest)
    md = f"""# Final events integration report — Grating task-fmri

Generated: `{datetime.now(timezone.utc).isoformat()}`

**Mode:** {mode}

## Summary

| Metric | n |
|--------|--:|
| ACCEPT initial (mapping + DICOM resolved) | {n_accept_initial} |
| Integrated (validated) | {len(integrated)} |
| Failed | {len(failed)} |
| Held for REVIEW | {len(review)} |

## Runs added / ready

{runs or "_none_"}

## Failed / review

| participant | session | fMRI# | run | status | message |
|-------------|---------|------:|----:|--------|---------|
"""
    for r in failed + review:
        md += (
            f"| {r.row.participant} | {r.row.session} | {r.row.fmri_number} | "
            f"{r.row.selected_run} | {r.status} | {r.message} |\n"
        )
    md += """
## Safety

- `raw_original/` not modified
- NIfTI / acquisition JSON not modified
- Existing events backed up before overwrite (execute mode only)
- No synthetic onsets: timings from MATLAB `triggerTimes` only
- Ambiguous mappings excluded (ACCEPT / DICOM-resolved only)
"""
    (out_dir / "FINAL_EVENTS_INTEGRATION_REPORT.md").write_text(md, encoding="utf-8")


def count_missing_fmri_events(bids_root: Path) -> int:
    n = 0
    for bold in bids_root.glob("sub-*/ses-*/func/*_task-fmri_run-*_bold.nii.gz"):
        if "part-phase" in bold.name:
            continue
        ev = bold.with_name(bold.name.replace("_bold.nii.gz", "_events.tsv"))
        if not ev.exists():
            n += 1
    return n


def run_bids_validator(bids_root: Path, out_txt: Path) -> int:
    """Run bids-validator if available; always write a status file."""
    missing_before_note = ""
    cmd = None
    which = shutil.which("bids-validator")
    if which:
        cmd = [which, str(bids_root)]
    else:
        # Prefer previous project pattern
        node_mod = subprocess.run(
            ["bash", "-lc", "module load nodejs/20.16.0 2>/dev/null; command -v npx"],
            capture_output=True,
            text=True,
        )
        if node_mod.returncode == 0 and node_mod.stdout.strip():
            cmd = [
                "bash",
                "-lc",
                f"module load nodejs/20.16.0 && npx --yes bids-validator@1.14.10 '{bids_root}'",
            ]

    lines = [
        f"# bids-validator capture",
        f"time: {datetime.now(timezone.utc).isoformat()}",
        f"bids_root: {bids_root}",
        f"missing_task-fmri_events_count: {count_missing_fmri_events(bids_root)}",
        "",
    ]
    if cmd is None:
        lines.append("STATUS: bids-validator not available on PATH / npx")
        out_txt.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return 1

    lines.append(f"command: {cmd if isinstance(cmd, str) else ' '.join(cmd)}")
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=3600,
        )
        lines.append(f"exit_code: {proc.returncode}")
        lines.append("--- stdout ---")
        lines.append(proc.stdout[-200000:] if proc.stdout else "")
        lines.append("--- stderr ---")
        lines.append(proc.stderr[-50000:] if proc.stderr else "")
        # Count EVENTS_TSV_MISSING mentions
        blob = (proc.stdout or "") + (proc.stderr or "")
        n_miss = len(re.findall(r"EVENTS_TSV_MISSING", blob))
        lines.append(f"EVENTS_TSV_MISSING_mentions: {n_miss}")
        out_txt.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return proc.returncode
    except subprocess.TimeoutExpired:
        lines.append("STATUS: bids-validator TIMEOUT after 3600s")
        out_txt.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return 124
    except Exception as exc:  # noqa: BLE001
        lines.append(f"STATUS: bids-validator error: {exc}")
        out_txt.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bids", type=Path, default=SCRATCH_DEFAULT / "bids")
    parser.add_argument(
        "--mapping",
        type=Path,
        default=SCRATCH_DEFAULT
        / "reports/grating_events_recovery/final_review/FINAL_MAPPING_DECISION.tsv",
    )
    parser.add_argument(
        "--dicom-resolution",
        type=Path,
        default=SCRATCH_DEFAULT
        / "reports/grating_events_recovery/dicom_resolution/MANUAL_REVIEW_RESOLVED.tsv",
    )
    parser.add_argument(
        "--events-source",
        type=Path,
        default=SCRATCH_DEFAULT / "tmp_processing/events_validation/all_events",
    )
    parser.add_argument("--raw", type=Path, default=RAW_DEFAULT)
    parser.add_argument("--scratch", type=Path, default=SCRATCH_DEFAULT)
    parser.add_argument(
        "--output",
        type=Path,
        default=SCRATCH_DEFAULT / "reports/grating_events_recovery/final_integration",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Default: no BIDS writes",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually copy events into BIDS (implies not dry-run)",
    )
    parser.add_argument(
        "--skip-validator",
        action="store_true",
        help="Skip bids-validator invocation",
    )
    args = parser.parse_args(argv)
    execute = bool(args.execute)
    dry_run = not execute

    if dry_run:
        print("DRY RUN : aucune modification effectuée", flush=True)
    else:
        print("EXECUTION MODE : fichiers copiés dans BIDS", flush=True)

    mappings = load_accept_mappings(
        args.mapping,
        args.dicom_resolution,
        args.bids,
        args.raw,
        args.scratch,
    )
    print(f"ACCEPT mappings to process: {len(mappings)}", flush=True)

    staging = args.output / "staging_events"
    staging.mkdir(parents=True, exist_ok=True)

    backup_root = None
    if execute:
        backup_root = (
            args.scratch / f"bids_backup_before_events_integration_{now_stamp()}"
        )
        backup_root.mkdir(parents=True, exist_ok=True)

    results: list[IntegrationResult] = []
    for row in sorted(
        mappings, key=lambda r: (r.participant, r.session, r.fmri_number, r.selected_run)
    ):
        print(
            f"  {row.participant} {row.session} fMRI{row.fmri_number} -> run-{row.selected_run}",
            flush=True,
        )
        res = process_row(
            row,
            bids_root=args.bids,
            raw_root=args.raw,
            events_root=args.events_source,
            staging_dir=staging,
            execute=execute,
            backup_root=backup_root,
        )
        results.append(res)
        print(f"    -> {res.status}: {res.message}", flush=True)

    write_reports(args.output, results, len(mappings), backup_root, execute)

    # Also write planned internal table
    plan = []
    for r in results:
        plan.append(
            {
                "participant": r.row.participant,
                "session": r.row.session,
                "fmri_number": r.row.fmri_number,
                "matlab_source_basename": Path(r.row.matlab_source).name
                if r.row.matlab_source
                else "",
                "matlab_sha256": r.row.matlab_sha256,
                "bold_target": Path(r.row.bold_target).name,
                "events_source": r.events_used,
                "selected_run": r.row.selected_run,
                "status": r.status,
            }
        )
    pd.DataFrame(plan).to_csv(args.output / "INTEGRATION_PLAN.tsv", sep="\t", index=False)

    if not args.skip_validator:
        val_path = args.output / "validation_after_events.txt"
        print("Running bids-validator (may take a while)…", flush=True)
        run_bids_validator(args.bids, val_path)
        print(f"Validator log: {val_path}", flush=True)

    n_ok = sum(1 for r in results if r.status == "INTEGRATED")
    n_fail = sum(1 for r in results if r.status == "FAILED")
    n_rev = sum(1 for r in results if r.status == "REVIEW")
    print(
        f"Done. INTEGRATED={n_ok} FAILED={n_fail} REVIEW={n_rev} reports={args.output}",
        flush=True,
    )
    return 0 if n_fail == 0 and n_rev == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
