"""Record conversion provenance under derivatives/neuro_pipeline/."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from neuro_pipeline import __version__
from neuro_pipeline.provenance.hash_manager import HashManager
from neuro_pipeline.provenance.models import (
    ConversionInfo,
    ConversionProvenance,
    PathHash,
    SoftwareInfo,
)

LOGGER = logging.getLogger(__name__)


class ProvenanceRecorder:
    """Write SHA-256 provenance artifacts after conversion (never touches sources)."""

    def __init__(self, hash_manager: HashManager | None = None) -> None:
        self.hash_manager = hash_manager or HashManager()

    def hash_input(self, dicom_folder: Path | str) -> PathHash:
        """Hash source DICOM folder contents (read-only)."""
        root = Path(dicom_folder)
        digest, _ = self.hash_manager.hash_folder(root)
        return PathHash(path=str(root.resolve()), hash=digest)

    def hash_output(self, output_folder: Path | str) -> tuple[PathHash, list[dict[str, str]]]:
        """Hash conversion outputs (NIfTI/BIDS/JSON), excluding derivatives metadata loops."""
        root = Path(output_folder)
        digest, records = self.hash_manager.hash_folder(root)
        # Filter nested provenance for manifest clarity
        filtered = [
            r
            for r in records
            if not r["path"].startswith("derivatives/neuro_pipeline/")
        ]
        return PathHash(path=str(root.resolve()), hash=digest), filtered

    def write(
        self,
        *,
        dataset_or_output_root: Path | str,
        input_path: Path | str,
        input_hash: PathHash | None = None,
        dcm2niix_version: str = "",
        parameters: Mapping[str, Any] | None = None,
    ) -> Path:
        """Create ``derivatives/neuro_pipeline/conversion_provenance.json`` (+ manifest)."""
        root = Path(dataset_or_output_root)
        deriv = root / "derivatives" / "neuro_pipeline"
        deriv.mkdir(parents=True, exist_ok=True)

        if input_hash is None:
            input_hash = self.hash_input(input_path)

        output_hash, file_records = self.hash_output(root)
        stamp = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")

        provenance = ConversionProvenance(
            software=SoftwareInfo(name="NeuroPipeline", version=__version__),
            conversion=ConversionInfo(
                date=stamp,
                dcm2niix_version=dcm2niix_version or "",
                parameters=dict(parameters or {}),
            ),
            input=input_hash,
            output=output_hash,
            files=file_records,
        )

        prov_path = deriv / "conversion_provenance.json"
        prov_path.write_text(
            json.dumps(provenance.to_dict(), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

        manifest = {
            "generated_at": stamp,
            "input": provenance.input.__dict__
            if hasattr(provenance.input, "__dict__")
            else {
                "path": provenance.input.path,
                "hash": provenance.input.hash,
            },
            "output_root": str(root.resolve()),
            "file_count": len(file_records),
            "files": file_records,
            "provenance_file": str(prov_path.relative_to(root)),
        }
        manifest_path = deriv / "conversion_manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        LOGGER.info("Wrote provenance: %s", prov_path)
        return prov_path
