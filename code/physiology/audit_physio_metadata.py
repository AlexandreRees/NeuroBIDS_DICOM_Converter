#!/usr/bin/env python3
"""Safe, non-destructive audit of Siemens physiological recordings.

This module INSPECTS physiological logs under ``raw_original/`` and REPORTS
what it finds. It is intentionally conservative:

    * It NEVER modifies, moves, copies, or deletes anything under
      ``raw_original/`` (or anywhere outside the report output directory).
    * It NEVER guesses or fills in missing metadata. Any value that is not
      explicitly present in a file or in existing project metadata is written
      as the literal string ``NA``.
    * It does NOT create BIDS mappings or convert anything. It only classifies
      how confidently each physiology file could later be associated with a
      BIDS run: ``confirmed`` / ``possible`` / ``ambiguous`` / ``unmatched``.

Outputs (all under ``reports/physiology_audit/``):

    physiology_inventory.tsv            discovery + checksums (section A)
    physiology_metadata_report.tsv      header parse + nearby metadata + BIDS
                                        association (sections B, C, D)
    physiology_summary.md               human-readable counts (section E)
    physiology_conversion_candidates.tsv  files that are BOTH sampling-frequency
                                        known AND BIDS-run confirmed (subset)

Run with::

    python3 code/physiology/audit_physio_metadata.py
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import logging
import os
import re
from dataclasses import dataclass, field, fields
from datetime import datetime, timezone
from pathlib import Path

LOGGER = logging.getLogger("physiology_audit")

NA = "NA"

# ---------------------------------------------------------------------------
# Defaults (all overridable via CLI). Absolute paths per project layout.
# ---------------------------------------------------------------------------
DEFAULT_RAW_ROOT = Path("/project/def-amirs/raw_original")
DEFAULT_METADATA = Path("/lustre07/scratch/alexrees/metadata")
DEFAULT_BIDS = Path("/lustre07/scratch/alexrees/bids")
DEFAULT_OUT = Path("/lustre07/scratch/alexrees/reports/physiology_audit")

PHYSIO_EXTENSIONS = (".ecg", ".resp", ".puls", ".pmu", ".ext", ".ext1", ".ext2")

# Nearby-file search (section C).
METADATA_SEARCH_EXTENSIONS = (".mat", ".m", ".txt", ".log")
METADATA_SEARCH_STRINGS = (
    "SamplingFrequency",
    "sampling_rate",
    "SampleRate",
    "Frequency",
    "Hz",
    "TR",
    "Trigger",
    "StartTime",
    "Timestamp",
    "ECG",
    "RESP",
    "PULS",
)
# Bound the nearby search so a session folder full of DICOMs cannot blow up.
MAX_NEARBY_FILES_PER_SESSION = 4000
MAX_NEARBY_DIRS_PER_SESSION = 8000
MAX_NEARBY_BYTES_READ = 4 * 1024 * 1024  # 4 MB per candidate file
MAX_REPORTED_METADATA_SOURCES = 25

# DICOM dump directories are pruned from both walks: physiology logs and
# associated MATLAB/text metadata never live inside a DICOM series tree, and
# descending into them (tens of thousands of .IMA files) is what makes a naive
# walk unusably slow. Pruning is a traversal optimisation only; it changes no
# reported value.
_RE_DICOM_SERIES_DIR = re.compile(r".+_\d{3,4}$")


def _is_dicom_dump_dir(name: str) -> bool:
    upper = name.upper()
    if _RE_DICOM_SERIES_DIR.match(name):
        return True
    if upper.startswith("DR_SHMUEL"):
        return True
    if "PROTOCOL_" in upper:
        return True
    return False

# Regexes for the Siemens ASCII PMU footer / markers.
_RE_LOGVERSION = re.compile(r"LOGVERSION[_A-Z0-9]*", re.IGNORECASE)
# NOTE: the Siemens "<CHAN> Freq Per:" footer line reports a PHYSIOLOGICAL rate
# (e.g. pulse in beats/min and its period in ms), NOT the ADC sampling
# frequency. It is captured separately and must never be reported as the
# sampling frequency.
_RE_FREQ_PER = re.compile(
    r"^(ECG|PULS|RESP|EXT2?|EXT)\s+Freq\s+Per:\s*(-?\d+)\s+(-?\d+)", re.MULTILINE
)
# An explicit, labelled sampling frequency is the ONLY thing accepted as
# sampling_frequency. Siemens ASCII PMU logs do not contain this, so it will
# normally be NA (never assumed from scanner defaults).
_RE_SAMPLING_FREQ = re.compile(
    r"(?:SamplingFrequency|SampleRate|sampling_rate)\s*[:=]?\s*(\d+(?:\.\d+)?)",
    re.IGNORECASE,
)
_RE_NRTRIG = re.compile(
    r"NrTrig\s+NrMP\s+NrArr\s+AcqWin:\s*(-?\d+)\s+(-?\d+)\s+(-?\d+)\s+(-?\d+)"
)
_RE_LOGSTART_MDH = re.compile(r"LogStartMDHTime:\s*(-?\d+)")
_RE_LOGSTOP_MDH = re.compile(r"LogStopMDHTime:\s*(-?\d+)")
_RE_LOGSTART_MPCU = re.compile(r"LogStartMPCUTime:\s*(-?\d+)")
_RE_LOGSTOP_MPCU = re.compile(r"LogStopMPCUTime:\s*(-?\d+)")
_RE_VSN = re.compile(r"VSN\s+([0-9][0-9.]*)\s+([0-9A-Za-z\-]+)")

# Subject / session recognition from raw folder names.
_RE_SUBJECT = re.compile(r"(SUB[A-Z]*\d+)", re.IGNORECASE)
_RE_SESSION = re.compile(r"session[\s_-]*0*([12])", re.IGNORECASE)

# Siemens data-stream control codes to exclude when counting waveform samples.
_PMU_CONTROL_CODES = {"5000", "5002", "5003", "6000", "6002", "6003"}


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------
@dataclass
class InventoryRow:
    filepath: str
    filename: str
    subject_candidate: str
    session_candidate: str
    mapped_participant: str
    mapped_session: str
    cohort: str
    extension: str
    size_bytes: str
    modification_time: str
    md5: str


@dataclass
class MetadataRow:
    filepath: str
    filename: str
    extension: str
    parse_status: str
    sampling_frequency: str = NA
    n_channels: str = NA
    n_samples: str = NA
    start_timestamp: str = NA
    log_stop_mdh_time: str = NA
    log_start_mpcu_time: str = NA
    log_stop_mpcu_time: str = NA
    trigger_info: str = NA
    acquisition_markers: str = NA
    physiological_rate_freq_per: str = NA
    logversion: str = NA
    header_tokens: str = NA
    metadata_source_files: str = NA
    bids_match_status: str = "unmatched"
    bids_match_path: str = NA
    n_candidate_runs: str = NA
    candidate_runs: str = NA


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
        force=True,
    )


def _md5(path: Path) -> str:
    h = hashlib.md5()
    try:
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                h.update(chunk)
    except OSError as exc:
        LOGGER.warning("md5 failed for %s: %s", path, exc)
        return NA
    return h.hexdigest()


def _write_tsv(path: Path, rows, fieldnames) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(fieldnames), delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _dataclass_dict(obj) -> dict:
    return {f.name: getattr(obj, f.name) for f in fields(obj)}


# ---------------------------------------------------------------------------
# Existing-metadata loading (read-only). Used ONLY to resolve IDs that already
# exist in the project; never to invent values.
# ---------------------------------------------------------------------------
@dataclass
class ProjectMetadata:
    canonical_to_participant: dict = field(default_factory=dict)
    folder_to_participant: dict = field(default_factory=dict)
    # keyed by source_subject_folder -> (canonical_subject, session_label, cohort)
    folder_to_session: dict = field(default_factory=dict)


def load_project_metadata(metadata_root: Path) -> ProjectMetadata:
    meta = ProjectMetadata()

    part_csv = metadata_root / "participant_mapping.csv"
    if part_csv.is_file():
        with part_csv.open(newline="", encoding="utf-8", errors="replace") as fh:
            for row in csv.DictReader(fh):
                pid = (row.get("participant_id") or "").strip()
                canon = (row.get("canonical_subject_id") or "").strip()
                if pid and canon:
                    meta.canonical_to_participant[canon] = pid
                folders = (row.get("source_subject_folder") or "").split("|")
                for folder in folders:
                    folder = folder.strip()
                    if folder and pid:
                        meta.folder_to_participant[folder] = pid
    else:
        LOGGER.warning("participant_mapping.csv not found under %s", metadata_root)

    sess_csv = metadata_root / "session_mapping.csv"
    if sess_csv.is_file():
        with sess_csv.open(newline="", encoding="utf-8", errors="replace") as fh:
            for row in csv.DictReader(fh):
                folder = (row.get("source_subject_folder") or "").strip()
                if not folder:
                    continue
                canon = (row.get("canonical_subject") or row.get("canonical_subject_id") or "").strip()
                sess = (row.get("session_label") or "").strip()
                cohort = (row.get("cohort") or "").strip()
                if folder not in meta.folder_to_session and (canon or sess):
                    meta.folder_to_session[folder] = (canon, sess, cohort)
    else:
        LOGGER.warning("session_mapping.csv not found under %s", metadata_root)

    LOGGER.info(
        "Loaded metadata: %d canonical->participant, %d folder->participant, %d folder->session",
        len(meta.canonical_to_participant),
        len(meta.folder_to_participant),
        len(meta.folder_to_session),
    )
    return meta


# ---------------------------------------------------------------------------
# Section A: discovery
# ---------------------------------------------------------------------------
def discover_physio_files(raw_root: Path) -> list[Path]:
    # Full recursive walk with no pruning: discovery must never miss a real
    # physiology file. It only tests filename extensions (no file reads), so it
    # stays fast even across DICOM trees.
    found: list[Path] = []
    wanted = {e.lower() for e in PHYSIO_EXTENSIONS}
    for dirpath, _dirs, filenames in os.walk(raw_root):
        for name in filenames:
            ext = os.path.splitext(name)[1].lower()
            if ext in wanted:
                found.append(Path(dirpath) / name)
    found.sort()
    LOGGER.info("Discovered %d physiology files under %s", len(found), raw_root)
    return found


def _subject_candidate(path: Path) -> str:
    for part in reversed(path.parts):
        m = _RE_SUBJECT.search(part)
        if m:
            return m.group(1).upper()
    return NA


def _session_candidate(path: Path) -> str:
    for part in reversed(path.parts):
        m = _RE_SESSION.search(part)
        if m:
            return f"ses-{int(m.group(1)):02d}"
    return NA


def _match_session_folder(path: Path, meta: ProjectMetadata):
    """Return (participant, session_label, cohort, source_folder) using existing
    metadata only, by locating a known raw session folder in the file's path."""
    parts = set(path.parts)
    for folder, (canon, sess, cohort) in meta.folder_to_session.items():
        if folder in parts:
            participant = meta.canonical_to_participant.get(canon) or meta.folder_to_participant.get(folder) or NA
            return participant, (sess or NA), (cohort or NA), folder
    # Fall back to participant-only resolution from folder name.
    for folder, pid in meta.folder_to_participant.items():
        if folder in parts:
            return pid, NA, NA, folder
    return NA, NA, NA, NA


