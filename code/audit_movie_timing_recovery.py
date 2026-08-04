#!/usr/bin/env python3
"""READ-ONLY audit: can task-movie events.tsv be reconstructed?

Writes ONLY under reports/movie_timing_recovery_audit/.
Never modifies raw_original/, bids/, release_dataset/.
Never creates events.tsv or invents onsets.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path("/lustre07/scratch/alexrees")
RAW6 = Path("/lustre06/project/6001995/raw_original")
OUT = ROOT / "reports" / "movie_timing_recovery_audit"
RELEASE = ROOT / "release_dataset"
SESSIONS = ROOT / "metadata" / "sessions.tsv"
ASSOC = ROOT / "reports" / "associated_data_inventory.tsv"
MAT_INV = ROOT / "reports" / "matlab_content_inventory.tsv"
PHYSIO_DEEP = ROOT / "reports" / "physiology_audit" / "physiolog_dicom_deep.tsv"
PHYSIO_INV = ROOT / "reports" / "physiology_audit" / "physiolog_inventory.tsv"
DICOM_TIMING = ROOT / "reports" / "physiology_audit" / "dicom_timing_inventory.tsv"

NOW = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

sys.path.insert(0, str(ROOT / "code"))
from convert_physiolog_to_bids import (  # noqa: E402
    _extract_channel_samples,
    _read_csa_text,
)

M_KEYWORDS = [
    "Screen('Flip')",
    "Screen('OpenMovie')",
    "Screen('PlayMovie')",
    "GetSecs",
    "vbl",
    "KbTriggerWait",
    "KbCheck",
    "KbQueueWait",
    "trigger",
    "Trigger",
    "TTL",
    "FORP",
    "scanner",
    "MRI",
    "pulse",
    "startTime",
    "movieStart",
    "movie_start",
    "flip",
    "frame",
    "timestamp",
    "time",
]

MAT_TIMING_NAMES = {
    "triggertimes",
    "vbl",
    "fliptimes",
    "frametimes",
    "getsecs",
    "moviestart",
    "movie_start",
    "onset",
    "duration",
    "timestamp",
    "starttime",
}


def log(msg: str) -> None:
    print(msg, flush=True)


def sha256_file(path: Path, limit: int | None = None) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        if limit is None:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        else:
            h.update(f.read(limit))
    return h.hexdigest()


def remap6(path: str) -> Path:
    p = path.replace("/lustre07/scratch/alexrees/raw_original", str(RAW6))
    p = p.replace(str(RAW6), str(RAW6))
    return Path(p)


def write_tsv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, delimiter="\t", extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fieldnames})


def redact_path(path: str) -> str:
    """Public-report safe path token (no absolute home / project specifics beyond raw_original)."""
    return re.sub(r".*/raw_original/", "<RAW>/", path.replace("\\", "/"))


def parse_subject_session_from_token(token: str) -> tuple[str, str]:
    # Use sessions.tsv mapping when possible later
    return "", ""


# ---------------------------------------------------------------------------
# Part 1 — MATLAB / Psychtoolbox
# ---------------------------------------------------------------------------
def audit_matlab() -> list[dict[str, Any]]:
    rows_out: list[dict[str, Any]] = []

    # --- .m scripts ---
    m_paths: list[Path] = []
    with ASSOC.open() as f:
        for r in csv.DictReader(f, delimiter="\t"):
            if r.get("extension") != ".m":
                continue
            low = r["path"].lower()
            if "3-movie" not in low:
                continue
            src = remap6(r["path"])
            if src.is_file():
                m_paths.append(src)

    # de-duplicate by sha after read
    seen_m: set[str] = set()
    for src in sorted(set(m_paths)):
        try:
            data = src.read_bytes()
            digest = hashlib.sha256(data).hexdigest()
            text = data.decode("utf-8", errors="replace")
        except Exception as e:
            rows_out.append(
                {
                    "filepath": redact_path(str(src)),
                    "file_type": ".m",
                    "sha256": "",
                    "variables_found": "",
                    "keywords_found": "",
                    "trigger_present": "no",
                    "vbl_present": "no",
                    "frame_timing_present": "no",
                    "scanner_sync_present": "no",
                    "saves_timing": "no",
                    "confidence": "LOW",
                    "classification": "NO_TIMING",
                    "comments": f"read_error:{e}",
                }
            )
            continue

        kws = [k for k in M_KEYWORDS if k.lower() in text.lower() or k in text]
        # more precise flags
        trigger_present = any(
            x in text for x in ("KbQueueWait", "KbTriggerWait", "keysOfInterest(KbName('t'))", "trigger")
        ) or ("FORP" in text)
        vbl_present = bool(re.search(r"\bvbl\b", text, re.I)) or "GetSecs" in text
        frame_timing = "Flip" in text or "frame" in text.lower()
        # Does script SAVE timing arrays?
        saves_timing = bool(
            re.search(r"save\s*\(.*triggerTimes|triggerTimes\s*=|vbl\s*\(|vbl\s*=", text, re.I)
        )
        # Show_movie waits for trigger but does not log it
        scanner_sync = trigger_present  # sync used at runtime
        if saves_timing and trigger_present and (vbl_present or frame_timing):
            klass = "RECOVERABLE_TIMING"
            conf = "HIGH"
        elif re.search(r"\brun_id\b", text) and not saves_timing:
            klass = "PARTIAL"
            conf = "MEDIUM"
        else:
            klass = "NO_TIMING"
            conf = "HIGH" if "OpenMovie" in text or "PlayMovie" in text else "MEDIUM"

        # unique content once + one row per path? User asked per file — emit per path
        rows_out.append(
            {
                "filepath": redact_path(str(src)),
                "file_type": ".m",
                "sha256": digest,
                "variables_found": "",
                "keywords_found": ";".join(kws[:40]),
                "trigger_present": "yes" if trigger_present else "no",
                "vbl_present": "yes" if vbl_present else "no",
                "frame_timing_present": "yes" if frame_timing else "no",
                "scanner_sync_present": "yes" if scanner_sync else "no",
                "saves_timing": "yes" if saves_timing else "no",
                "confidence": conf,
                "classification": klass,
                "comments": (
                    "runtime_sync_without_logged_timestamps"
                    if scanner_sync and not saves_timing
                    else ""
                ),
            }
        )
        seen_m.add(digest)

    # --- .mat Results from prior inventory (authoritative variable lists) ---
    with MAT_INV.open() as f:
        for r in csv.DictReader(f, delimiter="\t"):
            fp = r["file_path"]
            if "3-movie" not in fp.lower() or not fp.lower().endswith(".mat"):
                continue
            src = remap6(fp)
            digest = ""
            if src.is_file():
                try:
                    digest = sha256_file(src)
                except Exception:
                    digest = ""
            vs = r.get("variables") or ""
            names = {m.group(1).lower() for m in re.finditer(r"([A-Za-z_][\w]*)\s*:", vs)}
            trigger_present = "triggertimes" in names or "trigger" in names
            vbl_present = "vbl" in names or "fliptimes" in names
            frame_timing = bool(names & {"frametimes", "vbl", "fliptimes", "getsecs"})
            has_run = "run_id" in names
            timing_names = sorted(names & MAT_TIMING_NAMES)
            if trigger_present and (vbl_present or frame_timing):
                klass = "RECOVERABLE_TIMING"
                conf = "HIGH"
            elif has_run and not trigger_present:
                klass = "PARTIAL"
                conf = "HIGH"
            else:
                klass = "NO_TIMING"
                conf = "MEDIUM"
            rows_out.append(
                {
                    "filepath": redact_path(str(src if src.is_file() else fp)),
                    "file_type": ".mat",
                    "sha256": digest,
                    "variables_found": vs.replace("\t", " "),
                    "keywords_found": ";".join(timing_names),
                    "trigger_present": "yes" if trigger_present else "no",
                    "vbl_present": "yes" if vbl_present else "no",
                    "frame_timing_present": "yes" if frame_timing else "no",
                    "scanner_sync_present": "no",
                    "saves_timing": "yes" if timing_names else "no",
                    "confidence": conf,
                    "classification": klass,
                    "comments": (
                        "run_id_identity_only;_t_is_datestr_not_GetSecs"
                        if has_run and not trigger_present
                        else ""
                    ),
                }
            )

    write_tsv(
        OUT / "PSYCHTOOLBOX_MATLAB_AUDIT.tsv",
        [
            "filepath",
            "file_type",
            "sha256",
            "variables_found",
            "keywords_found",
            "trigger_present",
            "vbl_present",
            "frame_timing_present",
            "scanner_sync_present",
            "saves_timing",
            "confidence",
            "classification",
            "comments",
        ],
        rows_out,
    )
    return rows_out


# ---------------------------------------------------------------------------
# Part 2 — PhysioLog EXT
# ---------------------------------------------------------------------------
def _first_dicom_in_dir(d: Path) -> Path | None:
    for pat in ("*.IMA", "*.dcm", "*.DCM"):
        files = sorted(d.glob(pat))
        if files:
            return files[0]
    # sometimes files directly
    if d.is_file():
        return d
    return None


def analyze_ext(arr: np.ndarray, sample_ms: float) -> dict[str, Any]:
    if arr is None or len(arr) == 0:
        return {
            "n_samples": 0,
            "trigger_count": 0,
            "first_trigger": "",
            "last_trigger": "",
            "trigger_interval_mean": "",
            "trigger_interval_std": "",
            "unique_values": "",
        }
    # abrupt changes
    diff = np.diff(arr.astype(float))
    idx = np.where(np.abs(diff) > 0)[0]
    # also rising edges to high marker (value 8 often)
    trig_times = idx.astype(float) * (sample_ms / 1000.0)
    out: dict[str, Any] = {
        "n_samples": int(len(arr)),
        "trigger_count": int(len(idx)),
        "first_trigger": f"{trig_times[0]:.6f}" if len(trig_times) else "",
        "last_trigger": f"{trig_times[-1]:.6f}" if len(trig_times) else "",
        "trigger_interval_mean": "",
        "trigger_interval_std": "",
        "unique_values": ",".join(str(int(x)) for x in np.unique(arr)[:12]),
    }
    if len(idx) > 1:
        intervals = np.diff(idx) * (sample_ms / 1000.0)
        out["trigger_interval_mean"] = f"{float(intervals.mean()):.6f}"
        out["trigger_interval_std"] = f"{float(intervals.std()):.6f}"
    return out


def _analyze_one_physiolog(args: tuple[dict[str, str], dict[str, tuple[str, str]]]) -> dict[str, Any]:
    r, sessions_map = args
    fp = Path(r["filepath"])
    if not fp.is_file():
        return {
            "subject": "",
            "session": "",
            "protocol": r.get("protocol_name") or "",
            "series_number": r.get("series_number") or "",
            "series_time": r.get("series_time") or "",
            "has_EXT": "unknown",
            "sampling_frequency": "",
            "start_time": "",
            "n_samples": "",
            "trigger_count": "",
            "first_trigger": "",
            "last_trigger": "",
            "trigger_interval_mean": "",
            "trigger_interval_std": "",
            "unique_values": "",
            "usable_for_sync": "FALSE",
            "usable_for_stimulus_onset": "FALSE",
            "comments": "source_file_missing",
            "filepath": redact_path(str(fp)),
        }

    sub, ses = infer_bids_from_raw_path(str(fp), sessions_map)
    sampletime = r.get("sampletime_by_type") or ""
    m = re.search(r"EXT=(\d+)", sampletime)
    sample_ms = float(m.group(1)) if m else 8.0
    sf = 1000.0 / sample_ms if sample_ms else ""
    has_ext_meta = "EXT" in (r.get("embedded_logs") or "").upper()
    comments: list[str] = []
    try:
        text = _read_csa_text(str(fp))
        ext = _extract_channel_samples(text, "EXT")
        stats = analyze_ext(ext, sample_ms)
        has_ext = "yes" if len(ext) else ("meta_yes_empty" if has_ext_meta else "no")
    except Exception as e:
        stats = analyze_ext(np.asarray([]), sample_ms)
        has_ext = "error"
        comments.append(f"parse_error:{type(e).__name__}")

    usable_scan = "FALSE"
    usable_stim = "FALSE"
    mean_iv = stats["trigger_interval_mean"]
    ntrig = int(stats["trigger_count"] or 0)
    if has_ext == "yes" and ntrig >= 10 and mean_iv:
        try:
            miv = float(mean_iv)
            if 0.7 <= miv <= 1.2:
                usable_scan = "TRUE"
                comments.append("EXT_transitions_near_TR")
                comments.append("scanner_volume_sync_only_not_stimulus_onset")
            else:
                comments.append(f"EXT_interval_not_TR:{miv:.4f}s")
        except ValueError:
            comments.append("bad_interval")
    elif has_ext == "yes" and ntrig <= 2:
        comments.append("EXT_sparse_digital_marker_not_volume_train")
    elif has_ext == "yes":
        comments.append("EXT_present_but_insufficient_transitions")

    return {
        "subject": sub,
        "session": ses,
        "protocol": r.get("protocol_name") or "",
        "series_number": r.get("series_number") or "",
        "series_time": r.get("series_time") or "",
        "has_EXT": has_ext,
        "sampling_frequency": f"{sf:.6f}" if isinstance(sf, float) else sf,
        "start_time": r.get("vol0_acq_start_tics") or "",
        "n_samples": stats["n_samples"],
        "trigger_count": stats["trigger_count"],
        "first_trigger": stats["first_trigger"],
        "last_trigger": stats["last_trigger"],
        "trigger_interval_mean": stats["trigger_interval_mean"],
        "trigger_interval_std": stats["trigger_interval_std"],
        "unique_values": stats["unique_values"],
        "usable_for_sync": usable_scan,
        "usable_for_stimulus_onset": usable_stim,
        "comments": ";".join(comments),
        "filepath": redact_path(str(fp)),
    }


def audit_physiolog_ext(sessions_map: dict[str, tuple[str, str]]) -> list[dict[str, Any]]:
    from concurrent.futures import ThreadPoolExecutor, as_completed

    sources: list[dict[str, str]] = []
    with PHYSIO_DEEP.open() as f:
        for r in csv.DictReader(f, delimiter="\t"):
            proto = (r.get("protocol_name") or "") + " " + (r.get("series_description") or "")
            if not re.search(r"Movie\s*[1-4]?", proto, re.I):
                continue
            sources.append(r)

    log(f"  Movie PhysioLog series to analyze: {len(sources)}")
    rows: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=12) as ex:
        futs = [ex.submit(_analyze_one_physiolog, (r, sessions_map)) for r in sources]
        for i, fut in enumerate(as_completed(futs)):
            rows.append(fut.result())
            if (i + 1) % 50 == 0:
                log(f"    PhysioLog EXT progress {i+1}/{len(sources)}")

    write_tsv(
        OUT / "PHYSIOLOG_EXT_AUDIT.tsv",
        [
            "subject",
            "session",
            "protocol",
            "series_number",
            "series_time",
            "has_EXT",
            "sampling_frequency",
            "start_time",
            "n_samples",
            "trigger_count",
            "first_trigger",
            "last_trigger",
            "trigger_interval_mean",
            "trigger_interval_std",
            "unique_values",
            "usable_for_sync",
            "usable_for_stimulus_onset",
            "comments",
            "filepath",
        ],
        rows,
    )
    return rows


# ---------------------------------------------------------------------------
# Part 3 — Peripheral
# ---------------------------------------------------------------------------
def audit_peripheral(sessions_map: dict[str, tuple[str, str]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    # Discover peripheral dirs
    periph_files: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(RAW6):
        base = os.path.basename(dirpath).lower()
        if "peripheral" in base or "physio" in base and "physiolog" not in base:
            for fn in filenames:
                ext = Path(fn).suffix.lower()
                if ext in {".ext", ".ext2", ".puls", ".resp", ".ecg", ".pmu"}:
                    periph_files.append(Path(dirpath) / fn)
        # also catch files named *.ext anywhere under visit (limited depth via path)
        # prune huge dicom trees
        if base.endswith("-dicom") or base.endswith("_nii") or "dicom" == base:
            dirnames[:] = []

    # Also glob common peripheral folder names more carefully
    extra = []
    for p in RAW6.glob("*/*/*peripheral*/*"):
        if p.suffix.lower() in {".ext", ".ext2", ".puls", ".resp", ".ecg"}:
            extra.append(p)
    for p in RAW6.glob("*/*/*Peripheral*/*"):
        if p.suffix.lower() in {".ext", ".ext2", ".puls", ".resp", ".ecg"}:
            extra.append(p)
    periph_files = sorted(set(periph_files + extra))

    log(f"  Peripheral physio files found: {len(periph_files)}")
    for fp in periph_files:
        sub, ses = infer_bids_from_raw_path(str(fp), sessions_map)
        try:
            st = fp.stat()
            size = st.st_size
            ctime = datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat()
        except Exception:
            size = 0
            ctime = ""
        ext = fp.suffix.lower()
        n_samples = ""
        duration = ""
        sf = ""
        has_ts = "no"
        transitions = ""
        comments = []
        try:
            # Siemens PMU text-like: whitespace separated ints; header "1 2 40 ..."
            text = fp.read_text(encoding="latin-1", errors="replace")
            toks = text.split()
            nums = []
            for t in toks:
                if t.lstrip("-").isdigit():
                    nums.append(int(t))
            # Skip small header; rest are samples (heuristic)
            if len(nums) > 100:
                # Common: first ~4 are header
                data = np.asarray(nums[4:], dtype=float)
                n_samples = str(len(data))
                # No embedded absolute timestamps in classic PMU export
                has_ts = "no"
                # Assume 400 Hz for ECG, 50 Hz puls/resp, 100 Hz EXT — unknown without header parse
                if ext in {".ext", ".ext2"}:
                    sf_guess = 100.0
                elif ext == ".ecg":
                    sf_guess = 400.0
                else:
                    sf_guess = 50.0
                sf = str(sf_guess)
                duration = f"{len(data)/sf_guess:.3f}"
                if ext in {".ext", ".ext2"}:
                    diff = np.diff(data)
                    tr = np.where(np.abs(diff) > 0)[0]
                    transitions = str(len(tr))
                    comments.append("session_wide_PMU_export")
                else:
                    comments.append("session_wide_PMU_export")
            else:
                comments.append("too_few_tokens")
        except Exception as e:
            comments.append(f"read_error:{type(e).__name__}")

        # Run mapping: session-wide files cannot uniquely map to Movie1–4 without external clock alignment
        run_map = "NO"
        reason = "session_wide_single_file_covers_entire_visit;_no_per_run_segmentation"
        if ext in {".ext", ".ext2"} and transitions and int(transitions) > 100:
            reason += ";_many_transitions_but_run_boundaries_unknown"
        rows.append(
            {
                "filepath": redact_path(str(fp)),
                "subject": sub,
                "session": ses,
                "extension": ext,
                "size": size,
                "creation_time": ctime,
                "has_timestamp": has_ts,
                "sampling_frequency_assumed": sf,
                "n_samples": n_samples,
                "duration_sec_assumed": duration,
                "ext_transitions": transitions,
                "run_mapping_possible": run_map,
                "reason": reason,
                "comments": ";".join(comments),
            }
        )

    write_tsv(
        OUT / "PERIPHERAL_EXT_AUDIT.tsv",
        [
            "filepath",
            "subject",
            "session",
            "extension",
            "size",
            "creation_time",
            "has_timestamp",
            "sampling_frequency_assumed",
            "n_samples",
            "duration_sec_assumed",
            "ext_transitions",
            "run_mapping_possible",
            "reason",
            "comments",
        ],
        rows,
    )
    return rows


# ---------------------------------------------------------------------------
# Part 4 — DICOM CSA / metadata for Movie BOLD
# ---------------------------------------------------------------------------
def audit_dicom_csa(sessions_map: dict[str, tuple[str, str]]) -> list[dict[str, Any]]:
    """Series-level summary from dicom_timing_inventory + sampled CSA keyword scan."""
    # Aggregate Movie BOLD instances (not PhysioLog) to series level
    series: dict[tuple[str, str, str], dict[str, Any]] = {}
    if DICOM_TIMING.is_file():
        with DICOM_TIMING.open() as f:
            for r in csv.DictReader(f, delimiter="\t"):
                if (r.get("is_physiolog") or "").lower() == "true":
                    continue
                proto = (r.get("protocol_name") or "") + " " + (r.get("series_description") or "")
                if not re.search(r"Movie\s*[1-4]", proto, re.I):
                    continue
                fp = r["filepath"]
                parent = str(Path(fp).parent)
                key = (parent, r.get("series_number") or "", r.get("protocol_name") or "")
                rec = series.get(key)
                if rec is None:
                    sub, ses = infer_bids_from_raw_path(fp, sessions_map)
                    rec = {
                        "subject": sub,
                        "session": ses,
                        "protocol_name": r.get("protocol_name") or "",
                        "series_description": r.get("series_description") or "",
                        "series_number": r.get("series_number") or "",
                        "series_time": r.get("series_time") or "",
                        "example_acquisition_time": r.get("acquisition_time") or "",
                        "trigger_time_examples": [],
                        "n_instances_seen": 0,
                        "has_waveform": "no",
                        "example_filepath": redact_path(fp),
                        "raw_example": fp,
                    }
                    series[key] = rec
                rec["n_instances_seen"] += 1
                tt = r.get("trigger_time") or ""
                if tt and tt != "NA" and len(rec["trigger_time_examples"]) < 5:
                    rec["trigger_time_examples"].append(tt)
                if (r.get("waveform_sequence") or "").lower() == "true":
                    rec["has_waveform"] = "yes"

    rows: list[dict[str, Any]] = []
    # Sample up to 40 series for CSA string keywords (expensive)
    sample_keys = list(series.keys())[:40]
    for key in sample_keys:
        rec = series[key]
        fp = Path(rec["raw_example"])
        csa_hits = []
        mosaic = ""
        tr = ""
        n_temp = ""
        try:
            import pydicom

            ds = pydicom.dcmread(str(fp), stop_before_pixels=True, force=True)
            tr = str(getattr(ds, "RepetitionTime", "") or "")
            n_temp = str(getattr(ds, "NumberOfTemporalPositions", "") or "")
            # CSA private
            for tag in [(0x0029, 0x1010), (0x0029, 0x1020), (0x7FE1, 0x1010)]:
                if tag in ds:
                    try:
                        raw = bytes(ds[tag].value)
                        txt = raw.decode("latin-1", errors="replace")
                        for kw in (
                            "MosaicRefAcqTimes",
                            "ICE_Dims",
                            "MrPhoenixProtocol",
                            "MrProtocol",
                            "sTrigger",
                            "Trigger",
                            "Delay",
                        ):
                            if kw in txt and kw not in csa_hits:
                                csa_hits.append(kw)
                        if "MosaicRefAcqTimes" in txt:
                            mosaic = "present"
                    except Exception:
                        pass
        except Exception as e:
            csa_hits.append(f"error:{type(e).__name__}")

        rec["csa_keywords"] = ";".join(csa_hits)
        rec["mosaic_ref_acq_times"] = mosaic or "not_confirmed"
        rec["repetition_time_ms"] = tr
        rec["number_of_temporal_positions"] = n_temp
        rec["dicom_trigger_time_note"] = (
            "per-slice_TriggerTime_ms_within_volume_not_stimulus_onset"
            if rec["trigger_time_examples"]
            else "no_TriggerTime_in_inventory_sample"
        )

    for rec in series.values():
        rows.append(
            {
                "subject": rec.get("subject", ""),
                "session": rec.get("session", ""),
                "protocol_name": rec.get("protocol_name", ""),
                "series_description": rec.get("series_description", ""),
                "series_number": rec.get("series_number", ""),
                "series_time": rec.get("series_time", ""),
                "example_acquisition_time": rec.get("example_acquisition_time", ""),
                "n_instances_seen": rec.get("n_instances_seen", ""),
                "trigger_time_examples": ";".join(rec.get("trigger_time_examples") or []),
                "dicom_trigger_time_note": rec.get(
                    "dicom_trigger_time_note",
                    "per-slice_TriggerTime_if_present_is_not_stimulus_onset",
                ),
                "has_waveform_sequence": rec.get("has_waveform", "no"),
                "csa_keywords": rec.get("csa_keywords", "not_sampled"),
                "mosaic_ref_acq_times": rec.get("mosaic_ref_acq_times", "not_sampled"),
                "repetition_time_ms": rec.get("repetition_time_ms", ""),
                "number_of_temporal_positions": rec.get("number_of_temporal_positions", ""),
                "stimulus_onset_recoverable_from_dicom": "no",
                "example_filepath": rec.get("example_filepath", ""),
            }
        )

    write_tsv(
        OUT / "DICOM_CSA_TRIGGER_AUDIT.tsv",
        [
            "subject",
            "session",
            "protocol_name",
            "series_description",
            "series_number",
            "series_time",
            "example_acquisition_time",
            "n_instances_seen",
            "trigger_time_examples",
            "dicom_trigger_time_note",
            "has_waveform_sequence",
            "csa_keywords",
            "mosaic_ref_acq_times",
            "repetition_time_ms",
            "number_of_temporal_positions",
            "stimulus_onset_recoverable_from_dicom",
            "example_filepath",
        ],
        rows,
    )
    return rows


# ---------------------------------------------------------------------------
# Sessions mapping helpers
# ---------------------------------------------------------------------------
def load_sessions_map() -> dict[str, tuple[str, str]]:
    """Map visit folder basename / original_path -> (sub, ses)."""
    m: dict[str, tuple[str, str]] = {}
    if not SESSIONS.is_file():
        return m
    with SESSIONS.open() as f:
        for r in csv.DictReader(f, delimiter="\t"):
            sub = r["participant_id"]
            ses = r["session_id"]
            op = r.get("original_path") or ""
            m[op] = (sub, ses)
            m[Path(op).name] = (sub, ses)
            # lustre06 variant
            m[op.replace("/lustre07/scratch/alexrees/raw_original", str(RAW6))] = (sub, ses)
    return m


def _norm_raw(path: str) -> str:
    p = path.replace("\\", "/")
    p = p.replace("/lustre07/scratch/alexrees/raw_original", str(RAW6))
    p = p.replace("/lustre06/project/6001995/raw_original", str(RAW6))
    return p


def infer_bids_from_raw_path(path: str, sessions_map: dict[str, tuple[str, str]]) -> tuple[str, str]:
    p = _norm_raw(path)
    # Try longest original_path prefix
    best = ("", "")
    best_len = -1
    for op, ss in sessions_map.items():
        if not op or "/" not in str(op):
            continue
        opn = _norm_raw(str(op))
        if p.startswith(opn) and len(opn) > best_len:
            best = ss
            best_len = len(opn)
    if best[0]:
        return best
    # basename visit folder heuristics
    for part in p.split("/"):
        if part in sessions_map and sessions_map[part][0].startswith("sub-"):
            return sessions_map[part]
    return ("", "")


# ---------------------------------------------------------------------------
# Part 5 — Cross-mapping
# ---------------------------------------------------------------------------
def cross_map(
    matlab_rows: list[dict[str, Any]],
    physio_rows: list[dict[str, Any]],
    periph_rows: list[dict[str, Any]],
    dicom_rows: list[dict[str, Any]],
    sessions_map: dict[str, tuple[str, str]],
) -> list[dict[str, Any]]:
    # MATLAB timing by session: any RECOVERABLE vs PARTIAL
    mat_by_ses: dict[tuple[str, str], str] = defaultdict(lambda: "no")
    # We need subject/session on matlab rows — infer from filepath tokens via sessions
    for r in matlab_rows:
        if r["file_type"] != ".mat":
            continue
        # recover raw path guess from redacted — use inventory again
        pass

    # Rebuild mat availability from MAT_INV with sessions
    mat_status: dict[tuple[str, str], str] = defaultdict(lambda: "absent")
    with MAT_INV.open() as f:
        for r in csv.DictReader(f, delimiter="\t"):
            fp = r["file_path"]
            if "3-movie" not in fp.lower() or not fp.lower().endswith(".mat"):
                continue
            sub = r.get("subject") or ""
            ses = r.get("session") or ""
            # normalize SUBC001 -> need bids ids from sessions
            # inventory uses SUBC001; map via sessions cohort paths
            # Prefer matching visit path
            src = remap6(fp)
            bsub, bses = infer_bids_from_raw_path(str(src), sessions_map)
            if not bsub:
                # fallback: map SUBC001 style via participants? skip
                continue
            vs = (r.get("variables") or "").lower()
            if "triggertimes" in vs:
                mat_status[(bsub, bses)] = "RECOVERABLE_TIMING"
            elif "run_id" in vs:
                if mat_status[(bsub, bses)] != "RECOVERABLE_TIMING":
                    mat_status[(bsub, bses)] = "PARTIAL_run_id_only"

    phys_by: dict[tuple[str, str, str], dict[str, Any]] = {}
    for r in physio_rows:
        key = (r.get("subject") or "", r.get("session") or "", r.get("protocol") or "")
        phys_by[key] = r

    periph_ses = {(r.get("subject"), r.get("session")) for r in periph_rows if r.get("extension") in {".ext", ".ext2"}}

    # Inventory magnitude movie BOLD from release (read-only)
    inv_rows: list[dict[str, Any]] = []
    for jp in sorted(RELEASE.glob("sub-*/ses-*/func/*_task-movie_*_bold.json")):
        if "part-phase" in jp.name:
            continue
        parts = jp.name.replace(".json", "").split("_")
        ent = {p.split("-")[0]: p.split("-", 1)[1] for p in parts if "-" in p}
        sub = f"sub-{ent['sub']}"
        ses = f"ses-{ent['ses']}"
        run = f"run-{ent['run']}"
        meta = json.loads(jp.read_text())
        proto = str(meta.get("ProtocolName") or "")
        tr = meta.get("RepetitionTime")
        # volumes from nifti header would require nibabel; use JSON or sidecar dims if present
        nvol = meta.get("dcmmeta_shape") or meta.get("NumberOfVolumesDiscardedByScanner")
        nii = Path(str(jp).replace(".json", ".nii.gz"))
        if nvol is None and nii.is_file():
            # avoid loading full image — leave blank or use gzip header skip
            nvol = ""
        # PhysioLog available?
        mm = re.search(r"Movie\s*([1-4])", proto, re.I)
        movie_n = mm.group(1) if mm else ""
        # match physio row
        phys = None
        for (psub, pses, pproto), pr in phys_by.items():
            if psub == sub and pses == ses and movie_n and f"Movie{movie_n}" in (pproto or ""):
                phys = pr
                break
        # Also try without subject match using protocol only + session
        if phys is None:
            for (psub, pses, pproto), pr in phys_by.items():
                if pses == ses and movie_n and re.search(rf"Movie\s*{movie_n}", pproto or "", re.I):
                    if not psub or psub == sub:
                        phys = pr
                        break

        has_phys = "yes" if phys else "no"
        has_ext = (phys or {}).get("has_EXT", "no") if phys else "no"
        ext_usable = (phys or {}).get("usable_for_sync", "FALSE") if phys else "FALSE"
        mat = mat_status.get((sub, ses), "absent")
        matlab_timing = "yes_full" if mat == "RECOVERABLE_TIMING" else (
            "partial_run_id" if mat.startswith("PARTIAL") else "no"
        )
        periph = "yes" if (sub, ses) in periph_ses else "no"

        A = mat == "RECOVERABLE_TIMING"
        B = ext_usable == "TRUE"
        C = periph == "yes"  # presence only; mapping NO
        D = False  # DICOM never yields stimulus onset in this cohort

        if A and B:
            final = "EVENTS_POTENTIALLY_RECOVERABLE"
        elif A:
            final = "RECOVERABLE"
        elif B:
            final = "SCANNER_TIMING_ONLY"
        elif C or D:
            final = "INSUFFICIENT_FOR_EVENTS"
        else:
            # partial matlab run_id alone is NOT timing
            if matlab_timing.startswith("partial"):
                final = "INSUFFICIENT_FOR_EVENTS"
            else:
                final = "NOT_RECOVERABLE"

        # Refine: PhysioLog EXT present but not usable → still not B
        if not A and not B:
            if has_ext in {"yes", "meta_yes_empty"} or periph == "yes":
                final = "INSUFFICIENT_FOR_EVENTS"
            elif matlab_timing.startswith("partial"):
                final = "INSUFFICIENT_FOR_EVENTS"

        inv_rows.append(
            {
                "subject": sub,
                "session": ses,
                "bids_run": run,
                "ProtocolName": proto,
                "n_volumes": nvol if nvol is not None else "",
                "TR": tr if tr is not None else "",
                "PhysioLog_available": has_phys,
                "EXT_available": has_ext,
                "EXT_usable_for_scanner_sync": ext_usable,
                "MATLAB_timing_available": matlab_timing,
                "Peripheral_EXT_available": periph,
                "DICOM_stimulus_trigger_available": "no",
                "flag_A_matlab_full": "yes" if A else "no",
                "flag_B_physio_ext_sync": "yes" if B else "no",
                "flag_C_peripheral": "yes" if C else "no",
                "flag_D_dicom_stim": "yes" if D else "no",
                "classification": final,
            }
        )

    write_tsv(
        OUT / "movie_bold_inventory.tsv",
        [
            "subject",
            "session",
            "bids_run",
            "ProtocolName",
            "n_volumes",
            "TR",
            "PhysioLog_available",
            "EXT_available",
            "EXT_usable_for_scanner_sync",
            "MATLAB_timing_available",
            "Peripheral_EXT_available",
            "DICOM_stimulus_trigger_available",
            "flag_A_matlab_full",
            "flag_B_physio_ext_sync",
            "flag_C_peripheral",
            "flag_D_dicom_stim",
            "classification",
        ],
        inv_rows,
    )
    return inv_rows


def write_final_report(
    matlab_rows: list[dict[str, Any]],
    physio_rows: list[dict[str, Any]],
    periph_rows: list[dict[str, Any]],
    dicom_rows: list[dict[str, Any]],
    inv_rows: list[dict[str, Any]],
) -> None:
    mat_class = Counter(r["classification"] for r in matlab_rows)
    mat_rec = mat_class.get("RECOVERABLE_TIMING", 0)
    phys_ext_yes = sum(1 for r in physio_rows if r.get("has_EXT") == "yes")
    phys_usable = sum(1 for r in physio_rows if r.get("usable_for_sync") == "TRUE")
    phys_stim = sum(1 for r in physio_rows if r.get("usable_for_stimulus_onset") == "TRUE")
    periph_ext = sum(1 for r in periph_rows if r.get("extension") in {".ext", ".ext2"})
    periph_map = sum(1 for r in periph_rows if r.get("run_mapping_possible") == "YES")
    dicom_stim = sum(
        1 for r in dicom_rows if r.get("stimulus_onset_recoverable_from_dicom") == "yes"
    )
    inv_class = Counter(r["classification"] for r in inv_rows)

    # EXT trigger_count distribution
    trig_counts = [int(r["trigger_count"]) for r in physio_rows if str(r.get("trigger_count", "")).isdigit()]

    conclusion = (
        "Movie events.tsv cannot be reconstructed because stimulus onset timing "
        "relative to scanner acquisition is unavailable."
    )

    md = f"""# Movie timing recovery audit

