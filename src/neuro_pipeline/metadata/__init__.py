"""Metadata preservation package."""

from neuro_pipeline.metadata.metadata_models import MetadataSummary, SidecarInfo
from neuro_pipeline.metadata.sidecar_manager import MetadataManager

__all__ = ["MetadataManager", "MetadataSummary", "SidecarInfo"]