def build_inventory(files: list[Path], meta: ProjectMetadata) -> list[InventoryRow]:
    rows: list[InventoryRow] = []
    for path in files:
        try:
            stat = path.stat()
            size = str(stat.st_size)
            mtime = datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat()
        except OSError as exc:
            LOGGER.warning("stat failed for %s: %s", path, exc)
            size, mtime = NA, NA
        participant, sess, cohort, _folder = _match_session_folder(path, meta)
        rows.append(
            InventoryRow(
                filepath=str(path),
                filename=path.name,
                subject_candidate=_subject_candidate(path),
                session_candidate=_session_candidate(path),
                mapped_participant=participant,
                mapped_session=sess,
                cohort=cohort,
                extension=path.suffix.lower(),
                size_bytes=size,
                modification_time=mtime,
                md5=_md5(path),
            )
        )
    return rows


# ---------------------------------------------------------------------------
# Section B: safe header parsing
# ---------------------------------------------------------------------------
def _looks_binary(raw: bytes) -> bool:
    head = raw[:256]
    if b"\x00" in head:
        return True
    # Fraction of non-text bytes.
    text_bytes = sum(1 for b in head if 9 <= b <= 13 or 32 <= b <= 126)
    return len(head) > 0 and (text_bytes / len(head)) < 0.7


