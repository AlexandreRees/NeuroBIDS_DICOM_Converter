#!/usr/bin/env python3
"""READ-ONLY Siemens PMU EXT (.ext / .ext2) recoverability audit.

Purpose
-------
Determine whether peripheral PMU EXT files contain recoverable scanner-like
trigger trains and whether they can be fail-closed mapped to a unique BIDS
BOLD run. Does NOT create events.tsv. Does NOT inject EXT into BIDS.

Safety
------
* Never modifies raw_original/, bids/, release_dataset/, or existing derivatives/
* Writes ONLY under reports/ext_recovery_audit/ (or --output)
* --dry-run is REQUIRED (refuses to run without it)
* No PHI in outputs (no absolute paths, no SUBC/SUBG tokens, hashed UIDs)

Example
-------
python code/audit_ext_recovery.py \\
  --raw /lustre06/project/6001995/raw_original \\
  --bids /lustre07/scratch/alexrees/bids \\
  --output reports/ext_recovery_audit \\
  --dry-run
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import logging
import os
import re
import struct
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import numpy as np

try:
    import pydicom
except ImportError:  # pragma: no cover
    pydicom = None

LOGGER = logging.getLogger("audit_ext_recovery")

NA = "NA"
PMU_CTRL = {"5000", "5002", "5003", "6000", "6002", "6003"}
_RE_SUBJ = re.compile(r"(SUB[A-Z]*\d+)", re.I)
_RE_DATE = re.compile(r"20\d{2}[A-Z]{3,}\d{0,2}", re.I)
_RE_SESS = re.compile(r"session[\s_-]*0*([12])", re.I)
_RE_LOGSTART = re.compile(r"LogStartMDHTime:\s*(-?\d+)")
_RE_LOGSTOP = re.compile(r"LogStopMDHTime:\s*(-?\d+)")
_RE_NRTRIG = re.compile(r"NrTrig\s+NrMP\s+NrArr\s+AcqWin:\s*(-?\d+)\s+(-?\d+)\s+(-?\d+)\s+(-?\d+)")
_RE_FREQ = re.compile(
    r"^(EXT2?|EXT)\s+Freq\s+Per:\s*(-?\d+)\s+(-?\d+)", re.M | re.I
)
_RE_BOLD = re.compile(
    r"^(?P<sub>sub-[0-9]+)_"
    r"(?P<ses>ses-[0-9]+)_"
    r"task-(?P<task>[^_]+)_"
    r"(?:run-(?P<run>[0-9]+)_)?"
    r"bold\.json$",
    re.I,
)
PHI_SCAN_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("SUBC_token", re.compile(r"\bSUBC\d+", re.I)),
    ("SUBG_token", re.compile(r"\bSUBG\d+", re.I)),
    ("Windows_path", re.compile(r"[A-Za-z]:\\")),
    ("Unix_home", re.compile(r"/home/[A-Za-z0-9._-]+")),
    ("Absolute_lustre", re.compile(r"/lustre\d+/")),
    ("Absolute_project", re.compile(r"/project/")),
    ("PatientName", re.compile(r"\bPatientName\b", re.I)),
    ("Email", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha(s: str, n: int = 12) -> str:
    return hashlib.sha256(s.encode("utf-8", errors="replace")).hexdigest()[:n]


def _hash_uid(uid: str) -> str:
    uid = (uid or "").strip()
    if not uid:
        return NA
    return "uid_" + _sha(uid, 16)


def anonymize_relpath(path: Path, raw_root: Path) -> str:
    try:
        rel = path.resolve().relative_to(raw_root.resolve()).as_posix()
    except Exception:
        rel = path.name
    rel = _RE_SUBJ.sub(lambda m: "SUBJ_" + _sha(m.group(1).upper(), 8), rel)
    rel = _RE_DATE.sub("DATE", rel)
    # scrub residual long numeric IDs that look like study dates
    rel = re.sub(r"\b20\d{6}\b", "DATE", rel)
    return rel



def nifti_n_volumes(nii_path: Path) -> Optional[int]:
    """Read NIfTI dim[4] from header only (supports .nii / .nii.gz)."""
    try:
        if str(nii_path).endswith('.nii.gz'):
            with gzip.open(nii_path, 'rb') as fh:
                hdr = fh.read(352)
        else:
            with nii_path.open('rb') as fh:
                hdr = fh.read(352)
        if len(hdr) < 56:
            return None
        sizeof_hdr = struct.unpack('<i', hdr[0:4])[0]
        if sizeof_hdr not in (348, 540):
            sizeof_hdr = struct.unpack('>i', hdr[0:4])[0]
            endian = '>'
        else:
            endian = '<'
        dim = struct.unpack(f'{endian}8h', hdr[40:56])
        if dim[0] >= 4 and dim[4] > 0:
            return int(dim[4])
        if dim[0] == 3:
            return 1
    except OSError:
        return None
    return None


def write_tsv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames, delimiter="\t", extrasaction="ignore")
        w.writeheader()
        for r in rows:
            out = {k: ("" if r.get(k) is None else r.get(k)) for k in fieldnames}
            w.writerow(out)


def load_participant_maps(metadata_roots: list[Path]) -> tuple[dict[str, str], dict[str, tuple[str, str]]]:
    """folder_name -> participant_id ; folder_name -> (participant, session)."""
    folder_to_pid: dict[str, str] = {}
    folder_to_sess: dict[str, tuple[str, str]] = {}
    for root in metadata_roots:
        part = root / "participant_mapping.csv"
        if part.is_file():
            with part.open(newline="", encoding="utf-8", errors="replace") as fh:
                for row in csv.DictReader(fh):
                    pid = (row.get("participant_id") or "").strip()
                    for folder in (row.get("source_subject_folder") or "").split("|"):
                        folder = folder.strip()
                        if folder and pid:
                            folder_to_pid[folder] = pid
        sess = root / "session_mapping.csv"
        if sess.is_file():
            with sess.open(newline="", encoding="utf-8", errors="replace") as fh:
                for row in csv.DictReader(fh):
                    folder = (row.get("source_subject_folder") or "").strip()
                    pid = folder_to_pid.get(folder, "")
                    # prefer explicit participant if present
                    for key in ("participant_id", "bids_participant", "participant"):
                        if row.get(key):
                            pid = row[key].strip()
                    sl = (row.get("session_label") or "").strip()
                    if folder and pid:
                        folder_to_sess[folder] = (pid, sl or NA)
                        folder_to_pid.setdefault(folder, pid)
    return folder_to_pid, folder_to_sess


def map_path_to_bids_ids(
    path: Path, folder_to_pid: dict[str, str], folder_to_sess: dict[str, tuple[str, str]]
) -> tuple[str, str]:
    parts = set(path.parts)
    for folder, (pid, ses) in folder_to_sess.items():
        if folder in parts:
            return pid, ses if ses != NA else NA
    for folder, pid in folder_to_pid.items():
        if folder in parts:
            # session guess from path
            ses = NA
            for part in path.parts:
                m = _RE_SESS.search(part)
                if m:
                    ses = f"ses-{int(m.group(1)):02d}"
                    break
            return pid, ses
    # unmapped — emit opaque id (no SUBC)
    cand = NA
    for part in reversed(path.parts):
        m = _RE_SUBJ.search(part)
        if m:
            cand = "unmap_" + _sha(m.group(1).upper(), 10)
            break
    if cand == NA:
        cand = "unmap_" + _sha(str(path), 10)
    ses = NA
    for part in path.parts:
        m = _RE_SESS.search(part)
        if m:
            ses = f"ses-{int(m.group(1)):02d}"
            break
    return cand, ses


# ---------------------------------------------------------------------------
# EXT discovery + parsing
# ---------------------------------------------------------------------------
def discover_ext_files(raw_root: Path) -> list[Path]:
    """Prefer GNU find (faster on Lustre); fall back to os.walk."""
    import subprocess

    found: list[Path] = []
    try:
        LOGGER.info("Discovering EXT via find under raw…")
        proc = subprocess.run(
            [
                "find",
                str(raw_root),
                "(",
                "-iname",
                "*.ext",
                "-o",
                "-iname",
                "*.ext2",
                ")",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=3600,
        )
        for line in proc.stdout.splitlines():
            line = line.strip()
            if line:
                found.append(Path(line))
    except Exception as exc:
        LOGGER.warning("find failed (%s); falling back to os.walk", exc)
        found = []
        for dirpath, _dirs, filenames in os.walk(raw_root):
            for name in filenames:
                low = name.lower()
                if low.endswith(".ext") or low.endswith(".ext2"):
                    found.append(Path(dirpath) / name)
    found = sorted(set(found))
    LOGGER.info("Discovered %d EXT files under raw", len(found))
    return found


@dataclass
class ExtParse:
    parse_status: str = "unreadable"
    n_samples: int = 0
    n_transitions: int = 0
    n_digital_transitions: int = 0  # 0<->nonzero flips
    values: list[int] = field(default_factory=list)
    transition_indices: list[int] = field(default_factory=list)
    log_start_mdh: Optional[int] = None
    log_stop_mdh: Optional[int] = None
    nr_trig: Optional[int] = None
    freq_per_a: Optional[int] = None
    freq_per_b: Optional[int] = None
    duration_seconds: Optional[float] = None
    sampling_frequency: Optional[float] = None
    first_timestamp: str = NA
    last_timestamp: str = NA
    format_guess: str = NA


def _extract_waveform_values(tokens: list[str]) -> list[int]:
    """Siemens PMU stream: prefer tokens between 6002 and 5003; else all non-ctrl ints."""
    start = None
    end = None
    if "6002" in tokens:
        start = tokens.index("6002") + 1
    if "5003" in tokens:
        end = tokens.index("5003")
    if start is not None and end is not None and end > start:
        region = tokens[start:end]
    elif "5002" in tokens:
        # data may follow leading info ending in 5002
        i = tokens.index("5002") + 1
        region = tokens[i:]
        if "5003" in region:
            region = region[: region.index("5003")]
    else:
        region = tokens

    vals: list[int] = []
    for tok in region:
        if tok in PMU_CTRL:
            continue
        # skip footer labels that leaked into stream
        if not tok.lstrip("-").isdigit():
            break
        try:
            vals.append(int(tok))
        except ValueError:
            break
    return vals


def parse_ext_file(path: Path) -> ExtParse:
    out = ExtParse()
    try:
        raw = path.read_bytes()
    except OSError:
        return out
    if not raw:
        out.parse_status = "empty"
        return out
    if b"\x00" in raw[:256]:
        out.parse_status = "binary_unsupported"
        return out

    text = raw.decode("latin-1", errors="replace")
    # footer / header metadata
    m = _RE_LOGSTART.search(text)
    if m:
        out.log_start_mdh = int(m.group(1))
        out.first_timestamp = f"MDH:{m.group(1)}"
    m = _RE_LOGSTOP.search(text)
    if m:
        out.log_stop_mdh = int(m.group(1))
        out.last_timestamp = f"MDH:{m.group(1)}"
    m = _RE_NRTRIG.search(text)
    if m:
        out.nr_trig = int(m.group(1))
    m = _RE_FREQ.search(text)
    if m:
        out.freq_per_a = int(m.group(2))
        out.freq_per_b = int(m.group(3))

    if out.log_start_mdh is not None and out.log_stop_mdh is not None:
        # Siemens MDH times are ms-of-day (may wrap); use abs delta
        dt_ms = out.log_stop_mdh - out.log_start_mdh
        if dt_ms < 0:
            dt_ms += 24 * 60 * 60 * 1000
        out.duration_seconds = dt_ms / 1000.0

    # Prefer stream before footer labels
    cut = len(text)
    for marker in ("\nECG", "\nPULS", "\nRESP", "\nEXT ", "\nLogStart"):
        j = text.find(marker)
        if j > 0:
            cut = min(cut, j)
    stream = text[:cut] if cut < len(text) else text
    tokens = stream.split()
    # Also allow CSV-like two-column parse
    vals = _extract_waveform_values(tokens)
    fmt = "siemens_pmu_ascii"
    if len(vals) < 10:
        # try line-oriented numeric / csv
        vals2: list[int] = []
        times: list[float] = []
        for line in text.splitlines():
            line = line.strip()
            if not line or line[0].isalpha() or ":" in line[:20]:
                continue
            parts = re.split(r"[\s,;]+", line)
            nums = []
            for p in parts:
                try:
                    nums.append(float(p))
                except ValueError:
                    nums = []
                    break
            if len(nums) == 1:
                vals2.append(int(nums[0]))
            elif len(nums) >= 2:
                times.append(nums[0])
                vals2.append(int(nums[1]))
        if len(vals2) > len(vals):
            vals = vals2
            fmt = "csv_or_lines"
            if len(times) == len(vals2) and len(times) > 1:
                out.duration_seconds = float(times[-1] - times[0])
                out.first_timestamp = f"t:{times[0]:.6g}"
                out.last_timestamp = f"t:{times[-1]:.6g}"
                if out.duration_seconds > 0:
                    out.sampling_frequency = (len(times) - 1) / out.duration_seconds

    out.n_samples = len(vals)
    out.format_guess = fmt
    if out.n_samples == 0:
        out.parse_status = "no_waveform"
        return out

    # transitions (keep indices only; drop waveform to limit memory)
    tr_idx = [i for i in range(1, len(vals)) if vals[i] != vals[i - 1]]
    out.transition_indices = tr_idx
    out.n_transitions = len(tr_idx)
    dig = 0
    for i in tr_idx:
        a, b = vals[i - 1], vals[i]
        if a == 0 or b == 0 or (abs(a) <= 2 and abs(b) <= 2):
            dig += 1
    out.n_digital_transitions = dig
    out.values = []  # release waveform

    if out.sampling_frequency is None and out.duration_seconds and out.duration_seconds > 0 and out.n_samples > 1:
        # Derived only from MDH duration + sample count (not Siemens default invent)
        out.sampling_frequency = (out.n_samples - 1) / out.duration_seconds

    out.parse_status = "ok"
    return out


def characterize_signal(ext_id: str, parse: ExtParse) -> dict[str, Any]:
    row = {
        "ext_id": ext_id,
        "n_transitions": parse.n_transitions,
        "n_digital_transitions": parse.n_digital_transitions,
        "nr_trig_footer": parse.nr_trig if parse.nr_trig is not None else NA,
        "mean_interval": NA,
        "median_interval": NA,
        "std_interval": NA,
        "min_interval": NA,
        "max_interval": NA,
        "regularity_score": NA,
        "trigger_like_score": 0.0,
        "notes": parse.parse_status,
    }
    if parse.n_transitions < 2 or not parse.sampling_frequency or parse.sampling_frequency <= 0:
        row["notes"] = parse.parse_status + ";insufficient_for_interval"
        return row

    # intervals in seconds between transitions
    idx = np.asarray(parse.transition_indices, dtype=float)
    dt = np.diff(idx) / float(parse.sampling_frequency)
    dt = dt[np.isfinite(dt) & (dt > 0)]
    if dt.size == 0:
        return row
    mean_i = float(np.mean(dt))
    med_i = float(np.median(dt))
    std_i = float(np.std(dt))
    cv = std_i / med_i if med_i > 0 else 999.0
    # regularity: 1 when CV→0
    regularity = float(max(0.0, min(1.0, 1.0 / (1.0 + cv))))

    # trigger-like: many transitions + regular + median near plausible TR band (0.5–3s)
    # or near 1 sample cadence if oversampled digital
    n = parse.n_transitions
    dens = min(1.0, n / 50.0)
    tr_band = 1.0 if 0.4 <= med_i <= 3.0 else (0.4 if 0.05 <= med_i <= 5.0 else 0.1)
    dig_frac = parse.n_digital_transitions / max(n, 1)
    trigger_like = float(max(0.0, min(1.0, 0.35 * dens + 0.35 * regularity + 0.20 * tr_band + 0.10 * dig_frac)))

    row.update(
        {
            "mean_interval": f"{mean_i:.6g}",
            "median_interval": f"{med_i:.6g}",
            "std_interval": f"{std_i:.6g}",
            "min_interval": f"{float(np.min(dt)):.6g}",
            "max_interval": f"{float(np.max(dt)):.6g}",
            "regularity_score": f"{regularity:.4f}",
            "trigger_like_score": f"{trigger_like:.4f}",
            "notes": parse.parse_status,
        }
    )
    # keep numeric copies on object via return side channel
    row["_mean_interval"] = mean_i
    row["_median_interval"] = med_i
    row["_trigger_like"] = trigger_like
    row["_regularity"] = regularity
    return row


# ---------------------------------------------------------------------------
# BOLD inventory
# ---------------------------------------------------------------------------
def inventory_bold(bids: Path) -> list[dict[str, Any]]:
    from concurrent.futures import ThreadPoolExecutor, as_completed

    rows: list[dict[str, Any]] = []
    LOGGER.info("Scanning BOLD JSON under bids…")
    bold_jsons = sorted(bids.glob("sub-*/ses-*/func/*_bold.json"))
    LOGGER.info("Found %d *_bold.json", len(bold_jsons))

    def _one(jp: Path) -> Optional[dict[str, Any]]:
        m = _RE_BOLD.match(jp.name)
        if not m:
            return None
        try:
            meta = json.loads(jp.read_text(encoding="utf-8"))
        except Exception:
            meta = {}
        tr = meta.get("RepetitionTime")
        try:
            tr_f = float(tr) if tr is not None else float("nan")
        except Exception:
            tr_f = float("nan")
        nvol: Any = NA
        nvol_i = meta.get("NumberOfTemporalPositions")
        if nvol_i is not None and not isinstance(nvol_i, list):
            try:
                nvol = int(nvol_i)
            except Exception:
                nvol = NA
        if nvol == NA:
            nii = jp.with_name(jp.name.replace("_bold.json", "_bold.nii.gz"))
            if not nii.is_file():
                nii = jp.with_name(jp.name.replace("_bold.json", "_bold.nii"))
            if nii.is_file():
                nv = nifti_n_volumes(nii)
                nvol = nv if nv is not None else NA
        dur = NA
        if isinstance(nvol, int) and nvol > 0 and np.isfinite(tr_f):
            dur = f"{tr_f * nvol:.6g}"
        return {
            "subject": m.group("sub"),
            "session": m.group("ses"),
            "task": m.group("task"),
            "run": m.group("run") or "NA",
            "TR": f"{tr_f:.6g}" if np.isfinite(tr_f) else NA,
            "n_volumes": nvol if nvol != NA else NA,
            "duration_seconds": dur,
            "AcquisitionTime": meta.get("AcquisitionTime") or meta.get("AcquisitionDateTime") or NA,
            "SeriesDescription": meta.get("SeriesDescription") or meta.get("ProtocolName") or NA,
            "_tr": tr_f,
            "_nvol": nvol if isinstance(nvol, int) else None,
            "_dur": float(dur) if dur != NA else None,
            "bold_id": jp.stem.replace("_bold", ""),
        }

    done = 0
    with ThreadPoolExecutor(max_workers=16) as ex:
        futs = [ex.submit(_one, jp) for jp in bold_jsons]
        for fut in as_completed(futs):
            row = fut.result()
            done += 1
            if row is not None:
                rows.append(row)
            if done % 250 == 0:
                LOGGER.info("BOLD inventory progress: %d/%d", done, len(bold_jsons))
    rows.sort(key=lambda r: (r["subject"], r["session"], r["task"], r["run"]))
    LOGGER.info("BOLD runs inventoried: %d", len(rows))
    return rows


# ---------------------------------------------------------------------------
# DICOM timing (series-level, hashed UIDs)
# ---------------------------------------------------------------------------
def inventory_dicom_timing_from_metadata(metadata_roots: list[Path]) -> list[dict[str, Any]]:
    """Hashed DICOM timing from session_mapping.csv (no raw UIDs)."""
    rows: list[dict[str, Any]] = []
    for root in metadata_roots:
        sess = root / "session_mapping.csv"
        if not sess.is_file():
            continue
        with sess.open(newline="", encoding="utf-8", errors="replace") as fh:
            for row in csv.DictReader(fh):
                suid = (row.get("series_instance_uid") or "").strip()
                rows.append(
                    {
                        "series_uid_hash": _hash_uid(suid) if suid else NA,
                        "series_number": row.get("series_number") or NA,
                        "series_description": str(row.get("series_description") or NA)[:80],
                        "modality": row.get("modality") or NA,
                        "acquisition_time": NA,
                        "series_time": row.get("series_time") or NA,
                        "trigger_time": NA,
                        "n_temporal_positions": NA,
                        "instance_number": NA,
                        "relative_dir": NA,
                        "source": "session_mapping",
                    }
                )
        break
    LOGGER.info("DICOM timing rows from metadata: %d", len(rows))
    return rows


def inventory_dicom_timing(raw_root: Path, max_series: int = 20000) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if pydicom is None:
        LOGGER.warning("pydicom not available — DICOM_TIMING_INVENTORY empty")
        return rows
    skip_dir_names = {
        "peripheral", "physio", "matlab", "nii", "nifti", "derivatives",
        "work", "tmp", "temp", ".git",
    }
    n_series = 0
    for dirpath, dirnames, filenames in os.walk(raw_root):
        # prune noisy / non-DICOM trees
        dirnames[:] = [
            d for d in dirnames
            if d.lower() not in skip_dir_names
            and "peripheral" not in d.lower()
            and "physio" not in d.lower()
            and not d.lower().endswith("_matlab")
            and "matlab" not in d.lower()
        ]
        dcms = [
            f for f in filenames
            if f.lower().endswith((".dcm", ".ima"))
            or (f.endswith(".IMA"))
        ]
        if not dcms:
            continue
        dpath = Path(dirpath)
        rep = None
        for name in sorted(dcms)[:5]:
            fp = dpath / name
            try:
                ds = pydicom.dcmread(str(fp), stop_before_pixels=True, force=True)
                if getattr(ds, "Modality", None) or getattr(ds, "SeriesInstanceUID", None):
                    rep = ds
                    break
            except Exception:
                continue
        if rep is None:
            continue
        n_series += 1
        if n_series % 200 == 0:
            LOGGER.info("DICOM series reps so far: %d", n_series)
        rows.append(
            {
                "series_uid_hash": _hash_uid(str(getattr(rep, "SeriesInstanceUID", "") or "")),
                "series_number": getattr(rep, "SeriesNumber", NA),
                "series_description": str(getattr(rep, "SeriesDescription", NA) or NA)[:80],
                "modality": getattr(rep, "Modality", NA),
                "acquisition_time": getattr(rep, "AcquisitionTime", NA),
                "series_time": getattr(rep, "SeriesTime", NA),
                "trigger_time": getattr(rep, "TriggerTime", NA),
                "n_temporal_positions": getattr(rep, "NumberOfTemporalPositions", NA),
                "instance_number": getattr(rep, "InstanceNumber", NA),
                "relative_dir": anonymize_relpath(dpath, raw_root),
            }
        )
        if n_series >= max_series:
            LOGGER.warning("DICOM series cap (%d) reached", max_series)
            break
    LOGGER.info("DICOM series reps: %d", len(rows))
    return rows



# ---------------------------------------------------------------------------
# Matching EXT → BOLD (fail-closed)
# ---------------------------------------------------------------------------
def score_ext_bold(parse: ExtParse, char: dict[str, Any], bold: dict[str, Any]) -> dict[str, Any]:
    """Return component scores in [0,1] and decision fields."""
    tr = bold.get("_tr")
    nvol = bold.get("_nvol")
    dur = bold.get("_dur")
    med_i = char.get("_median_interval")
    n_tr = parse.n_digital_transitions or parse.n_transitions
    # Prefer footer NrTrig when present
    if parse.nr_trig is not None and parse.nr_trig > 0:
        n_tr_use = parse.nr_trig
    else:
        n_tr_use = n_tr

    trigger_match = 0.0
    if isinstance(nvol, int) and nvol > 0 and n_tr_use > 0:
        rel = abs(n_tr_use - nvol) / max(nvol, 1)
        trigger_match = float(max(0.0, 1.0 - rel))

    tr_match = 0.0
    if med_i is not None and tr is not None and np.isfinite(tr) and tr > 0 and med_i > 0:
        rel = abs(med_i - tr) / tr
        tr_match = float(max(0.0, 1.0 - rel))

    duration_match = 0.0
    if parse.duration_seconds and dur is not None and dur > 0:
        # Session-wide EXT duration >> single run → low score (fail-closed)
        rel = abs(parse.duration_seconds - dur) / max(dur, 1.0)
        if parse.duration_seconds > 2.5 * dur:
            duration_match = float(max(0.0, 0.15 - 0.01 * (parse.duration_seconds / dur)))
            duration_match = max(0.0, duration_match)
        else:
            duration_match = float(max(0.0, 1.0 - rel))

    # DICOM time proximity not available without absolute clocks → 0 unless AcquisitionTime present
    # and EXT MDH convertible — we do NOT invent clock sync → leave 0 (fail-closed)
    dicom_match = 0.0

    # Session-wide penalty
    session_wide_penalty = 0.0
    if parse.duration_seconds and dur and parse.duration_seconds > 3.0 * dur:
        session_wide_penalty = 0.35

    tl = float(char.get("_trigger_like") or 0.0)
    score = (
        0.30 * trigger_match
        + 0.25 * tr_match
        + 0.25 * duration_match
        + 0.10 * dicom_match
        + 0.10 * tl
        - session_wide_penalty
    )
    score = float(max(0.0, min(1.0, score)))

    return {
        "score": score,
        "trigger_match": trigger_match,
        "TR_match": tr_match,
        "duration_match": duration_match,
        "dicom_match": dicom_match,
        "session_wide_penalty": session_wide_penalty,
        "n_triggers_used": n_tr_use,
    }


def map_ext_to_bold(
    ext_rows: list[dict[str, Any]],
    parses: dict[str, ExtParse],
    chars: dict[str, dict[str, Any]],
    bold_rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    candidates: list[dict[str, Any]] = []
    summary: list[dict[str, Any]] = []

    bold_by_subses: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for b in bold_rows:
        bold_by_subses[(b["subject"], b["session"])].append(b)

    for er in ext_rows:
        eid = er["ext_id"]
        parse = parses[eid]
        char = chars[eid]
        sub = er.get("subject_mapped", NA)
        ses = er.get("session_mapped", NA)
        pool = bold_by_subses.get((sub, ses), [])
        # If session unknown, do not global-match (fail-closed)
        scored: list[tuple[float, dict[str, Any], dict[str, Any]]] = []
        for b in pool:
            sc = score_ext_bold(parse, char, b)
            scored.append((sc["score"], sc, b))
        scored.sort(key=lambda x: -x[0])

        decision = "REJECT"
        if not scored:
            decision = "REJECT"
            candidates.append(
                {
                    "ext_id": eid,
                    "subject": sub,
                    "session": ses,
                    "task": NA,
                    "run": NA,
                    "score": 0.0,
                    "trigger_match": 0.0,
                    "TR_match": 0.0,
                    "duration_match": 0.0,
                    "dicom_match": 0.0,
                    "decision": "REJECT",
                    "reason": "no_bold_in_mapped_session_or_unmapped",
                }
            )
        else:
            top_score, top_sc, top_b = scored[0]
            near = [s for s, _, _ in scored if s >= top_score - 0.05 and s >= 0.5]
            # ACCEPT only if extremely clear AND unique
            if top_score > 0.95 and len(near) == 1 and top_sc["session_wide_penalty"] == 0:
                decision = "ACCEPT"
            elif top_score >= 0.5 or len(near) > 1:
                decision = "REVIEW"
            else:
                decision = "REJECT"

            for rank, (s, sc, b) in enumerate(scored[:10], start=1):
                dec = decision if rank == 1 else "CANDIDATE"
                # Never escalate non-top to ACCEPT
                if dec == "ACCEPT" and rank != 1:
                    dec = "CANDIDATE"
                # Fail-closed: if decision ACCEPT but another near, force REVIEW
                if decision == "ACCEPT" and len(near) > 1:
                    decision = "REVIEW"
                    dec = "REVIEW" if rank == 1 else "CANDIDATE"
                candidates.append(
                    {
                        "ext_id": eid,
                        "subject": b["subject"],
                        "session": b["session"],
                        "task": b["task"],
                        "run": b["run"],
                        "score": f"{s:.4f}",
                        "trigger_match": f"{sc['trigger_match']:.4f}",
                        "TR_match": f"{sc['TR_match']:.4f}",
                        "duration_match": f"{sc['duration_match']:.4f}",
                        "dicom_match": f"{sc['dicom_match']:.4f}",
                        "decision": dec if rank == 1 else "CANDIDATE",
                        "reason": (
                            f"rank={rank};n_trig={sc['n_triggers_used']};"
                            f"penalty_sw={sc['session_wide_penalty']:.2f}"
                        ),
                    }
                )
            # ensure top decision reflected
            if candidates:
                # fix last batch top row decision
                for c in reversed(candidates):
                    if c["ext_id"] == eid and not str(c["decision"]).startswith("CAND"):
                        c["decision"] = decision
                        break

        # Trigger recovery summary vs each bold in session (compact)
        for b in pool:
            sc = score_ext_bold(parse, char, b)
            summary.append(
                {
                    "ext_id": eid,
                    "bold_id": b["bold_id"],
                    "subject": b["subject"],
                    "session": b["session"],
                    "task": b["task"],
                    "run": b["run"],
                    "bold_TR": b["TR"],
                    "bold_n_volumes": b["n_volumes"],
                    "ext_n_transitions": parse.n_transitions,
                    "ext_nr_trig_footer": parse.nr_trig if parse.nr_trig is not None else NA,
                    "ext_median_interval": char.get("median_interval", NA),
                    "trigger_count_abs_diff": (
                        abs((parse.nr_trig or parse.n_digital_transitions or parse.n_transitions) - (b["_nvol"] or -1))
                        if b.get("_nvol")
                        else NA
                    ),
                    "score": f"{sc['score']:.4f}",
                    "decision_hint": (
                        "POSSIBLE"
                        if sc["score"] >= 0.5 and sc["session_wide_penalty"] == 0
                        else "UNLIKELY"
                    ),
                }
            )

    return candidates, summary


# ---------------------------------------------------------------------------
# PHI scan + report
# ---------------------------------------------------------------------------
def phi_scan(output_dir: Path) -> list[dict[str, Any]]:
    rows = []
    for fp in sorted(output_dir.rglob("*")):
        if not fp.is_file():
            continue
        if fp.suffix.lower() not in {".tsv", ".md", ".txt", ".csv"}:
            continue
        try:
            text = fp.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for name, pat in PHI_SCAN_PATTERNS:
            for i, line in enumerate(text.splitlines(), start=1):
                if pat.search(line):
                    rows.append(
                        {
                            "file": fp.name,
                            "line": i,
                            "pattern": name,
                            "severity": "HIGH" if name.startswith(("SUB", "Unix", "Windows", "Absolute", "Patient", "Email")) else "MEDIUM",
                            "status": "FAIL",
                        }
                    )
                    break
    if not rows:
        rows.append(
            {
                "file": NA,
                "line": NA,
                "pattern": NA,
                "severity": NA,
                "status": "PASS",
            }
        )
    return rows


def write_report(
    path: Path,
    inv: list[dict[str, Any]],
    chars: list[dict[str, Any]],
    bold: list[dict[str, Any]],
    dicom: list[dict[str, Any]],
    cands: list[dict[str, Any]],
) -> dict[str, int]:
    n_ext = len(inv)
    n_ok = sum(1 for r in inv if r.get("parse_status") == "ok")
    n_triglike = sum(1 for r in chars if float(r.get("trigger_like_score") or 0) >= 0.5)
    # unique ext decisions from candidates (non-CANDIDATE)
    decisions = {}
    for c in cands:
        if c["decision"] == "CANDIDATE":
            continue
        decisions[c["ext_id"]] = c["decision"]
    n_accept = sum(1 for d in decisions.values() if d == "ACCEPT")
    n_review = sum(1 for d in decisions.values() if d == "REVIEW")
    n_reject = sum(1 for d in decisions.values() if d == "REJECT")
    # also count EXT with only REJECT stub
    for r in inv:
        decisions.setdefault(r["ext_id"], "REJECT")
    n_reject = sum(1 for d in decisions.values() if d == "REJECT")
    n_review = sum(1 for d in decisions.values() if d == "REVIEW")
    n_accept = sum(1 for d in decisions.values() if d == "ACCEPT")

    accept_list = [eid for eid, d in decisions.items() if d == "ACCEPT"]
    review_list = [eid for eid, d in decisions.items() if d == "REVIEW"]

    lines = [
        "# EXT recovery audit",
        "",
        f"Generated (UTC): {_now()}",
        "",
        "Read-only evaluation of Siemens peripheral PMU `.ext` / `.ext2` recoverability.",
        "No `events.tsv` created. No BIDS/raw modification.",
        "",
        "## Dataset summary",
        "",
        f"- EXT files found: **{n_ext}**",
        f"- EXT parsable waveforms: **{n_ok}**",
        f"- EXT trigger-like (score≥0.5): **{n_triglike}**",
        f"- BOLD runs inventoried: **{len(bold)}**",
        f"- DICOM series reps: **{len(dicom)}**",
        f"- Mappings ACCEPT: **{n_accept}**",
        f"- Mappings REVIEW: **{n_review}**",
        f"- Mappings REJECT: **{n_reject}**",
        "",
        "## Scientifically usable EXT",
        "",
    ]
    if accept_list:
        for eid in accept_list:
            lines.append(f"- `{eid}`")
    else:
        lines.append("_None. Fail-closed: no EXT met ACCEPT (score>0.95, unique, not session-wide)._")
    lines += ["", "## Ambiguous EXT", ""]
    if review_list:
        for eid in review_list[:50]:
            lines.append(f"- `{eid}`")
        if len(review_list) > 50:
            lines.append(f"- … {len(review_list) - 50} more")
    else:
        lines.append("_None._")
    lines += [
        "",
        "## Why EXT were not integrated",
        "",
        "1. **Session-wide recording** — peripheral `.ext` typically spans the entire visit,",
        "   far longer than any single BOLD run (`duration_match` collapses under fail-closed rules).",
        "2. **No run identifier** — filenames/folders do not encode BIDS task/run entities.",
        "3. **No validated StartTime** — MDH ticks exist but absolute sync to BOLD `AcquisitionTime`",
        "   is not assumed (would invent a clock transform).",
        "4. **Ambiguous trigger counts** — transition counts / `NrTrig` rarely match a unique",
        "   run's `n_volumes` within the session.",
        "5. **SamplingFrequency** — Siemens `Freq Per` for EXT is often `0 0`; Fs is only",
        "   derived when MDH start/stop + sample count are both present.",
        "",
        "## Method notes",
        "",
        "- Waveforms parsed as Siemens ASCII PMU token streams (control codes 5000/5002/5003/6000/6002/6003 excluded).",
        "- `trigger_like_score` combines transition density, interval regularity, TR-plausible median interval, digital flip fraction.",
        "- ACCEPT requires score>0.95, a single near-candidate, and no session-wide duration penalty.",
        "",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"ACCEPT": n_accept, "REVIEW": n_review, "REJECT": n_reject}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--raw", type=Path, required=True, help="Path to raw_original (read-only)")
    p.add_argument("--bids", type=Path, required=True, help="Path to BIDS root (read-only)")
    p.add_argument(
        "--output",
        type=Path,
        default=Path("reports/ext_recovery_audit"),
        help="Output directory (must be under reports/)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="REQUIRED. Confirms read-only audit (writes only to --output).",
    )
    p.add_argument("--metadata", type=Path, nargs="*", default=None, help="Dirs with participant_mapping.csv")
    p.add_argument("--max-dicom-series", type=int, default=300,
                   help="Cap raw pydicom series sample (0=metadata only)")
    p.add_argument("--limit-ext", type=int, default=None, help="Optional cap for smoke tests")
    p.add_argument("-v", "--verbose", action="store_true")
    return p


def main(argv: Optional[list[str]] = None) -> int:
    args = build_argparser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    if not args.dry_run:
        LOGGER.error("--dry-run is mandatory for this audit. Refusing to run.")
        print("ERROR: --dry-run is required", file=sys.stderr)
        return 2

    raw = args.raw.resolve()
    bids = args.bids.resolve()
    out = args.output
    if not str(out).replace("\\", "/").startswith("reports/") and "reports/ext_recovery_audit" not in str(out):
        # allow absolute path ending with reports/ext_recovery_audit
        if out.name != "ext_recovery_audit" and "ext_recovery_audit" not in out.parts:
            LOGGER.error("Output must be reports/ext_recovery_audit (got %s)", out)
            return 2

    if not raw.is_dir():
        LOGGER.error("raw not found: %s", raw)
        return 2
    if not bids.is_dir():
        LOGGER.error("bids not found: %s", bids)
        return 2

    # Resolve output under workspace if relative
    if not out.is_absolute():
        # prefer CWD; also support running from scratch root
        out = (Path.cwd() / out).resolve()
    out.mkdir(parents=True, exist_ok=True)

    meta_roots = args.metadata or [
        Path("/lustre07/scratch/alexrees/metadata"),
        Path("/home/alexrees/scratch/metadata"),
    ]
    folder_to_pid, folder_to_sess = load_participant_maps(meta_roots)

    # --- Step 1–2: EXT inventory + parse ---
    ext_files = discover_ext_files(raw)
    if args.limit_ext:
        ext_files = ext_files[: args.limit_ext]

    inv_rows: list[dict[str, Any]] = []
    parses: dict[str, ExtParse] = {}
    char_rows: list[dict[str, Any]] = []
    chars: dict[str, dict[str, Any]] = {}

    for i, fp in enumerate(ext_files, start=1):
        rel = anonymize_relpath(fp, raw)
        ext_id = "ext_" + _sha(rel + "|" + str(fp.stat().st_size if fp.exists() else 0), 12)
        sub, ses = map_path_to_bids_ids(fp, folder_to_pid, folder_to_sess)
        parse = parse_ext_file(fp)
        parses[ext_id] = parse
        try:
            size_b = fp.stat().st_size
            mtime = datetime.fromtimestamp(fp.stat().st_mtime, timezone.utc).isoformat()
        except OSError:
            size_b = -1
            mtime = NA

        inv_rows.append(
            {
                "ext_id": ext_id,
                "relative_path": rel,
                "extension": fp.suffix.lower(),
                "size_bytes": size_b,
                "duration_seconds": f"{parse.duration_seconds:.6g}" if parse.duration_seconds else NA,
                "n_samples": parse.n_samples,
                "sampling_frequency": f"{parse.sampling_frequency:.6g}" if parse.sampling_frequency else NA,
                "n_transitions": parse.n_transitions,
                "first_timestamp": parse.first_timestamp,
                "last_timestamp": parse.last_timestamp,
                "parse_status": parse.parse_status,
                "format_guess": parse.format_guess,
                "subject_mapped": sub,
                "session_mapped": ses,
                "mtime_utc": mtime,
                "parent_dir": anonymize_relpath(fp.parent, raw),
            }
        )
        ch = characterize_signal(ext_id, parse)
        chars[ext_id] = ch
        char_rows.append({k: v for k, v in ch.items() if not k.startswith("_")})
        LOGGER.info(
            "Parsed %d/%d EXT status=%s n_samp=%s n_tr=%s",
            i,
            len(ext_files),
            parse.parse_status,
            parse.n_samples,
            parse.n_transitions,
        )

    # --- Step 3: BOLD ---
    bold_rows = inventory_bold(bids)

    # --- Step 4: DICOM ---
    dicom_rows = inventory_dicom_timing_from_metadata(meta_roots)
    if args.max_dicom_series > 0:
        raw_dicom = inventory_dicom_timing(raw, max_series=args.max_dicom_series)
        for r in raw_dicom:
            r["source"] = "pydicom_sample"
            dicom_rows.append(r)
    else:
        LOGGER.info("Skipping raw DICOM sample (--max-dicom-series 0)")

    # --- Step 5–6: matching ---
    cand_rows, trig_summary = map_ext_to_bold(inv_rows, parses, chars, bold_rows)

    # Write tables
    write_tsv(
        out / "EXT_INVENTORY.tsv",
        inv_rows,
        [
            "ext_id",
            "relative_path",
            "extension",
            "size_bytes",
            "duration_seconds",
            "n_samples",
            "sampling_frequency",
            "n_transitions",
            "first_timestamp",
            "last_timestamp",
        ],
    )
    write_tsv(
        out / "EXT_SIGNAL_CHARACTERIZATION.tsv",
        char_rows,
        [
            "ext_id",
            "n_transitions",
            "mean_interval",
            "median_interval",
            "std_interval",
            "regularity_score",
            "trigger_like_score",
        ],
    )
    write_tsv(
        out / "BOLD_RUN_INVENTORY.tsv",
        bold_rows,
        ["subject", "session", "task", "run", "TR", "n_volumes", "duration_seconds", "AcquisitionTime"],
    )
    write_tsv(
        out / "DICOM_TIMING_INVENTORY.tsv",
        dicom_rows,
        [
            "series_uid_hash",
            "series_number",
            "series_description",
            "modality",
            "acquisition_time",
            "series_time",
            "trigger_time",
            "n_temporal_positions",
            "instance_number",
            "relative_dir",
            "source",
        ],
    )
    write_tsv(
        out / "EXT_BOLD_MAPPING_CANDIDATES.tsv",
        cand_rows,
        [
            "ext_id",
            "subject",
            "session",
            "task",
            "run",
            "score",
            "trigger_match",
            "TR_match",
            "duration_match",
            "dicom_match",
            "decision",
        ],
    )
    write_tsv(
        out / "TRIGGER_RECOVERY_SUMMARY.tsv",
        trig_summary,
        [
            "ext_id",
            "bold_id",
            "subject",
            "session",
            "task",
            "run",
            "bold_TR",
            "bold_n_volumes",
            "ext_n_transitions",
            "ext_nr_trig_footer",
            "ext_median_interval",
            "trigger_count_abs_diff",
            "score",
            "decision_hint",
        ],
    )

    counts = write_report(out / "EXT_RECOVERY_REPORT.md", inv_rows, char_rows, bold_rows, dicom_rows, cand_rows)
    phi_rows = phi_scan(out)
    write_tsv(out / "PHI_SCAN_EXT_REPORT.tsv", phi_rows, ["file", "line", "pattern", "severity", "status"])

    print()
    print("EXT recovery audit completed")
    print()
    print(f"ACCEPT: {counts['ACCEPT']}")
    print(f"REVIEW: {counts['REVIEW']}")
    print(f"REJECT: {counts['REJECT']}")
    print()
    print("BIDS modified:")
    print("NO")
    print()
    print("RAW modified:")
    print("NO")
    return 0


if __name__ == "__main__":
    sys.exit(main())
