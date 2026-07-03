"""Configuration for the MRI anonymization pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class AnonymizationConfig:
    """Runtime configuration for public dataset anonymization."""

    input_dir: Path
    output_root: Path
    enable_defacing: bool = False
    seed: str | None = None
    preserve_patient_sex: bool = True
    num_workers: int = 4
    dataset_name: str = "Anonymized Neuroimaging Dataset"
    license_text: str = "CC0"

    @property
    def deterministic(self) -> bool:
        """Return True when a reproducibility seed is provided."""
        return self.seed is not None

    @property
    def random_mode(self) -> bool:
        """Return True when cryptographically random anonymization is used."""
        return self.seed is None

    def validate(self) -> None:
        """Validate configuration values."""
        if not self.input_dir.is_dir():
            raise FileNotFoundError(f"Input directory not found: {self.input_dir}")
        if self.num_workers < 1:
            raise ValueError("num_workers must be >= 1")