def _count_waveform_samples(text: str) -> str:
    """Count integer waveform samples in the Siemens data stream.

    The data region lies between the first ``6002`` (end of the leading info
    block) and the first following ``5003`` (end of data). Control codes are
    excluded. Returns NA if the structure is not recognisable.
    """
    tokens = text.split()
    try:
        start = tokens.index("6002")
    except ValueError:
        return NA
    end = None
    for i in range(start + 1, len(tokens)):
        if tokens[i] == "5003":
            end = i
            break
    if end is None:
        return NA
    n = 0
    for tok in tokens[start + 1 : end]:
        if tok.isdigit() and tok not in _PMU_CONTROL_CODES:
            n += 1
    return str(n) if n > 0 else NA


def _inline_markers(text: str) -> str:
    tokens = text.split()
    c5000 = sum(1 for t in tokens if t == "5000")
    c6000 = sum(1 for t in tokens if t == "6000")
    if c5000 == 0 and c6000 == 0:
        return NA
    return f"trigger_on(5000)={c5000};marker(6000)={c6000}"


def _header_tokens(text: str) -> str:
    tokens = text.split()
    try:
        first_5002 = tokens.index("5002")
    except ValueError:
        return NA
    head = tokens[:first_5002]
    return " ".join(head) if head else NA


