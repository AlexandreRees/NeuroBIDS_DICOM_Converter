"""Load pipeline provenance artifacts for Methods section generation."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from neuro_pipeline.utils.paths import ProjectPaths

LOGGER = logging.getLogger(__name__)

PLACEHOLDER = "[NOT AVAILABLE IN PIPELINE METADATA]"

STEP_CONTEXT_FILES: tuple[tuple[str, str], ...] = (
    ("inventory", "inventory_context.json"),
    ("generate_mapping", "generate_mapping_context.json"),
    ("convert_to_bids", "convert_to_bids_context.json"),
    ("validate_dataset", "validate_dataset_context.json"),
    ("quality_control", "quality_control_context.json"),
    ("derivatives_build", "derivatives_build_context.json"),
    ("release_dataset", "release_dataset_context.json"),
    ("validate_public_dataset", "validate_public_dataset_context.json"),
    ("release_gate", "release_gate_context.json"),
)


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        LOGGER.warning("Could not parse JSON: %s", path)
        return {}
    return payload if isinstance(payload, dict) else {}


def _load_csv(path: Path) -> pd.DataFrame:
    if not path.is_file():
        return pd.DataFrame()
    try:
        return pd.read_csv(path, dtype=str).fillna("")
    except (OSError, pd.errors.ParserError):
        LOGGER.warning("Could not read CSV: %s", path)
        return pd.DataFrame()


@dataclass
class MethodsSourceData:
    """Aggregated provenance inputs for Methods generation."""

    manifest: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)
    research_checkpoints: dict[str, Any] = field(default_factory=dict)
    release_checkpoints: dict[str, Any] = field(default_factory=dict)
    step_contexts: dict[str, dict[str, Any]] = field(default_factory=dict)
    release_manifest: dict[str, Any] = field(default_factory=dict)
    release_status: dict[str, Any] = field(default_factory=dict)
    release_gate_report: dict[str, Any] = field(default_factory=dict)
    release_ready: dict[str, Any] = field(default_factory=dict)
    acquisition_validation: dict[str, Any] = field(default_factory=dict)
    acquisition_blocklist: dict[str, Any] = field(default_factory=dict)
    raw_bids_lock: dict[str, Any] = field(default_factory=dict)
    raw_bids_checksums: dict[str, Any] = field(default_factory=dict)
    defacing_report: dict[str, Any] = field(default_factory=dict)
    qc_report: dict[str, Any] = field(default_factory=dict)
    bids_validation_report: dict[str, Any] = field(default_factory=dict)
    inventory: pd.DataFrame = field(default_factory=pd.DataFrame)
    conversion_report: pd.DataFrame = field(default_factory=pd.DataFrame)
    qc_detail: pd.DataFrame = field(default_factory=pd.DataFrame)
    qc_summary: pd.DataFrame = field(default_factory=pd.DataFrame)
    geometry_validation: pd.DataFrame = field(default_factory=pd.DataFrame)
    conversion_log_count: int = 0


def load_methods_sources(paths: ProjectPaths) -> MethodsSourceData:
    """Load all provenance artifacts referenced by the Methods generator."""
    data = MethodsSourceData()
    data.manifest = _load_json(paths.pipeline_manifest_json)
    data.provenance = data.manifest.get("provenance", {})
    if not isinstance(data.provenance, dict):
        data.provenance = {}

    data.research_checkpoints = _load_json(paths.research_checkpoints_json)
    data.release_checkpoints = _load_json(paths.release_checkpoints_json)
    data.release_manifest = _load_json(paths.anonymization_release / "release_manifest.json")
    data.release_status = _load_json(paths.anonymization_release / "release_status.json")
    data.release_gate_report = _load_json(paths.release_gate_report_json)
    data.release_ready = _load_json(paths.release_ready_json)
    data.acquisition_validation = _load_json(paths.acquisition_validation_json)
    data.acquisition_blocklist = _load_json(paths.acquisition_blocklist_json)
    data.raw_bids_lock = _load_json(paths.metadata / "raw_bids_lock.json")
    data.raw_bids_checksums = _load_json(paths.metadata / "raw_bids_checksums.json")
    data.defacing_report = _load_json(paths.defacing_report_json)
    data.qc_report = _load_json(paths.derivatives / "qc" / "qc_report.json")
    data.bids_validation_report = _load_json(paths.validation_report_json)

    data.inventory = _load_csv(paths.inventory_csv)
    data.conversion_report = _load_csv(paths.conversion_report_csv)
    data.qc_detail = _load_csv(paths.qc_detail_csv)
    data.qc_summary = _load_csv(paths.qc_summary_csv)
    data.geometry_validation = _load_csv(paths.geometry_validation_csv)

    for step_name, filename in STEP_CONTEXT_FILES:
        context = _load_json(paths.metadata / filename)
        if context:
            data.step_contexts[step_name] = context

    if paths.conversion_logs_dir.is_dir():
        data.conversion_log_count = sum(
            1 for path in paths.conversion_logs_dir.iterdir() if path.is_file()
        )

    return data


def step_was_completed(sources: MethodsSourceData, step: str, *, pipeline: str = "research") -> bool:
    """Return True when a pipeline step is recorded as successfully completed."""
    checkpoints = sources.research_checkpoints if pipeline == "research" else sources.release_checkpoints
    steps = checkpoints.get("steps", {})
    if not isinstance(steps, dict):
        return False
    record = steps.get(step, {})
    if not isinstance(record, dict):
        return False
    return str(record.get("status", "")).lower() == "success"


def resolve_value(*candidates: object, default: str = PLACEHOLDER) -> str:
    """Return the first non-empty string candidate."""
    for candidate in candidates:
        if candidate is None:
            continue
        text = str(candidate).strip()
        if text and text.lower() not in {"unknown", "unavailable", "none"}:
            return text
    return default


def collect_software_versions(sources: MethodsSourceData) -> dict[str, str]:
    """Merge software version records from manifest provenance and step contexts."""
    versions: dict[str, str] = {}
    provenance_versions = sources.provenance.get("software_versions", {})
    if isinstance(provenance_versions, dict):
        for key, value in provenance_versions.items():
            if value:
                versions[str(key)] = str(value)

    manifest_keys = (
        ("dcm2niix", "dcm2niix_version"),
        ("bids-validator", "bids_validator_version"),
    )
    for name, manifest_key in manifest_keys:
        value = sources.manifest.get(manifest_key)
        if value:
            versions.setdefault(name, str(value))

    for context in sources.step_contexts.values():
        context_versions = context.get("software_versions", {})
        if isinstance(context_versions, dict):
            for key, value in context_versions.items():
                if value:
                    versions.setdefault(str(key), str(value))

    return dict(sorted(versions.items()))


def _artifact_path(sources: MethodsSourceData, key: str) -> str:
    artifacts = sources.manifest.get("artifacts", {})
    if isinstance(artifacts, dict):
        value = artifacts.get(key)
        if value:
            return str(value)
    return PLACEHOLDER


def _inventory_counts(sources: MethodsSourceData) -> tuple[str, str, str]:
    inventory = sources.inventory
    if inventory.empty:
        return PLACEHOLDER, PLACEHOLDER, PLACEHOLDER
    subject_cols = [c for c in ("cohort", "source_subject_folder", "source_subject_path") if c in inventory.columns]
    if len(subject_cols) == 3:
        subjects = inventory.drop_duplicates(subset=subject_cols).shape[0]
    else:
        subjects = PLACEHOLDER
    if "session_label" in inventory.columns and subject_cols:
        sessions = inventory.drop_duplicates(subset=[*subject_cols, "session_label"]).shape[0]
    elif "session_label" in inventory.columns:
        sessions = inventory["session_label"].nunique()
    else:
        sessions = PLACEHOLDER
    series = str(len(inventory)) if len(inventory) else PLACEHOLDER
    return str(subjects), str(sessions), series


def _conversion_counts(sources: MethodsSourceData) -> tuple[str, str, str]:
    report = sources.conversion_report
    if report.empty or "status" not in report.columns:
        return PLACEHOLDER, PLACEHOLDER, PLACEHOLDER
    success = int((report["status"] == "success").sum())
    failed = int((report["status"] == "failed").sum())
    skipped = int((report["status"] == "skipped").sum())
    return str(success), str(failed), str(skipped)


def _modality_qc_summary(sources: MethodsSourceData, modality: str) -> str:
    detail = sources.qc_detail
    if detail.empty or "modality" not in detail.columns or "status" not in detail.columns:
        return PLACEHOLDER
    subset = detail[detail["modality"] == modality]
    if subset.empty:
        return PLACEHOLDER
    counts = subset["status"].value_counts().to_dict()
    parts = [f"{status}: {count}" for status, count in sorted(counts.items())]
    return ", ".join(parts)


def _blocked_modalities_text(sources: MethodsSourceData) -> str:
    blocklist = sources.acquisition_blocklist
    blocked = blocklist.get("blocked_modalities", blocklist.get("sessions", {}))
    if not isinstance(blocked, dict) or not blocked:
        return PLACEHOLDER
    parts: list[str] = []
    for session_key, modalities in blocked.items():
        if not isinstance(modalities, dict):
            continue
        for modality, reasons in modalities.items():
            reason_text = "; ".join(reasons) if isinstance(reasons, list) else str(reasons)
            parts.append(f"{session_key}/{modality} ({reason_text})")
    return "; ".join(parts) if parts else PLACEHOLDER


def _steps_completed_text(sources: MethodsSourceData) -> str:
    steps = sources.manifest.get("steps_completed", [])
    if isinstance(steps, list) and steps:
        return ", ".join(str(step) for step in steps)
    research_steps = sources.research_checkpoints.get("steps", {})
    if isinstance(research_steps, dict) and research_steps:
        completed = [
            name
            for name, record in research_steps.items()
            if isinstance(record, dict) and record.get("status") == "success"
        ]
        if completed:
            return ", ".join(sorted(completed))
    return PLACEHOLDER


def _context_parameters(step: str, sources: MethodsSourceData) -> dict[str, Any]:
    context = sources.step_contexts.get(step, {})
    parameters = context.get("parameters", {})
    return parameters if isinstance(parameters, dict) else {}


def _section_dataset_preparation(sources: MethodsSourceData) -> list[str]:
    n_subjects, n_sessions, n_series = _inventory_counts(sources)
    mapping_done = step_was_completed(sources, "generate_mapping")
    inventory_done = step_was_completed(sources, "inventory")

    paragraphs = [
        "## 1. Dataset preparation",
        "",
        (
            "Source neuroimaging data were provided as DICOM files organized under "
            f"`{resolve_value(sources.manifest.get('paths', {}).get('raw_original') if isinstance(sources.manifest.get('paths'), dict) else None, default=PLACEHOLDER)}`. "
            "The inventory step scanned cohort-labelled subject folders and extracted "
            "StudyInstanceUID, SeriesInstanceUID, modality, and series metadata for each "
            "discovered acquisition."
        ),
        "",
        (
            f"Inventory records indicated {n_subjects} subject(s), {n_sessions} session(s), "
            f"and {n_series} indexed series instance(s) prior to conversion."
            if inventory_done or not sources.inventory.empty
            else (
                "Subject and session counts prior to conversion were "
                f"{PLACEHOLDER} because inventory outputs were not available."
            )
        ),
        "",
        (
            "Internal BIDS participant and session identifiers (for example, `sub-001`, "
            "`ses-01`) were assigned during the mapping step using deterministic "
            "pseudonyms derived from cohort, source subject folder, source subject path, "
            "and aggregated StudyInstanceUID values. Participant mapping tables were "
            "stored separately from the BIDS dataset and were not intended for public release."
            if mapping_done
            else (
                "Internal BIDS pseudonym assignment was "
                f"{PLACEHOLDER} because mapping step completion was not recorded."
            )
        ),
        "",
        (
            "This research pipeline stage performs pseudonymization of internal identifiers "
            "and does not constitute public-release anonymization. Public anonymization "
            "is described separately in Section 6 when release checkpoints are available."
        ),
    ]
    return paragraphs


def _section_dicom_to_bids(sources: MethodsSourceData) -> list[str]:
    versions = collect_software_versions(sources)
    dcm2niix_version = resolve_value(
        versions.get("dcm2niix"),
        sources.manifest.get("dcm2niix_version"),
    )
    bids_version = resolve_value(
        sources.provenance.get("bids_version"),
    )
    convert_params = _context_parameters("convert_to_bids", sources)
    dcm2niix_path = resolve_value(convert_params.get("dcm2niix_path"))
    success, failed, skipped = _conversion_counts(sources)
    conversion_done = step_was_completed(sources, "convert_to_bids")

    param_text = PLACEHOLDER
    if convert_params:
        rendered = ", ".join(f"{key}={value}" for key, value in sorted(convert_params.items()))
        param_text = rendered or PLACEHOLDER

    paragraphs = [
        "## 2. DICOM to BIDS conversion",
        "",
        (
            f"Raw DICOM images were converted to BIDS format using dcm2niix version "
            f"{dcm2niix_version}."
            if conversion_done or dcm2niix_version != PLACEHOLDER
            else (
                "DICOM to BIDS conversion was performed using dcm2niix; the recorded "
                f"version was {PLACEHOLDER}."
            )
        ),
        "",
        (
            f"Recorded conversion parameters included: {param_text}."
            if param_text != PLACEHOLDER
            else (
                f"Detailed dcm2niix invocation parameters were {PLACEHOLDER}. "
                f"Per-series conversion logs were stored under "
                f"`{_artifact_path(sources, 'conversion_logs')}` "
                f"({sources.conversion_log_count} log file(s) present)."
            )
        ),
        "",
        (
            f"The target BIDS specification version recorded in pipeline provenance was "
            f"{bids_version}."
        ),
        "",
        (
            "Conversion outputs were written to the internal research BIDS dataset. "
            "Per-series conversion outcomes, dcm2niix return codes, and audit results "
            f"were logged in `{_artifact_path(sources, 'conversion_report')}`. "
            "Metadata preservation was assessed using per-series conversion audit checks "
            "and, when available, DICOM-to-NIfTI geometry validation outputs stored in "
            f"`{_artifact_path(sources, 'geometry_validation')}`."
        ),
        "",
        (
            f"Conversion summary counts recorded in the pipeline manifest were: "
            f"{success} successful, {failed} failed, and {skipped} skipped series."
            if success != PLACEHOLDER
            else f"Conversion summary counts were {PLACEHOLDER}."
        ),
    ]
    if dcm2niix_path != PLACEHOLDER:
        paragraphs.extend(["", f"The dcm2niix executable path recorded at conversion time was `{dcm2niix_path}`."])
    return paragraphs


def _section_acquisition_validation(sources: MethodsSourceData) -> list[str]:
    acq = sources.acquisition_validation
    passed = acq.get("passed")
    row_count = acq.get("row_count")
    error_count = acq.get("error_count")
    missing_count = acq.get("missing_count")
    warning_count = acq.get("warning_count")
    t1_blocked = acq.get("t1_blocked_sessions", [])
    validation_done = step_was_completed(sources, "validate_dataset") or bool(acq)

    t1_blocked_text = (
        ", ".join(str(item) for item in t1_blocked)
        if isinstance(t1_blocked, list) and t1_blocked
        else PLACEHOLDER
    )
    blocked_text = _blocked_modalities_text(sources)

    paragraphs = [
        "## 3. Acquisition validation",
        "",
        (
            "After BIDS conversion, acquisitions were evaluated against a study-specific "
            "acquisition catalog using custom acquisition consistency checks implemented "
            "in the neuro-bids-pipeline. Structural, functional, diffusion, and fieldmap "
            "acquisitions were matched by series description and protocol name patterns, "
            "BIDS datatype, task label, phase-encoding direction, and run index where "
            "applicable."
            if validation_done
            else (
                "Acquisition validation against the study-specific catalog was "
                f"{PLACEHOLDER} because validation outputs were not available."
            )
        ),
        "",
        (
            "SeriesInstanceUID values from the session mapping and BIDS JSON sidecars "
            "were used to trace converted files back to source DICOM series. "
            "Phase-encoding AP/PA pairs and run identity were verified when present in "
            "the expected acquisition definitions."
        ),
        "",
        (
            f"Acquisition validation summary counts were: {row_count} evaluated row(s), "
            f"{error_count} error(s), {missing_count} missing acquisition(s), and "
            f"{warning_count} warning(s); overall pass status was `{passed}`."
            if row_count is not None
            else f"Acquisition validation summary counts were {PLACEHOLDER}."
        ),
        "",
        (
            f"Modality-specific blocking rules produced blocked modalities for: {blocked_text}."
            if blocked_text != PLACEHOLDER
            else (
                f"Modality-specific blocking records were {PLACEHOLDER} in "
                "`metadata/acquisition_blocklist.json`."
            )
        ),
        "",
        (
            f"Sessions with T1-dependent modalities blocked because of missing T1 "
            f"reference were: {t1_blocked_text}."
            if t1_blocked_text != PLACEHOLDER
            else f"T1-dependent blocking session records were {PLACEHOLDER}."
        ),
        "",
        (
            f"Detailed acquisition validation results were written to "
            f"`{_artifact_path(sources, 'acquisition_validation')}`."
        ),
    ]
    return paragraphs


def _section_quality_control(sources: MethodsSourceData) -> list[str]:
    qc_done = step_was_completed(sources, "quality_control") or not sources.qc_detail.empty
    qc_report = sources.qc_report
    volumes = qc_report.get("volumes")
    pass_count = qc_report.get("pass")
    warn_count = qc_report.get("warn")
    fail_count = qc_report.get("fail")

    paragraphs = [
        "## 4. Quality control",
        "",
        (
            "Quality control was performed using the neuro-bids-pipeline internal QC "
            "module, which scanned converted NIfTI volumes in the research BIDS dataset "
            "and recorded header readability, affine presence, JSON sidecar presence, "
            "file size, and derived pass/warn/fail status labels."
            if qc_done
            else f"Quality control outputs were {PLACEHOLDER}."
        ),
        "",
        f"Anatomical (`anat`) QC status summary: {_modality_qc_summary(sources, 'anat')}.",
        f"Functional (`func`) QC status summary: {_modality_qc_summary(sources, 'func')}.",
        f"Diffusion (`dwi`) QC status summary: {_modality_qc_summary(sources, 'dwi')}.",
        "",
        (
            f"Dataset-level QC counts recorded in `qc_report.json` were: "
            f"{volumes} volume(s), {pass_count} pass, {warn_count} warn, {fail_count} fail."
            if volumes is not None
            else f"Dataset-level QC counts were {PLACEHOLDER}."
        ),
        "",
        "Generated QC reports included:",
        f"- `{_artifact_path(sources, 'qc_detail')}`",
        f"- `{_artifact_path(sources, 'qc_summary')}`",
        f"- `{_artifact_path(sources, 'pipeline_qc_summary')}`",
        "",
        (
            f"Acquisition blocklist entries indicating excluded or blocked modalities "
            f"were: {_blocked_modalities_text(sources)}."
            if _blocked_modalities_text(sources) != PLACEHOLDER
            else (
                f"Explicit exclusion criteria beyond QC status labels were "
                f"{PLACEHOLDER} in pipeline metadata."
            )
        ),
    ]
    return paragraphs


def _section_integrity(sources: MethodsSourceData) -> list[str]:
    versions = collect_software_versions(sources)
    version_lines = [
        f"- {name}: {value}" for name, value in versions.items()
    ] or [f"- {PLACEHOLDER}"]

    locked = bool(sources.raw_bids_lock.get("immutable"))
    lock_time = resolve_value(sources.raw_bids_lock.get("locked_at"), default=PLACEHOLDER)
    file_count = resolve_value(sources.raw_bids_lock.get("file_count"), default=PLACEHOLDER)
    dataset_version = resolve_value(
        sources.raw_bids_lock.get("dataset_version"),
        sources.raw_bids_checksums.get("dataset_version"),
        default=PLACEHOLDER,
    )
    checksum_files = sources.raw_bids_checksums.get("file_count")
    input_hash = resolve_value(sources.provenance.get("input_dataset_hash"), default=PLACEHOLDER)
    execution_date = resolve_value(
        sources.provenance.get("execution_date"),
        sources.manifest.get("generated_at"),
        default=PLACEHOLDER,
    )
    git_commit = resolve_value(
        sources.provenance.get("git_commit"),
        default=PLACEHOLDER,
    )
    pipeline_version = resolve_value(
        sources.provenance.get("pipeline_version"),
        sources.manifest.get("pipeline_version"),
        default=PLACEHOLDER,
    )
    container_image = resolve_value(sources.provenance.get("container_image"), default=PLACEHOLDER)
    container_digest = resolve_value(sources.provenance.get("container_digest"), default=PLACEHOLDER)

    geometry_errors = sources.manifest.get("geometry_validation_errors")
    geometry_warnings = sources.manifest.get("geometry_validation_warnings")

    paragraphs = [
        "## 5. Data integrity and reproducibility",
        "",
        (
            f"The neuro-bids-pipeline version recorded in provenance was {pipeline_version} "
            f"(git commit `{git_commit}`)."
        ),
        "",
        (
            f"Research pipeline steps recorded as completed were: {_steps_completed_text(sources)}."
        ),
        "",
        (
            f"Execution timestamps recorded in pipeline provenance included "
            f"`{execution_date}`."
        ),
        "",
        "Software versions recorded in pipeline metadata were:",
        *version_lines,
        "",
        (
            f"The research BIDS dataset was checksum-locked at `{lock_time}` with "
            f"{file_count} file(s) and dataset version `{dataset_version}`."
            if locked
            else (
                f"Checksum locking status was {PLACEHOLDER}; "
                f"`metadata/raw_bids_lock.json` was not present or did not record immutability."
            )
        ),
        "",
        (
            f"The aggregate input dataset hash recorded in provenance was `{input_hash}`."
        ),
        "",
        (
            f"Checksum manifest file counts recorded {checksum_files} file(s) under "
            f"`metadata/raw_bids_checksums.json`."
            if checksum_files is not None
            else f"Checksum manifest details were {PLACEHOLDER}."
        ),
        "",
        (
            f"Geometry validation error and warning counts recorded in the pipeline "
            f"manifest were {geometry_errors} and {geometry_warnings}, respectively."
            if geometry_errors is not None
            else f"Geometry validation summary counts were {PLACEHOLDER}."
        ),
        "",
        (
            f"Container execution metadata recorded image `{container_image}` "
            f"(digest `{container_digest}`)."
            if container_image != PLACEHOLDER
            else f"Container execution metadata were {PLACEHOLDER}."
        ),
    ]
    return paragraphs


def _section_public_release(sources: MethodsSourceData) -> list[str]:
    release_done = step_was_completed(sources, "release_dataset", pipeline="release") or bool(
        sources.release_status
    )
    gate_done = step_was_completed(sources, "release_gate", pipeline="release") or bool(
        sources.release_gate_report
    )
    release_params = _context_parameters("release_dataset", sources)
    defacing_enabled = resolve_value(
        sources.release_status.get("defacing_applied"),
        sources.release_manifest.get("release_defacing_enabled"),
        release_params.get("defacing"),
        default=PLACEHOLDER,
    )
    defacing_reason = resolve_value(
        sources.release_manifest.get("release_defacing_reason"),
        release_params.get("defacing_reason"),
        default=PLACEHOLDER,
    )
    openneuro_mode = resolve_value(
        sources.release_status.get("openneuro_mode"),
        sources.release_manifest.get("openneuro_mode"),
        release_params.get("openneuro_mode"),
        default=PLACEHOLDER,
    )
    release_ready = resolve_value(
        sources.release_ready.get("ready"),
        sources.release_ready.get("release_ready"),
        default=PLACEHOLDER,
    )
    gate_passed = resolve_value(
        sources.release_gate_report.get("passed"),
        sources.release_gate_report.get("release_ready"),
        default=PLACEHOLDER,
    )

    paragraphs = [
        "## 6. Public release preparation",
        "",
        (
            "Public-release preparation was performed using the mri_anonymization "
            "release pipeline, which reads the locked internal research BIDS dataset "
            "and writes an anonymized BIDS dataset suitable for external sharing."
            if release_done
            else (
                f"Public-release preparation steps were {PLACEHOLDER} because release "
                "checkpoints or release status records were not available."
            )
        ),
        "",
        (
            f"Release anonymization parameters recorded in provenance included: "
            f"{', '.join(f'{k}={v}' for k, v in sorted(release_params.items()))}."
            if release_params
            else f"Release anonymization parameters were {PLACEHOLDER}."
        ),
        "",
        (
            f"Defacing was recorded as `{defacing_enabled}` (reason: {defacing_reason})."
            if defacing_enabled != PLACEHOLDER
            else f"Defacing status was {PLACEHOLDER}."
        ),
        "",
        (
            "Public dataset BIDS validation was performed during the release workflow "
            "when `validate_public_dataset` checkpoints were recorded."
            if step_was_completed(sources, "validate_public_dataset", pipeline="release")
            else f"Public dataset BIDS validation status was {PLACEHOLDER}."
        ),
        "",
        (
            f"Release gate evaluation recorded readiness `{release_ready}` and gate "
            f"pass status `{gate_passed}`."
            if release_ready != PLACEHOLDER or gate_passed != PLACEHOLDER
            else f"Release gate outcomes were {PLACEHOLDER}."
        ),
        "",
        (
            f"OpenNeuro-oriented release mode was recorded as `{openneuro_mode}`."
            if openneuro_mode != PLACEHOLDER
            else f"OpenNeuro release mode was {PLACEHOLDER}."
        ),
        "",
        (
            f"Release gate and readiness reports were stored in "
            f"`metadata/release_gate_report.json` and `metadata/release_ready.json`."
            if gate_done or sources.release_ready
            else f"Release gate report paths were {PLACEHOLDER}."
        ),
    ]
    return paragraphs


def build_methods_document(sources: MethodsSourceData) -> str:
    """Build manuscript-style METHODS markdown from provenance sources."""
    generated_at = resolve_value(
        sources.manifest.get("generated_at"),
        sources.research_checkpoints.get("updated_at"),
        default=PLACEHOLDER,
    )
    pipeline_version = resolve_value(
        sources.provenance.get("pipeline_version"),
        sources.manifest.get("pipeline_version"),
        default=PLACEHOLDER,
    )

    lines: list[str] = [
        "# Methods",
        "",
        "<!-- Generated automatically by neuro-bids-pipeline (neuro-generate-methods). -->",
        "<!-- Do not edit manually; regenerate from pipeline provenance when metadata change. -->",
        "",
        f"**Document generated from pipeline metadata recorded at:** {generated_at}  ",
        f"**Pipeline version:** {pipeline_version}",
        "",
        *_section_dataset_preparation(sources),
        "",
        *_section_dicom_to_bids(sources),
        "",
        *_section_acquisition_validation(sources),
        "",
        *_section_quality_control(sources),
        "",
        *_section_integrity(sources),
        "",
        *_section_public_release(sources),
        "",
    ]
    return "\n".join(lines).rstrip() + "\n"


def generate_methods_md(paths: ProjectPaths) -> Path:
    """Generate docs/METHODS.md from pipeline provenance artifacts."""
    paths.ensure_metadata_dir()
    output = paths.methods_md
    output.parent.mkdir(parents=True, exist_ok=True)

    sources = load_methods_sources(paths)
    document = build_methods_document(sources)
    output.write_text(document, encoding="utf-8")
    LOGGER.info("Wrote Methods document: %s", output)
    return output

