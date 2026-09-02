"""Multi-scanner detection support (Level 8)."""

from neuro_pipeline.scanner.models import ScannerInfo
from neuro_pipeline.scanner.scanner_detector import AutoDetector, ScannerDetector
from neuro_pipeline.scanner.scanner_profiles import (
    ScannerProfile,
    load_all_profiles,
    load_profile,
    select_profile_for_manufacturer,
)

__all__ = [
    "ScannerInfo",
    "ScannerDetector",
    "AutoDetector",
    "ScannerProfile",
    "load_all_profiles",
    "load_profile",
    "select_profile_for_manufacturer",
]
