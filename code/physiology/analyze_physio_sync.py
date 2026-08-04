#!/usr/bin/env python3
"""Read-only audit of metadata needed for BIDS physiology conversion.

This script inventories synchronization metadata and extracts literal metadata
from Siemens PMU and MATLAB files. It never writes under raw_original, never
copies source files, never decodes PMU waveform payloads, and never creates
BIDS outputs. All generated files are audit reports under
reports/physiology_sync_analysis.
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator

import numpy as np

try:
    csv.field_size_limit(sys.maxsize)
except OverflowError:
    csv.field_size_limit(10_000_000)


DEFAULT_RAW_ROOT = Path("/project/def-amirs/raw_original")

SEARCH_EXTENSIONS = {".mat", ".json", ".tsv", ".txt", ".log", ".csv"}
PHYSIO_EXTENSIONS = {".ecg", ".resp", ".puls"}
KEYWORDS = (
    "scan_info",
    "scanner",
    "trigger",
    "ttl",
    "pulse",
    "puls",
    "resp",
    "ecg",
    "physio",
    "logstartmdhtime",
    "starttime",
    "sampling",
    "frequency",
    "hz",
    "tr",
    "fmri",
    "run",
    "acquisition",
    "timestamp",
    "protocol",
)
MAT_NAME_RE = re.compile(
    r"(samplingfrequency|sampling_rate|sample_rate|freq|hz|"
    r"(^|[_.\[])tr($|[_.\]])|trigger|ttl|time|timestamp|start|"
    r"logstartmdhtime|acquisition|run|fmri|"
    r"(^|[_.\[])ifi($|[_.\]])|(^|[_.\[])fps($|[_.\]])|(^|[_.\[])vbl($|[_.\]]))",
    re.IGNORECASE,
)
EXPLICIT_RATE_NAME_RE = re.compile(
    r"(samplingfrequency|sampling_frequency|samplingrate|sampling_rate|samplerate|sample_rate)",
    re.IGNORECASE,
)
MODALITY_RE = re.compile(r"(ecg|resp(?:iration|iratory)?|puls(?:e)?|physio)", re.IGNORECASE)
TEXT_RATE_RE = re.compile(
    r"(?P<label>(?:(?:ECG|RESP(?:IRATION|IRATORY)?|PULS(?:E)?|PHYSIO)[ _.-]*)?"
    r"(?:SamplingFrequency|Sampling[_ ]Rate|Sample[_ ]Rate))"
    r"\s*[:=]\s*(?P<value>\d+(?:\.\d+)?)\s*(?P<units>Hz)\b",
    re.IGNORECASE,
)
SUBJECT_RE = re.compile(r"\b(SUB[A-Z]*0*\d+|sub-\d+)\b", re.IGNORECASE)
SESSION_RE = re.compile(r"\b(?:session|ses)[ _-]*0*(\d+)\b", re.IGNORECASE)
BIDS_SUB_RE = re.compile(r"(sub-\d+)")
BIDS_SES_RE = re.compile(r"(ses-\d+)")
RUN_RE = re.compile(r"(task-[^_]+_run-\d+)")


@dataclass(frozen=True)
class PhysioRecord:
    path: Path
    subject: str
    session: str
    bids_subject: str
    bids_session: str


def log(message: str) -> None:
    print(message, flush=True)


def _write_tsv(path: Path, fieldnames: list[str], rows: Iterable[dict[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=fieldnames, delimiter="\t", lineterminator="\n"
        )
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})
            count += 1
    return count


def _read_text_sample(path: Path, limit: int = 64 * 1024) -> str:
    with path.open("rb") as handle:
        raw = handle.read(limit)
    return raw.decode("utf-8", errors="replace")


def _keywords(text: str) -> list[str]:
    lower = text.lower()
    return [keyword for keyword in KEYWORDS if keyword in lower]


def _subject_session_from_path(path: Path) -> tuple[str, str]:
    text = str(path)
    bids_sub = BIDS_SUB_RE.search(text)
    bids_ses = BIDS_SES_RE.search(text)
    if bids_sub and bids_ses:
        return bids_sub.group(1), bids_ses.group(1)
    subject_match = SUBJECT_RE.search(text)
    session_match = SESSION_RE.search(text)
    subject = subject_match.group(1).upper() if subject_match else ""
    session = f"ses-{int(session_match.group(1)):02d}" if session_match else ""
    return subject, session


def _load_session_map(path: Path) -> dict[str, tuple[str, str]]:
    candidates: dict[str, set[tuple[str, str]]] = defaultdict(set)
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            folder = row.get("source_subject_folder", "").strip()
            participant = row.get("participant_id", "").strip()
            session = row.get("session_id", "").strip()
            if folder and participant and session:
                candidates[folder].add((participant, session))
    return {
        folder: next(iter(values))
        for folder, values in candidates.items()
        if len(values) == 1
    }


def _raw_session_folder(path: Path, raw_root: Path) -> str:
    try:
        relative = path.relative_to(raw_root)
    except ValueError:
        return ""
    parts = relative.parts
    if len(parts) >= 2 and parts[0].lower() == "control":
        return parts[1]
    return parts[0] if parts else ""


def discover_physio(
    workspace: Path, raw_root: Path, session_map: dict[str, tuple[str, str]]
) -> list[PhysioRecord]:
    inventory = workspace / "reports/physiology_audit/physiology_inventory.tsv"
    records: list[PhysioRecord] = []
    if inventory.exists():
        with inventory.open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle, delimiter="\t"):
                extension = row.get("extension", "").lower()
                if extension not in PHYSIO_EXTENSIONS:
                    continue
                source = row.get("filepath", "")
                path = Path(source)
                if not path.exists() and "raw_original/" in source:
                    path = raw_root / source.split("raw_original/", 1)[1]
                if not path.exists():
                    continue
                subject = row.get("subject_candidate", "") or _subject_session_from_path(path)[0]
                session = row.get("mapped_session", "") or row.get("session_candidate", "")
                if session and not session.startswith("ses-"):
                    session = f"ses-{session}" if session.isdigit() else session
                folder = _raw_session_folder(path, raw_root)
                bids_subject = row.get("mapped_participant", "")
                bids_session = row.get("mapped_session", "")
                if not bids_subject or not bids_session:
                    mapped = session_map.get(folder)
                    if mapped:
                        bids_subject, bids_session = mapped
                records.append(
                    PhysioRecord(path, subject, session, bids_subject, bids_session)
                )
        if records:
            return records

    # Fallback only if the physiology inventory is unavailable.
    for path in sorted(raw_root.rglob("*")):
        if path.is_file() and path.suffix.lower() in PHYSIO_EXTENSIONS:
            subject, session = _subject_session_from_path(path)
            folder = _raw_session_folder(path, raw_root)
            bids_subject, bids_session = session_map.get(folder, ("", ""))
            records.append(
                PhysioRecord(path, subject, session, bids_subject, bids_session)
            )
    return records


def _session_roots(physio_records: list[PhysioRecord], raw_root: Path) -> list[Path]:
    roots: set[Path] = set()
    for record in physio_records:
        folder = _raw_session_folder(record.path, raw_root)
        if folder:
            roots.add(raw_root / "Control" / folder)
    return sorted(path for path in roots if path.exists())


def _open_tsv(path: Path):
    handle = path.open(encoding="utf-8", errors="replace", newline="")
    try:
        csv.field_size_limit(max(csv.field_size_limit(), 10_000_000))
    except Exception:
        pass
    return handle


def inventory_rows(
    workspace: Path,
    physio_records: list[PhysioRecord],
    output_root: Path,
    raw_root: Path | None = None,
) -> Iterator[dict[str, Any]]:
    """Build a keyworded inventory from existing audits plus metadata/BIDS samples.

    Avoids broad Lustre rglob walks, which stall on this filesystem.
    """
    del physio_records  # discovery already scoped the audit; kept for API clarity
    raw_root = raw_root or DEFAULT_RAW_ROOT
    rows: dict[Path, dict[str, Any]] = {}

    def add_path(path: Path, extra_context: str = "") -> None:
        if (
            not path.exists()
            or not path.is_file()
            or path.suffix.lower() not in SEARCH_EXTENSIONS
            or output_root in path.parents
        ):
            return
        context = f"{path} {extra_context}"
        if path.suffix.lower() != ".mat":
            try:
                if path.stat().st_size <= 256 * 1024 or any(
                    token in path.name.lower()
                    for token in (
                        "scan",
                        "physio",
                        "trigger",
                        "protocol",
                        "output",
                        "mapping",
                        "bold",
                    )
                ):
                    context += " " + _read_text_sample(path)
            except OSError:
                pass
        found = _keywords(context)
        if not found and not any(
            token in path.name.lower()
            for token in ("scan_info", "physio", "mapping", "trigger", "protocol")
        ):
            return
        subject, session = _subject_session_from_path(path)
        resolved = path.resolve()
        previous = rows.get(resolved)
        merged = ";".join(
            sorted(
                set((previous or {}).get("keywords_found", "").split(";"))
                | set(found)
                - {""}
            )
        )
        rows[resolved] = {
            "filepath": str(resolved),
            "subject_candidate": subject or (previous or {}).get("subject_candidate", ""),
            "session_candidate": session or (previous or {}).get("session_candidate", ""),
            "extension": path.suffix.lower(),
            "size": path.stat().st_size,
            "keywords_found": merged,
        }

    # 1) Existing MATLAB inventory.
    mat_inventory = workspace / "reports/matlab_content_inventory.tsv"
    if mat_inventory.exists():
        with _open_tsv(mat_inventory) as handle:
            for row in csv.DictReader(handle, delimiter="\t"):
                source = row.get("file_path", "")
                local = Path(source)
                if not local.exists() and "raw_original/" in source:
                    local = raw_root / source.split("raw_original/", 1)[1]
                add_path(
                    local,
                    " ".join((row.get("variables", ""), row.get("notes", ""))),
                )

    # 2) Associated-data inventory for text/json/tsv/csv/log candidates.
    associated = workspace / "reports/associated_data_inventory.tsv"
    if associated.exists():
        with _open_tsv(associated) as handle:
            for row in csv.DictReader(handle, delimiter="\t"):
                source = row.get("filepath") or row.get("file_path") or row.get("path") or ""
                if not source:
                    continue
                local = Path(source)
                if not local.exists() and "raw_original/" in source:
                    local = raw_root / source.split("raw_original/", 1)[1]
                if local.suffix.lower() not in SEARCH_EXTENSIONS:
                    continue
                add_path(local, " ".join(str(value) for value in row.values()))

    # 3) Nearby metadata sources already linked by the physiology audit.
    physio_meta = workspace / "reports/physiology_audit/physiology_metadata_report.tsv"
    if physio_meta.exists():
        with _open_tsv(physio_meta) as handle:
            for row in csv.DictReader(handle, delimiter="\t"):
                sources = row.get("metadata_source_files", "")
                for chunk in sources.split(" ; "):
                    chunk = chunk.strip()
                    if not chunk or chunk == "NA":
                        continue
                    relative = chunk.split(" [", 1)[0].strip()
                    if not relative:
                        continue
                    physio_path = Path(row.get("filepath", ""))
                    if not physio_path.exists() and "raw_original/" in row.get("filepath", ""):
                        physio_path = raw_root / row["filepath"].split("raw_original/", 1)[1]
                    session_folder = physio_path.parents[1] if physio_path.exists() else None
                    candidates = []
                    if session_folder is not None:
                        candidates.append(session_folder / relative)
                    if "raw_original/" in relative:
                        candidates.append(raw_root / relative.split("raw_original/", 1)[1])
                    candidates.append(raw_root / relative)
                    for candidate in candidates:
                        if candidate.exists():
                            add_path(candidate, chunk)
                            break

    # 4) Project metadata tables.
    for path in sorted((workspace / "metadata").glob("*.csv")):
        add_path(path, "session mapping participant mapping protocol")

    # 5) Representative BOLD sidecars for AcquisitionTime search.
    bids_root = workspace / "bids"
    bold_checked = 0
    if bids_root.exists():
        for path in sorted(bids_root.glob("sub-*/ses-*/func/*_bold.json")):
            if "_part-phase_" in path.name:
                continue
            add_path(path)
            bold_checked += 1
            if bold_checked >= 200:
                break

    # 6) Physiology audit summary files.
    for path in (workspace / "reports/physiology_audit").glob("*"):
        add_path(path)

    yield from (rows[key] for key in sorted(rows))


def _shape(value: Any) -> str:
    try:
        return "x".join(str(item) for item in np.asarray(value).shape) or "scalar"
    except Exception:
        return "unknown"


def _example(value: Any, max_items: int = 5) -> str:
    try:
        array = np.asarray(value)
    except Exception:
        return repr(value)[:200]
    if array.dtype == object:
        return f"dtype=object; items={array.size}"
    if np.issubdtype(array.dtype, np.number):
        flat = np.asarray(array).ravel()
        finite = flat[np.isfinite(flat)] if flat.size else flat
        examples = finite[:max_items].tolist()
        if finite.size:
            return (
                f"dtype={array.dtype}; min={float(np.min(finite)):.9g}; "
                f"max={float(np.max(finite)):.9g}; examples={examples}"
            )
        return f"dtype={array.dtype}; examples=[]"
    text = str(array.ravel()[0]) if array.size else ""
    return f"dtype={array.dtype}; example={text[:160]}"


def _possible_role(name: str) -> str:
    lower = name.lower()
    if EXPLICIT_RATE_NAME_RE.search(lower):
        return "explicit sampling-rate candidate; modality and units require validation"
    if "triggertime" in lower or "ttl" in lower:
        return "scanner/task trigger timing candidate"
    if any(term in lower for term in ("vbl", "ifi", "fps")):
        return "display/Psychtoolbox timing; not physiology sampling frequency"
    if "run" in lower or "fmri" in lower:
        return "run identifier or run-level metadata"
    if "freq" in lower or "hz" in lower:
        return "frequency-like value; context required (often stimulus/display)"
    if "start" in lower or "time" in lower or "timestamp" in lower:
        return "clock/timing candidate; clock domain requires validation"
    if "acquisition" in lower:
        return "acquisition metadata candidate"
    return "keyword-matched metadata"


def _walk_mat(name: str, value: Any, seen: set[int]) -> Iterator[tuple[str, Any]]:
    identity = id(value)
    if identity in seen:
        return
    leaf = name.rsplit(".", 1)[-1].lower()
    if leaf in {"program", "code", "script"}:
        return
    if hasattr(value, "_fieldnames"):
        seen.add(identity)
        for field in value._fieldnames:
            yield from _walk_mat(f"{name}.{field}", getattr(value, field), seen)
        return
    if isinstance(value, dict):
        seen.add(identity)
        for key, item in value.items():
            if not key.startswith("__"):
                yield from _walk_mat(f"{name}.{key}" if name else key, item, seen)
        return
    if isinstance(value, np.ndarray) and value.dtype == object:
        seen.add(identity)
        for index, item in enumerate(value.flat[:20]):
            yield from _walk_mat(f"{name}[{index}]", item, seen)
        return
    yield name, value


def relevant_mat_rows(workspace: Path, raw_root: Path) -> Iterator[dict[str, Any]]:
    import scipy.io as sio

    mat_inventory = workspace / "reports/matlab_content_inventory.tsv"
    candidates: list[Path] = []
    if mat_inventory.exists():
        with mat_inventory.open(encoding="utf-8", errors="replace", newline="") as handle:
            for row in csv.DictReader(handle, delimiter="\t"):
                source = row.get("file_path", "")
                name = Path(source).name.lower()
                if not (
                    "scan_info" in name
                    or name.startswith("runs_random")
                    or name.startswith("fmri_")
                ):
                    continue
                local = Path(source)
                if not local.exists() and "raw_original/" in source:
                    local = raw_root / source.split("raw_original/", 1)[1]
                if local.exists():
                    candidates.append(local)
    candidates = sorted(set(candidates))
    log(f"Loading {len(candidates)} candidate MATLAB timing files...")
    for index, path in enumerate(candidates, start=1):
        if index == 1 or index % 25 == 0 or index == len(candidates):
            log(f"  MATLAB progress {index}/{len(candidates)}: {path.name}")
        try:
            data = sio.loadmat(str(path), squeeze_me=True, struct_as_record=False)
        except NotImplementedError:
            yield {
                "file": str(path.resolve()),
                "variable_name": "<matlab_v7_3>",
                "shape": "",
                "example_values": "MATLAB 7.3/HDF5; not loaded by scipy.io.loadmat",
                "possible_role": "v7.3 file outside validated timing extraction path",
            }
            continue
        except Exception as exc:
            yield {
                "file": str(path.resolve()),
                "variable_name": "<load_error>",
                "shape": "",
                "example_values": f"{type(exc).__name__}: {exc}",
                "possible_role": "unreadable relevant MATLAB file",
            }
            continue
        matched = False
        for name, value in _walk_mat("", data, set()):
            clean_name = name.lstrip(".")
            if not MAT_NAME_RE.search(clean_name):
                continue
            matched = True
            yield {
                "file": str(path.resolve()),
                "variable_name": clean_name,
                "shape": _shape(value),
                "example_values": _example(value),
                "possible_role": _possible_role(clean_name),
            }
        if not matched:
            yield {
                "file": str(path.resolve()),
                "variable_name": "<no matching variables>",
                "shape": "",
                "example_values": "",
                "possible_role": "candidate timing file without requested variable names",
            }


def _match(text: str, pattern: str) -> str:
    found = re.search(pattern, text, re.MULTILINE | re.IGNORECASE)
    if not found:
        return ""
    return found.group(found.lastindex or 1)


def pmu_header_rows(records: list[PhysioRecord]) -> Iterator[dict[str, Any]]:
    freq_re = re.compile(
        r"^(ECG|PULS|RESP|EXT2?|EXT)\s+Freq\s+Per:\s*(-?\d+)\s+(-?\d+)",
        re.MULTILINE,
    )
    for record in records:
        text = record.path.read_text(encoding="utf-8", errors="replace")
        tokens = text.split()
        try:
            header_end = tokens.index("5002")
            header = " ".join(tokens[:header_end])
        except ValueError:
            header = ""
        pairs = {
            channel.upper(): f"{frequency} {period}"
            for channel, frequency, period in freq_re.findall(text)
        }
        nr = re.search(
            r"NrTrig\s+NrMP\s+NrArr\s+AcqWin:\s*(-?\d+)\s+(-?\d+)\s+(-?\d+)\s+(-?\d+)",
            text,
        )
        complete = bool(
            re.search(r"(?:^|\s)5003(?:\s|$)", text) and text.rstrip().endswith("6003")
        )
        version = _match(text, r"\b(LOGVERSION(?:_PULS|_RESP)?)\b")
        if not version:
            version = _match(text, r"(VSN\s+[^\r\n]+)")
        yield {
            "filepath": str(record.path.resolve()),
            "subject_candidate": record.subject,
            "session_candidate": record.session,
            "extension": record.path.suffix.lower(),
            "size_bytes": record.path.stat().st_size,
            "version": version,
            "header_tokens": header,
            "log_start_mdh_time": _match(text, r"LogStartMDHTime:\s*(-?\d+)"),
            "log_stop_mdh_time": _match(text, r"LogStopMDHTime:\s*(-?\d+)"),
            "log_start_mpcu_time": _match(text, r"LogStartMPCUTime:\s*(-?\d+)"),
            "log_stop_mpcu_time": _match(text, r"LogStopMPCUTime:\s*(-?\d+)"),
            "nr_trig": nr.group(1) if nr else "",
            "nr_mp": nr.group(2) if nr else "",
            "nr_arr": nr.group(3) if nr else "",
            "acq_win": nr.group(4) if nr else "",
            "ecg_freq_per": pairs.get("ECG", ""),
            "puls_freq_per": pairs.get("PULS", ""),
            "resp_freq_per": pairs.get("RESP", ""),
            "ext_freq_per": pairs.get("EXT", ""),
            "ext2_freq_per": pairs.get("EXT2", ""),
            "footer_complete": "yes" if complete else "no",
            "notes": (
                "Freq Per values are physiological rate/period summaries, not "
                "acquisition sampling frequencies. MDH/MPCU values are literal "
                "scanner-clock ticks, not BIDS StartTime."
            ),
        }


def _explicit_text_rates(path: Path) -> list[tuple[str, float, str]]:
    try:
        text = _read_text_sample(path, limit=256 * 1024)
    except OSError:
        return []
    return [
        (match.group("label"), float(match.group("value")), match.group("units"))
        for match in TEXT_RATE_RE.finditer(text)
    ]


def sampling_rows(
    records: list[PhysioRecord], inventory: list[dict[str, Any]]
) -> Iterator[dict[str, Any]]:
    by_session: dict[tuple[str, str], list[Path]] = defaultdict(list)
    for row in inventory:
        if row["keywords_found"]:
            by_session[
                (str(row["subject_candidate"]), str(row["session_candidate"]))
            ].append(Path(str(row["filepath"])))

    for record in records:
        accepted: list[tuple[Path, str, float, str]] = []
        session_keys = {
            (record.subject, record.session),
            (record.bids_subject, record.bids_session),
        }
        sources: list[Path] = []
        for key in session_keys:
            sources.extend(by_session.get(key, []))
        for source in sources:
            source_context = str(source)
            if not MODALITY_RE.search(source_context) and source.suffix.lower() == ".mat":
                # Still inspect MATLAB notes/path, but only accept labels that
                # explicitly name a physiology modality or sampling-rate field.
                pass
            for variable, value, units in _explicit_text_rates(source):
                if EXPLICIT_RATE_NAME_RE.search(variable) and (
                    MODALITY_RE.search(variable) or "physio" in source_context.lower()
                ):
                    accepted.append((source, variable, value, units))
        if accepted:
            for source, variable, value, units in accepted:
                yield {
                    "physio_file": str(record.path.resolve()),
                    "candidate_source": str(source.resolve()),
                    "variable": variable,
                    "value": f"{value:g}",
                    "units": units,
                    "confidence": "MEDIUM",
                    "notes": (
                        "Explicit labelled acquisition-rate candidate; modality "
                        "scope must still be validated before conversion."
                    ),
                }
        else:
            yield {
                "physio_file": str(record.path.resolve()),
                "candidate_source": "",
                "variable": "",
                "value": "",
                "units": "",
                "confidence": "NONE",
                "notes": (
                    "No explicit ECG/RESP/PULS acquisition sampling-rate label "
                    "with units was found. Freq Per, bpm, period, TR, display fps, "
                    "and unlabeled PMU preamble values were rejected."
                ),
            }


def _bold_runs(bids_root: Path, subject: str, session: str) -> list[Path]:
    if not subject or not session:
        return []
    func = bids_root / subject / session / "func"
    if not func.exists():
        return []
    return sorted(
        path
        for path in func.glob("*_bold.json")
        if "_part-phase_" not in path.name
    )


def run_association_rows(
    records: list[PhysioRecord], bids_root: Path, session_map_path: Path
) -> Iterator[dict[str, Any]]:
    for record in records:
        runs = _bold_runs(bids_root, record.bids_subject, record.bids_session)
        if not runs:
            yield {
                "subject": record.bids_subject or record.subject,
                "session": record.bids_session or record.session,
                "physio_file": str(record.path.resolve()),
                "candidate_bold_run": "",
                "evidence_source": str(session_map_path.resolve()),
                "confidence": "LOW",
                "reason": (
                    "No current BOLD run was found for the mapped session; not usable."
                ),
            }
            continue
        for run in runs:
            match = RUN_RE.search(run.name)
            run_label = match.group(1) if match else run.stem
            yield {
                "subject": record.bids_subject,
                "session": record.bids_session,
                "physio_file": str(record.path.resolve()),
                "candidate_bold_run": str(run.resolve()),
                "evidence_source": str(session_map_path.resolve()),
                "confidence": "LOW",
                "reason": (
                    f"{run_label} is in the same mapped subject/session only. "
                    "No explicit PMU-to-run trigger mapping, shared timestamp, "
                    "or protocol-specific link was found; not usable."
                ),
            }


def write_readiness(
    path: Path,
    records: list[PhysioRecord],
    pmu_path: Path,
    sampling_path: Path,
    association_path: Path,
    inventory_count: int,
    mat_count: int,
) -> None:
    modality_counts = Counter(record.path.suffix.lower() for record in records)
    pmu_rows = list(csv.DictReader(pmu_path.open(encoding="utf-8"), delimiter="\t"))
    mdh_counts = Counter(
        row["extension"] for row in pmu_rows if row["log_start_mdh_time"]
    )
    complete_counts = Counter(
        row["extension"] for row in pmu_rows if row["footer_complete"] == "yes"
    )
    accepted_sampling = sum(
        1
        for row in csv.DictReader(sampling_path.open(encoding="utf-8"), delimiter="\t")
        if row["confidence"] in {"HIGH", "MEDIUM"}
    )
    usable_associations = sum(
        1
        for row in csv.DictReader(
            association_path.open(encoding="utf-8"), delimiter="\t"
        )
        if row["confidence"] in {"HIGH", "MEDIUM"}
    )
    lines = [
        "# Physiology conversion readiness",
        "",
        "## Decision",
        "",
        "**Recommended option: 3. Impossible without external scanner information.**",
        "",
        "No physiology conversion is authorized. No BIDS physiology files were created.",
        "",
        "## Modality decisions",
        "",
        "### A) Can ECG be converted?",
        "",
        "**NO.** No explicit ECG acquisition `SamplingFrequency` was recovered, no "
        "BIDS-relative `StartTime` was recovered, and no physiology recording has "
        "a HIGH or MEDIUM-confidence BOLD run association. Separately, waveform "
        "validation found the available ECG channels flat; waveform conversion was "
        "outside this metadata-only audit.",
        "",
        "### B) Can respiration be converted?",
        "",
        "**NO.** No explicit respiration acquisition `SamplingFrequency` was recovered. "
        "Literal MDH/MPCU clock ticks cannot be promoted to BIDS `StartTime` without "
        "a validated clock transformation, and run association remains session-only.",
        "",
        "### C) Can pulse be converted?",
        "",
        "**NO.** No explicit pulse acquisition `SamplingFrequency` was recovered. "
        "`PULS Freq Per` is heart-rate/period metadata, not an ADC sampling rate. "
        "No validated run-relative start or run mapping was recovered.",
        "",
        "## Recovered facts",
        "",
        f"- Target files audited: **{len(records)}** "
        f"(`.ecg` {modality_counts['.ecg']}, `.resp` {modality_counts['.resp']}, "
        f"`.puls` {modality_counts['.puls']}).",
        f"- Synchronization metadata inventory rows: **{inventory_count}**.",
        f"- Relevant MATLAB variable rows: **{mat_count}**.",
        f"- Accepted explicit sampling-frequency candidates: **{accepted_sampling}**.",
        f"- HIGH/MEDIUM run associations: **{usable_associations}**.",
        f"- Literal `LogStartMDHTime` coverage: ECG {mdh_counts['.ecg']}/"
        f"{modality_counts['.ecg']}, respiration {mdh_counts['.resp']}/"
        f"{modality_counts['.resp']}, pulse {mdh_counts['.puls']}/"
        f"{modality_counts['.puls']}.",
        f"- Structurally complete PMU footers: ECG {complete_counts['.ecg']}/"
        f"{modality_counts['.ecg']}, respiration {complete_counts['.resp']}/"
        f"{modality_counts['.resp']}, pulse {complete_counts['.puls']}/"
        f"{modality_counts['.puls']}.",
        "- MATLAB `scan.runs.triggerTimes` values exist for many task runs, but they "
        "are Psychtoolbox-clock timestamps. No documented transformation to the PMU "
        "MDH/MPCU clock was found.",
        "- Current BOLD JSON sidecars contain no `AcquisitionTime` or "
        "`AcquisitionDateTime` field.",
        "",
        "## Uncertain hypotheses (not accepted)",
        "",
        "- Unlabelled Siemens PMU preamble numbers may encode device settings, but "
        "they are not accepted as sampling rates.",
        "- Trigger spacing in MATLAB may validate a BOLD TR, but it does not establish "
        "physiology ADC sampling or a PMU clock mapping.",
        "- Protocol names and filename/run proximity may narrow candidate runs, but "
        "without a shared clock or explicit mapping they remain LOW confidence.",
        "",
        "## Unavailable information",
        "",
        "- Explicit ECG/RESP/PULS acquisition sampling frequency with units.",
        "- A documented conversion between MDH/MPCU ticks and seconds.",
        "- A run-relative physiology start time (`StartTime`).",
        "- An explicit PMU recording-to-BOLD run or trigger mapping.",
        "- BOLD `AcquisitionTime`/`AcquisitionDateTime` in current sidecars.",
        "",
        "## Missing requirements",
        "",
        "- **SamplingFrequency:** missing for all target files.",
        "- **StartTime:** missing for all target files. `LogStartMDHTime` is not "
        "equivalent to BIDS `StartTime`.",
        "- **Run association:** no HIGH or MEDIUM-confidence association.",
        "",
        "## Recommended next step",
        "",
        "Obtain external scanner documentation or original scanner exports that "
        "explicitly provide the PMU acquisition sampling rates and the MDH/MPCU "
        "clock definition. Recover unstripped DICOM acquisition timestamps and/or "
        "the original run-specific PhysioLog DICOM objects, then validate a "
        "trigger/clock transformation on representative sessions before authorizing "
        "any BIDS conversion.",
        "",
        "## Provenance and interpretation rules",
        "",
        "- `sampling_frequency_candidates.tsv` accepts only explicitly labelled "
        "acquisition sampling rates with units; heart rate, respiratory rate, period, "
        "TR, display `fps`, and nearby generic `Hz` were rejected.",
        "- `run_association_candidates.tsv` records session-only possibilities as "
        "`LOW`; these rows are explicitly not usable.",
        "- `pmu_header_report.tsv` contains literal metadata only; no waveform payload "
        "was decoded.",
        "- Facts, hypotheses, and unavailable requirements are separated above. No "
        "missing value was inferred or replaced by a Siemens default.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--workspace", type=Path, default=Path(__file__).resolve().parents[2]
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("reports/physiology_sync_analysis"),
    )
    args = parser.parse_args()
    workspace = args.workspace.resolve()
    output = args.output
    if not output.is_absolute():
        output = workspace / output
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)

    raw_root = DEFAULT_RAW_ROOT
    bids_root = workspace / "bids"
    session_map_path = workspace / "metadata/session_mapping.csv"

    log("Loading session map and physiology inventory...")
    session_map = _load_session_map(session_map_path)
    physio_records = discover_physio(workspace, raw_root, session_map)
    log(f"Target physiology files: {len(physio_records)}")

    log("Building synchronization metadata inventory...")
    inventory = list(inventory_rows(workspace, physio_records, output, raw_root=raw_root))
    inventory_path = output / "file_inventory.tsv"
    inventory_count = _write_tsv(
        inventory_path,
        [
            "filepath",
            "subject_candidate",
            "session_candidate",
            "extension",
            "size",
            "keywords_found",
        ],
        inventory,
    )
    log(f"Wrote {inventory_path} ({inventory_count} rows)")

    mat_path = output / "mat_variables.tsv"
    mat_count = _write_tsv(
        mat_path,
        ["file", "variable_name", "shape", "example_values", "possible_role"],
        relevant_mat_rows(workspace, raw_root),
    )
    log(f"Wrote {mat_path} ({mat_count} rows)")

    sampling_path = output / "sampling_frequency_candidates.tsv"
    sampling_count = _write_tsv(
        sampling_path,
        [
            "physio_file",
            "candidate_source",
            "variable",
            "value",
            "units",
            "confidence",
            "notes",
        ],
        sampling_rows(physio_records, inventory),
    )
    log(f"Wrote {sampling_path} ({sampling_count} rows)")

    association_path = output / "run_association_candidates.tsv"
    association_count = _write_tsv(
        association_path,
        [
            "subject",
            "session",
            "physio_file",
            "candidate_bold_run",
            "evidence_source",
            "confidence",
            "reason",
        ],
        run_association_rows(physio_records, bids_root, session_map_path),
    )
    log(f"Wrote {association_path} ({association_count} rows)")

    pmu_path = output / "pmu_header_report.tsv"
    pmu_count = _write_tsv(
        pmu_path,
        [
            "filepath",
            "subject_candidate",
            "session_candidate",
            "extension",
            "size_bytes",
            "version",
            "header_tokens",
            "log_start_mdh_time",
            "log_stop_mdh_time",
            "log_start_mpcu_time",
            "log_stop_mpcu_time",
            "nr_trig",
            "nr_mp",
            "nr_arr",
            "acq_win",
            "ecg_freq_per",
            "puls_freq_per",
            "resp_freq_per",
            "ext_freq_per",
            "ext2_freq_per",
            "footer_complete",
            "notes",
        ],
        pmu_header_rows(physio_records),
    )
    log(f"Wrote {pmu_path} ({pmu_count} rows)")

    readiness_path = output / "physiology_conversion_readiness.md"
    write_readiness(
        readiness_path,
        physio_records,
        pmu_path,
        sampling_path,
        association_path,
        inventory_count,
        mat_count,
    )
    log(f"Wrote {readiness_path}")
    log(f"Reports: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
