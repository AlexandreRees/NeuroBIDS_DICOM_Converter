"""Acquisition consistency manager for post-conversion BIDS validation."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from neuro_pipeline.acquisition_catalog import (
    ACQUISITION_PAIRS,
    EXPECTED_ACQUISITIONS,
    T1_ACQUISITION_ID,
    T1_DEPENDENT_MODALITIES,
    ExpectedAcquisition,
    extract_pe_direction,
    score_series_match,
)
from neuro_pipeline.acquisition_integrity import (
    ModalityIntegrityResult,
    check_single_t1_reference,
    run_modality_integrity_check,
)
from neuro_pipeline.utils.errors import FatalPipelineError
from neuro_pipeline.utils.paths import ProjectPaths

NIFTI_SUFFIXES = (".nii.gz", ".nii")
TASK_PATTERN = re.compile(r"task-([a-zA-Z0-9]+)")
RUN_PATTERN = re.compile(r"run-(\d+)")
DIR_PATTERN = re.compile(r"dir-([A-Za-z]+)")
SUFFIX_PATTERN = re.compile(r"_(T1w|T2w|FLAIR|bold|dwi|epi|sbref)(?:_|$)")


@dataclass
class BidsFileInfo:
    """Parsed BIDS NIfTI file with sidecar metadata."""

    relative_path: str
    participant_id: str
    session_label: str
    datatype: str
    filename: str
    stem: str
    task: str
    run: int | None
    pe_dir_label: str
    suffix: str
    series_instance_uid: str
    series_description: str
    protocol_name: str
    phase_encoding_direction: str
    intended_for: list[str]
    json_path: str


@dataclass
class AcquisitionReportRow:
    """One row in the acquisition consistency report."""

    participant_id: str
    session_label: str
    expected_acquisition: str
    found_acquisition: str
    bids_file: str
    bids_datatype: str
    expected_datatype: str
    run_number: str
    expected_run: str
    task: str
    expected_task: str
    phase_encoding_direction: str
    expected_pe_direction: str
    series_instance_uid: str
    modality: str
    missing_companion_files: str
    metadata_validation_status: str
    integrity_status: str
    status: str
    error_message: str

    def to_report_dict(self) -> dict[str, str]:
        """Map to user-facing report column names."""
        return {
            "participant": self.participant_id,
            "session": self.session_label,
            "modality": self.modality,
            "expected_acquisition": self.expected_acquisition,
            "detected_bids_file": self.bids_file,
            "found_acquisition": self.found_acquisition,
            "bids_datatype": self.bids_datatype,
            "expected_datatype": self.expected_datatype,
            "run_number": self.run_number,
            "expected_run": self.expected_run,
            "TaskName": self.task,
            "expected_task": self.expected_task,
            "PhaseEncodingDirection": self.phase_encoding_direction,
            "expected_pe_direction": self.expected_pe_direction,
            "series_instance_uid": self.series_instance_uid,
            "missing_companion_files": self.missing_companion_files,
            "metadata_validation_status": self.metadata_validation_status,
            "integrity_status": self.integrity_status,
            "validation_status": self.status,
            "error_message": self.error_message,
        }


@dataclass
class AcquisitionConsistencyReport:
    """Full acquisition consistency validation result."""

    passed: bool = True
    rows: list[AcquisitionReportRow] = field(default_factory=list)
    blocked_modalities: dict[str, dict[str, list[str]]] = field(default_factory=dict)
    t1_blocked_sessions: set[str] = field(default_factory=set)
    critical_errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def add_row(self, row: AcquisitionReportRow) -> None:
        self.rows.append(row)
        if row.status in {"error", "missing"}:
            self.passed = False

    def block_modality(
        self,
        participant_id: str,
        session_label: str,
        modality: str,
        reason: str,
    ) -> None:
        key = f"{participant_id}/{session_label}"
        self.blocked_modalities.setdefault(key, {})
        if modality not in self.blocked_modalities[key]:
            self.blocked_modalities[key][modality] = []
        self.blocked_modalities[key][modality].append(reason)
        self.critical_errors.append(f"{key} [{modality}]: {reason}")

    def block_t1_dependent(
        self,
        participant_id: str,
        session_label: str,
        reason: str,
    ) -> None:
        """Block all modalities that require a T1 reference for this session."""
        session_key = f"{participant_id}/{session_label}"
        self.t1_blocked_sessions.add(session_key)
        for modality in T1_DEPENDENT_MODALITIES:
            self.block_modality(participant_id, session_label, modality, reason)

    def to_dict(self) -> dict[str, object]:
        return {
            "passed": self.passed,
            "row_count": len(self.rows),
            "error_count": sum(1 for row in self.rows if row.status == "error"),
            "warning_count": sum(1 for row in self.rows if row.status == "warning"),
            "missing_count": sum(1 for row in self.rows if row.status == "missing"),
            "pass_count": sum(1 for row in self.rows if row.status == "pass"),
            "blocked_modalities": self.blocked_modalities,
            "t1_blocked_sessions": sorted(self.t1_blocked_sessions),
            "critical_errors": self.critical_errors,
            "warnings": self.warnings,
            "rows": [row.to_report_dict() for row in self.rows],
        }


def _json_sidecar_path(nifti_path: Path) -> Path:
    if nifti_path.name.endswith(".nii.gz"):
        return Path(str(nifti_path).replace(".nii.gz", ".json"))
    return nifti_path.with_suffix(".json")


def _is_nifti(path: Path) -> bool:
    name = path.name.lower()
    return name.endswith(".nii.gz") or name.endswith(".nii")


def _parse_bids_stem(stem: str) -> dict[str, object]:
    task_match = TASK_PATTERN.search(stem)
    run_match = RUN_PATTERN.search(stem)
    dir_match = DIR_PATTERN.search(stem)
    suffix_match = SUFFIX_PATTERN.search(stem)
    return {
        "task": task_match.group(1).lower() if task_match else "",
        "run": int(run_match.group(1)) if run_match else None,
        "pe_dir_label": dir_match.group(1).upper() if dir_match else "",
        "suffix": suffix_match.group(1) if suffix_match else "",
    }


def _pe_from_json_value(value: str) -> str:
    """Map BIDS PhaseEncodingDirection to AP/PA heuristic for axial stacks."""
    if not value:
        return ""
    normalized = value.strip().lower()
    if normalized in {"j-", "j-"}:
        return "AP"
    if normalized in {"j+", "j+"}:
        return "PA"
    if normalized in {"i-", "i-"}:
        return "RL"
    if normalized in {"i+", "i+"}:
        return "LR"
    return value.upper()


def scan_bids_files(
    raw_bids: Path,
    uid_lookup: dict[str, dict[str, str]],
) -> list[BidsFileInfo]:
    """Scan raw_bids and parse NIfTI + JSON metadata."""
    files: list[BidsFileInfo] = []
    if not raw_bids.is_dir():
        return files

    for nifti_path in sorted(raw_bids.rglob("*")):
        if not nifti_path.is_file() or not _is_nifti(nifti_path):
            continue

        relative = nifti_path.relative_to(raw_bids)
        parts = relative.parts
        participant_id = parts[0]
        session_label = ""
        datatype = ""
        if len(parts) > 1 and parts[1].startswith("ses-"):
            session_label = parts[1]
            datatype = parts[2] if len(parts) > 2 else ""
        elif len(parts) > 1:
            datatype = parts[1]

        stem = nifti_path.name.replace(".nii.gz", "").replace(".nii", "")
        parsed = _parse_bids_stem(stem)

        sidecar = _json_sidecar_path(nifti_path)
        sidecar_data: dict[str, object] = {}
        if sidecar.is_file():
            try:
                sidecar_data = json.loads(sidecar.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                sidecar_data = {}

        series_uid = str(sidecar_data.get("SeriesInstanceUID", "") or "")
        lookup = uid_lookup.get(series_uid, {})
        series_description = str(
            sidecar_data.get("SeriesDescription", "") or lookup.get("series_description", "")
        )
        protocol_name = str(
            sidecar_data.get("ProtocolName", "") or lookup.get("protocol_name", "")
        )

        pe_json = str(sidecar_data.get("PhaseEncodingDirection", "") or "")
        intended_raw = sidecar_data.get("IntendedFor", [])
        if isinstance(intended_raw, str):
            intended_for = [intended_raw]
        elif isinstance(intended_raw, list):
            intended_for = [str(item) for item in intended_raw]
        else:
            intended_for = []

        pe_label = parsed["pe_dir_label"] or _pe_from_json_value(pe_json)
        if not pe_label:
            pe_label = extract_pe_direction(series_description) or ""

        files.append(
            BidsFileInfo(
                relative_path=str(relative),
                participant_id=participant_id,
                session_label=session_label,
                datatype=datatype,
                filename=nifti_path.name,
                stem=stem,
                task=str(parsed["task"]),
                run=parsed["run"],  # type: ignore[arg-type]
                pe_dir_label=pe_label,
                suffix=str(parsed["suffix"]),
                series_instance_uid=series_uid,
                series_description=series_description,
                protocol_name=protocol_name,
                phase_encoding_direction=pe_json,
                intended_for=intended_for,
                json_path=str(sidecar.relative_to(raw_bids)) if sidecar.is_file() else "",
            )
        )
    return files


def _load_uid_lookup(session_mapping: pd.DataFrame) -> dict[str, dict[str, str]]:
    lookup: dict[str, dict[str, str]] = {}
    for _, row in session_mapping.iterrows():
        uid = str(row.get("series_instance_uid", "")).strip()
        if not uid:
            continue
        lookup[uid] = {
            "series_description": str(row.get("series_description", "")),
            "protocol_name": str(row.get("protocol_name", "")),
            "participant_id": str(row.get("participant_id", "")),
            "session_label": str(row.get("session_label", "")),
            "bids_modality": str(row.get("bids_modality", "")),
        }
    return lookup


def _load_conversion_index(conversion_report: Path) -> dict[str, dict[str, str]]:
    if not conversion_report.is_file():
        return {}
    df = pd.read_csv(conversion_report, dtype=str).fillna("")
    index: dict[str, dict[str, str]] = {}
    for _, row in df.iterrows():
        uid = str(row.get("series_instance_uid", "")).strip()
        if uid:
            index[uid] = dict(row)
    return index


def match_series_to_acquisitions(
    series_rows: list[dict[str, str]],
) -> tuple[dict[str, dict[str, str]], list[str]]:
    """Assign each expected acquisition to at most one series row."""
    assignments: dict[str, dict[str, str]] = {}
    errors: list[str] = []

    candidates: list[tuple[float, ExpectedAcquisition, dict[str, str]]] = []
    for series in series_rows:
        for expected in EXPECTED_ACQUISITIONS:
            score = score_series_match(
                series.get("series_description", ""),
                series.get("protocol_name", ""),
                expected,
            )
            if score > 0:
                candidates.append((score, expected, series))

    candidates.sort(key=lambda item: (-item[0], item[1].acquisition_id))
    used_series: set[str] = set()
    used_expected: set[str] = set()

    for score, expected, series in candidates:
        uid = series.get("series_instance_uid", "")
        if expected.acquisition_id in used_expected or uid in used_series:
            continue
        assignments[expected.acquisition_id] = series
        used_expected.add(expected.acquisition_id)
        used_series.add(uid)

    for expected in EXPECTED_ACQUISITIONS:
        if expected.acquisition_id not in assignments and expected.required:
            errors.append(f"Missing required acquisition: {expected.acquisition_id}")

    series_to_expected: dict[str, list[str]] = defaultdict(list)
    for expected_id, series in assignments.items():
        uid = series.get("series_instance_uid", "")
        series_to_expected[uid].append(expected_id)

    for uid, expected_ids in series_to_expected.items():
        if len(expected_ids) > 1:
            desc = assignments[expected_ids[0]].get("series_description", uid)
            errors.append(
                f"Multiple acquisitions collapsed onto one series ({desc}): "
                f"{expected_ids}"
            )

    unmatched = [
        row
        for row in series_rows
        if row.get("series_instance_uid", "") not in used_series
    ]
    return assignments, errors + [
        f"Unmatched series not mapped to catalog: {row.get('series_description', '')}"
        for row in unmatched
    ]


def _find_bids_file_for_series(
    bids_files: list[BidsFileInfo],
    participant_id: str,
    session_label: str,
    series_uid: str,
    expected: ExpectedAcquisition,
    conversion_row: dict[str, str] | None,
) -> BidsFileInfo | None:
    """Locate the converted BIDS file for a series."""
    matches = [
        item
        for item in bids_files
        if item.participant_id == participant_id
        and item.session_label == session_label
        and item.series_instance_uid == series_uid
    ]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        return matches[0]

    if conversion_row:
        expected_stem = str(conversion_row.get("expected_filename", ""))
        output_dir = Path(str(conversion_row.get("bids_output_dir", "")))
        for item in bids_files:
            if item.participant_id != participant_id or item.session_label != session_label:
                continue
            if expected_stem and item.stem == expected_stem:
                return item
            if output_dir and expected_stem in item.relative_path:
                return item

    datatype_matches = [
        item
        for item in bids_files
        if item.participant_id == participant_id
        and item.session_label == session_label
        and item.datatype == expected.expected_datatype
    ]
    if expected.expected_task:
        datatype_matches = [
            item for item in datatype_matches if item.task == expected.expected_task
        ]
    if expected.expected_run is not None:
        datatype_matches = [
            item
            for item in datatype_matches
            if item.run == expected.expected_run
        ]
    if expected.expected_pe_direction:
        datatype_matches = [
            item
            for item in datatype_matches
            if item.pe_dir_label == expected.expected_pe_direction
            or extract_pe_direction(item.series_description) == expected.expected_pe_direction
        ]
    if len(datatype_matches) == 1:
        return datatype_matches[0]
    return None


def _validate_task_name(
    expected: ExpectedAcquisition,
    bids_file: BidsFileInfo | None,
) -> tuple[str, str]:
    if not expected.expected_task:
        return "pass", ""
    if bids_file is None:
        return "error", "Cannot verify TaskName — BIDS file not found"
    if not bids_file.task:
        return "error", "TaskName missing from BIDS filename"
    if bids_file.task != expected.expected_task:
        return "warning", (
            f"TaskName mismatch: expected '{expected.expected_task}', "
            f"found '{bids_file.task}'"
        )
    return "pass", ""


def _validate_pe_direction(
    expected: ExpectedAcquisition,
    series_row: dict[str, str],
    bids_file: BidsFileInfo | None,
) -> tuple[str, str]:
    if not expected.expected_pe_direction:
        return "pass", ""

    combined = (
        f"{series_row.get('series_description', '')} "
        f"{series_row.get('protocol_name', '')}"
    )
    series_pe = extract_pe_direction(combined)
    if not series_pe:
        return "error", f"AP/PA direction missing in DICOM metadata for {expected.acquisition_id}"

    if series_pe != expected.expected_pe_direction:
        return "error", (
            f"AP/PA mismatch in series metadata: expected {expected.expected_pe_direction}, "
            f"found {series_pe}"
        )

    if bids_file is None:
        return "error", "Cannot verify PE direction — BIDS file not found"

    bids_pe = bids_file.pe_dir_label or _pe_from_json_value(bids_file.phase_encoding_direction)
    if not bids_pe and not bids_file.phase_encoding_direction:
        return "error", "PhaseEncodingDirection missing from JSON sidecar and filename"

    if bids_pe and bids_pe in {"AP", "PA"} and bids_pe != expected.expected_pe_direction:
        return "error", (
            f"AP/PA mismatch in BIDS metadata: expected {expected.expected_pe_direction}, "
            f"found {bids_pe}"
        )
    return "pass", ""


def _validate_run_identity(
    expected: ExpectedAcquisition,
    bids_file: BidsFileInfo | None,
    run_usage: dict[tuple[str, str, str, int], list[str]],
    participant_id: str,
    session_label: str,
) -> tuple[str, str]:
    if expected.expected_run is None or not expected.expected_task:
        return "pass", ""
    if bids_file is None:
        return "error", "Cannot verify run number — BIDS file not found"
    if bids_file.run is None:
        return "error", "Run number missing from BIDS filename"
    if bids_file.run != expected.expected_run:
        return "error", (
            f"Run number mismatch: expected run-{expected.expected_run:02d}, "
            f"found run-{bids_file.run:02d}"
        )

    key = (participant_id, session_label, expected.expected_task or "", bids_file.run)
    run_usage[key].append(expected.acquisition_id)
    if len(run_usage[key]) > 1:
        return "error", (
            f"Ambiguous run numbering: run-{bids_file.run:02d} used by "
            f"{run_usage[key]}"
        )
    return "pass", ""


def _validate_datatype(
    expected: ExpectedAcquisition,
    series_row: dict[str, str],
    bids_file: BidsFileInfo | None,
) -> tuple[str, str]:
    mapped = str(series_row.get("bids_modality", "")).strip()
    if mapped and mapped != expected.expected_datatype:
        return "error", (
            f"Wrong BIDS datatype assignment: expected '{expected.expected_datatype}', "
            f"mapped to '{mapped}'"
        )
    if bids_file and bids_file.datatype != expected.expected_datatype:
        return "error", (
            f"BIDS file in wrong folder: expected '{expected.expected_datatype}', "
            f"found in '{bids_file.datatype}'"
        )
    return "pass", ""


def _default_integrity_fields() -> dict[str, str]:
    return {
        "modality": "",
        "missing_companion_files": "",
        "metadata_validation_status": "skip",
        "integrity_status": "skip",
    }


def _apply_integrity_result(
    comments: list[str],
    status: str,
    integrity: ModalityIntegrityResult,
) -> tuple[list[str], str, str, str, str]:
    """Merge integrity findings into row status and companion-file fields."""
    comments = comments + integrity.messages
    missing = ", ".join(integrity.missing_companion_files)
    if integrity.integrity_status == "error" or integrity.metadata_validation_status == "error":
        status = "error"
    elif integrity.integrity_status == "warning" or integrity.metadata_validation_status == "warning":
        if status == "pass":
            status = "warning"
    return (
        comments,
        status,
        missing,
        integrity.metadata_validation_status,
        integrity.integrity_status,
    )


def _build_report_row(
    *,
    participant_id: str,
    session_label: str,
    expected: ExpectedAcquisition | None,
    expected_acquisition: str,
    found_acquisition: str,
    bids_file: BidsFileInfo | None,
    series_row: dict[str, str] | None,
    uid: str,
    status: str,
    error_message: str,
    integrity_fields: dict[str, str] | None = None,
) -> AcquisitionReportRow:
    fields = _default_integrity_fields()
    if integrity_fields:
        fields.update(integrity_fields)
    if expected:
        fields["modality"] = expected.category
    return AcquisitionReportRow(
        participant_id=participant_id,
        session_label=session_label,
        expected_acquisition=expected_acquisition,
        found_acquisition=found_acquisition,
        bids_file=bids_file.relative_path if bids_file else "",
        bids_datatype=bids_file.datatype if bids_file else str((series_row or {}).get("bids_modality", "")),
        expected_datatype=expected.expected_datatype if expected else "",
        run_number=str(bids_file.run or "") if bids_file else "",
        expected_run=str(expected.expected_run or "") if expected else "",
        task=bids_file.task if bids_file else "",
        expected_task=(expected.expected_task or "") if expected else "",
        phase_encoding_direction=(
            bids_file.pe_dir_label or bids_file.phase_encoding_direction if bids_file else ""
        ),
        expected_pe_direction=(expected.expected_pe_direction or "") if expected else "",
        series_instance_uid=uid,
        modality=fields["modality"],
        missing_companion_files=fields["missing_companion_files"],
        metadata_validation_status=fields["metadata_validation_status"],
        integrity_status=fields["integrity_status"],
        status=status,
        error_message=error_message,
    )


def _validate_intended_for(
    ap_acquisition: ExpectedAcquisition,
    pa_acquisition: ExpectedAcquisition,
    ap_file: BidsFileInfo | None,
    pa_file: BidsFileInfo | None,
    func_dwi_files: list[BidsFileInfo],
) -> list[str]:
    """Return warnings/errors for fieldmap IntendedFor linkage."""
    messages: list[str] = []
    if ap_file is None or pa_file is None:
        return messages

    for fmap_file in (ap_file, pa_file):
        if not fmap_file.intended_for:
            messages.append(
                f"warning: IntendedFor missing for fieldmap {fmap_file.stem}"
            )
            continue
        targets = set(fmap_file.intended_for)
        valid_targets = {item.relative_path for item in func_dwi_files}
        invalid = targets - valid_targets
        if invalid:
            messages.append(
                f"error: IntendedFor points to unknown files in {fmap_file.stem}: "
                f"{sorted(invalid)}"
            )
    return messages


def run_acquisition_consistency_checks(paths: ProjectPaths) -> AcquisitionConsistencyReport:
    """Validate that all expected acquisitions are uniquely identifiable in raw_bids/."""
    report = AcquisitionConsistencyReport()

    if not paths.session_mapping_csv.is_file():
        report.passed = False
        report.critical_errors.append("Missing session_mapping.csv")
        return report

    session_mapping = pd.read_csv(paths.session_mapping_csv, dtype=str).fillna("")
    if "bids_modality" not in session_mapping.columns:
        session_mapping["bids_modality"] = session_mapping.apply(
            lambda row: _infer_modality_from_row(row),
            axis=1,
        )

    conversion_index = _load_conversion_index(paths.conversion_report_csv)
    uid_lookup = _load_uid_lookup(session_mapping)
    bids_files = scan_bids_files(paths.raw_bids, uid_lookup)

    sessions = (
        session_mapping[["participant_id", "session_label"]]
        .drop_duplicates()
        .sort_values(["participant_id", "session_label"])
    )

    for _, session in sessions.iterrows():
        participant_id = str(session["participant_id"])
        session_label = str(session["session_label"])
        series_rows = session_mapping[
            (session_mapping["participant_id"] == participant_id)
            & (session_mapping["session_label"] == session_label)
        ].to_dict(orient="records")

        assignments, match_errors = match_series_to_acquisitions(series_rows)
        for message in match_errors:
            if message.startswith("Missing required acquisition"):
                acq_id = message.split(": ", 1)[1]
                expected = _get_expected(acq_id)
                report.add_row(
                    _build_report_row(
                        participant_id=participant_id,
                        session_label=session_label,
                        expected=expected,
                        expected_acquisition=acq_id,
                        found_acquisition="",
                        bids_file=None,
                        series_row=None,
                        uid="",
                        status="missing",
                        error_message=message,
                    )
                )
                if expected and expected.acquisition_id == T1_ACQUISITION_ID:
                    report.block_t1_dependent(
                        participant_id,
                        session_label,
                        "T1w_MPR missing — T1-dependent processing blocked",
                    )
                elif expected:
                    report.block_modality(
                        participant_id,
                        session_label,
                        expected.expected_datatype,
                        message,
                    )
            elif message.startswith("Multiple acquisitions collapsed"):
                report.passed = False
                report.critical_errors.append(
                    f"{participant_id}/{session_label}: {message}"
                )
                report.block_modality(
                    participant_id,
                    session_label,
                    "func",
                    message,
                )

        run_usage: dict[tuple[str, str, str, int], list[str]] = defaultdict(list)
        found_by_id: dict[str, BidsFileInfo | None] = {}
        series_by_id: dict[str, dict[str, str]] = {}

        for expected in EXPECTED_ACQUISITIONS:
            series_row = assignments.get(expected.acquisition_id)
            if series_row is None:
                continue
            uid = str(series_row.get("series_instance_uid", ""))
            conversion_row = conversion_index.get(uid)
            found_by_id[expected.acquisition_id] = _find_bids_file_for_series(
                bids_files,
                participant_id,
                session_label,
                uid,
                expected,
                conversion_row,
            )
            series_by_id[expected.acquisition_id] = series_row

        func_dwi = [
            item
            for item in bids_files
            if item.participant_id == participant_id
            and item.session_label == session_label
            and item.datatype in {"func", "dwi"}
        ]
        func_dwi_targets = {item.relative_path for item in func_dwi}
        spin_echo_present = (
            found_by_id.get("SpinEchoFieldMap_AP") is not None
            and found_by_id.get("SpinEchoFieldMap_PA") is not None
        )

        for expected in EXPECTED_ACQUISITIONS:
            series_row = assignments.get(expected.acquisition_id)
            if series_row is None:
                if expected.required:
                    continue
                report.add_row(
                    _build_report_row(
                        participant_id=participant_id,
                        session_label=session_label,
                        expected=expected,
                        expected_acquisition=expected.acquisition_id,
                        found_acquisition="",
                        bids_file=None,
                        series_row=None,
                        uid="",
                        status="missing",
                        error_message="Optional acquisition not found",
                    )
                )
                continue

            uid = str(series_row.get("series_instance_uid", ""))
            conversion_row = conversion_index.get(uid)
            bids_file = found_by_id.get(expected.acquisition_id)

            comments: list[str] = []
            status = "pass"

            for check_fn, args in (
                (_validate_datatype, (expected, series_row, bids_file)),
                (_validate_pe_direction, (expected, series_row, bids_file)),
                (_validate_run_identity, (expected, bids_file, run_usage, participant_id, session_label)),
                (_validate_task_name, (expected, bids_file)),
            ):
                check_status, message = check_fn(*args)
                if message:
                    comments.append(message)
                if check_status == "error":
                    status = "error"
                elif check_status == "warning" and status == "pass":
                    status = "warning"

            if bids_file is None and status == "pass":
                status = "error"
                comments.append("Converted BIDS file not found for matched series")

            if conversion_row and conversion_row.get("status") not in {"success", "skipped"}:
                status = "error"
                comments.append(
                    f"Conversion status: {conversion_row.get('status', 'unknown')}"
                )

            if bids_file:
                same_stem = [
                    item.relative_path
                    for item in bids_files
                    if item.participant_id == participant_id
                    and item.session_label == session_label
                    and item.stem == bids_file.stem
                ]
                if len(same_stem) > 1:
                    status = "error"
                    comments.append(
                        f"Duplicate BIDS filename stem '{bids_file.stem}': {same_stem}"
                    )

                uid_collisions = [
                    item.relative_path
                    for item in bids_files
                    if item.participant_id == participant_id
                    and item.session_label == session_label
                    and item.series_instance_uid
                    and item.series_instance_uid == bids_file.series_instance_uid
                    and item.relative_path != bids_file.relative_path
                ]
                if uid_collisions:
                    status = "error"
                    comments.append(
                        f"SeriesInstanceUID {uid} mapped to multiple BIDS files: "
                        f"{uid_collisions + [bids_file.relative_path]}"
                    )

            integrity = run_modality_integrity_check(
                paths.raw_bids,
                expected,
                series_row,
                bids_file,
                spin_echo_pair_present=spin_echo_present,
                func_dwi_targets=func_dwi_targets,
            )
            comments, status, missing_files, meta_status, integrity_status = _apply_integrity_result(
                comments,
                status,
                integrity,
            )

            report.add_row(
                _build_report_row(
                    participant_id=participant_id,
                    session_label=session_label,
                    expected=expected,
                    expected_acquisition=expected.acquisition_id,
                    found_acquisition=series_row.get("series_description", ""),
                    bids_file=bids_file,
                    series_row=series_row,
                    uid=uid,
                    status=status,
                    error_message="; ".join(comments),
                    integrity_fields={
                        "modality": expected.category,
                        "missing_companion_files": missing_files,
                        "metadata_validation_status": meta_status,
                        "integrity_status": integrity_status,
                    },
                )
            )

            if status == "error":
                report.block_modality(
                    participant_id,
                    session_label,
                    expected.expected_datatype,
                    "; ".join(comments) or f"Validation failed for {expected.acquisition_id}",
                )
            if (
                expected.acquisition_id == T1_ACQUISITION_ID
                and status in {"error", "missing"}
            ):
                report.block_t1_dependent(
                    participant_id,
                    session_label,
                    "; ".join(comments) or "T1w_MPR validation failed",
                )

        t1_status, t1_message = check_single_t1_reference(
            [(T1_ACQUISITION_ID, found_by_id.get(T1_ACQUISITION_ID))]
        )
        if t1_status == "error":
            report.passed = False
            report.block_modality(
                participant_id,
                session_label,
                "anat",
                t1_message,
            )
            report.critical_errors.append(f"{participant_id}/{session_label}: {t1_message}")

        for ap_id, pa_id in ACQUISITION_PAIRS:
            ap_expected = _get_expected(ap_id)
            pa_expected = _get_expected(pa_id)
            ap_file = found_by_id.get(ap_id)
            pa_file = found_by_id.get(pa_id)
            pair_modality = ap_expected.expected_datatype if ap_expected else "fmap"
            if ap_file is None or pa_file is None:
                missing = ap_id if ap_file is None else pa_id
                report.passed = False
                report.block_modality(
                    participant_id,
                    session_label,
                    pair_modality,
                    f"Incomplete AP/PA pair: missing {missing}",
                )
                report.critical_errors.append(
                    f"{participant_id}/{session_label}: incomplete pair ({ap_id}/{pa_id})"
                )
            elif ap_expected and ap_expected.expected_datatype == "fmap":
                for message in _validate_intended_for(
                    ap_expected, pa_expected, ap_file, pa_file, func_dwi
                ):
                    if message.startswith("error:"):
                        report.passed = False
                        report.block_modality(
                            participant_id,
                            session_label,
                            "fmap",
                            message,
                        )
                    else:
                        report.warnings.append(
                            f"{participant_id}/{session_label}: {message}"
                        )

    return report


def _get_expected(acquisition_id: str) -> ExpectedAcquisition | None:
    for item in EXPECTED_ACQUISITIONS:
        if item.acquisition_id == acquisition_id:
            return item
    return None


def _infer_modality_from_row(row: pd.Series) -> str:
    from neuro_pipeline.utils.dicom_helpers import infer_bids_modality

    return infer_bids_modality(
        str(row.get("modality", "")),
        str(row.get("series_description", "")),
    )


def write_acquisition_consistency_reports(
    report: AcquisitionConsistencyReport,
    csv_path: Path,
    json_path: Path,
) -> None:
    """Write CSV and JSON acquisition consistency reports."""
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.parent.mkdir(parents=True, exist_ok=True)

    rows = [row.to_report_dict() for row in report.rows]
    pd.DataFrame(rows).to_csv(csv_path, index=False)
    json_path.write_text(
        json.dumps(report.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def write_acquisition_blocklist(
    report: AcquisitionConsistencyReport,
    blocklist_path: Path,
) -> None:
    """Write per-session modality blocklist for downstream tools."""
    blocklist_path.parent.mkdir(parents=True, exist_ok=True)
    sessions: dict[str, dict[str, object]] = {}
    for session_key, modalities in report.blocked_modalities.items():
        sessions[session_key] = {
            "blocked_modalities": {
                modality: reasons for modality, reasons in modalities.items()
            },
            "t1_dependent_blocked": session_key in report.t1_blocked_sessions,
        }
    payload = {
        "passed": report.passed,
        "session_count": len(sessions),
        "t1_blocked_sessions": sorted(report.t1_blocked_sessions),
        "sessions": sessions,
    }
    blocklist_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def run_acquisition_validation(
    paths: ProjectPaths,
    *,
    fail_on_error: bool = False,
) -> AcquisitionConsistencyReport:
    """Run acquisition checks, write reports, optionally fail on errors."""
    report = run_acquisition_consistency_checks(paths)
    write_acquisition_consistency_reports(
        report,
        paths.acquisition_validation_csv,
        paths.acquisition_validation_json,
    )
    write_acquisition_blocklist(report, paths.acquisition_blocklist_json)

    if fail_on_error and not report.passed:
        sample = "; ".join(report.critical_errors[:3])
        raise FatalPipelineError(
            f"Acquisition validation failed ({len(report.critical_errors)} issue(s)): {sample}"
        )
    return report
