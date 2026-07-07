"""BIDS derivatives metadata and enhanced pipeline provenance."""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

from neuro_pipeline.bids_constants import BIDS_SPEC_VERSION
from neuro_pipeline.utils.execution_context import ExecutionContext
from neuro_pipeline.utils.extensions import PIPELINE_VERSION
from neuro_pipeline.utils.paths import ProjectPaths

LOGGER = logging.getLogger(__name__)

DERIVATIVES_NAME = "neuro-bids-pipeline derivatives"


def compute_dataset_hash_from_checksum_manifest(manifest: dict[str, Any]) -> str:
    """Return an aggregate SHA256 over sorted per-file checksums."""
    digest = hashlib.sha256()
    files = manifest.get("files", [])
    if not isinstance(files, list):
        return ""
    for entry in sorted(files, key=lambda item: str(item.get("relative_path", ""))):
        if not isinstance(entry, dict):
            continue
        digest.update(str(entry.get("relative_path", "")).encode())
        digest.update(str(entry.get("sha256", "")).encode())
    return digest.hexdigest()


def resolve_input_dataset_hash(paths: ProjectPaths) -> str:
    """Resolve locked raw_bids checksum aggregate hash when available."""
    checksum_path = paths.metadata / "raw_bids_checksums.json"
    if checksum_path.is_file():
        manifest = json.loads(checksum_path.read_text(encoding="utf-8"))
        aggregate = compute_dataset_hash_from_checksum_manifest(manifest)
        if aggregate:
            return aggregate
        return str(manifest.get("dataset_version", ""))
    return "unavailable"


def build_derivatives_dataset_description(
    paths: ProjectPaths,
    *,
    context: ExecutionContext | None = None,
) -> dict[str, Any]:
    """Build BIDS derivatives dataset_description.json payload."""
    ctx = context or ExecutionContext.capture(project_root=paths.root)
    generated_by: dict[str, Any] = {
        "Name": "neuro-bids-pipeline",
        "Version": PIPELINE_VERSION,
        "Code": f"git+{ctx.git_commit}",
    }
    if ctx.python_version:
        generated_by["PythonVersion"] = ctx.python_version
    for key, value in ctx.software_versions.items():
        generated_by[key] = value
    if ctx.container_image:
        generated_by["Container"] = ctx.container_image
    if ctx.container_digest:
        generated_by["ContainerDigest"] = ctx.container_digest

    return {
        "Name": DERIVATIVES_NAME,
        "BIDSVersion": BIDS_SPEC_VERSION,
        "DatasetType": "derivative",
        "GeneratedBy": [generated_by],
        "SourceDatasets": [
            {
                "URL": str(paths.raw_bids.resolve()),
                "Version": resolve_input_dataset_hash(paths),
            }
        ],
    }


def write_derivatives_dataset_description(
    paths: ProjectPaths,
    *,
    context: ExecutionContext | None = None,
) -> Path:
    """Write derivatives/neuro_pipeline/dataset_description.json."""
    paths.ensure_derivatives_dir()
    payload = build_derivatives_dataset_description(paths, context=context)
    output = paths.derivatives_dataset_description_json
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    LOGGER.info("Wrote derivatives dataset_description.json: %s", output)
    return output


def build_provenance_block(
    paths: ProjectPaths,
    *,
    context: ExecutionContext | None = None,
    parameters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build provenance metadata for pipeline_manifest.json."""
    ctx = context or ExecutionContext.capture(project_root=paths.root)
    return {
        "execution_date": ctx.started_at,
        "execution_id": ctx.execution_id,
        "pipeline_version": ctx.pipeline_version,
        "git_commit": ctx.git_commit,
        "git_dirty": ctx.git_dirty,
        "python_version": ctx.python_version,
        "platform": ctx.platform,
        "bids_version": BIDS_SPEC_VERSION,
        "software_versions": dict(ctx.software_versions),
        "parameters": dict(parameters or ctx.parameters),
        "input_dataset_hash": resolve_input_dataset_hash(paths),
        "output_paths": {
            "raw_bids": str(paths.raw_bids.resolve()),
            "derivatives": str(paths.derivatives.resolve()),
            "metadata": str(paths.metadata.resolve()),
        },
        "container_image": ctx.container_image,
        "container_digest": ctx.container_digest,
    }
