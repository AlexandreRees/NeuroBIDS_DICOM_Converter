"""Project directory layout and artifact path resolution."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


COHORT_NAMES: tuple[str, ...] = ("Controls", "Data_ON", "Data_TON", "Glaucoma")


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
        """Anonymized DICOM staging area."""
        return self.root / "staging"

    @property
    def raw_bids(self) -> Path:
        """Final BIDS raw dataset root."""
        return self.root / "raw_bids"

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
        """Source-to-BIDS participant mapping."""
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
    def defacing_report_json(self) -> Path:
        """Global defacing report."""
        return self.derivatives / "defacing" / "defacing_report.json"

    @property
    def publication_gate_report_json(self) -> Path:
        """Publication gate full report."""
        return self.metadata / "publication_gate_report.json"

    @property
    def publication_blockers_csv(self) -> Path:
        """Publication gate blocker table."""
        return self.metadata / "publication_blockers.csv"

    @property
    def publication_ready_json(self) -> Path:
        """Publication readiness flag."""
        return self.metadata / "publication_ready.json"

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
