"""Required artifacts per pipeline step for resume support."""

from __future__ import annotations

from neuro_pipeline.utils.paths import ProjectPaths


def research_step_artifacts(paths: ProjectPaths, step: str) -> list:
    """Return artifact paths that must exist for a research step to be considered complete."""
    derivatives = paths.derivatives
    mapping: dict[str, list] = {
        "inventory": [paths.inventory_csv],
        "generate_mapping": [paths.participant_mapping_csv, paths.session_mapping_csv],
        "convert_to_bids": [
            paths.raw_bids,
            derivatives / "conversion" / "conversion_report.csv",
            derivatives / "conversion" / "conversion_audit.csv",
            derivatives / "validation" / "acquisition_validation.csv",
            paths.acquisition_blocklist_json,
        ],
        "validate_dataset": [
            derivatives / "validation" / "bids_validation_report.json",
            derivatives / "validation" / "bids_integrity_report.json",
            derivatives / "validation" / "acquisition_validation.csv",
            paths.acquisition_blocklist_json,
        ],
        "quality_control": [
            derivatives / "qc" / "qc_detail.csv",
            derivatives / "qc" / "qc_report.html",
        ],
        "derivatives_build": [
            paths.metadata / "raw_bids_lock.json",
            paths.metadata / "raw_bids_checksums.json",
        ],
    }
    return mapping.get(step, [])


def release_step_artifacts(paths: ProjectPaths, step: str) -> list:
    mapping: dict[str, list] = {
        "anonymize": [
            paths.public_dataset,
            paths.anonymization_release / "release_manifest.json",
        ],
        "validate_public_dataset": [
            paths.anonymization_release / "validation" / "bids_validation_report.json",
            paths.anonymization_release / "validation" / "bids_validation_summary.csv",
        ],
        "release_gate": [
            paths.release_ready_json,
            paths.metadata / "openneuro_readiness_report.json",
        ],
    }
    return mapping.get(step, [])