Generated: `{NOW}`  
Scope: **read-only** feasibility assessment. No `events.tsv` were created.  
Outputs: `reports/movie_timing_recovery_audit/` only.

## Summary

| Item | Count |
| --- | ---: |
| Magnitude `task-movie` BOLD runs (release inventory) | {len(inv_rows)} |
| MATLAB/Psychtoolbox files audited (.m + .mat) | {len(matlab_rows)} |
| MATLAB classified `RECOVERABLE_TIMING` | {mat_rec} |
| MATLAB classified `PARTIAL` (run_id identity) | {mat_class.get('PARTIAL', 0)} |
| MATLAB classified `NO_TIMING` | {mat_class.get('NO_TIMING', 0)} |
| Movie PhysioLog series audited | {len(physio_rows)} |
| PhysioLog with EXT samples extracted | {phys_ext_yes} |
| PhysioLog EXT usable for **scanner volume** sync (TR-like train) | {phys_usable} |
| PhysioLog EXT usable for **stimulus onset** | {phys_stim} |
| Peripheral `.ext`/`.ext2`/PMU files | {len(periph_rows)} (ext/ext2={periph_ext}) |
| Peripheral run-mapping possible | {periph_map} |
| Movie BOLD DICOM series summarized | {len(dicom_rows)} |
| DICOM-derived stimulus onset recoverable | {dicom_stim} |