def parse_physio_header(path: Path) -> MetadataRow:
    row = MetadataRow(
        filepath=str(path),
        filename=path.name,
        extension=path.suffix.lower(),
        parse_status="unreadable",
    )
    try:
        raw = path.read_bytes()
    except OSError as exc:
        LOGGER.warning("read failed for %s: %s", path, exc)
        return row

    if not raw:
        row.parse_status = "empty"
        return row

    # Binary .pmu (VSN) format: extract only what is literally present.
    if _looks_binary(raw):
        row.parse_status = "binary_pmu"
        head_text = raw[:512].decode("latin-1", errors="replace")
        m = _RE_VSN.search(head_text)
        if m:
            row.logversion = f"VSN {m.group(1)} {m.group(2)}"
        return row

    text = raw.decode("latin-1", errors="replace")
    row.parse_status = "parsed_text"

    m = _RE_LOGVERSION.search(text)
    if m:
        row.logversion = m.group(0)

    row.header_tokens = _header_tokens(text)
    row.n_samples = _count_waveform_samples(text)
    row.acquisition_markers = _inline_markers(text)

    # Sampling frequency: ONLY accept an explicitly labelled ADC sampling rate.
    # Siemens ASCII PMU logs do not contain one, so this is normally NA. We do
    # NOT derive it from tick clocks or scanner-model defaults.
    m = _RE_SAMPLING_FREQ.search(text)
    row.sampling_frequency = m.group(1) if m else NA

    # Physiological rate for this modality from the "<CHAN> Freq Per:" footer.
    # Reported for transparency only; this is NOT the sampling frequency.
    modality = path.suffix.lower().lstrip(".").upper()
    if modality.startswith("EXT") and modality != "EXT2":
        modality = "EXT"
    for chan, freq, per in _RE_FREQ_PER.findall(text):
        if chan.upper() == modality and freq not in ("0", "-0"):
            row.physiological_rate_freq_per = f"freq={freq};per={per}"
            break

    # Timestamps: literal tick values present in the footer.
    for regex, attr in (
        (_RE_LOGSTART_MDH, "start_timestamp"),
        (_RE_LOGSTOP_MDH, "log_stop_mdh_time"),
        (_RE_LOGSTART_MPCU, "log_start_mpcu_time"),
        (_RE_LOGSTOP_MPCU, "log_stop_mpcu_time"),
    ):
        m = regex.search(text)
        if m:
            setattr(row, attr, m.group(1))

    # Trigger information: authoritative footer count (NrTrig).
    m = _RE_NRTRIG.search(text)
    if m:
        row.trigger_info = f"NrTrig={m.group(1)};NrMP={m.group(2)};NrArr={m.group(3)};AcqWin={m.group(4)}"

    # n_channels is not reliably encoded; do not guess.
    row.n_channels = NA
    return row


