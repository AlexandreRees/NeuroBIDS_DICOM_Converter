"""Project directory layout and artifact path resolution."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from neuro_pipeline.config.constants import COHORT_NAMES


@dataclass(frozen=True)
class ProjectPaths:
    """Canonical paths for a neuroimaging BIDS conversion project."""

    root: Path

    @property
    def raw_original(self) -> Path:
        """Immutable source DICOM directory."""
        return self.root / "raw_original"

    @property
    def staging(self) -> Path:
        """Legacy directory (deprecated — research pipeline reads raw_original directly)."""
        return self.root / "staging"

    @property
    def raw_bids(self) -> Path:
        """Canonical internal BIDS dataset for research analyses."""
        return self.root / "raw_bids"

    @property
    def anonymization_release(self) -> Path:
        """Public-release pipeline output root (Public_Dataset + Private/)."""
        return self.root / "anonymization_release"

    @property
    def public_dataset(self) -> Path:
        """Anonymized BIDS dataset safe for external sharing."""
        return self.anonymization_release / "Public_Dataset"

    @property
    def private_release(self) -> Path:
        """Private release artifacts (mappings, date shifts) — never publish."""
        return self.anonymization_release / "Private"

    @property
    def release_failed_files_csv(self) -> Path:
        """Failed files from public-release anonymization."""
        return self.private_release / "logs" / "failed_files.csv"

    @property
    def derivatives_root(self) -> Path:
        """Top-level BIDS derivatives directory."""
        return self.root / "derivatives"

    @property
    def derivatives(self) -> Path:
        """Pipeline-specific derivatives output root."""
        return self.derivatives_root / "neuro_pipeline"

    @property
    def metadata(self) -> Path:
        """Tabular outputs, manifests, and step logs."""
        return self.root / "metadata"

    @property
    def logs(self) -> Path:
        """Shared pipeline log directory."""
        return self.root / "logs"

    @property
    def inventory_csv(self) -> Path:
        """Discovered subject/session inventory."""
        return self.metadata / "inventory.csv"

    @property
    def inventory_warnings(self) -> Path:
        """Inventory step human-readable warning log."""
        return self.metadata / "inventory_warnings.log"

    @property
    def inventory_warnings_csv(self) -> Path:
        """Structured inventory warnings table."""
        return self.metadata / "inventory_warnings.csv"

    @property
    def inventory_corrupt_csv(self) -> Path:
        """Per-subject corrupted DICOM tracking table."""
        return self.metadata / "inventory_corrupt_dicom.csv"

    @property
    def participant_mapping_csv(self) -> Path:
        """Private source-to-BIDS participant pseudonym mapping (never publish)."""
        return self.metadata / "participant_mapping.csv"

    @property
    def session_mapping_csv(self) -> Path:
        """Session-level mapping table."""
        return self.metadata / "session_mapping.csv"

    @property
    def participants_tsv(self) -> Path:
        """BIDS participants.tsv."""
        return self.raw_bids / "participants.tsv"

    @property
    def dataset_description_json(self) -> Path:
        """BIDS dataset_description.json."""
        return self.raw_bids / "dataset_description.json"

    @property
    def pipeline_manifest_json(self) -> Path:
        """Machine-readable manifest for downstream extension tools."""
        return self.metadata / "pipeline_manifest.json"

    @property
    def research_checkpoints_json(self) -> Path:
        """Research pipeline step checkpoint store."""
        return self.metadata / "research_checkpoints.json"

    @property
    def release_checkpoints_json(self) -> Path:
        """Release pipeline step checkpoint store."""
        return self.metadata / "release_checkpoints.json"

    @property
    def methods_md(self) -> Path:
        """Manuscript-ready Methods section generated from pipeline provenance."""
        return self.root / "docs" / "METHODS.md"

    @property
    def deidentify_report_csv(self) -> Path:
        """Per-file de-identification report."""
        return self.metadata / "deidentify_report.csv"

    @property
    def conversion_report_csv(self) -> Path:
        """Per-series dcm2niix conversion report."""
        return self.derivatives / "conversion" / "conversion_report.csv"

    @property
    def conversion_logs_dir(self) -> Path:
        """dcm2niix per-series log directory."""
        return self.derivatives / "conversion" / "logs"

    @property
    def acquisition_validation_csv(self) -> Path:
        """Per-acquisition validation detail report."""
        return self.derivatives / "validation" / "acquisition_validation.csv"

    @property
    def acquisition_validation_json(self) -> Path:
        """Machine-readable acquisition validation report."""
        return self.derivatives / "validation" / "acquisition_validation.json"

    @property
    def acquisition_blocklist_json(self) -> Path:
        """Per-session modality blocklist for downstream processing."""
        return self.metadata / "acquisition_blocklist.json"

    @property
    def geometry_validation_csv(self) -> Path:
        """DICOM → NIfTI geometry validation detail report."""
        return self.derivatives / "validation" / "geometry_validation.csv"

    @property
    def pipeline_qc_summary_html(self) -> Path:
        """Publication-ready HTML QC summary aggregating validation outputs."""
        return self.derivatives / "qc" / "pipeline_qc_summary.html"

    @property
    def derivatives_dataset_description_json(self) -> Path:
        """BIDS derivatives dataset_description.json."""
        return self.derivatives / "dataset_description.json"

    @property
    def validation_report_json(self) -> Path:
        """BIDS validator JSON output."""
        return self.derivatives / "validation" / "bids_validation_report.json"

    @property
    def validation_summary_csv(self) -> Path:
        """Flattened BIDS validation summary."""
        return self.derivatives / "validation" / "bids_validation_summary.csv"

    @property
    def qc_summary_csv(self) -> Path:
        """Dataset-level QC summary."""
        return self.derivatives / "qc" / "qc_summary.csv"

    @property
    def qc_detail_csv(self) -> Path:
        """Per-scan QC detail table."""
        return self.derivatives / "qc" / "qc_detail.csv"

    @property
    def mriqc_output_dir(self) -> Path:
        """MRIQC IQM outputs (BIDS derivatives layout)."""
        return self.derivatives_root / "mriqc"

    @property
    def mriqc_work_dir(self) -> Path:
        """Scratch directory for MRIQC container working files."""
        return self.metadata / "mriqc_work"

    @property
    def mriqc_config_yaml(self) -> Path:
        """Optional project-local MRIQC configuration override."""
        return self.metadata / "mriqc_config.yaml"

    @property
    def mriqc_log(self) -> Path:
        """MRIQC step log file."""
        return self.metadata / "mriqc.log"

    @property
    def mriqc_run_summary_json(self) -> Path:
        """Global MRIQC execution summary."""
        return self.mriqc_output_dir / "mriqc_run_summary.json"

    @property
    def mriqc_report_links_dir(self) -> Path:
        """Linked/copied MRIQC HTML reports for the QC report bundle."""
        return self.derivatives / "qc" / "mriqc_reports"

    def mriqc_modality_output_dir(self, modality: str) -> Path:
        """MRIQC outputs for one modality (independent BIDS derivatives subtree)."""
        return self.mriqc_output_dir / modality

    def mriqc_modality_work_dir(self, modality: str) -> Path:
        """Scratch directory for one MRIQC modality run."""
        return self.mriqc_work_dir / modality

    def mriqc_modality_report_links_dir(self, modality: str) -> Path:
        """Linked HTML reports for one MRIQC modality."""
        return self.mriqc_report_links_dir / modality

    @property
    def defacing_report_json(self) -> Path:
        """Global defacing report."""
        return self.derivatives / "defacing" / "defacing_report.json"

    @property
    def release_gate_report_json(self) -> Path:
        """Public-release gate report."""
        return self.metadata / "release_gate_report.json"

    @property
    def release_blockers_csv(self) -> Path:
        """Public-release gate blocker table."""
        return self.metadata / "release_blockers.csv"

    @property
    def release_ready_json(self) -> Path:
        """Public-release readiness flag."""
        return self.metadata / "release_ready.json"

    @property
    def publication_gate_report_json(self) -> Path:
        """Deprecated alias — use release_gate_report_json."""
        return self.release_gate_report_json

    @property
    def publication_blockers_csv(self) -> Path:
        """Deprecated alias — use release_blockers_csv."""
        return self.release_blockers_csv

    @property
    def publication_ready_json(self) -> Path:
        """Deprecated alias — use release_ready_json."""
        return self.release_ready_json

    @property
    def master_log(self) -> Path:
        """Orchestrator master log file."""
        return self.logs / "pipeline_master.log"

    def defacing_session_log(self, participant_id: str, session_label: str) -> Path:
        """Per-session defacing log path under derivatives."""
        return (
            self.derivatives
            / participant_id
            / session_label
            / "logs"
            / "defacing_report.json"
        )

    def defacing_output_dir(
        self,
        participant_id: str,
        session_label: str,
    ) -> Path:
        """Defaced anatomical output directory for a session."""
        return self.derivatives / participant_id / session_label / "anat"

    def ensure_metadata_dir(self) -> None:
        """Create metadata directory if missing."""
        self.metadata.mkdir(parents=True, exist_ok=True)

    def ensure_logs_dir(self) -> None:
        """Create logs directory if missing."""
        self.logs.mkdir(parents=True, exist_ok=True)

    def ensure_derivatives_dir(self) -> None:
        """Create pipeline derivatives directory if missing."""
        self.derivatives.mkdir(parents=True, exist_ok=True)

    def validate_project_root(self) -> None:
        """Verify the project root contains required top-level folders."""
        if not self.root.is_dir():
            raise FileNotFoundError(f"Project root does not exist: {self.root}")
        if not self.raw_original.is_dir():
            raise FileNotFoundError(
                f"Missing required directory: {self.raw_original}"
            )

    def validate_writable(self, path: Path) -> None:
        """Ensure a directory exists and is writable."""
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".write_probe"
        try:
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
        except OSError as exc:
            raise PermissionError(f"Directory not writable: {path}") from exc


def resolve_project_root(project_root: Path | None) -> ProjectPaths:
    """Resolve and validate project paths from an optional root argument."""
    root = (project_root or Path.cwd()).resolve()
    paths = ProjectPaths(root=root)
    paths.validate_project_root()
    return paths
