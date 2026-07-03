"""Output path layout for public and private anonymization artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AnonymizationPaths:
    """Canonical paths for anonymization outputs."""

    output_root: Path

    @property
    def public_dataset(self) -> Path:
        """Public BIDS dataset root."""
        return self.output_root / "Public_Dataset"

    @property
    def private(self) -> Path:
        """Private mapping and audit data (never publish)."""
        return self.output_root / "Private"

    @property
    def subject_mapping_csv(self) -> Path:
        """Original-to-anonymized subject mapping."""
        return self.private / "subject_mapping.csv"

    @property
    def date_shift_csv(self) -> Path:
        """Per-subject date shift offsets in days."""
        return self.private / "date_shift.csv"

    @property
    def logs_dir(self) -> Path:
        """Processing logs directory."""
        return self.private / "logs"

    @property
    def processing_log(self) -> Path:
        """Main processing log file."""
        return self.logs_dir / "processing.log"

    @property
    def skipped_files_csv(self) -> Path:
        """Skipped file audit table."""
        return self.logs_dir / "skipped_files.csv"

    @property
    def failed_files_csv(self) -> Path:
        """Failed file audit table."""
        return self.logs_dir / "failed_files.csv"

    @property
    def anonymization_summary_csv(self) -> Path:
        """Per-file processing summary."""
        return self.logs_dir / "anonymization_summary.csv"

    @property
    def defacing_report_csv(self) -> Path:
        """Defacing outcome report."""
        return self.logs_dir / "defacing_report.csv"

    @property
    def validation_report_md(self) -> Path:
        """Public validation report."""
        return self.public_dataset / "validation_report.md"

    @property
    def anonymization_md(self) -> Path:
        """Public anonymization documentation."""
        return self.public_dataset / "ANONYMIZATION.md"

    @property
    def dataset_description_json(self) -> Path:
        """BIDS dataset_description.json."""
        return self.public_dataset / "dataset_description.json"

    @property
    def participants_tsv(self) -> Path:
        """BIDS participants.tsv."""
        return self.public_dataset / "participants.tsv"

    @property
    def readme(self) -> Path:
        """Dataset README."""
        return self.public_dataset / "README.md"

    @property
    def changes(self) -> Path:
        """BIDS CHANGES file."""
        return self.public_dataset / "CHANGES"

    @property
    def license_file(self) -> Path:
        """Dataset LICENSE file."""
        return self.public_dataset / "LICENSE"

    def ensure_directories(self) -> None:
        """Create output directories."""
        self.public_dataset.mkdir(parents=True, exist_ok=True)
        self.private.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