# ---------------------------------------------------------------------------
# Section C: nearby MATLAB / text metadata sources
# ---------------------------------------------------------------------------
def _session_root_for(path: Path, meta: ProjectMetadata, raw_root: Path) -> Path:
    """Best-effort raw session directory for nearby search (read-only)."""
    parts = path.parts
    known = set(meta.folder_to_session) | set(meta.folder_to_participant)
    for i, part in enumerate(parts):
        if part in known:
            return Path(*parts[: i + 1])
    # Fallback: parent of the file's parent (…/<session>/<peripheral>/<file>).
    parent = path.parent
    if parent.parent != raw_root and parent.parent != parent:
        return parent.parent
    return parent


def _scan_session_metadata_sources(session_root: Path) -> list[tuple[str, list[str]]]:
    """Return [(relative_path, [matched_strings]), ...] for candidate files."""
    results: list[tuple[str, list[str]]] = []
    wanted = {e.lower() for e in METADATA_SEARCH_EXTENSIONS}
    scanned = 0
    dirs_seen = 0
    for dirpath, dirs, filenames in os.walk(session_root):
        # Prune DICOM series trees: associated MATLAB/text metadata never lives
        # inside them, and descending wastes time on tens of thousands of .IMA.
        dirs[:] = [d for d in dirs if not _is_dicom_dump_dir(d)]
        dirs_seen += 1
        if dirs_seen > MAX_NEARBY_DIRS_PER_SESSION:
            return results
        for name in filenames:
            if scanned >= MAX_NEARBY_FILES_PER_SESSION:
                return results
            ext = os.path.splitext(name)[1].lower()
            if ext not in wanted:
                continue
            scanned += 1
            fpath = Path(dirpath) / name
            try:
                with fpath.open("rb") as fh:
                    blob = fh.read(MAX_NEARBY_BYTES_READ)
            except OSError:
                continue
            text = blob.decode("latin-1", errors="replace")
            matched = [s for s in METADATA_SEARCH_STRINGS if s in text]
            if matched:
                try:
                    rel = str(fpath.relative_to(session_root))
                except ValueError:
                    rel = str(fpath)
                results.append((rel, matched))
    return results