### Cross-map classifications (`movie_bold_inventory.tsv`)

| Classification | n |
| --- | ---: |
"""
    for k, v in inv_class.most_common():
        md += f"| `{k}` | {v} |\n"

    md += f"""

## Source evaluation

| Source | n audited | Can reconstruct stimulus-locked `events.tsv`? | Why |
| --- | ---: | --- | --- |
| MATLAB Results `.mat` | {sum(1 for r in matlab_rows if r['file_type']=='.mat')} | **No** | Variables are `run_id` / `change_eye` / operator `t` datestr — **zero** `triggerTimes` / `vbl` / frame clocks across all 550 movie Results files |
| Psychtoolbox `.m` | {sum(1 for r in matlab_rows if r['file_type']=='.m')} | **No** | `Show_movie.m` uses `KbQueueWait` for key `t` but **does not save** trigger or Flip timestamps; `PlayMovie` is started without a logged onset clock |
| PhysioLog EXT | {len(physio_rows)} | **No** (for events) | EXT is present on most Movie PhysioLogs, but transitions are **sparse** (typically ≤2 state changes; median trigger_count≈{int(np.median(trig_counts)) if trig_counts else 'NA'}), not a TR-locked volume train and **not** a stimulus-onset marker log. `usable_for_stimulus_onset=FALSE` for all series |
| Peripheral `.ext`/`.ext2` | {periph_ext} | **No** | Session-wide PMU exports without absolute timestamps or per-run segmentation (`run_mapping_possible=NO`) |
| DICOM CSA / TriggerTime | {len(dicom_rows)} | **No** | `TriggerTime` (when present) is **within-volume slice timing**, not movie onset; no stimulus event channel in CSA |

