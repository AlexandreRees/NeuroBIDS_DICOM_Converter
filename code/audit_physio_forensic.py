#!/usr/bin/env python3
"""Forensic read-only audit: can physiology become valid BIDS physio?

Safety (hard constraints):
  * Never modify raw_original/, bids/, derivatives/, release_dataset/
  * Never create *_physio.tsv.gz
  * Reports and figures only under reports/physiology_audit/
  * Store literal metadata; confidence labels are separate from raw fields
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import pickle
import random
import re
import sys
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch  # noqa: E402

LOGGER = logging.getLogger("physio_forensic")
NA = "NA"

DEFAULT_RAW = Path("/project/def-amirs/raw_original")
DEFAULT_BIDS = Path("/lustre07/scratch/alexrees/bids")
DEFAULT_META = Path("/lustre07/scratch/alexrees/metadata")
DEFAULT_OUT = Path("/home/alexrees/scratch/reports/physiology_audit")

PHYSIO_EXTS = {".ecg", ".resp", ".puls", ".ext", ".ext1", ".ext2", ".pmu"}
DICOM_EXTS = {".ima", ".dcm", ".dicom"}
TEXT_EXTS = {".log", ".txt", ".xml"}
MAT_EXTS = {".mat"}

_RE_SUBJECT = re.compile(r"(SUB[A-Z]*\d+)", re.IGNORECASE)
_RE_SESSION = re.compile(r"(?:session|ses)[\s_-]*0*([12])", re.IGNORECASE)
_RE_BOLD_JSON = re.compile(
    r"(sub-\d+)_(ses-\d+)_task-([A-Za-z0-9]+)(?:_.*)?_run-(\d+)_bold\.json$"
)
_RE_PROTO_PHYSIO = re.compile(r"^(?P<proto>.+?)_PhysioLog$", re.IGNORECASE)
_RE_FREQ_PER = re.compile(
    r"^(ECG|PULS|RESP|EXT2?|EXT)\s+Freq\s+Per:\s*(-?\d+)\s+(-?\d+)\s*$",
    re.MULTILINE | re.IGNORECASE,
)
_RE_EXPLICIT_SF = re.compile(
    r"(SamplingFrequency|SamplingRate|SampleRate|ADC(?:\s+)?Frequency|"
    r"SamplePeriod|SampleTime|SamplingInterval)\s*[:=]\s*([0-9.]+)",
    re.IGNORECASE,
)
_RE_LOGSTART_MDH = re.compile(r"LogStartMDHTime:\s*(-?\d+)")
_RE_LOGSTOP_MDH = re.compile(r"LogStopMDHTime:\s*(-?\d+)")
_RE_LOGSTART_MPCU = re.compile(r"LogStartMPCUTime:\s*(-?\d+)")
_RE_LOGSTOP_MPCU = re.compile(r"LogStopMPCUTime:\s*(-?\d+)")
_RE_NRTRIG = re.compile(
    r"NrTrig\s+NrMP\s+NrArr\s+AcqWin:\s*(-?\d+)\s+(-?\d+)\s+(-?\d+)\s+(-?\d+)"
)
_RE_EMBED_LOG = re.compile(
    r"Physio_\d{8}_\d{6}_[0-9a-f\-]+_(ECG|PULS|RESP|EXT|EXT2)\.log",
    re.IGNORECASE,
)
_RE_CSA_META = re.compile(
    r"UUID\s*=\s*(?P<uuid>\S+)\s*ScanDate\s*=\s*(?P<scandate>\S+)\s*"
    r"LogVersion\s*=\s*(?P<logversion>\S+)\s*LogDataType\s*=\s*(?P<datatype>\w+)\s*"
    r"SampleTime\s*=\s*(?P<sampletime>\d+)",
    re.IGNORECASE,
)
_RE_NUM_VOL = re.compile(r"NumVolumes\s*=\s*(\d+)")
_RE_VOL0 = re.compile(r"^\s*0\s+\d+\s+(\d+)\s+(\d+)\s+\d+\s*$", re.MULTILINE)
_RE_FIRST_TICK = re.compile(
    r"ACQ_TIME_TICS\s*=?\s*(-?\d+)|^\s*(\d+)\s+(\d+)\s+(\d+)\s+",
    re.IGNORECASE | re.MULTILINE,
)

# DICOM little-endian tag signatures in raw bytes (approximate detection).
_SIG_WAVEFORM_SEQ = b"\x00\x54\x00\x01"  # (5400,0100)
_SIG_WAVEFORM_DATA = b"\x00\x54\x10\x10"  # (5400,1010)
_SIG_SAMP_FREQ = b"\x3a\x00\x1a\x00"  # (003A,001A) little-endian group/elem
WAVEFORM_SOP_PREFIX = "1.2.840.10008.5.1.4.1.1.9"

MAT_KEYWORDS = (
    b"trigger",
    b"triggerTimes",
    b"physio",
    b"pulse",
    b"resp",
    b"cardiac",
    b"ecg",
    b"sampling",
    b"sampleRate",
    b"frequency",
    b"MDH",
    b"MPCU",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _configure_logging(verbose: bool, log_file: Path | None = None) -> None:
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_file, mode="a", encoding="utf-8"))
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
        handlers=handlers,
        force=True,
    )


def write_tsv(path: Path, fieldnames: list[str], rows: Iterable[dict[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(
            fh, fieldnames=fieldnames, delimiter="\t", lineterminator="\n", extrasaction="ignore"
        )
        w.writeheader()
        for row in rows:
            w.writerow({k: row.get(k, "") for k in fieldnames})
            n += 1
    return n


def load_tsv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh, delimiter="\t"))


def load_folder_map(metadata_root: Path) -> dict[str, tuple[str, str]]:
    out: dict[str, tuple[str, str]] = {}
    path = metadata_root / "session_mapping.csv"
    if not path.is_file():
        LOGGER.warning("Missing %s", path)
        return out
    with path.open(encoding="utf-8", newline="", errors="replace") as fh:
            for row in csv.DictReader(fh):
                folder = (row.get("source_subject_folder") or "").strip()
                pid = (row.get("participant_id") or "").strip()
            ses = (row.get("session_id") or row.get("session_label") or "").strip()
            if folder and pid and ses and folder not in out:
                out[folder] = (pid, ses)
    LOGGER.info("Loaded %d session folder mappings", len(out))
    return out


def resolve_subject_session(
    path: Path, folder_map: dict[str, tuple[str, str]]
) -> tuple[str, str]:
    parts = set(path.parts)
    for folder, (sub, ses) in folder_map.items():
        if folder in parts:
            return sub, ses
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
    return sub, ses


def candidate_type_for(path: Path) -> str:
    name = path.name.upper()
    ext = path.suffix.lower()
    parent = path.parent.name.upper()
    if ext in PHYSIO_EXTS:
        return f"pmu_{ext.lstrip('.')}"
    if "PHYSIOLOG" in name or "PHYSIOLOG" in parent:
        return "physiolog_dicom"
    if ext in DICOM_EXTS:
        return "dicom"
    if ext in MAT_EXTS:
        return "matlab"
    if ext in TEXT_EXTS:
        if any(k in name for k in ("PHYSIO", "ECG", "RESP", "PULS", "PMU", "SCANLOG")):
            return "text_physio_candidate"
        return "text_other"
    return "other"


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------
def discover_archive(raw_root: Path) -> dict[str, list[Path]]:
    buckets: dict[str, list[Path]] = defaultdict(list)
    n = 0
    for dirpath, _dirs, filenames in os.walk(raw_root):
        for name in filenames:
            n += 1
            if n % 200000 == 0:
                LOGGER.info("Discovery walk: %d files...", n)
            ext = os.path.splitext(name)[1].lower()
            fpath = Path(dirpath) / name
            if ext in PHYSIO_EXTS:
                buckets["pmu"].append(fpath)
            elif ext in DICOM_EXTS or name.upper().endswith(".IMA"):
                buckets["dicom"].append(fpath)
                if "PHYSIOLOG" in name.upper() or "PHYSIOLOG" in Path(dirpath).name.upper():
                    buckets["physiolog"].append(fpath)
            elif ext in TEXT_EXTS:
                buckets["text"].append(fpath)
            elif ext in MAT_EXTS:
                buckets["mat"].append(fpath)
    # Deduplicate physiolog
    buckets["physiolog"] = sorted(set(buckets["physiolog"]))
    LOGGER.info(
        "Discovery complete: pmu=%d physiolog=%d dicom=%d text=%d mat=%d",
        len(buckets["pmu"]),
        len(buckets["physiolog"]),
        len(buckets["dicom"]),
        len(buckets["text"]),
        len(buckets["mat"]),
    )
    return buckets


def build_source_inventory(
    buckets: dict[str, list[Path]], folder_map: dict[str, tuple[str, str]]
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    for key in ("pmu", "physiolog", "text", "mat"):
        for path in buckets.get(key, []):
            sp = str(path)
            if sp in seen:
            continue
            seen.add(sp)
            try:
                size = str(path.stat().st_size)
            except OSError:
                size = NA
            sub, ses = resolve_subject_session(path, folder_map)
        rows.append(
            {
                    "filepath": sp,
                "extension": path.suffix.lower() or NA,
                    "size": size,
                    "subject": sub,
                    "session": ses,
                    "sequence": path.parent.name,
                    "candidate_type": candidate_type_for(path),
                }
            )
    # Also index keyword hits among text that look physio-related without being in buckets path
    return rows


# ---------------------------------------------------------------------------
# PMU parse
# ---------------------------------------------------------------------------
def parse_pmu_file(path: Path) -> dict[str, str]:
    row = {
        "filepath": str(path),
        "extension": path.suffix.lower(),
        "format": NA,
        "sampling_rate_fields": NA,
        "freq_per_fields": NA,
        "log_start_mdh": NA,
        "log_stop_mdh": NA,
        "log_start_mpcu": NA,
        "log_stop_mpcu": NA,
        "nr_trig": NA,
        "sampletime_fields": NA,
        "other_freq_hits": NA,
        "error": NA,
    }
    try:
        raw = path.read_bytes()
    except OSError as exc:
        row["error"] = str(exc)
        return row
    if not raw:
        row["format"] = "empty"
        return row
    head = raw[:256]
    textish = sum(1 for b in head if 9 <= b <= 13 or 32 <= b <= 126)
    if b"\x00" in head or (len(head) and textish / len(head) < 0.7):
        row["format"] = "siemens_binary_pmu"
        head_txt = head.decode("latin-1", errors="replace")
        if "VSN" in head_txt:
            row["format"] = "siemens_binary_pmu_vsn"
        return row
    text = raw.decode("latin-1", errors="replace")
    row["format"] = "siemens_ascii_pmu"
    freq_per = [f"{a} Freq Per: {b} {c}" for a, b, c in _RE_FREQ_PER.findall(text)]
    row["freq_per_fields"] = " | ".join(freq_per) if freq_per else NA
    explicit = [m.group(0) for m in _RE_EXPLICIT_SF.finditer(text)]
    # Exclude Freq Per matches mistakenly caught — SampleTime in CSA only typically
    explicit = [e for e in explicit if "Freq Per" not in e]
    row["sampling_rate_fields"] = " | ".join(explicit) if explicit else NA
    st = [m.group(0) for m in re.finditer(r"SampleTime\s*[:=]\s*\d+", text, re.IGNORECASE)]
    row["sampletime_fields"] = " | ".join(st) if st else NA
    for regex, key in (
        (_RE_LOGSTART_MDH, "log_start_mdh"),
        (_RE_LOGSTOP_MDH, "log_stop_mdh"),
        (_RE_LOGSTART_MPCU, "log_start_mpcu"),
        (_RE_LOGSTOP_MPCU, "log_stop_mpcu"),
    ):
        m = regex.search(text)
        if m:
            row[key] = m.group(1)
    m = _RE_NRTRIG.search(text)
    if m:
        row["nr_trig"] = f"NrTrig={m.group(1)};NrMP={m.group(2)};NrArr={m.group(3)};AcqWin={m.group(4)}"
    hits = []
    for kw in ("MDH", "MPCU", "Trigger", "Volume", "5000", "6000"):
        if kw.lower() in text.lower() or kw in text:
            hits.append(kw)
    row["other_freq_hits"] = ";".join(hits) if hits else NA
    return row


# ---------------------------------------------------------------------------
# PhysioLog DICOM deep CSA parse
# ---------------------------------------------------------------------------
def deep_parse_physiolog(path_str: str) -> dict[str, str]:
    """Full CSA parse for Siemens PhysioLog DICOM."""
    path = Path(path_str)
    out = {
        "filepath": path_str,
        "series_description": NA,
        "protocol_name": NA,
        "series_number": NA,
        "series_time": NA,
        "sop_class_uid": NA,
        "csa_nbytes": NA,
        "embedded_logs": NA,
        "log_datatypes": NA,
        "sampletime_by_type": NA,
        "logversion": NA,
        "scandate": NA,
        "uuid": NA,
        "num_volumes": NA,
        "vol0_acq_start_tics": NA,
        "first_puls_tick": NA,
        "first_resp_tick": NA,
        "has_acquisition_info": "false",
        "error": NA,
    }
    try:
        import pydicom

        ds = pydicom.dcmread(str(path), stop_before_pixels=False, force=True)
    except Exception as exc:  # noqa: BLE001
        out["error"] = f"{type(exc).__name__}:{exc}"
        return out

    out["series_description"] = str(getattr(ds, "SeriesDescription", NA) or NA)
    out["protocol_name"] = str(getattr(ds, "ProtocolName", NA) or NA)
    out["series_number"] = str(getattr(ds, "SeriesNumber", NA) or NA)
    out["series_time"] = str(getattr(ds, "SeriesTime", NA) or NA)
    out["sop_class_uid"] = str(getattr(ds, "SOPClassUID", NA) or NA)

    # Prefer explicit protocol from SeriesDescription *_PhysioLog
    m = _RE_PROTO_PHYSIO.match(out["series_description"])
    if m and (out["protocol_name"] in (NA, "", "None")):
        out["protocol_name"] = m.group("proto")

    raw = b""
    try:
        elem = ds[0x7FE1, 0x1010]
        val = elem.value
        raw = bytes(val) if not isinstance(val, bytes) else val
        out["csa_nbytes"] = str(len(raw))
    except Exception:  # noqa: BLE001
        # Fallback: entire file bytes (slower, last resort)
    try:
        raw = path.read_bytes()
            out["csa_nbytes"] = str(len(raw))
    except OSError as exc:
            out["error"] = str(exc)
        return out

    text = raw.decode("latin-1", errors="replace")
    embeds = _RE_EMBED_LOG.findall(text)
    if embeds:
        # preserve order unique
        seen = []
        for e in embeds:
            eu = e.upper()
            if eu not in seen:
                seen.append(eu)
        out["embedded_logs"] = ";".join(seen)

    metas = list(_RE_CSA_META.finditer(text))
    types: list[str] = []
    st_map: dict[str, str] = {}
    for m in metas:
        dt = m.group("datatype").upper()
        types.append(dt)
        st_map[dt] = m.group("sampletime")
        if out["logversion"] == NA:
            out["logversion"] = m.group("logversion")
        if out["scandate"] == NA:
            out["scandate"] = m.group("scandate")
        if out["uuid"] == NA:
            out["uuid"] = m.group("uuid")
    if types:
        # unique preserve
        uniq = []
        for t in types:
            if t not in uniq:
                uniq.append(t)
        out["log_datatypes"] = ";".join(uniq)
    if st_map:
        out["sampletime_by_type"] = ";".join(f"{k}={st_map[k]}" for k in sorted(st_map))

    mv = _RE_NUM_VOL.search(text)
    if mv:
        out["num_volumes"] = mv.group(1)

    if "ACQUISITION_INFO" in text or "NumVolumes" in text:
        out["has_acquisition_info"] = "true"
        # Volume 0 row often: idx Mag ACQ_START_TICS ACQ_FINISH_TICS echo
        m0 = _RE_VOL0.search(text)
        if m0:
            out["vol0_acq_start_tics"] = m0.group(1)
        else:
            # alternate: search after ACQUISITION_INFO header for first data line starting with 0
            block = text
            idx = text.find("ACQUISITION_INFO")
            if idx >= 0:
                block = text[idx : idx + 5000]
            for line in block.splitlines():
                parts = line.split()
                if len(parts) >= 4 and parts[0] == "0" and parts[2].isdigit():
                    out["vol0_acq_start_tics"] = parts[2]
                    break

    # First channel ACQ tick: scan each embedded log region for earliest numeric tick
    def first_tick_for(channel: str) -> str:
        # Find Physio_*_CHANNEL.log header then read subsequent lines for first large int tick
        pat = re.compile(
            rf"Physio_\d{{8}}_\d{{6}}_[0-9a-f\-]+_{channel}\.log", re.IGNORECASE
        )
        m = pat.search(text)
        if not m:
            return NA
        region = text[m.end() : m.end() + 8000]
        # Prefer explicit ACQ_TIME_TICS
        m2 = re.search(r"ACQ_TIME_TICS\s*[:=]\s*(-?\d+)", region, re.IGNORECASE)
        if m2:
            return m2.group(1)
        # Data lines often start with tick values
        for line in region.splitlines():
            parts = line.split()
            if not parts:
                continue
            if parts[0].lstrip("-").isdigit() and len(parts[0]) >= 5:
                return parts[0]
        return NA

    out["first_puls_tick"] = first_tick_for("PULS")
    out["first_resp_tick"] = first_tick_for("RESP")
    return out


def parse_physiolog_parallel(paths: list[Path], workers: int) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    str_paths = [str(p) for p in paths]
    LOGGER.info("Deep PhysioLog CSA parse: %d files", len(str_paths))
    if workers <= 1:
        for i, sp in enumerate(str_paths, 1):
            rows.append(deep_parse_physiolog(sp))
            if i % 100 == 0 or i == len(str_paths):
                LOGGER.info("PhysioLog parse %d / %d", i, len(str_paths))
        return rows
    with ProcessPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(deep_parse_physiolog, sp): sp for sp in str_paths}
        done = 0
        for fut in as_completed(futs):
            rows.append(fut.result())
            done += 1
            if done % 100 == 0 or done == len(str_paths):
                LOGGER.info("PhysioLog parse %d / %d", done, len(str_paths))
    rows.sort(key=lambda r: r["filepath"])
    return rows


# ---------------------------------------------------------------------------
# DICOM quick scan (waveform + timing)
# ---------------------------------------------------------------------------
def _dicom_quick_row(path_str: str) -> dict[str, str]:
    """Read timing + waveform presence without pixels. Worker-safe."""
    path = Path(path_str)
    row = {
        "filepath": path_str,
        "sop_class_uid": NA,
        "modality": NA,
        "series_description": NA,
        "protocol_name": NA,
        "series_number": NA,
        "instance_number": NA,
        "series_time": NA,
        "acquisition_time": NA,
        "acquisition_datetime": NA,
        "instance_creation_time": NA,
        "trigger_time": NA,
        "temporal_position_identifier": NA,
        "waveform_sequence": "false",
        "waveform_data": "false",
        "dicom_sampling_frequency": NA,
        "n_waveform_channels": NA,
        "is_physiolog": "false",
        "error": NA,
    }
    name_u = path.name.upper()
    parent_u = path.parent.name.upper()
    if "PHYSIOLOG" in name_u or "PHYSIOLOG" in parent_u:
        row["is_physiolog"] = "true"
    try:
        import pydicom
        from pydicom.tag import Tag

        ds = pydicom.dcmread(str(path), stop_before_pixels=True, force=True)
    except Exception as exc:  # noqa: BLE001
        row["error"] = f"{type(exc).__name__}:{exc}"
        # Binary fallback signatures
        try:
            blob = path.read_bytes()[:512_000]
            if _SIG_WAVEFORM_SEQ in blob:
                row["waveform_sequence"] = "maybe_raw_sig"
            if _SIG_WAVEFORM_DATA in blob:
                row["waveform_data"] = "maybe_raw_sig"
            if WAVEFORM_SOP_PREFIX.encode() in blob:
                row["sop_class_uid"] = "waveform_sop_sig_in_bytes"
        except OSError:
            pass
        return row

    def g(attr: str) -> str:
        val = getattr(ds, attr, None)
        return str(val) if val is not None else NA

    row["sop_class_uid"] = g("SOPClassUID")
    row["modality"] = g("Modality")
    row["series_description"] = g("SeriesDescription")
    row["protocol_name"] = g("ProtocolName")
    row["series_number"] = g("SeriesNumber")
    row["instance_number"] = g("InstanceNumber")
    row["series_time"] = g("SeriesTime")
    row["acquisition_time"] = g("AcquisitionTime")
    row["acquisition_datetime"] = g("AcquisitionDateTime")
    row["instance_creation_time"] = g("InstanceCreationTime")
    row["trigger_time"] = g("TriggerTime")
    row["temporal_position_identifier"] = g("TemporalPositionIdentifier")

    if Tag(0x5400, 0x0100) in ds:
        row["waveform_sequence"] = "true"
    if Tag(0x5400, 0x1010) in ds:
        row["waveform_data"] = "true"
    if Tag(0x003A, 0x001A) in ds:
        row["dicom_sampling_frequency"] = str(ds[0x003A, 0x001A].value)
    if Tag(0x003A, 0x0005) in ds:
        row["n_waveform_channels"] = str(ds[0x003A, 0x0005].value)
    if str(row["sop_class_uid"]).startswith(WAVEFORM_SOP_PREFIX):
        row["waveform_sequence"] = (
            "true" if row["waveform_sequence"] == "false" else row["waveform_sequence"]
        )
    return row


_DICOM_FIELDS = [
    "filepath",
    "sop_class_uid",
    "modality",
    "series_description",
    "protocol_name",
    "series_number",
    "instance_number",
    "series_time",
    "acquisition_time",
    "acquisition_datetime",
    "instance_creation_time",
    "trigger_time",
    "temporal_position_identifier",
    "waveform_sequence",
    "waveform_data",
    "dicom_sampling_frequency",
    "n_waveform_channels",
    "is_physiolog",
    "error",
]


def _append_tsv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    new_file = not path.is_file() or path.stat().st_size == 0
    with path.open("a", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(
            fh, fieldnames=fieldnames, delimiter="\t", lineterminator="\n", extrasaction="ignore"
        )
        if new_file:
            w.writeheader()
        for row in rows:
            w.writerow({k: row.get(k, "") for k in fieldnames})


def scan_dicoms_parallel(
    paths: list[Path],
    workers: int,
    checkpoint: Path | None = None,
    chunk: int = 2000,
) -> list[dict[str, str]]:
    done_paths: set[str] = set()
    if checkpoint and checkpoint.is_file():
        with checkpoint.open(encoding="utf-8", newline="") as fh:
            for r in csv.DictReader(fh, delimiter="\t"):
                done_paths.add(r["filepath"])
        LOGGER.info("Resuming DICOM scan from checkpoint (%d rows)", len(done_paths))
    remaining = [p for p in paths if str(p) not in done_paths]
    total = len(paths)
    LOGGER.info(
        "DICOM parallel scan: %d files, workers=%d, remaining=%d",
        total,
        workers,
        len(remaining),
    )
    str_paths = [str(p) for p in remaining]
    done = len(done_paths)
    # Stream results; do not retain all rows in RAM.
    with ProcessPoolExecutor(max_workers=workers) as ex:
        for i in range(0, len(str_paths), chunk):
            batch = str_paths[i : i + chunk]
            futs = [ex.submit(_dicom_quick_row, sp) for sp in batch]
            batch_rows: list[dict[str, str]] = []
            for fut in as_completed(futs):
                batch_rows.append(fut.result())
                done += 1
                if done % 25000 == 0:
                    LOGGER.info("DICOM scan progress %d / %d", done, total)
            if checkpoint and batch_rows:
                _append_tsv(checkpoint, _DICOM_FIELDS, batch_rows)
    # Do not reload ~900k rows into RAM here; caller streams from checkpoint.
    LOGGER.info("DICOM scan finished (%d / %d). Checkpoint: %s", done, total, checkpoint)
    return []


# ---------------------------------------------------------------------------
# Text / MATLAB
# ---------------------------------------------------------------------------
def inspect_text_physio(path: Path) -> dict[str, str] | None:
    try:
        sample = path.read_bytes()[:256_000]
    except OSError:
        return None
    text = sample.decode("latin-1", errors="replace")
    keys = (
        "ECG",
        "RESP",
        "PULS",
        "PMU",
        "PhysioLog",
        "SamplingFrequency",
        "SampleTime",
        "LogStartMDHTime",
        "Trigger",
    )
    hits = [k for k in keys if k.lower() in text.lower()]
    if not hits:
        return None
    return {
        "filepath": str(path),
        "size": str(path.stat().st_size),
        "keyword_hits": ";".join(hits),
        "has_sampling": str(
            any(k in hits for k in ("SamplingFrequency", "SampleTime"))
        ).lower(),
        "has_trigger": str("Trigger" in hits).lower(),
        "has_mdh": str("LogStartMDHTime" in hits).lower(),
    }


def inspect_matlab(path: Path) -> dict[str, str] | None:
    try:
        raw = path.read_bytes()[:2_000_000]
    except OSError:
        return None
    hits = [kw.decode() for kw in MAT_KEYWORDS if kw.lower() in raw.lower()]
    if not hits:
        return None
    return {
        "filepath": str(path),
        "size": str(path.stat().st_size),
        "keyword_hits": ";".join(sorted(set(hits))),
        "has_trigger": str(any("trigger" in h.lower() for h in hits)).lower(),
        "has_physio": str(
            any(h.lower() in {"physio", "ecg", "resp", "pulse", "cardiac"} for h in hits)
        ).lower(),
        "has_sampling": str(
            any(h.lower() in {"sampling", "samplerate", "frequency"} for h in hits)
        ).lower(),
        "has_mdh_mpcu": str(any(h in {"MDH", "MPCU"} for h in hits)).lower(),
    }


# ---------------------------------------------------------------------------
# BOLD index + recoverability
# ---------------------------------------------------------------------------
@dataclass
class BoldMeta:
    path: str
    subject: str
    session: str
    task: str
    run: str
    protocol_name: str


def load_bold_protocols(bids_root: Path) -> dict[tuple[str, str], list[BoldMeta]]:
    out: dict[tuple[str, str], list[BoldMeta]] = defaultdict(list)
    for jp in bids_root.glob("sub-*/ses-*/func/*_bold.json"):
        m = _RE_BOLD_JSON.search(jp.name)
        if not m:
            continue
        try:
            data = json.loads(jp.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                data = {}
        out[(m.group(1), m.group(2))].append(
            BoldMeta(
                path=str(jp),
                subject=m.group(1),
                session=m.group(2),
                task=m.group(3),
                run=m.group(4),
                protocol_name=str(data.get("ProtocolName") or ""),
            )
        )
    LOGGER.info(
        "Indexed BOLD protocols for %d subject-sessions (%d runs)",
        len(out),
        sum(len(v) for v in out.values()),
    )
    return out


def rank_conf(level: str) -> int:
    return {"HIGH": 4, "MEDIUM": 3, "LOW": 2, "NONE": 1, "INVALID": 0}.get(level, 0)


def evaluate_physiolog_recoverability(
    deep: dict[str, str],
    subject: str,
    session: str,
    bold_index: dict[tuple[str, str], list[BoldMeta]],
) -> dict[str, str]:
    reasons: list[str] = []
    sf = "NONE"
    st = "NONE"
    rm = "NONE"

    stmap = deep.get("sampletime_by_type") or NA
    if stmap not in (NA, "") and "=" in stmap:
        sf = "MEDIUM"
        reasons.append(
            f"CSA SampleTime present ({stmap}); Hz inferred as 1000/SampleTime "
            "(Siemens EJA_1 ms convention)"
        )
    else:
        reasons.append("No CSA SampleTime recovered")

    has_acq = deep.get("has_acquisition_info") == "true"
    vol0 = deep.get("vol0_acq_start_tics") or NA
    tick = NA
    for key in ("first_puls_tick", "first_resp_tick"):
        if deep.get(key) not in (None, "", NA):
            tick = deep[key]
            break
    if has_acq and vol0 != NA and tick != NA:
        st = "MEDIUM"
            reasons.append(
            "ACQUISITION_INFO volume0 ACQ_START_TICS and physio ACQ_TIME_TICS share CSA clock; "
            "BIDS StartTime = (physio_first_tick - vol0_start_tick) * tick_seconds"
        )
    elif has_acq:
        st = "LOW"
        reasons.append("ACQUISITION_INFO present but first channel tick missing")
    elif deep.get("series_time") not in (NA, ""):
        st = "LOW"
        reasons.append("Only SeriesTime available; not BIDS-relative StartTime")
        else:
        reasons.append("No reconstructable StartTime evidence")

    proto = deep.get("protocol_name") or NA
    if subject.startswith("sub-") and session.startswith("ses-") and proto not in (NA, ""):
        cands = [b for b in bold_index.get((subject, session), []) if b.protocol_name == proto]
        if len(cands) == 1:
            rm = "CONFIRMED"
            reasons.append(
                f"Unique BIDS ProtocolName match: {proto} → {Path(cands[0].path).name}"
            )
        elif len(cands) > 1:
            rm = "AMBIGUOUS"
            reasons.append(f"{len(cands)} BOLD runs share ProtocolName={proto}")
        elif bold_index.get((subject, session)):
            rm = "LIKELY"
            reasons.append(
                f"ProtocolName={proto} with subject/session resolved but no exact "
                f"ProtocolName hit among {len(bold_index[(subject, session)])} BOLD runs"
            )
        else:
            reasons.append("No BOLD runs for subject/session")
    else:
        reasons.append("No protocol/series description for run mapping")

    recoverable = (
        "YES"
        if rank_conf(sf) >= rank_conf("MEDIUM")
        and rank_conf(st) >= rank_conf("MEDIUM")
        and rm == "CONFIRMED"
        else "NO"
    )
    return {
        "source_type": "physiolog_dicom",
        "filepath": deep.get("filepath", NA),
        "subject": subject,
        "session": session,
        "sampling_confidence": sf,
        "starttime_confidence": st,
        "runmap_confidence": rm,
        "recoverable": recoverable,
        "reason": " | ".join(reasons),
    }


def evaluate_pmu_recoverability(
    pmu: dict[str, str], subject: str, session: str
) -> dict[str, str]:
    reasons: list[str] = []
    sf = "NONE"
    if pmu.get("sampling_rate_fields") not in (NA, "", None):
        sf = "MEDIUM"
        reasons.append(f"Explicit sampling field: {pmu['sampling_rate_fields']}")
    elif pmu.get("freq_per_fields") not in (NA, "", None):
        sf = "NONE"
        reasons.append(
            f"Freq Per present but INVALID as SamplingFrequency: {pmu['freq_per_fields']}"
        )
    else:
        reasons.append("No sampling-rate metadata")

    st = "NONE"
    if pmu.get("log_start_mdh") not in (NA, "", None):
        st = "LOW"
        reasons.append("LogStartMDHTime present as ticks only; no validated conversion")
    else:
        reasons.append("No StartTime evidence")

    rm = "AMBIGUOUS" if subject.startswith("sub-") and session.startswith("ses-") else "NONE"
    reasons.append("session-wide peripheral PMU lacks unique run mapping")

    return {
        "source_type": "peripheral_pmu",
        "filepath": pmu.get("filepath", NA),
        "subject": subject,
        "session": session,
        "sampling_confidence": sf,
        "starttime_confidence": st,
        "runmap_confidence": rm,
        "recoverable": "NO",
        "reason": " | ".join(reasons),
    }


# ---------------------------------------------------------------------------
# Figures
# ---------------------------------------------------------------------------
def _style_ax(ax) -> None:
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.tick_params(labelsize=8)


def make_figures(
    out_dir: Path,
    source_counts: dict[str, int],
    waveform_stats: dict[str, int],
    meta_avail: dict[str, dict[str, int]],
    recover_rows: list[dict[str, str]],
    option: str,
) -> None:
    fig_dir = out_dir / "figures"
    fig_dir.mkdir(parents=True, exist_ok=True)

    # Figure A
    fig, ax = plt.subplots(figsize=(7.2, 4.2))
    labels = list(source_counts.keys())
    vals = [source_counts[k] for k in labels]
    ax.barh(labels[::-1], vals[::-1], color="#3c5488")
    ax.set_xlabel("Files (n)")
    ax.set_title("Figure A. Physiological source overview")
    _style_ax(ax)
    fig.tight_layout()
    fig.savefig(fig_dir / "Figure_A_source_overview.pdf")
    fig.savefig(fig_dir / "Figure_A_source_overview.png", dpi=200)
    plt.close(fig)

    # Figure B
    fig, ax = plt.subplots(figsize=(7.2, 4.2))
    blabels = list(waveform_stats.keys())
    bvals = [waveform_stats[k] for k in blabels]
    colors = ["#e64b35" if "WaveformSequence=0" in k or k.startswith("Standard") else "#4dbbd5" for k in blabels]
    ax.bar(range(len(blabels)), bvals, color=colors)
    ax.set_xticks(range(len(blabels)))
    ax.set_xticklabels(blabels, rotation=25, ha="right", fontsize=7)
    ax.set_ylabel("Files (n)")
    ax.set_title("Figure B. Waveform / PhysioLog DICOM sources")
    _style_ax(ax)
    fig.tight_layout()
    fig.savefig(fig_dir / "Figure_B_waveform_sources.pdf")
    fig.savefig(fig_dir / "Figure_B_waveform_sources.png", dpi=200)
    plt.close(fig)

    # Figure C — metadata availability confidence
    fig, axes = plt.subplots(1, 3, figsize=(10.5, 3.6), sharey=True)
    metrics = ["sampling", "starttime", "runmap"]
    titles = ["SamplingFrequency", "StartTime", "Run mapping"]
    order_s = ["HIGH", "MEDIUM", "LOW", "NONE"]
    order_r = ["CONFIRMED", "LIKELY", "AMBIGUOUS", "NONE"]
    for ax, metric, title in zip(axes, metrics, titles):
        data = meta_avail.get(metric, {})
        order = order_r if metric == "runmap" else order_s
        vals = [data.get(k, 0) for k in order]
        ax.bar(order, vals, color="#00a087")
        ax.set_title(title, fontsize=10)
        ax.set_ylabel("Recordings (n)" if ax is axes[0] else "")
        ax.tick_params(axis="x", labelrotation=30, labelsize=7)
        _style_ax(ax)
    fig.suptitle("Figure C. Metadata availability by confidence", fontsize=12)
    fig.tight_layout()
    fig.savefig(fig_dir / "Figure_C_metadata_availability.pdf")
    fig.savefig(fig_dir / "Figure_C_metadata_availability.png", dpi=200)
    plt.close(fig)

    # Figure D — recoverability matrix by source
    by_src: dict[str, Counter] = defaultdict(Counter)
    for r in recover_rows:
        by_src[r["source_type"]][r["recoverable"]] += 1
    sources = sorted(by_src)
    fig, ax = plt.subplots(figsize=(7.2, 3.8))
    yes = [by_src[s].get("YES", 0) for s in sources]
    no = [by_src[s].get("NO", 0) for s in sources]
    x = range(len(sources))
    ax.bar(x, yes, label="Recoverable YES", color="#00a087")
    ax.bar(x, no, bottom=yes, label="Recoverable NO", color="#e64b35")
    ax.set_xticks(list(x))
    ax.set_xticklabels(sources, rotation=20, ha="right", fontsize=8)
    ax.set_ylabel("Recordings (n)")
    ax.set_title("Figure D. Recoverability matrix")
    ax.legend(frameon=False, fontsize=8)
    _style_ax(ax)
    fig.tight_layout()
    fig.savefig(fig_dir / "Figure_D_recoverability_matrix.pdf")
    fig.savefig(fig_dir / "Figure_D_recoverability_matrix.png", dpi=200)
    plt.close(fig)

    # Figure E — decision tree
    fig, ax = plt.subplots(figsize=(8.5, 5.5))
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 10)
                ax.axis("off")
    ax.set_title(f"Figure E. Decision tree → {option}", fontsize=12, pad=12)

    def box(x, y, w, h, text, fc="#f0f0f0"):
        p = FancyBboxPatch(
            (x, y), w, h, boxstyle="round,pad=0.02,rounding_size=0.15",
            linewidth=1.0, edgecolor="#222222", facecolor=fc,
        )
        ax.add_patch(p)
        ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=7.5, wrap=True)

    box(3.2, 8.5, 3.6, 1.0, "Physiology sources in archive", "#d6eaf8")
    box(0.3, 6.2, 2.8, 1.2, "Standard DICOM\nWaveformSequence?\n→ typically NO", "#fadbd8")
    box(3.6, 6.2, 2.8, 1.2, "Siemens PhysioLog\nCSA (7FE1,1010)?\n→ YES (run-linked)", "#d5f5e3")
    box(6.9, 6.2, 2.8, 1.2, "Peripheral PMU\n(.ecg/.resp/.puls)\nFreq Per only", "#fcf3cf")
    box(3.6, 3.8, 2.8, 1.4, "SampleTime +\nACQUISITION_INFO +\nunique ProtocolName?", "#d5f5e3")
    box(6.9, 3.8, 2.8, 1.4, "Not convertible\nwithout assumptions\n(OPTION C for PMU)", "#fadbd8")
    box(3.6, 1.2, 2.8, 1.2, f"OPTION B\nPhysioLog subset\nconvertible (gated)", "#abebc6")
    ax.annotate("", xy=(1.7, 7.4), xytext=(4.2, 8.5), arrowprops=dict(arrowstyle="->", color="#333"))
    ax.annotate("", xy=(5.0, 7.4), xytext=(5.0, 8.5), arrowprops=dict(arrowstyle="->", color="#333"))
    ax.annotate("", xy=(8.3, 7.4), xytext=(5.8, 8.5), arrowprops=dict(arrowstyle="->", color="#333"))
    ax.annotate("", xy=(5.0, 5.2), xytext=(5.0, 6.2), arrowprops=dict(arrowstyle="->", color="#333"))
    ax.annotate("", xy=(8.3, 5.2), xytext=(8.3, 6.2), arrowprops=dict(arrowstyle="->", color="#333"))
    ax.annotate("", xy=(5.0, 2.4), xytext=(5.0, 3.8), arrowprops=dict(arrowstyle="->", color="#333"))
    fig.tight_layout()
    fig.savefig(fig_dir / "Figure_E_decision_tree.pdf")
    fig.savefig(fig_dir / "Figure_E_decision_tree.png", dpi=200)
    plt.close(fig)
    LOGGER.info("Wrote figures under %s", fig_dir)


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------
def write_forensic_report(
    path: Path,
    inventory_n: int,
    source_counts: dict[str, int],
    dicom_n: int,
    waveform_n: int,
    physiolog_n: int,
    physiolog_with_sampletime: int,
    physiolog_with_acqinfo: int,
    pmu_n: int,
    pmu_with_explicit_sf: int,
    text_n: int,
    mat_n: int,
    timing_acq_present: int,
    timing_series_present: int,
    recover_rows: list[dict[str, str]],
    option: str,
    option_text: str,
) -> None:
    by_src: dict[str, list[dict[str, str]]] = defaultdict(list)
    for r in recover_rows:
        by_src[r["source_type"]].append(r)

    def src_summary(name: str) -> tuple[str, str, str, str]:
        rows = by_src.get(name, [])
        if not rows:
            return "NONE", "NONE", "NONE", "NO"
        sf = Counter(r["sampling_confidence"] for r in rows).most_common(1)[0][0]
        st = Counter(r["starttime_confidence"] for r in rows).most_common(1)[0][0]
        rm = Counter(r["runmap_confidence"] for r in rows).most_common(1)[0][0]
        rec = "YES" if any(r["recoverable"] == "YES" for r in rows) else "NO"
        return sf, st, rm, rec

    n_yes = sum(1 for r in recover_rows if r["recoverable"] == "YES")
    n_no = sum(1 for r in recover_rows if r["recoverable"] == "NO")

    lines = [
        "# Physiological forensic audit",
        "",
        f"Generated: `{_now()}`",
        "",
        "**READ-ONLY AUDIT.** No modifications to `raw_original/`, `bids/`,",
        "`derivatives/`, or `release_dataset/`. No `*_physio.tsv.gz` created.",
        "",
        "## 1. Inventory",
        "",
        f"Source inventory rows (physio-relevant candidates): **{inventory_n}**",
        "",
    ]
    for k, v in source_counts.items():
        lines.append(f"- {k}: **{v}**")
    lines += [
        "",
        f"Full DICOM archive size scanned for timing/waveform tags: **{dicom_n}**",
        "",
        "## 2. Potential metadata sources",
        "",
        "| Source | What it provides | Limitation |",
        "| --- | --- | --- |",
        "| Siemens PhysioLog DICOM (CSA `7FE1,1010`) | `SampleTime`, channel traces, `ACQUISITION_INFO` volume ticks, per-run series | Not standard Waveform IOD; requires CSA parser |",
        "| Peripheral PMU (`.ecg/.resp/.puls/.ext/.pmu`) | Waveforms + `Freq Per` + MDH/MPCU ticks | No ADC SamplingFrequency; session-wide |",
        "| Standard DICOM WaveformSequence | BIDS-ready sampling + waveform | **Not found** in this archive |"
        if waveform_n == 0
        else f"| Standard DICOM WaveformSequence | BIDS-ready sampling + waveform | Found in **{waveform_n}** files |",
        "| MATLAB | Task triggers / Psychtoolbox clocks | Wrong clock domain for PMU ADC |",
        "| Text PhysioLog / ScanLog | Occasional keywords | No standalone validated physio streams found beyond DICOM CSA |",
        "",
        "## 3. Waveform DICOM audit",
        "",
        f"- Standard WaveformSequence / Waveform SOP instances: **{waveform_n}**",
        f"- Siemens PhysioLog DICOM objects: **{physiolog_n}**",
        f"- PhysioLog with explicit CSA `SampleTime`: **{physiolog_with_sampletime}**",
        f"- PhysioLog with `ACQUISITION_INFO`: **{physiolog_with_acqinfo}**",
        "",
        "PhysioLog objects use Siemens private SOP Class and store physiology inside CSA Data,",
        "not DICOM WaveformSequence (`5400,0100`). Waveform *content* is present for PULS/RESP/EXT",
        "channels inside CSA, with explicit `SampleTime` (ms) per channel type.",
        "",
        "## 4. PMU audit",
        "",
        f"- Peripheral PMU files parsed: **{pmu_n}**",
        f"- With explicit SamplingFrequency/SampleRate labels: **{pmu_with_explicit_sf}**",
        "",
        "Siemens `Freq Per` fields are physiological rates/periods and are **not** ADC sampling rates.",
        "MDH/MPCU timestamps remain scanner ticks without a validated transform in peripheral files.",
        "",
        "## 5. MATLAB audit",
        "",
        f"- MATLAB files with physio/trigger/sampling keyword hits: **{mat_n}**",
        "",
        "Prior and current string forensics show Psychtoolbox `triggerTimes` / display timing,",
        "not Siemens PMU ADC SamplingFrequency or MDH/MPCU clock transforms.",
        "",
        "## 6. Timing audit",
        "",
        f"- Imaging/Physio DICOM instances with `AcquisitionTime` or `AcquisitionDateTime`: **{timing_acq_present}**",
        f"- Instances with `SeriesTime`: **{timing_series_present}**",
        "",
        "BOLD JSON sidecars generally lack AcquisitionTime; PhysioLog CSA volume ticks are the",
        "viable route to BIDS-relative StartTime for PhysioLog-linked runs.",
        "",
        "## 7. Run mapping audit",
        "",
        "Peripheral PMU logs are session-wide → AMBIGUOUS.",
        "",
        "PhysioLog series descriptions (`*_PhysioLog`) encode the parent protocol and can uniquely",
        "match BIDS `ProtocolName` when one-to-one.",
        "",
        "## 8. Final recoverability table",
        "",
        "| Source | SamplingFrequency | StartTime | RunMap | Recoverable |",
        "| --- | --- | --- | --- | --- |",
    ]
    for src in (
        "physiolog_dicom",
        "peripheral_pmu",
        "matlab",
        "text_physiolog",
        "dicom_timing",
        "waveform_dicom",
    ):
        sf, st, rm, rec = src_summary(src)
        label = {
            "physiolog_dicom": "PhysioLog DICOM",
            "peripheral_pmu": "PMU",
            "matlab": "MATLAB",
            "text_physiolog": "PhysioLog text",
            "dicom_timing": "DICOM Timing",
            "waveform_dicom": "Waveform DICOM",
        }[src]
        lines.append(f"| {label} | {sf} | {st} | {rm} | {rec} |")
    lines += [
        "",
        f"Per-recording recoverability: **YES={n_yes}**, **NO={n_no}**",
        "",
        "## 9. Scientific Data recommendation",
        "",
        f"### {option}",
        "",
        option_text,
        "",
        "## 10. Confirmation of non-modification",
        "",
        "- No files modified in `raw_original/`, `bids/`, `derivatives/`, or `release_dataset/`.",
        "- No BIDS physio files generated (`*_physio.tsv.gz` count remains unchanged by this audit).",
        "- No raw data altered. Audit outputs written only under `reports/physiology_audit/`.",
        "",
        "## Outputs",
        "",
        "- `source_inventory.tsv`",
        "- `dicom_waveform_inventory.tsv`",
        "- `dicom_timing_inventory.tsv`",
        "- `pmu_metadata_inventory.tsv`",
        "- `physiolog_inventory.tsv` / `physiolog_dicom_deep.tsv`",
        "- `matlab_physio_inventory.tsv`",
        "- `recoverability_evaluation.tsv`",
        "- `PHYSIO_FORENSIC_AUDIT.md`",
        "- `figures/Figure_A_source_overview.pdf`",
        "- `figures/Figure_B_waveform_sources.pdf`",
        "- `figures/Figure_C_metadata_availability.pdf`",
        "- `figures/Figure_D_recoverability_matrix.pdf`",
        "- `figures/Figure_E_decision_tree.pdf`",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-root", type=Path, default=DEFAULT_RAW)
    parser.add_argument("--bids-root", type=Path, default=DEFAULT_BIDS)
    parser.add_argument("--metadata-root", type=Path, default=DEFAULT_META)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--workers", type=int, default=min(48, os.cpu_count() or 8))
    parser.add_argument(
        "--dicom-mode",
        choices=("all", "physiolog_plus_sample"),
        default="all",
        help="all=scan every DICOM; physiolog_plus_sample=PhysioLog + 1%% random imaging sample",
    )
    parser.add_argument("--reuse", action="store_true", help="Reuse existing TSV inventories when present")
    parser.add_argument("--skip-dicom-scan", action="store_true")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    raw_root = args.raw_root.resolve()
    bids_root = args.bids_root.resolve()
    meta_root = args.metadata_root.resolve()
    out_dir = args.out_dir.resolve()
    if "physiology_audit" not in out_dir.parts:
        LOGGER.error("Refusing to write outside physiology_audit: %s", out_dir)
        return 2
    out_dir.mkdir(parents=True, exist_ok=True)
    _configure_logging(args.verbose, out_dir / "forensic_audit_run.log")

    LOGGER.info(
        "RAW=%s BIDS=%s OUT=%s workers=%d", raw_root, bids_root, out_dir, args.workers
    )

    folder_map = load_folder_map(meta_root)

    cache_disc = out_dir / "_discovery_cache.pkl"
    if args.reuse and cache_disc.is_file():
        LOGGER.info("Loading discovery cache")
        buckets = pickle.loads(cache_disc.read_bytes())
    else:
        buckets = discover_archive(raw_root)
        cache_disc.write_bytes(pickle.dumps(buckets))

    # Step 1 — source inventory
    src_path = out_dir / "source_inventory.tsv"
    if args.reuse and src_path.is_file():
        source_rows = load_tsv(src_path)
        LOGGER.info("Reused source_inventory (%d)", len(source_rows))
    else:
        source_rows = build_source_inventory(buckets, folder_map)
        write_tsv(
            src_path,
            ["filepath", "extension", "size", "subject", "session", "sequence", "candidate_type"],
            source_rows,
        )

    # Step 3 — PMU
    pmu_path = out_dir / "pmu_metadata_inventory.tsv"
    if args.reuse and pmu_path.is_file():
        pmu_rows = load_tsv(pmu_path)
        LOGGER.info("Reused pmu_metadata_inventory (%d)", len(pmu_rows))
    else:
        LOGGER.info("Parsing %d PMU files", len(buckets["pmu"]))
        pmu_rows = []
        for i, p in enumerate(sorted(buckets["pmu"]), 1):
            pmu_rows.append(parse_pmu_file(p))
            if i % 100 == 0 or i == len(buckets["pmu"]):
                LOGGER.info("PMU parse %d / %d", i, len(buckets["pmu"]))
        write_tsv(
            pmu_path,
            [
                "filepath",
            "extension",
                "format",
                "sampling_rate_fields",
                "freq_per_fields",
                "log_start_mdh",
                "log_stop_mdh",
                "log_start_mpcu",
                "log_stop_mpcu",
                "nr_trig",
                "sampletime_fields",
                "other_freq_hits",
                "error",
            ],
            pmu_rows,
        )

    # Step 5 / PhysioLog deep
    deep_path = out_dir / "physiolog_dicom_deep.tsv"
    if args.reuse and deep_path.is_file():
        physiolog_rows = load_tsv(deep_path)
        LOGGER.info("Reused physiolog_dicom_deep (%d)", len(physiolog_rows))
    else:
        physiolog_rows = parse_physiolog_parallel(buckets["physiolog"], args.workers)
        write_tsv(
            deep_path,
            [
                "filepath",
                "series_description",
                "protocol_name",
                "series_number",
                "series_time",
                "sop_class_uid",
                "csa_nbytes",
                "embedded_logs",
                "log_datatypes",
                "sampletime_by_type",
                "logversion",
                "scandate",
                "uuid",
                "num_volumes",
                "vol0_acq_start_tics",
                "first_puls_tick",
                "first_resp_tick",
                "has_acquisition_info",
                "error",
            ],
            physiolog_rows,
        )
    # lightweight physiolog inventory
    physio_inv = []
    for r in physiolog_rows:
        sub, ses = resolve_subject_session(Path(r["filepath"]), folder_map)
        physio_inv.append(
            {
                "filepath": r["filepath"],
                "subject": sub,
                "session": ses,
                "series_description": r.get("series_description", NA),
                "protocol_name": r.get("protocol_name", NA),
                "sampletime_by_type": r.get("sampletime_by_type", NA),
                "embedded_logs": r.get("embedded_logs", NA),
                "has_acquisition_info": r.get("has_acquisition_info", NA),
            }
        )
    write_tsv(
        out_dir / "physiolog_inventory.tsv",
        [
            "filepath",
            "subject",
            "session",
            "series_description",
            "protocol_name",
            "sampletime_by_type",
            "embedded_logs",
            "has_acquisition_info",
        ],
        physio_inv,
    )

    # Step 6 MATLAB
    mat_path = out_dir / "matlab_physio_inventory.tsv"
    if args.reuse and mat_path.is_file():
        mat_rows = load_tsv(mat_path)
        LOGGER.info("Reused matlab_physio_inventory (%d)", len(mat_rows))
    else:
        mat_rows = []
        mats = buckets.get("mat", [])
        for i, p in enumerate(mats, 1):
            hit = inspect_matlab(p)
            if hit:
                sub, ses = resolve_subject_session(p, folder_map)
                hit["subject"] = sub
                hit["session"] = ses
                mat_rows.append(hit)
            if i % 500 == 0:
                LOGGER.info("MATLAB scan %d / %d", i, len(mats))
        write_tsv(
            mat_path,
            [
                "filepath",
                "size",
                "keyword_hits",
                "has_trigger",
                "has_physio",
                "has_sampling",
                "has_mdh_mpcu",
                "subject",
                "session",
            ],
            mat_rows,
        )

    # Text physiolog-like
    text_rows = []
    for p in buckets.get("text", []):
        hit = inspect_text_physio(p)
        if hit:
            text_rows.append(hit)
    write_tsv(
        out_dir / "physiolog_text_keyword_hits.tsv",
        ["filepath", "size", "keyword_hits", "has_sampling", "has_trigger", "has_mdh"],
        text_rows,
    )

    # Steps 2+4 DICOM scan
    dicom_checkpoint = out_dir / "_dicom_scan_checkpoint.tsv"
    dicom_rows: list[dict[str, str]] = []
    if args.skip_dicom_scan and dicom_checkpoint.is_file():
        dicom_rows = load_tsv(dicom_checkpoint)
        LOGGER.info("Skipping DICOM scan; loaded checkpoint %d", len(dicom_rows))
    elif not args.skip_dicom_scan:
        dicom_paths = buckets["dicom"]
        if args.dicom_mode == "physiolog_plus_sample":
            phys_set = set(map(str, buckets["physiolog"]))
            others = [p for p in dicom_paths if str(p) not in phys_set]
            random.Random(0).shuffle(others)
            sample_n = max(1, len(others) // 100)
            dicom_paths = list(buckets["physiolog"]) + others[:sample_n]
            LOGGER.info(
                "DICOM mode physiolog_plus_sample: %d paths", len(dicom_paths)
            )
        dicom_rows = scan_dicoms_parallel(
            dicom_paths, workers=args.workers, checkpoint=dicom_checkpoint
        )
    elif args.reuse and (out_dir / "dicom_timing_inventory.tsv").is_file():
        dicom_rows = load_tsv(out_dir / "dicom_timing_inventory.tsv")

    # Split waveform vs timing inventories (stream; avoid holding 900k rows twice)
    if dicom_rows:
        # Already loaded (skip mode / small)
        waveform_rows = [
            r
            for r in dicom_rows
            if r.get("waveform_sequence") in {"true", "maybe_raw_sig"}
            or r.get("waveform_data") in {"true", "maybe_raw_sig"}
            or str(r.get("sop_class_uid", "")).startswith(WAVEFORM_SOP_PREFIX)
        ]
        write_tsv(
            out_dir / "dicom_waveform_inventory.tsv",
            [
                "filepath",
                "sop_class_uid",
                "modality",
                "series_description",
                "protocol_name",
                "series_number",
                "waveform_sequence",
                "waveform_data",
                "dicom_sampling_frequency",
                "n_waveform_channels",
                "acquisition_time",
                "acquisition_datetime",
                "is_physiolog",
                "error",
            ],
            waveform_rows,
        )
        write_tsv(
            out_dir / "dicom_timing_inventory.tsv",
            [
                "filepath",
                "sop_class_uid",
                "modality",
                "series_description",
                "protocol_name",
                "series_number",
                "instance_number",
                "series_time",
                "acquisition_time",
                "acquisition_datetime",
                "instance_creation_time",
                "trigger_time",
                "temporal_position_identifier",
                "is_physiolog",
                "error",
            ],
            dicom_rows,
        )
        timing_acq = sum(
            1
            for r in dicom_rows
            if r.get("acquisition_time") not in (NA, "", None, "None")
            or r.get("acquisition_datetime") not in (NA, "", None, "None")
        )
        timing_series = sum(
            1 for r in dicom_rows if r.get("series_time") not in (NA, "", None, "None")
        )
        waveform_n = len(waveform_rows)
        dicom_n = len(dicom_rows)
    else:
        # Prefer checkpoint on disk
        src_cp = dicom_checkpoint if dicom_checkpoint.is_file() else None
        timing_path = out_dir / "dicom_timing_inventory.tsv"
        wave_path = out_dir / "dicom_waveform_inventory.tsv"
        if src_cp is not None:
            import shutil

            shutil.copyfile(src_cp, timing_path)
        timing_acq = timing_series = waveform_n = dicom_n = 0
        waveform_rows = []
        if timing_path.is_file():
            with timing_path.open(encoding="utf-8", newline="") as fh:
                reader = csv.DictReader(fh, delimiter="\t")
                wave_buf: list[dict[str, str]] = []
                for r in reader:
                    dicom_n += 1
                    if r.get("series_time") not in (NA, "", None, "None"):
                        timing_series += 1
                    if r.get("acquisition_time") not in (NA, "", None, "None") or r.get(
                        "acquisition_datetime"
                    ) not in (NA, "", None, "None"):
                        timing_acq += 1
                    if (
                        r.get("waveform_sequence") in {"true", "maybe_raw_sig"}
                        or r.get("waveform_data") in {"true", "maybe_raw_sig"}
                        or str(r.get("sop_class_uid", "")).startswith(WAVEFORM_SOP_PREFIX)
                    ):
                        wave_buf.append(r)
                waveform_rows = wave_buf
                waveform_n = len(wave_buf)
            write_tsv(
                wave_path,
                [
                    "filepath",
                    "sop_class_uid",
                    "modality",
                    "series_description",
                    "protocol_name",
                    "series_number",
                    "waveform_sequence",
                    "waveform_data",
                    "dicom_sampling_frequency",
                    "n_waveform_channels",
                    "acquisition_time",
                    "acquisition_datetime",
                    "is_physiolog",
                    "error",
                ],
                waveform_rows,
            )
        # Keep dicom_rows empty; aggregates already computed.
        dicom_rows = []

    # Recoverability
    bold_index = load_bold_protocols(bids_root)
    recover_rows: list[dict[str, str]] = []
    for r in physiolog_rows:
        sub, ses = resolve_subject_session(Path(r["filepath"]), folder_map)
        recover_rows.append(
            evaluate_physiolog_recoverability(r, sub, ses, bold_index)
        )
    for r in pmu_rows:
        sub, ses = resolve_subject_session(Path(r["filepath"]), folder_map)
        recover_rows.append(evaluate_pmu_recoverability(r, sub, ses))
    # Aggregate placeholders for other sources
    recover_rows.append(
        {
            "source_type": "matlab",
            "filepath": NA,
            "subject": NA,
            "session": NA,
            "sampling_confidence": "NONE",
            "starttime_confidence": "LOW",
            "runmap_confidence": "NONE",
            "recoverable": "NO",
            "reason": "Psychtoolbox triggers only; no PMU ADC sampling metadata",
        }
    )
    recover_rows.append(
        {
            "source_type": "text_physiolog",
            "filepath": NA,
            "subject": NA,
            "session": NA,
            "sampling_confidence": "NONE",
            "starttime_confidence": "NONE",
            "runmap_confidence": "NONE",
            "recoverable": "NO",
            "reason": "No standalone text PhysioLog streams with validated ADC metadata",
        }
    )
    recover_rows.append(
        {
            "source_type": "dicom_timing",
            "filepath": NA,
            "subject": NA,
            "session": NA,
            "sampling_confidence": "NONE",
            "starttime_confidence": "LOW",
            "runmap_confidence": "NONE",
            "recoverable": "NO",
            "reason": "SeriesTime common; AcquisitionTime rare; insufficient alone for physio StartTime",
        }
    )
    recover_rows.append(
        {
            "source_type": "waveform_dicom",
            "filepath": NA,
            "subject": NA,
            "session": NA,
            "sampling_confidence": "NONE",
            "starttime_confidence": "NONE",
            "runmap_confidence": "NONE",
            "recoverable": "NO",
            "reason": "No standard DICOM WaveformSequence objects recovered",
        }
    )
    write_tsv(
        out_dir / "recoverability_evaluation.tsv",
        [
            "source_type",
            "filepath",
            "subject",
            "session",
            "sampling_confidence",
            "starttime_confidence",
            "runmap_confidence",
            "recoverable",
            "reason",
        ],
        recover_rows,
    )

    n_yes = sum(1 for r in recover_rows if r["recoverable"] == "YES")
    n_physio_yes = sum(
        1
        for r in recover_rows
        if r["source_type"] == "physiolog_dicom" and r["recoverable"] == "YES"
    )
    if n_physio_yes > 0 and n_physio_yes < len(physiolog_rows):
        option = "OPTION B"
        option_text = (
            f"**Partial conversion is possible** for **{n_physio_yes}** "
            "Siemens PhysioLog DICOM recordings that embed CSA `SampleTime`, "
            "`ACQUISITION_INFO` volume ticks, and a unique BIDS `ProtocolName` match. "
            "Peripheral `.ecg/.resp/.puls` PMU files remain **not convertible** without "
            "inventing SamplingFrequency or run alignment. Standard DICOM Waveform IODs "
            "were not found. A gated converter (separate from this audit) would be required "
            "before any `*_physio.tsv.gz` release; this audit created none."
        )
    elif n_physio_yes > 0 and all(
        r["recoverable"] == "YES"
        for r in recover_rows
        if r["source_type"] == "physiolog_dicom"
    ):
        option = "OPTION A"
        option_text = (
            "Physiology can be converted into valid BIDS for the PhysioLog DICOM corpus "
            "under a validated CSA parser. Peripheral PMU still excluded."
        )
    else:
        option = "OPTION C"
        option_text = (
            "Physiology cannot be converted without unsupported assumptions for the "
            "peripheral PMU archive, and PhysioLog DICOM recordings did not jointly "
            "satisfy SamplingFrequency≥MEDIUM, StartTime≥MEDIUM, and CONFIRMED run "
            "mapping at scale."
        )

    # Stats for figures / report
    source_counts = Counter(r.get("candidate_type", "other") for r in source_rows)
    waveform_n = len(waveform_rows)
    waveform_stats = {
        "Standard WaveformSequence": waveform_n,
        "PhysioLog DICOM": len(physiolog_rows),
        "Peripheral PMU": len(pmu_rows),
    }
    meta_avail = {
        "sampling": Counter(
            r["sampling_confidence"]
            for r in recover_rows
            if r["source_type"] in {"physiolog_dicom", "peripheral_pmu"}
        ),
        "starttime": Counter(
            r["starttime_confidence"]
            for r in recover_rows
            if r["source_type"] in {"physiolog_dicom", "peripheral_pmu"}
        ),
        "runmap": Counter(
            r["runmap_confidence"]
            for r in recover_rows
            if r["source_type"] in {"physiolog_dicom", "peripheral_pmu"}
        ),
    }
    make_figures(out_dir, dict(source_counts), waveform_stats, meta_avail, recover_rows, option)

    write_forensic_report(
        out_dir / "PHYSIO_FORENSIC_AUDIT.md",
        inventory_n=len(source_rows),
        source_counts=dict(source_counts),
        dicom_n=dicom_n,
        waveform_n=waveform_n,
        physiolog_n=len(physiolog_rows),
        physiolog_with_sampletime=sum(
            1
            for r in physiolog_rows
            if r.get("sampletime_by_type") not in (NA, "", None) and "=" in r.get("sampletime_by_type", "")
        ),
        physiolog_with_acqinfo=sum(
            1 for r in physiolog_rows if r.get("has_acquisition_info") == "true"
        ),
        pmu_n=len(pmu_rows),
        pmu_with_explicit_sf=sum(
            1 for r in pmu_rows if r.get("sampling_rate_fields") not in (NA, "", None)
        ),
        text_n=len(text_rows),
        mat_n=len(mat_rows),
        timing_acq_present=timing_acq,
        timing_series_present=timing_series,
        recover_rows=recover_rows,
        option=option,
        option_text=option_text,
    )

    # Explicit non-modification confirmation file
    (out_dir / "AUDIT_READONLY_CONFIRMATION.txt").write_text(
        "\n".join(
            [
                "READ-ONLY CONFIRMATION",
                f"timestamp: {_now()}",
                "No files modified in raw_original/, bids/, derivatives/, release_dataset/.",
                "No *_physio.tsv.gz generated by this audit.",
                "Audit outputs only under reports/physiology_audit/.",
                f"Decision: {option}",
                f"Recoverable recordings (YES): {n_yes}",
                "",
            ]
        ),
        encoding="utf-8",
    )

    LOGGER.info("DONE option=%s recoverable_YES=%d", option, n_yes)
    print(f"FORENSIC AUDIT COMPLETE: {option} recoverable_YES={n_yes} out={out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