def attach_metadata_sources(
    rows: list[MetadataRow], meta: ProjectMetadata, raw_root: Path
) -> None:
    """Populate metadata_source_files, caching the scan per session root."""
    cache: dict[str, list[tuple[str, list[str]]]] = {}
    for row in rows:
        path = Path(row.filepath)
        session_root = _session_root_for(path, meta, raw_root)
        key = str(session_root)
        if key not in cache:
            LOGGER.debug("Scanning nearby metadata under %s", session_root)
            cache[key] = _scan_session_metadata_sources(session_root)
        sources = cache[key]
        if not sources:
            row.metadata_source_files = NA
            continue
        rendered = [f"{rel} [{','.join(keys)}]" for rel, keys in sources[:MAX_REPORTED_METADATA_SOURCES]]
        if len(sources) > MAX_REPORTED_METADATA_SOURCES:
            rendered.append(f"(+{len(sources) - MAX_REPORTED_METADATA_SOURCES} more)")
        row.metadata_source_files = " ; ".join(rendered)


# ---------------------------------------------------------------------------
# Section D: BIDS run association (report only; no mappings created)
# ---------------------------------------------------------------------------
_RE_BOLD_RUN = re.compile(r"task-([A-Za-z0-9]+)_(?:.*?_)?run-(\d+)")


def _bids_func_runs(func_dir: Path) -> list[str]:
    if not func_dir.is_dir():
        return []
    runs: set[str] = set()
    loose_bold = 0
    for entry in func_dir.iterdir():
        name = entry.name
        if not name.endswith("_bold.nii.gz"):
            continue
        m = _RE_BOLD_RUN.search(name)
        if m:
            runs.add(f"task-{m.group(1)}_run-{m.group(2)}")
        else:
            loose_bold += 1
    ordered = sorted(runs)
    ordered.extend(f"bold_no_run_entity_{i+1}" for i in range(loose_bold))
    return ordered


def associate_with_bids(
    rows: list[MetadataRow], inventory: list[InventoryRow], bids_root: Path
) -> None:
    inv_by_path = {r.filepath: r for r in inventory}
    for row in rows:
        inv = inv_by_path.get(row.filepath)
        participant = inv.mapped_participant if inv else NA
        session = inv.mapped_session if inv else NA

        if participant == NA or not participant:
            row.bids_match_status = "unmatched"
            row.bids_match_path = NA
            row.n_candidate_runs = NA
            row.candidate_runs = NA
            continue

        if session and session != NA:
            func_dir = bids_root / participant / session / "func"
            runs = _bids_func_runs(func_dir)
            row.bids_match_path = str(bids_root / participant / session)
            row.n_candidate_runs = str(len(runs))
            row.candidate_runs = ";".join(runs) if runs else NA
            if not runs:
                row.bids_match_status = "unmatched"
            elif len(runs) == 1:
                # Session resolved from existing metadata and exactly one func
                # run exists -> unambiguous target.
                row.bids_match_status = "confirmed"
            else:
                # One session-spanning physio recording vs many runs: cannot
                # pin to a single run without guessing.
                row.bids_match_status = "ambiguous"
            continue

        # Subject resolved but session not resolved from metadata.
        subj_dir = bids_root / participant
        has_func = subj_dir.is_dir() and any(subj_dir.glob("ses-*/func/*_bold.nii.gz"))
        if has_func:
            row.bids_match_status = "possible"
            row.bids_match_path = str(subj_dir)
            row.n_candidate_runs = NA
            row.candidate_runs = NA
        else:
            row.bids_match_status = "unmatched"
            row.bids_match_path = NA
            row.n_candidate_runs = NA
            row.candidate_runs = NA