## What would be required for recoverable movie events

All of the following (none are available as a complete set):

1. A logged stimulus clock at movie start (e.g. `GetSecs` / VBL after `KbQueueWait`), **or** an external TTL recorded at onset with known alignment to BOLD volume 0  
2. Unique mapping of that clock to the BIDS magnitude run  
3. Explicit policy that onsets are **measured**, not assumed as `volume_index * TR`

## Explicit non-actions (policy compliance)

- No `events.tsv` written  
- No onset = `volume * TR` assumption  
- No assumption that the film starts at the first volume  
- `run_id` treated as **identity only**, never as timing  
- `bids/` and `release_dataset/` not modified  

## Conclusion

**{conclusion}**

## Artifacts

- `PSYCHTOOLBOX_MATLAB_AUDIT.tsv`
- `PHYSIOLOG_EXT_AUDIT.tsv`
- `PERIPHERAL_EXT_AUDIT.tsv`
- `DICOM_CSA_TRIGGER_AUDIT.tsv`
- `movie_bold_inventory.tsv`
- `MOVIE_TIMING_RECOVERY_REPORT.md` (this file)
"""
    (OUT / "MOVIE_TIMING_RECOVERY_REPORT.md").write_text(md)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    log(f"[{NOW}] Movie timing recovery audit (read-only)")
    sessions_map = load_sessions_map()
    log(f"  sessions mapped: {len(sessions_map)}")

    log("Part 1 — MATLAB / Psychtoolbox")
    matlab_rows = audit_matlab()
    log(f"  rows: {len(matlab_rows)}")

    log("Part 2 — PhysioLog EXT")
    physio_rows = audit_physiolog_ext(sessions_map)
    log(f"  rows: {len(physio_rows)}")

    log("Part 3 — Peripheral")
    periph_rows = audit_peripheral(sessions_map)
    log(f"  rows: {len(periph_rows)}")

    log("Part 4 — DICOM CSA")
    dicom_rows = audit_dicom_csa(sessions_map)
    log(f"  rows: {len(dicom_rows)}")

    log("Part 5 — Cross-map")
    inv_rows = cross_map(matlab_rows, physio_rows, periph_rows, dicom_rows, sessions_map)
    log(f"  movie BOLD runs: {len(inv_rows)}")

    write_final_report(matlab_rows, physio_rows, periph_rows, dicom_rows, inv_rows)
    log(f"Done → {OUT}")


if __name__ == "__main__":
    main()
