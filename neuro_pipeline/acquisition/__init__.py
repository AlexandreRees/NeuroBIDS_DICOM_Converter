"""Acquisition discovery, catalog, and consistency validation."""

from neuro_pipeline.acquisition.catalog import (
    ACQUISITION_PAIRS,
    EXPECTED_ACQUISITIONS,
    T1_ACQUISITION_ID,
    T1_DEPENDENT_MODALITIES,
    ExpectedAcquisition,
)
from neuro_pipeline.acquisition.consistency import (
    AcquisitionConsistencyReport,
    run_acquisition_validation,
)
from neuro_pipeline.acquisition.integrity import ModalityIntegrityResult

__all__ = [
    "ACQUISITION_PAIRS",
    "EXPECTED_ACQUISITIONS",
    "T1_ACQUISITION_ID",
    "T1_DEPENDENT_MODALITIES",
    "AcquisitionConsistencyReport",
    "ExpectedAcquisition",
    "ModalityIntegrityResult",
    "run_acquisition_validation",
]
