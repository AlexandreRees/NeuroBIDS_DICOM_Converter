#!/usr/bin/env python3
"""Deep read-only physiology recovery audit for BIDS Level-1 readiness.

Inspects Siemens PhysioLog files under raw_original/, compares them to BIDS
BOLD sidecars, and writes audit reports only under reports/physiology_audit/.

Safety constraints (hard):
  * Never modify bids/ or raw_original/
  * Never create *_physio.tsv.gz or any BIDS physiology products
  * Never invent SamplingFrequency, StartTime, or run mappings
  * Never treat Siemens ``Freq Per`` as ADC sampling frequency
  * Never convert MDH/MPCU ticks to BIDS StartTime without validation
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

LOGGER = logging.getLogger("physio_recovery")
NA = "NA"

DEFAULT_RAW = Path("/project/def-amirs/raw_original")
DEFAULT_BIDS = Path("/lustre07/scratch/alexrees/bids")
DEFAULT_META = Path("/lustre07/scratch/alexrees/metadata")
DEFAULT_OUT = Path("/home/alexrees/scratch/reports/physiology_audit")

PHYSIO_EXTS = {".ecg", ".resp", ".puls", ".ext", ".ext1", ".ext2", ".pmu"}
TEXT_EXTS = {".txt", ".log"}
PHYSIO_KEYWORDS = ("ECG", "RESP", "PULS", "PHYSIO", "PMU")

_RE_SUBJECT = re.compile(r"(SUB[A-Z]*\d+)", re.IGNORECASE)
_RE_SESSION = re.compile(r"(?:session|ses)[\s_-]*0*([12])", re.IGNORECASE)
_RE_BIDS_SUB = re.compile(r"(sub-\d+)", re.IGNORECASE)
_RE_BOLD = re.compile(
    r"(sub-\d+)_(ses-\d+)_task-([A-Za-z0-9]+)(?:_.*)?_run-(\d+)_bold\.nii\.gz$"
)
_RE_DICOM_SERIES_DIR = re.compile(r".+_\d{3,4}$")

_RE_LOGVERSION = re.compile(r"LOGVERSION[_A-Z0-9]*", re.IGNORECASE)
_RE_VSN = re.compile(r"VSN\s+([0-9][0-9.]*)\s+([0-9A-Za-z\-]+)")
_RE_FREQ_PER = re.compile(
    r"^(ECG|PULS|RESP|EXT2?|EXT)\s+Freq\s+Per:\s*(-?\d+)\s+(-?\d+)\s*$",
    re.MULTILINE | re.IGNORECASE,
)
_RE_MINMAX = re.compile(
    r"^(ECG|PULS|RESP|EXT2?|EXT)\s+Min\s+Max\s+Avg\s+StdDiff:\s+"
    r"(-?\d+)\s+(-?\d+)\s+(-?\d+)\s+(-?\d+)\s*$",
    re.MULTILINE | re.IGNORECASE,
)
_RE_NRTRIG = re.compile(
    r"NrTrig\s+NrMP\s+NrArr\s+AcqWin:\s*(-?\d+)\s+(-?\d+)\s+(-?\d+)\s+(-?\d+)"
)
_RE_LOGSTART_MDH = re.compile(r"LogStartMDHTime:\s*(-?\d+)")
_RE_LOGSTOP_MDH = re.compile(r"LogStopMDHTime:\s*(-?\d+)")
_RE_LOGSTART_MPCU = re.compile(r"LogStartMPCUTime:\s*(-?\d+)")
_RE_LOGSTOP_MPCU = re.compile(r"LogStopMPCUTime:\s*(-?\d+)")

# Explicit ADC / sample-rate labels only.
_RE_EXPLICIT_SF = re.compile(
    r"(?P<label>"
    r"(?:ECG|RESP(?:IRATION|IRATORY)?|PULS(?:E)?|PHYSIO)?[ _.-]*"
    r"(?:SamplingFrequency|Sampling[_ ]?Rate|Sample[_ ]?Rate|ADC[_ ]?Frequency|"
    r"SampleTime|SamplePeriod|SamplingInterval|SampleInterval)"
    r")\s*[:=]?\s*(?P<value>\d+(?:\.\d+)?)\s*(?P<units>Hz|ms|s|sec|seconds)?\b",
    re.IGNORECASE,
)
_RE_BARE_HZ = re.compile(
    r"\b(?P<label>Frequency|Freq)\s*[:=]\s*(?P<value>\d+(?:\.\d+)?)\s*(?P<units>Hz)\b",
    re.IGNORECASE,
)
_RE_COMMON_RATES = re.compile(r"(?<!\d)(400|500|600)(?!\d)")

_PMU_CONTROL = {"5000", "5002", "5003", "6000", "6002", "6003"}

# Siemens literature often cites these ADC rates; NEVER accept as fact here.
SIEMENS_DEFAULT_HYPOTHESES = {
    ".ecg": 400.0,
    ".puls": 50.0,
    ".resp": 50.0,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
        force=True,
    )


def _write_tsv(path: Path, fieldnames: list[str], rows: Iterable[dict[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(
            fh, fieldnames=fieldnames, delimiter="\t", lineterminator="\n", extrasaction="ignore"
        )
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fieldnames})
            n += 1
    return n


def _is_dicom_dump_dir(name: str) -> bool:
    upper = name.upper()
    if _RE_DICOM_SERIES_DIR.match(name):
        return True
    if upper.startswith("DR_SHMUEL"):
        return True
    if "PROTOCOL_" in upper:
        return True
    if upper.endswith("_NII") or upper.endswith("_DICOM"):
        return True
    return False


def _looks_binary(raw: bytes) -> bool:
    head = raw[:256]
    if not head:
        return False
    if b"\x00" in head:
        return True
    textish = sum(1 for b in head if 9 <= b <= 13 or 32 <= b <= 126)
    return (textish / len(head)) < 0.7


def _stat_times(path: Path) -> tuple[str, str, str]:
    try:
        st = path.stat()
    except OSError:
        return NA, NA, NA
    size = str(st.st_size)
    mtime = datetime.fromtimestamp(st.st_mtime, timezone.utc).isoformat()
    birth = getattr(st, "st_birthtime", None)
    if birth is not None:
        ctime = datetime.fromtimestamp(birth, timezone.utc).isoformat()
    else:
        # Linux ext4: st_ctime is metadata change, not birth — report as NA.
        ctime = NA
    return size, ctime, mtime


# ---------------------------------------------------------------------------
# Metadata maps
# ---------------------------------------------------------------------------
@dataclass
class SessionInfo:
    participant_id: str = NA
    session_id: str = NA
    cohort: str = NA
    study_date: str = NA
    study_time: str = NA
    source_folder: str = NA


@dataclass
class ProjectMaps:
    folder_to_session: dict[str, SessionInfo] = field(default_factory=dict)
    participant_folders: dict[str, str] = field(default_factory=dict)


def load_project_maps(metadata_root: Path) -> ProjectMaps:
    maps = ProjectMaps()
    sess = metadata_root / "session_mapping.csv"
    if sess.is_file():
        with sess.open(encoding="utf-8", newline="", errors="replace") as fh:
            for row in csv.DictReader(fh):
                folder = (row.get("source_subject_folder") or "").strip()
                if not folder:
                    continue
                info = SessionInfo(
                    participant_id=(row.get("participant_id") or "").strip() or NA,
                    session_id=(row.get("session_id") or row.get("session_label") or "").strip()
                    or NA,
                    cohort=(row.get("cohort") or "").strip() or NA,
                    study_date=(row.get("study_date") or row.get("acquisition_date") or "").strip()
                    or NA,
                    study_time=(row.get("study_time") or row.get("series_time") or "").strip()
                    or NA,
                    source_folder=folder,
                )
                # Prefer first included row; keep existing if already set.
                if folder not in maps.folder_to_session:
                    maps.folder_to_session[folder] = info
                elif maps.folder_to_session[folder].participant_id == NA and info.participant_id != NA:
                    maps.folder_to_session[folder] = info
    else:
        LOGGER.warning("session_mapping.csv missing under %s", metadata_root)

    part = metadata_root / "participant_mapping.csv"
    if part.is_file():
        with part.open(encoding="utf-8", newline="", errors="replace") as fh:
            for row in csv.DictReader(fh):
                pid = (row.get("participant_id") or "").strip()
                folders = (row.get("source_subject_folder") or "").split("|")
                for folder in folders:
                    folder = folder.strip()
                    if folder and pid:
                        maps.participant_folders[folder] = pid
    LOGGER.info(
        "Loaded %d session folders, %d participant folder links",
        len(maps.folder_to_session),
        len(maps.participant_folders),
    )
    return maps


def resolve_ids(path: Path, maps: ProjectMaps) -> tuple[str, str, SessionInfo | None]:
    parts = set(path.parts)
    for folder, info in maps.folder_to_session.items():
        if folder in parts:
            return info.participant_id, info.session_id, info
    for folder, pid in maps.participant_folders.items():
        if folder in parts:
            return pid, NA, None
    # Path heuristics only when mapping absent.
    sub = NA
    ses = NA
    for part in reversed(path.parts):
        if sub == NA:
            m = _RE_SUBJECT.search(part)
            if m:
                sub = m.group(1).upper()
        if ses == NA:
            m = _RE_SESSION.search(part)
            if m:
                ses = f"ses-{int(m.group(1)):02d}"
        if sub != NA and ses != NA:
            break
    return sub, ses, None


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------
def discover_files(raw_root: Path) -> list[Path]:
    found: list[Path] = []
    n_dirs = 0
    for dirpath, dirs, filenames in os.walk(raw_root):
        n_dirs += 1
        # Keep discovery complete for physio extensions, but prune DICOM dumps
        # when scanning for keyword .txt/.log to avoid pathological I/O.
        prune = [_is_dicom_dump_dir(d) for d in dirs]
        # Always discover by extension without reading content.
        for name in filenames:
            ext = os.path.splitext(name)[1].lower()
            fpath = Path(dirpath) / name
            if ext in PHYSIO_EXTS:
                found.append(fpath)
            elif ext in TEXT_EXTS and not any(
                _is_dicom_dump_dir(p) for p in Path(dirpath).parts[-3:]
            ):
                # Cheap name filter first; content check later.
                upper = name.upper()
                if any(k in upper for k in PHYSIO_KEYWORDS):
                    found.append(fpath)
        # Do not prune dirs for extension discovery of .ecg/.resp/... which can
        # sit next to DICOM trees; only skip deep DICOM series folders.
        dirs[:] = [d for d, skip in zip(dirs, prune) if not skip]
        if n_dirs % 5000 == 0:
            LOGGER.info("Walked %d directories, found %d candidates so far", n_dirs, len(found))

    # Second pass: keyword .txt that lacked keyword in filename — sample only
    # non-DICOM peripheral-like folders (already pruned walk above missed bare
    # names). Re-walk with content sniff for .txt under folders matching
    # physio/peripheral keywords.
    for dirpath, dirs, filenames in os.walk(raw_root):
        dirs[:] = [d for d in dirs if not _is_dicom_dump_dir(d)]
        leaf = Path(dirpath).name.upper()
        if not any(k in leaf for k in ("PHYSIO", "PERIPH", "PMU", "ECG", "PULS", "RESP")):
            continue
        for name in filenames:
            ext = os.path.splitext(name)[1].lower()
            if ext not in TEXT_EXTS:
                continue
            fpath = Path(dirpath) / name
            if fpath in found:
                continue
            try:
                sample = fpath.read_bytes()[:8192].decode("latin-1", errors="replace").upper()
            except OSError:
                continue
            if any(k in sample for k in PHYSIO_KEYWORDS):
                found.append(fpath)

    unique = sorted(set(found))
    LOGGER.info("Discovered %d physiology-related files under %s", len(unique), raw_root)
    return unique


def build_inventory(files: list[Path], maps: ProjectMaps) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for path in files:
        size, ctime, mtime = _stat_times(path)
        subject, session, _info = resolve_ids(path, maps)
        rows.append(
            {
                "file_path": str(path),
                "subject": subject,
                "session": session if session != NA else "session_unknown",
                "extension": path.suffix.lower() or NA,
                "file_size": size,
                "creation_time": ctime,
                "modification_time": mtime,
            }
        )
    return rows


# ---------------------------------------------------------------------------
# Format / sampling / timestamps
# ---------------------------------------------------------------------------
@dataclass
class ParsedPhysio:
    file: str
    extension: str
    format_detected: str = NA
    channels: str = NA
    n_samples: str = NA
    header_detected: str = "false"
    timestamp_present: str = "false"
    sampling_metadata_present: str = "false"
    parse_status: str = NA
    log_start_mdh: str = NA
    log_stop_mdh: str = NA
    log_start_mpcu: str = NA
    log_stop_mpcu: str = NA
    freq_per_raw: str = NA
    nr_trig: str = NA
    logversion: str = NA
    waveform: np.ndarray | None = None
    text_sample: str = ""


def _count_samples(tokens: list[str]) -> int | None:
    try:
        start = tokens.index("6002")
    except ValueError:
        return None
    end = None
    for i in range(start + 1, len(tokens)):
        if tokens[i] == "5003":
            end = i
            break
    if end is None:
        return None
    n = 0
    for tok in tokens[start + 1 : end]:
        if tok.lstrip("-").isdigit() and tok not in _PMU_CONTROL:
            n += 1
    return n if n > 0 else None


def _extract_waveform(tokens: list[str], max_points: int = 5000) -> np.ndarray | None:
    try:
        start = tokens.index("6002")
    except ValueError:
        return None
    values: list[int] = []
    for tok in tokens[start + 1 :]:
        if tok == "5003":
            break
        if tok.lstrip("-").isdigit() and tok not in _PMU_CONTROL:
            values.append(int(tok))
            if len(values) >= max_points:
                break
    if not values:
        return None
    return np.asarray(values, dtype=np.int32)


def parse_file(path: Path) -> ParsedPhysio:
    out = ParsedPhysio(file=str(path), extension=path.suffix.lower())
    try:
        raw = path.read_bytes()
    except OSError as exc:
        out.parse_status = f"unreadable:{exc}"
        out.format_detected = "unreadable"
        return out
    if not raw:
        out.parse_status = "empty"
        out.format_detected = "empty"
        return out

    if _looks_binary(raw):
        out.parse_status = "binary"
        out.format_detected = "siemens_binary_pmu_or_unknown"
        head = raw[:512].decode("latin-1", errors="replace")
        m = _RE_VSN.search(head)
        if m:
            out.logversion = f"VSN {m.group(1)} {m.group(2)}"
            out.header_detected = "true"
            out.format_detected = "siemens_binary_pmu_vsn"
        # Do not decode binary payload without a validated parser.
        return out

    text = raw.decode("latin-1", errors="replace")
    out.text_sample = text[:20000] + "\n" + text[-8000:]
    out.parse_status = "text"
    tokens = text.split()

    has_footer = bool(_RE_LOGSTART_MDH.search(text) or _RE_FREQ_PER.search(text))
    has_ctrl = any(t in _PMU_CONTROL for t in tokens[:200]) or "5002" in tokens or "6002" in tokens
    if has_footer or has_ctrl or _RE_LOGVERSION.search(text):
        out.format_detected = "siemens_ascii_pmu"
        out.header_detected = "true"
    else:
        out.format_detected = "text_unclassified"
        out.header_detected = "false"

    m = _RE_LOGVERSION.search(text)
    if m:
        out.logversion = m.group(0)

    channels: list[str] = []
    freq_bits: list[str] = []
    for chan, freq, per in _RE_FREQ_PER.findall(text):
        channels.append(chan.upper())
        freq_bits.append(f"{chan.upper()} Freq Per: {freq} {per}")
    for chan, *_rest in _RE_MINMAX.findall(text):
        cu = chan.upper()
        if cu not in channels:
            channels.append(cu)
    # Channel from extension if footer missing.
    ext_chan = {
        ".ecg": "ECG",
        ".resp": "RESP",
        ".puls": "PULS",
        ".ext": "EXT",
        ".ext1": "EXT1",
        ".ext2": "EXT2",
        ".pmu": "PMU",
    }.get(out.extension)
    if ext_chan and ext_chan not in channels:
        channels.append(ext_chan)
    out.channels = ";".join(channels) if channels else NA
    out.freq_per_raw = " | ".join(freq_bits) if freq_bits else NA

    n = _count_samples(tokens)
    out.n_samples = str(n) if n is not None else NA
    out.waveform = _extract_waveform(tokens)

    for regex, attr in (
        (_RE_LOGSTART_MDH, "log_start_mdh"),
        (_RE_LOGSTOP_MDH, "log_stop_mdh"),
        (_RE_LOGSTART_MPCU, "log_start_mpcu"),
        (_RE_LOGSTOP_MPCU, "log_stop_mpcu"),
    ):
        m = regex.search(text)
        if m:
            setattr(out, attr, m.group(1))
    if out.log_start_mdh != NA or out.log_start_mpcu != NA:
        out.timestamp_present = "true"

    m = _RE_NRTRIG.search(text)
    if m:
        out.nr_trig = f"NrTrig={m.group(1)};NrMP={m.group(2)};NrArr={m.group(3)};AcqWin={m.group(4)}"

    if _RE_EXPLICIT_SF.search(text) or _RE_BARE_HZ.search(text):
        out.sampling_metadata_present = "true"
    return out


def analyze_sampling(parsed: ParsedPhysio) -> list[dict[str, str]]:
    """Return one or more sampling-rate candidate rows for a file."""
    rows: list[dict[str, str]] = []
    text = parsed.text_sample

    def add(
        raw_field: str,
        candidate: str,
        confidence: str,
        reason: str,
    ) -> None:
        rows.append(
            {
                "file": parsed.file,
                "raw_frequency_field": raw_field,
                "candidate_sampling_frequency": candidate,
                "confidence": confidence,
                "reason": reason,
            }
        )

    # Explicit labelled rates.
    found_explicit = False
    for m in _RE_EXPLICIT_SF.finditer(text):
        label = m.group("label")
        value = float(m.group("value"))
        units = (m.group("units") or "").lower()
        low = label.lower()
        # Reject physiological period/rate mislabels if SamplePeriod without Hz.
        if "period" in low or "interval" in low or "sampletime" in low.replace("_", ""):
            if units in ("ms",):
                hz = 1000.0 / value if value > 0 else None
                if hz:
                    add(
                        m.group(0).strip(),
                        f"{hz:.6g}",
                        "MEDIUM",
                        "Derived from explicitly labelled sample interval/period in ms; "
                        "not Siemens Freq Per.",
                    )
                    found_explicit = True
                else:
                    add(m.group(0).strip(), NA, "INVALID", "Non-positive sample interval.")
            elif units in ("s", "sec", "seconds"):
                hz = 1.0 / value if value > 0 else None
                if hz:
                    add(
                        m.group(0).strip(),
                        f"{hz:.6g}",
                        "MEDIUM",
                        "Derived from explicitly labelled sample interval in seconds.",
                    )
                    found_explicit = True
            else:
                add(
                    m.group(0).strip(),
                    str(value),
                    "LOW",
                    "Label mentions period/interval/time but units ambiguous; not accepted as Hz.",
                )
            continue
        # SamplingFrequency / SampleRate / ADC frequency.
        if units in ("", "hz"):
            add(
                m.group(0).strip(),
                str(value),
                "HIGH",
                f"Explicit acquisition sampling label '{label}' with value treated as Hz.",
            )
            found_explicit = True
        else:
            add(
                m.group(0).strip(),
                NA,
                "INVALID",
                f"Explicit label '{label}' has unsupported units '{units}'.",
            )

    for m in _RE_BARE_HZ.finditer(text):
        # Bare Frequency/Freq ... Hz — Medium only if not part of Freq Per line.
        span_start = max(0, m.start() - 20)
        context = text[span_start : m.end() + 10]
        if re.search(r"Freq\s+Per", context, re.IGNORECASE):
            continue
        add(
            m.group(0).strip(),
            m.group("value"),
            "MEDIUM",
            "Bare Frequency/Freq ... Hz label (not Freq Per); not modality-qualified.",
        )
        found_explicit = True

    # Document Freq Per as INVALID for sampling.
    if parsed.freq_per_raw != NA:
        add(
            parsed.freq_per_raw,
            NA,
            "INVALID",
            "Siemens 'Freq Per' reports physiological rate (e.g. bpm) and period (ms), "
            "NOT ADC SamplingFrequency. Explicitly rejected.",
        )

    # Common Siemens default numbers appearing in header tokens — LOW hypothesis only.
    if parsed.header_detected == "true" and not found_explicit:
        header_match = _RE_COMMON_RATES.findall(text[:2000])
        if header_match:
            add(
                f"unlabelled_preamble_values={','.join(header_match)}",
                NA,
                "LOW",
                "Unlabelled integers 400/500/600 appear near header; may be device settings "
                "or control codes context. NOT accepted as SamplingFrequency.",
            )
        hyp = SIEMENS_DEFAULT_HYPOTHESES.get(parsed.extension)
        if hyp is not None:
            add(
                f"siemens_literature_default_hypothesis={hyp}",
                str(hyp),
                "LOW",
                "Undocumented Siemens model-default hypothesis only; forbidden for conversion.",
            )

    if not rows:
        add(NA, NA, "INVALID", "No frequency-related field recovered.")
    return rows


# ---------------------------------------------------------------------------
# BOLD sidecars + mapping
# ---------------------------------------------------------------------------
@dataclass
class BoldRun:
    path: Path
    subject: str
    session: str
    task: str
    run: str
    series_number: str = NA
    protocol_name: str = NA
    series_description: str = NA
    acquisition_time: str = NA
    acquisition_datetime: str = NA
    repetition_time: str = NA


def load_bold_index(bids_root: Path) -> dict[tuple[str, str], list[BoldRun]]:
    index: dict[tuple[str, str], list[BoldRun]] = defaultdict(list)
    if not bids_root.is_dir():
        LOGGER.warning("BIDS root missing: %s", bids_root)
        return index
    for nii in bids_root.glob("sub-*/ses-*/func/*_bold.nii.gz"):
        m = _RE_BOLD.search(nii.name)
        if not m:
            continue
        subject, session, task, run = m.group(1), m.group(2), m.group(3), m.group(4)
        meta = BoldRun(
            path=nii,
            subject=subject,
            session=session,
            task=task,
            run=run,
        )
        sidecar = Path(str(nii).replace("_bold.nii.gz", "_bold.json"))
        if sidecar.is_file():
            try:
                data = json.loads(sidecar.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                data = {}
            meta.series_number = str(data.get("SeriesNumber", NA))
            meta.protocol_name = str(data.get("ProtocolName", NA))
            meta.series_description = str(data.get("SeriesDescription", NA))
            meta.acquisition_time = str(data.get("AcquisitionTime", NA) or NA)
            meta.acquisition_datetime = str(data.get("AcquisitionDateTime", NA) or NA)
            meta.repetition_time = str(data.get("RepetitionTime", NA))
        index[(subject.lower(), session.lower())].append(meta)
    for key in index:
        index[key].sort(key=lambda b: (b.task, int(b.run) if b.run.isdigit() else b.run))
    LOGGER.info(
        "Indexed %d BOLD runs across %d subject-sessions",
        sum(len(v) for v in index.values()),
        len(index),
    )
    return index


def reconstruct_timestamps(
    inventory_row: dict[str, str],
    parsed: ParsedPhysio,
    session_info: SessionInfo | None,
    bold_runs: list[BoldRun],
) -> dict[str, str]:
    # Never convert MDH ticks.
    candidate_start = NA
    confidence = "INVALID"
    reasons: list[str] = []

    if parsed.log_start_mdh != NA:
        reasons.append(f"LogStartMDHTime={parsed.log_start_mdh} (scanner ticks, not converted)")
    if parsed.log_start_mpcu != NA:
        reasons.append(f"LogStartMPCUTime={parsed.log_start_mpcu} (scanner ticks, not converted)")
    if session_info and session_info.study_time != NA:
        reasons.append(
            f"session_mapping study_date={session_info.study_date} study_time={session_info.study_time} "
            "(session-level DICOM StudyTime, not physio StartTime)"
        )

    bold_with_time = [
        b
        for b in bold_runs
        if b.acquisition_time not in (NA, "None", "null", "")
        or b.acquisition_datetime not in (NA, "None", "null", "")
    ]
    if bold_with_time:
        reasons.append(f"{len(bold_with_time)} BOLD sidecars expose AcquisitionTime/DateTime")
        confidence = "LOW"
    else:
        reasons.append("BOLD JSON sidecars lack AcquisitionTime/AcquisitionDateTime")
        if parsed.log_start_mdh != NA:
            confidence = "LOW"
            reasons.append(
                "MDH ticks present but no validated tick→seconds transform; "
                "cannot compute BIDS StartTime"
            )
        else:
            confidence = "INVALID"

    bold_list = ";".join(
        f"{b.subject}_{b.session}_task-{b.task}_run-{b.run}"
        f"[SeriesNumber={b.series_number};Protocol={b.protocol_name};"
        f"AcqTime={b.acquisition_time}]"
        for b in bold_runs[:40]
    )
    if len(bold_runs) > 40:
        bold_list += f";(+{len(bold_runs) - 40} more)"

    return {
        "physio_file": parsed.file,
        "candidate_start_time": candidate_start,
        "bold_candidates": bold_list if bold_list else NA,
        "confidence": confidence,
        "reason": " | ".join(reasons) if reasons else NA,
        "log_start_mdh_time": parsed.log_start_mdh,
        "log_stop_mdh_time": parsed.log_stop_mdh,
        "log_start_mpcu_time": parsed.log_start_mpcu,
        "log_stop_mpcu_time": parsed.log_stop_mpcu,
        "n_bold_same_session": str(len(bold_runs)),
        "n_bold_with_acquisition_time": str(len(bold_with_time)),
    }


def map_physio_to_bold(
    inventory_row: dict[str, str],
    parsed: ParsedPhysio,
    bold_runs: list[BoldRun],
    ts_row: dict[str, str],
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    subject = inventory_row["subject"]
    session = inventory_row["session"]

    if not subject.startswith("sub-") or not session.startswith("ses-"):
        rows.append(
            {
                "physio_file": parsed.file,
                "candidate_bold": NA,
                "mapping_confidence": "NO_MATCH",
                "reason": f"Unresolved BIDS subject/session (subject={subject}, session={session})",
            }
        )
        return rows

    if not bold_runs:
        rows.append(
            {
                "physio_file": parsed.file,
                "candidate_bold": NA,
                "mapping_confidence": "NO_MATCH",
                "reason": "No BOLD runs found for subject/session",
            }
        )
        return rows

    # Timestamp compatibility: only if BOLD has AcquisitionTime AND we have a
    # convertible physio start — which we never do here without validation.
    ts_ok = (
        ts_row["candidate_start_time"] != NA
        and ts_row["confidence"] in {"HIGH", "MEDIUM"}
        and int(ts_row["n_bold_with_acquisition_time"]) > 0
    )

    if len(bold_runs) == 1 and ts_ok:
        b = bold_runs[0]
        rows.append(
            {
                "physio_file": parsed.file,
                "candidate_bold": str(b.path),
                "mapping_confidence": "CONFIRMED",
                "reason": (
                    "Unique BOLD in session + validated compatible timestamp "
                    "(requires StartTime recovered)"
                ),
            }
        )
        return rows

    if len(bold_runs) == 1:
        b = bold_runs[0]
        rows.append(
            {
                "physio_file": parsed.file,
                "candidate_bold": str(b.path),
                "mapping_confidence": "LIKELY",
                "reason": (
                    "Unique BOLD in session but StartTime not recovered; "
                    "session-wide PMU still not run-aligned"
                ),
            }
        )
        return rows

    # Multiple BOLDs: session-level only → AMBIGUOUS for each candidate.
    # Prefer protocol proximity via filename hints (LOW evidence → still AMBIGUOUS).
    name_u = Path(parsed.file).name.upper()
    for b in bold_runs:
        hints: list[str] = []
        if b.protocol_name != NA and b.protocol_name.upper() in name_u:
            hints.append("protocol_name_in_physio_filename")
        if parsed.nr_trig != NA and "NrTrig=0" in parsed.nr_trig:
            hints.append("NrTrig=0 (no embedded volume triggers in footer)")
        reason = (
            f"Same subject/session; {len(bold_runs)} BOLD candidates; "
            "session-wide Siemens log cannot be uniquely assigned without "
            "validated clock/trigger alignment"
        )
        if hints:
            reason += "; hints=" + ",".join(hints)
        rows.append(
            {
                "physio_file": parsed.file,
                "candidate_bold": str(b.path),
                "mapping_confidence": "AMBIGUOUS",
                "reason": reason,
            }
        )
    return rows


# ---------------------------------------------------------------------------
# Figures
# ---------------------------------------------------------------------------
def make_figures(
    parsed_by_ext: dict[str, list[ParsedPhysio]],
    sampling_rows: list[dict[str, str]],
    out_dir: Path,
) -> None:
    fig_dir = out_dir / "figures"
    fig_dir.mkdir(parents=True, exist_ok=True)

    # Sampling-rate confidence distribution (not values — almost all INVALID/LOW).
    conf = Counter(r["confidence"] for r in sampling_rows)
    fig, ax = plt.subplots(figsize=(7, 4))
    labels = ["HIGH", "MEDIUM", "LOW", "INVALID"]
    vals = [conf.get(k, 0) for k in labels]
    ax.bar(labels, vals, color=["#2ca02c", "#1f77b4", "#ff7f0e", "#d62728"])
    ax.set_title("Physiology sampling-rate candidate confidence")
    ax.set_xlabel("Confidence class")
    ax.set_ylabel("Candidate rows (n)")
    ax.set_ylim(0, max(vals + [1]) * 1.15)
    for i, v in enumerate(vals):
        ax.text(i, v + max(vals + [1]) * 0.02, str(v), ha="center", fontsize=9)
    fig.tight_layout()
    fig.savefig(fig_dir / "sampling_rate_distribution.png", dpi=140)
    plt.close(fig)

    # Sample-count / duration distribution.
    # Duration only plotted when a HIGH/MEDIUM frequency exists for that file.
    high_med_hz: dict[str, float] = {}
    for r in sampling_rows:
        if r["confidence"] in {"HIGH", "MEDIUM"} and r["candidate_sampling_frequency"] not in (
            "",
            NA,
        ):
            try:
                high_med_hz[r["file"]] = float(r["candidate_sampling_frequency"])
            except ValueError:
                pass

    sample_counts: list[int] = []
    durations: list[float] = []
    duration_labels: list[str] = []
    for ext in (".ecg", ".resp", ".puls", ".ext", ".ext2", ".pmu"):
        for p in parsed_by_ext.get(ext, []):
            if p.n_samples not in (NA, ""):
                try:
                    n = int(p.n_samples)
                except ValueError:
                    continue
                sample_counts.append(n)
                hz = high_med_hz.get(p.file)
                if hz and hz > 0:
                    durations.append(n / hz)
                    duration_labels.append("validated_hz")
                else:
                    # Hypothetical duration using literature default — mark separate.
                    hyp = SIEMENS_DEFAULT_HYPOTHESES.get(ext)
                    if hyp:
                        durations.append(n / hyp)
                        duration_labels.append("hypothesis_only")

    fig, axes = plt.subplots(1, 2, figsize=(10, 4))
    if sample_counts:
        axes[0].hist(sample_counts, bins=30, color="#4c78a8", edgecolor="white")
    axes[0].set_title("Waveform sample counts (ASCII PMU)")
    axes[0].set_xlabel("n_samples")
    axes[0].set_ylabel("Files (n)")
    if durations:
        hyp_d = [d for d, lab in zip(durations, duration_labels) if lab == "hypothesis_only"]
        val_d = [d for d, lab in zip(durations, duration_labels) if lab == "validated_hz"]
        if hyp_d:
            axes[1].hist(
                hyp_d,
                bins=30,
                color="#f58518",
                alpha=0.85,
                edgecolor="white",
                label="hypothesis Hz only",
            )
        if val_d:
            axes[1].hist(
                val_d,
                bins=30,
                color="#54a24b",
                alpha=0.85,
                edgecolor="white",
                label="validated Hz",
            )
        axes[1].legend(fontsize=8)
    axes[1].set_title("Estimated duration (seconds)")
    axes[1].set_xlabel("Duration (s)")
    axes[1].set_ylabel("Files (n)")
    fig.suptitle(
        "Duration uses validated Hz when available; otherwise undocumented Siemens defaults "
        "(NOT for conversion)",
        fontsize=9,
    )
    fig.tight_layout()
    fig.savefig(fig_dir / "physio_duration_distribution.png", dpi=140)
    plt.close(fig)

    # Example traces.
    fig, axes = plt.subplots(3, 5, figsize=(14, 8), sharex=False)
    modalities = [(".ecg", "ECG"), (".resp", "RESP"), (".puls", "PULS")]
    for row_i, (ext, title) in enumerate(modalities):
        candidates = [p for p in parsed_by_ext.get(ext, []) if p.waveform is not None]
        # Prefer non-flat waveforms.
        def score(p: ParsedPhysio) -> float:
            w = p.waveform
            assert w is not None
            return float(np.std(w))

        candidates.sort(key=score, reverse=True)
        for col_i in range(5):
            ax = axes[row_i, col_i]
            if col_i >= len(candidates):
                ax.axis("off")
                continue
            p = candidates[col_i]
            w = p.waveform
            assert w is not None
            ax.plot(np.arange(len(w)), w, lw=0.6, color="#333333")
            ax.set_title(Path(p.file).name[:28], fontsize=7)
            if col_i == 0:
                ax.set_ylabel(f"{title}\namplitude", fontsize=8)
            ax.set_xlabel("sample index", fontsize=7)
            ax.tick_params(labelsize=6)
    fig.suptitle(
        "Example Siemens ASCII PMU traces (first ≤5000 samples; display only, not BIDS export)",
        fontsize=11,
    )
    fig.tight_layout()
    fig.savefig(fig_dir / "example_traces.png", dpi=140)
    plt.close(fig)
    LOGGER.info("Wrote figures under %s", fig_dir)


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------
def write_recovery_report(
    out_path: Path,
    inventory: list[dict[str, str]],
    format_rows: list[dict[str, str]],
    sampling_rows: list[dict[str, str]],
    ts_rows: list[dict[str, str]],
    map_rows: list[dict[str, str]],
    n_recoverable: int,
    n_impossible: int,
) -> None:
    ext_counts = Counter(r["extension"] for r in inventory)
    fmt_counts = Counter(r["format_detected"] for r in format_rows)
    conf_counts = Counter(r["confidence"] for r in sampling_rows)
    # Best confidence per file for sampling.
    best_sf: dict[str, str] = {}
    rank = {"HIGH": 4, "MEDIUM": 3, "LOW": 2, "INVALID": 1}
    for r in sampling_rows:
        prev = best_sf.get(r["file"])
        if prev is None or rank.get(r["confidence"], 0) > rank.get(prev, 0):
            best_sf[r["file"]] = r["confidence"]
    recovered_sf = sum(1 for c in best_sf.values() if c in {"HIGH", "MEDIUM"})
    not_recovered_sf = sum(1 for c in best_sf.values() if c not in {"HIGH", "MEDIUM"})

    ts_conf = Counter(r["confidence"] for r in ts_rows)
    # Collapse mapping to best per physio file.
    map_best: dict[str, str] = {}
    map_rank = {"CONFIRMED": 4, "LIKELY": 3, "AMBIGUOUS": 2, "NO_MATCH": 1}
    for r in map_rows:
        prev = map_best.get(r["physio_file"])
        if prev is None or map_rank.get(r["mapping_confidence"], 0) > map_rank.get(prev, 0):
            map_best[r["physio_file"]] = r["mapping_confidence"]
    map_counts = Counter(map_best.values())

    option = "A" if n_recoverable > 0 else "B"
    lines = [
        "# Physiological data recovery audit",
        "",
        f"Generated: `{_now()}`",
        "",
        "Read-only deep audit. **No files under `raw_original/` or `bids/` were modified.**",
        "**No `*_physio.tsv.gz` files were created.**",
        "",
        "## Summary",
        "",
        f"Total files: **{len(inventory)}**",
        "",
        f"- ECG (`.ecg`): **{ext_counts.get('.ecg', 0)}**",
        f"- RESP (`.resp`): **{ext_counts.get('.resp', 0)}**",
        f"- PULS (`.puls`): **{ext_counts.get('.puls', 0)}**",
        f"- EXT (`.ext`): **{ext_counts.get('.ext', 0)}**",
        f"- EXT2 (`.ext2`): **{ext_counts.get('.ext2', 0)}**",
        f"- PMU (`.pmu`): **{ext_counts.get('.pmu', 0)}**",
        f"- Other / text: **{sum(v for k, v in ext_counts.items() if k not in PHYSIO_EXTS)}**",
        "",
        "## Format detection",
        "",
    ]
    for k, v in sorted(fmt_counts.items(), key=lambda kv: (-kv[1], kv[0])):
        lines.append(f"- `{k}`: **{v}**")
    lines += [
        "",
        "Siemens ASCII PMU footers commonly expose `Freq Per`, Min/Max/Avg, "
        "`LogStartMDHTime` / `LogStopMDHTime`, and `NrTrig`. Binary `.pmu` files "
        "were not waveform-decoded without a validated parser.",
        "",
        "## Sampling frequency recovery",
        "",
        "| Status | Files (best confidence per file) |",
        "| --- | ---: |",
        f"| Recovered (HIGH/MEDIUM) | {recovered_sf} |",
        f"| Not recovered (LOW/INVALID only) | {not_recovered_sf} |",
        "",
        "Candidate-row confidence counts:",
        "",
    ]
    for k in ("HIGH", "MEDIUM", "LOW", "INVALID"):
        lines.append(f"- {k}: **{conf_counts.get(k, 0)}**")
    lines += [
        "",
        "**Rule enforced:** Siemens `Freq Per: <rate> <period_ms>` is physiological "
        "rate metadata and is classified **INVALID** as SamplingFrequency.",
        "",
        "## Timestamp recovery",
        "",
        f"- Rows analysed: **{len(ts_rows)}**",
        f"- Confidence INVALID: **{ts_conf.get('INVALID', 0)}**",
        f"- Confidence LOW: **{ts_conf.get('LOW', 0)}**",
        f"- Confidence MEDIUM/HIGH: **{ts_conf.get('MEDIUM', 0) + ts_conf.get('HIGH', 0)}**",
        "",
        "Literal `LogStartMDHTime` / `LogStartMPCUTime` ticks were recorded but "
        "**not converted** to BIDS `StartTime`. Current BOLD JSON sidecars generally "
        "lack `AcquisitionTime` / `AcquisitionDateTime`.",
        "",
        "## Physio-BOLD association",
        "",
        "| Class | Physio files (best class) |",
        "| --- | ---: |",
        f"| CONFIRMED | {map_counts.get('CONFIRMED', 0)} |",
        f"| LIKELY | {map_counts.get('LIKELY', 0)} |",
        f"| AMBIGUOUS | {map_counts.get('AMBIGUOUS', 0)} |",
        f"| NO_MATCH / FAILED | {map_counts.get('NO_MATCH', 0)} |",
        "",
        "CONFIRMED requires subject/session concordance **and** a recovered "
        "compatible StartTime **and** a unique BOLD target.",
        "",
        "## BIDS conversion readiness",
        "",
        f"- Files meeting full recovery criterion (SF + StartTime + unique run): **{n_recoverable}**",
        f"- Files impossible under current metadata: **{n_impossible}**",
        "",
    ]
    if option == "A":
        lines += [
            "### Option A: Ready for BIDS conversion",
            "",
            "At least one file has SamplingFrequency recovered, StartTime computed, "
            "and a unique BOLD run association. Conversion remains a separate gated step.",
            "",
        ]
    else:
        lines += [
            "### Option B: Insufficient metadata, keep excluded",
            "",
            "No physiology file simultaneously provides:",
            "",
            "1. explicit ADC `SamplingFrequency` (HIGH/MEDIUM),",
            "2. validated BIDS-relative `StartTime`,",
            "3. a unique CONFIRMED BOLD run mapping.",
            "",
            "Therefore **no Level-1 BIDS physiology conversion is authorized**. "
            "Keep ECG/RESP/PULS/EXT/PMU excluded from the public release until "
            "external scanner documentation or original PhysioLog DICOM objects "
            "supply the missing metadata.",
            "",
        ]
    lines += [
        "## Outputs",
        "",
        "- `physio_inventory.tsv`",
        "- `physio_format_analysis.tsv`",
        "- `physio_sampling_rate_analysis.tsv`",
        "- `timestamp_reconstruction.tsv`",
        "- `physio_run_mapping_candidates.tsv`",
        "- `physio_recovery_report.md`",
        "- `PHYSIO_RECOVERY_DECISION.md`",
        "- `figures/sampling_rate_distribution.png`",
        "- `figures/physio_duration_distribution.png`",
        "- `figures/example_traces.png`",
        "",
    ]
    out_path.write_text("\n".join(lines), encoding="utf-8")


def write_decision(
    out_path: Path,
    n_recoverable: int,
    n_impossible: int,
    reasons: list[str],
) -> None:
    rec = (
        "Do **not** include physiology in the Scientific Data Level-1 BIDS release. "
        "State in the Data Record that source PMU logs exist but lack validated "
        "SamplingFrequency, StartTime, and unique run linkage."
        if n_recoverable == 0
        else "A limited subset may be convertible after a gated converter validates "
        "payload parsing; only files counted as recoverable may be considered."
    )
    lines = [
        "# PHYSIO_RECOVERY_DECISION",
        "",
        f"Generated: `{_now()}`",
        "",
        f"Number recoverable: **{n_recoverable}**",
        f"Number impossible: **{n_impossible}**",
        "",
        "## Reasons",
        "",
    ]
    for r in reasons:
        lines.append(f"- {r}")
    lines += [
        "",
        "## Recommendation for Scientific Data release",
        "",
        rec,
        "",
        "Decision gate: SamplingFrequency recovered + StartTime computed + unique BOLD run.",
        "No `*_physio.tsv.gz` were written by this audit.",
        "",
    ]
    out_path.write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def assess_recoverable(
    file_path: str,
    sampling_rows: list[dict[str, str]],
    ts_row: dict[str, str],
    map_rows_for_file: list[dict[str, str]],
) -> bool:
    sf_ok = any(
        r["file"] == file_path
        and r["confidence"] in {"HIGH", "MEDIUM"}
        and r["candidate_sampling_frequency"] not in ("", NA)
        for r in sampling_rows
    )
    st_ok = (
        ts_row.get("candidate_start_time", NA) not in ("", NA)
        and ts_row.get("confidence") in {"HIGH", "MEDIUM"}
    )
    map_ok = any(r["mapping_confidence"] == "CONFIRMED" for r in map_rows_for_file)
    return bool(sf_ok and st_ok and map_ok)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-root", type=Path, default=DEFAULT_RAW)
    parser.add_argument("--bids-root", type=Path, default=DEFAULT_BIDS)
    parser.add_argument("--metadata-root", type=Path, default=DEFAULT_META)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    _configure_logging(args.verbose)

    raw_root = args.raw_root.resolve()
    bids_root = args.bids_root.resolve()
    meta_root = args.metadata_root.resolve()
    out_dir = args.out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    # Hard safety: refuse to write outside the physiology_audit report tree.
    if out_dir.name != "physiology_audit" and "physiology_audit" not in out_dir.parts:
        LOGGER.error("Refusing to write outside reports/physiology_audit/: %s", out_dir)
        return 2

    LOGGER.info("raw_root=%s", raw_root)
    LOGGER.info("bids_root=%s (read-only)", bids_root)
    LOGGER.info("out_dir=%s", out_dir)

    maps = load_project_maps(meta_root)
    files = discover_files(raw_root)
    inventory = build_inventory(files, maps)
    _write_tsv(
        out_dir / "physio_inventory.tsv",
        [
            "file_path",
            "subject",
            "session",
            "extension",
            "file_size",
            "creation_time",
            "modification_time",
        ],
        inventory,
    )

    bold_index = load_bold_index(bids_root)

    format_rows: list[dict[str, str]] = []
    sampling_rows: list[dict[str, str]] = []
    ts_rows: list[dict[str, str]] = []
    map_rows: list[dict[str, str]] = []
    parsed_list: list[ParsedPhysio] = []
    parsed_by_ext: dict[str, list[ParsedPhysio]] = defaultdict(list)

    inv_by_path = {r["file_path"]: r for r in inventory}

    for i, path in enumerate(files, 1):
        if i % 50 == 0 or i == len(files):
            LOGGER.info("Parsing %d / %d", i, len(files))
        parsed = parse_file(path)
        parsed_list.append(parsed)
        parsed_by_ext[parsed.extension].append(parsed)

        format_rows.append(
            {
                "file": parsed.file,
                "format_detected": parsed.format_detected,
                "channels": parsed.channels,
                "n_samples": parsed.n_samples,
                "header_detected": parsed.header_detected,
                "timestamp_present": parsed.timestamp_present,
                "sampling_metadata_present": parsed.sampling_metadata_present,
            }
        )
        sampling_rows.extend(analyze_sampling(parsed))

        inv = inv_by_path[str(path)]
        subject, session, sinfo = resolve_ids(path, maps)
        # Prefer inventory subject/session (already resolved).
        subject = inv["subject"]
        session = inv["session"]
        key = (subject.lower(), session.lower()) if subject.startswith("sub-") and session.startswith("ses-") else None
        bold_runs = bold_index.get(key, []) if key else []
        ts_row = reconstruct_timestamps(inv, parsed, sinfo, bold_runs)
        ts_rows.append(ts_row)
        map_rows.extend(map_physio_to_bold(inv, parsed, bold_runs, ts_row))

    _write_tsv(
        out_dir / "physio_format_analysis.tsv",
        [
            "file",
            "format_detected",
            "channels",
            "n_samples",
            "header_detected",
            "timestamp_present",
            "sampling_metadata_present",
        ],
        format_rows,
    )
    _write_tsv(
        out_dir / "physio_sampling_rate_analysis.tsv",
        [
            "file",
            "raw_frequency_field",
            "candidate_sampling_frequency",
            "confidence",
            "reason",
        ],
        sampling_rows,
    )
    _write_tsv(
        out_dir / "timestamp_reconstruction.tsv",
        [
            "physio_file",
            "candidate_start_time",
            "bold_candidates",
            "confidence",
            "reason",
            "log_start_mdh_time",
            "log_stop_mdh_time",
            "log_start_mpcu_time",
            "log_stop_mpcu_time",
            "n_bold_same_session",
            "n_bold_with_acquisition_time",
        ],
        ts_rows,
    )
    _write_tsv(
        out_dir / "physio_run_mapping_candidates.tsv",
        ["physio_file", "candidate_bold", "mapping_confidence", "reason"],
        map_rows,
    )

    map_by_file: dict[str, list[dict[str, str]]] = defaultdict(list)
    for r in map_rows:
        map_by_file[r["physio_file"]].append(r)
    ts_by_file = {r["physio_file"]: r for r in ts_rows}

    recoverable = []
    impossible = []
    for path in files:
        fp = str(path)
        ok = assess_recoverable(fp, sampling_rows, ts_by_file[fp], map_by_file.get(fp, []))
        (recoverable if ok else impossible).append(fp)

    make_figures(parsed_by_ext, sampling_rows, out_dir)

    reasons = [
        "Siemens Freq Per fields are physiological rates/periods, not ADC SamplingFrequency.",
        "No HIGH/MEDIUM explicit SamplingFrequency recovered for conversion gating "
        f"({sum(1 for r in sampling_rows if r['confidence']=='HIGH')} HIGH candidate rows).",
        "MDH/MPCU LogStart* ticks were not converted to BIDS StartTime (no validated transform).",
        "BOLD JSON sidecars lack AcquisitionTime/AcquisitionDateTime for clock alignment.",
        "Physio logs are session-wide vs many BOLD runs → AMBIGUOUS mapping dominates.",
        "Binary .pmu payloads were not decoded without a validated format-specific parser.",
    ]
    write_recovery_report(
        out_dir / "physio_recovery_report.md",
        inventory,
        format_rows,
        sampling_rows,
        ts_rows,
        map_rows,
        n_recoverable=len(recoverable),
        n_impossible=len(impossible),
    )
    write_decision(
        out_dir / "PHYSIO_RECOVERY_DECISION.md",
        n_recoverable=len(recoverable),
        n_impossible=len(impossible),
        reasons=reasons,
    )

    LOGGER.info(
        "Done. recoverable=%d impossible=%d outputs under %s",
        len(recoverable),
        len(impossible),
        out_dir,
    )
    print(
        f"PHYSIO RECOVERY: recoverable={len(recoverable)} "
        f"impossible={len(impossible)} out={out_dir}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