# ---------------------------------------------------------------------------
# Section E: summary + conversion candidates
# ---------------------------------------------------------------------------
def write_summary(
    summary_path: Path,
    inventory: list[InventoryRow],
    metadata: list[MetadataRow],
    n_candidates: int,
    raw_root: Path,
    bids_root: Path,
    metadata_root: Path,
) -> None:
    total = len(metadata)

    def count_ext(ext: str) -> int:
        return sum(1 for r in inventory if r.extension == ext)

    freq_found = sum(1 for r in metadata if r.sampling_frequency != NA)
    start_found = sum(1 for r in metadata if r.start_timestamp != NA)
    status_counts = {"confirmed": 0, "possible": 0, "ambiguous": 0, "unmatched": 0}
    for r in metadata:
        status_counts[r.bids_match_status] = status_counts.get(r.bids_match_status, 0) + 1
    parse_counts: dict[str, int] = {}
    for r in metadata:
        parse_counts[r.parse_status] = parse_counts.get(r.parse_status, 0) + 1

    lines = []
    lines.append("# Physiology audit summary")
    lines.append("")
    lines.append(f"Generated: `{_now_iso()}`")
    lines.append("")
    lines.append(
        "Read-only audit of Siemens physiological logs. **No files under "
        "`raw_original/` were modified, copied, or converted.** Missing values "
        "are reported as `NA` and are never inferred."
    )
    lines.append("")
    lines.append("## Inputs")
    lines.append("")
    lines.append(f"- Raw root: `{raw_root}`")
    lines.append(f"- Existing metadata: `{metadata_root}`")
    lines.append(f"- BIDS root: `{bids_root}`")
    lines.append("")
    lines.append("## File counts")
    lines.append("")
    lines.append(f"- Total physiology files: **{total}**")
    lines.append(f"- ECG (`.ecg`): **{count_ext('.ecg')}**")
    lines.append(f"- RESP (`.resp`): **{count_ext('.resp')}**")
    lines.append(f"- PULS (`.puls`): **{count_ext('.puls')}**")
    lines.append(f"- PMU (`.pmu`): **{count_ext('.pmu')}**")
    lines.append(f"- EXT (`.ext`): **{count_ext('.ext')}**")
    lines.append(f"- EXT1 (`.ext1`): **{count_ext('.ext1')}**")
    lines.append(f"- EXT2 (`.ext2`): **{count_ext('.ext2')}**")
    lines.append("")
    lines.append("## Parse status")
    lines.append("")
    for status in sorted(parse_counts):
        lines.append(f"- `{status}`: **{parse_counts[status]}**")
    lines.append("")
    lines.append("## Metadata presence")
    lines.append("")
    lines.append(f"- Sampling frequency found: **{freq_found}**")
    lines.append(f"- Sampling frequency missing (`NA`): **{total - freq_found}**")
    lines.append(f"- Start time found: **{start_found}**")
    lines.append(f"- Start time missing (`NA`): **{total - start_found}**")
    lines.append("")
    lines.append("## BIDS run association")
    lines.append("")
    lines.append(f"- `confirmed`: **{status_counts['confirmed']}**")
    lines.append(f"- `possible`: **{status_counts['possible']}**")
    lines.append(f"- `ambiguous`: **{status_counts['ambiguous']}**")
    lines.append(f"- `unmatched`: **{status_counts['unmatched']}**")
    lines.append("")
    lines.append("## Conversion candidates")
    lines.append("")
    lines.append(
        f"- Files with sampling frequency present **and** `confirmed` BIDS run: "
        f"**{n_candidates}**"
    )
    lines.append(
        "- Listed in `physiology_conversion_candidates.tsv`. This audit does "
        "**not** convert them; a validated converter must do that separately."
    )
    lines.append("")
    lines.append("## Notes")
    lines.append("")
    lines.append(
        "- Siemens ASCII PMU logs (`.ecg/.puls/.resp/.ext/.ext2`) rarely store an "
        "explicit sampling frequency; when absent it is reported as `NA` rather "
        "than assumed from model defaults."
    )
    lines.append(
        "- A single physiological recording typically spans an entire session "
        "(many fMRI runs). Sessions with more than one func run are therefore "
        "reported as `ambiguous`: run-level assignment requires a real converter "
        "using trigger/timing alignment, not a guess."
    )
    lines.append(
        "- `start_timestamp` is the literal `LogStartMDHTime` tick value from the "
        "footer (see also the MPCU columns in the metadata report)."
    )
    lines.append("")
    lines.append("## Outputs")
    lines.append("")
    lines.append("- `reports/physiology_audit/physiology_inventory.tsv`")
    lines.append("- `reports/physiology_audit/physiology_metadata_report.tsv`")
    lines.append("- `reports/physiology_audit/physiology_conversion_candidates.tsv`")
    lines.append("- `reports/physiology_audit/physiology_summary.md`")
    lines.append("")

    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
