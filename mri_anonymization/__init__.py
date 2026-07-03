"""Production-grade MRI dataset anonymization for public neuroimaging release."""

from mri_anonymization.config import AnonymizationConfig
from mri_anonymization.pipeline import AnonymizationPipeline

__version__ = "2.0.0"
__all__ = ["AnonymizationConfig", "AnonymizationPipeline", "__version__"]
