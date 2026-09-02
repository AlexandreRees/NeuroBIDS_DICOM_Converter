"""Optional BIDS export package."""

from neuro_pipeline.bids.conversion_plan import (
    BIDSConversionPlan,
    PlannedAcquisition,
    PlanValidationResult,
)
from neuro_pipeline.bids.entities_manager import BIDSEntityResolver, ResolvedEntities
from neuro_pipeline.bids.exporter import BIDSExporter, BidsExportResult
from neuro_pipeline.bids.longitudinal import LongitudinalManager
from neuro_pipeline.bids.metadata_validator import MetadataValidator, MetadataValidationResult
from neuro_pipeline.bids.naming import (
    build_bids_target,
    build_fallback_nifti_target,
    subject_id_from_series,
)
from neuro_pipeline.bids.naming_rules import NamingRule, SmartNamingRulesEngine
from neuro_pipeline.bids.subject_manager import SubjectManager
from neuro_pipeline.bids.validator import BIDSValidationResult, BIDSValidator

__all__ = [
    "BIDSConversionPlan",
    "BIDSExporter",
    "BidsExportResult",
    "BIDSEntityResolver",
    "BIDSValidator",
    "BIDSValidationResult",
    "LongitudinalManager",
    "MetadataValidator",
    "MetadataValidationResult",
    "NamingRule",
    "PlannedAcquisition",
    "PlanValidationResult",
    "ResolvedEntities",
    "SmartNamingRulesEngine",
    "SubjectManager",
    "build_bids_target",
    "build_fallback_nifti_target",
    "subject_id_from_series",
]