def _assert_output_safe(out_dir: Path, raw_root: Path) -> None:
    out_res = out_dir.resolve()
    raw_res = raw_root.resolve()
    if out_res == raw_res or raw_res in out_res.parents:
        raise SystemExit(
            f"Refusing to run: output directory {out_res} is inside the raw "
            f"archive {raw_res}. The audit must never write into raw_original."
        )


def main() -> None:
    ap = argparse.ArgumentParser(description="Non-destructive Siemens physiology audit.")
    ap.add_argument("--raw-root", type=Path, default=DEFAULT_RAW_ROOT)
    ap.add_argument("--metadata-root", type=Path, default=DEFAULT_METADATA)
    ap.add_argument("--bids-root", type=Path, default=DEFAULT_BIDS)
    ap.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    _configure_logging(args.verbose)
    _assert_output_safe(args.out_dir, args.raw_root)

    if not args.raw_root.is_dir():
        raise SystemExit(f"Raw root not found: {args.raw_root}")

    LOGGER.info("Physiology audit starting (read-only).")
    meta = load_project_metadata(args.metadata_root)

    files = discover_physio_files(args.raw_root)
    if not files:
        LOGGER.warning("No physiology files found; writing empty reports.")

    # A: inventory + checksums
    LOGGER.info("Building inventory + checksums for %d files ...", len(files))
    inventory = build_inventory(files, meta)

    # B: header parsing
    LOGGER.info("Parsing headers ...")
    metadata = [parse_physio_header(p) for p in files]

    # C: nearby metadata sources
    LOGGER.info("Scanning nearby MATLAB/text metadata sources ...")
    attach_metadata_sources(metadata, meta, args.raw_root)

    # D: BIDS association
    LOGGER.info("Associating with BIDS (report only) ...")
    associate_with_bids(metadata, inventory, args.bids_root)

    # Write A + B/C/D reports
    inv_fields = [f.name for f in fields(InventoryRow)]
    meta_fields = [f.name for f in fields(MetadataRow)]
    _write_tsv(
        args.out_dir / "physiology_inventory.tsv",
        [_dataclass_dict(r) for r in inventory],
        inv_fields,
    )
    _write_tsv(
        args.out_dir / "physiology_metadata_report.tsv",
        [_dataclass_dict(r) for r in metadata],
        meta_fields,
    )

    # Conversion candidates: sampling frequency present AND confirmed mapping.
    candidates = [
        r for r in metadata
        if r.sampling_frequency != NA and r.bids_match_status == "confirmed"
    ]
    _write_tsv(
        args.out_dir / "physiology_conversion_candidates.tsv",
        [_dataclass_dict(r) for r in candidates],
        meta_fields,
    )

    # E: summary
    write_summary(
        args.out_dir / "physiology_summary.md",
        inventory,
        metadata,
        len(candidates),
        args.raw_root,
        args.bids_root,
        args.metadata_root,
    )

    LOGGER.info("Done. Reports written to %s", args.out_dir)
    LOGGER.info(
        "Totals: files=%d, freq_found=%d, confirmed=%d, candidates=%d",
        len(metadata),
        sum(1 for r in metadata if r.sampling_frequency != NA),
        sum(1 for r in metadata if r.bids_match_status == "confirmed"),
        len(candidates),
    )


if __name__ == "__main__":
    main()
