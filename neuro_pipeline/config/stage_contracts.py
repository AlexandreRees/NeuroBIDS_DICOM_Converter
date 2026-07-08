"""Explicit input/output contracts and validation criteria per pipeline stage."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from neuro_pipeline.utils.paths import ProjectPaths


@dataclass(frozen=True)
class StageContract:
    """Definition of one pipeline stage."""

    name: str
    description: str
    inputs: tuple[str, ...]
    outputs: tuple[str, ...]
    validation_criteria: tuple[str, ...]
    log_path: str


def research_stage_contracts(paths: ProjectPaths) -> dict[str, StageContract]:
    """Return research pipeline stage contracts resolved to project paths."""
    derivatives = paths.derivatives
    return {
        "inventory": StageContract(
            name="inventory",
            description="Discover DICOM subjects/sessions under raw_original/",
            inputs=("raw_original/",),
            outputs=(
                str(paths.inventory_csv.relative_to(paths.root)),
                str(paths.inventory_warnings_csv.relative_to(paths.root)),
            ),
            validation_criteria=(
                "inventory.csv exists and is non-empty",
                "no fatal corruption blocking all subjects",
            ),
            log_path=str((paths.metadata / "inventory.log").relative_to(paths.root)),
        ),
        "generate_mapping": StageContract(
            name="generate_mapping",
            description="Assign private internal pseudonyms (sub-001, ses-01)",
            inputs=(
                str(paths.inventory_csv.relative_to(paths.root)),
            ),
            outputs=(
                str(paths.participant_mapping_csv.relative_to(paths.root)),
                str(paths.session_mapping_csv.relative_to(paths.root)),
            ),
            validation_criteria=(
                "one participant_id per source subject",
                "session labels unique per participant",
            ),
            log_path=str((paths.metadata / "generate_mapping.log").relative_to(paths.root)),
        ),
        "convert_to_bids": StageContract(
            name="convert_to_bids",
            description="Convert raw_original DICOM to canonical raw_bids/",
            inputs=(
                "raw_original/",
                str(paths.session_mapping_csv.relative_to(paths.root)),
            ),
            outputs=(
                "raw_bids/",
                str((derivatives / "conversion/conversion_report.csv").relative_to(paths.root)),
                str((derivatives / "conversion/conversion_audit.csv").relative_to(paths.root)),
            ),
            validation_criteria=(
                "at least one successful conversion",
                "conversion audit passes geometry/metadata checks",
                "raw_bids checksum manifest written",
            ),
            log_path=str((paths.metadata / "convert_to_bids.log").relative_to(paths.root)),
        ),
        "validate_dataset": StageContract(
            name="validate_dataset",
            description="Run bids-validator and advanced BIDS integrity checks",
            inputs=("raw_bids/",),
            outputs=(
                str((derivatives / "validation/bids_validation_report.json").relative_to(paths.root)),
                str((derivatives / "validation/bids_integrity_report.json").relative_to(paths.root)),
            ),
            validation_criteria=(
                "bids-validator reports zero errors (unless explicitly skipped)",
                "advanced integrity checks pass",
            ),
            log_path=str((paths.metadata / "validate_dataset.log").relative_to(paths.root)),
        ),
        "quality_control": StageContract(
            name="quality_control",
            description="NIfTI header QC and HTML/JSON QC reports",
            inputs=("raw_bids/",),
            outputs=(
                str((derivatives / "qc/qc_detail.csv").relative_to(paths.root)),
                str((derivatives / "qc/qc_report.html").relative_to(paths.root)),
            ),
            validation_criteria=("zero failed volumes",),
            log_path=str((paths.metadata / "quality_control.log").relative_to(paths.root)),
        ),
        "derivatives_build": StageContract(
            name="derivatives_build",
            description="Finalize derivatives layout and lock raw_bids immutability",
            inputs=("raw_bids/",),
            outputs=(
                str((paths.metadata / "raw_bids_checksums.json").relative_to(paths.root)),
                str((paths.metadata / "raw_bids_lock.json").relative_to(paths.root)),
            ),
            validation_criteria=(
                "raw_bids contains no pipeline artifacts",
                "raw_bids checksum manifest matches locked state",
            ),
            log_path=str((paths.metadata / "derivatives_build.log").relative_to(paths.root)),
        ),
    }


def release_stage_contracts(paths: ProjectPaths) -> dict[str, StageContract]:
    """Return public-release pipeline stage contracts."""
    return {
        "anonymize": StageContract(
            name="anonymize",
            description="PS3.15 anonymization of raw_bids for external sharing",
            inputs=("raw_bids/",),
            outputs=(
                str(paths.public_dataset.relative_to(paths.root)),
                str((paths.anonymization_release / "release_manifest.json").relative_to(paths.root)),
            ),
            validation_criteria=(
                "zero failed files",
                "anonymization validation report PASS",
                "only intended metadata modified",
            ),
            log_path=str((paths.metadata / "release_dataset.log").relative_to(paths.root)),
        ),
        "release_gate": StageContract(
            name="release_gate",
            description="OpenNeuro readiness gate for Public_Dataset/",
            inputs=(str(paths.public_dataset.relative_to(paths.root)),),
            outputs=(
                str(paths.release_ready_json.relative_to(paths.root)),
                str((paths.metadata / "openneuro_readiness_report.html").relative_to(paths.root)),
            ),
            validation_criteria=("release_ready=true", "no private data leaks"),
            log_path=str((paths.metadata / "release_gate.log").relative_to(paths.root)),
        ),
    }
