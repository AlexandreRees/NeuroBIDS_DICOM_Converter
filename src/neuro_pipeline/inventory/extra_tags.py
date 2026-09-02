"""Optional DICOM tag readout from parser-identified sample files only."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger(__name__)

# Tags not always stored on DicomSeries / DicomSeriesMetadata today.
# Reading only the parser's sample_file keeps inventory synchronized with discovery.
OPTIONAL_TAGS: tuple[str, ...] = (
    "SequenceName",
    "SequenceVariant",
    "ScanningSequence",
    "InversionTime",
    "PixelBandwidth",
    "PhaseEncodingDirection",
    "InPlanePhaseEncodingDirectionDICOM",
    "SpacingBetweenSlices",
    "StationName",
    "InstitutionName",
    "BodyPartExamined",
    "PatientPosition",
    "ReceiveCoilName",
    "TransmitCoilName",
    "AcquisitionNumber",
    "ImagingFrequency",
)


def read_optional_tags(sample_file: Path | str | None) -> dict[str, Any]:
    """Read optional metadata tags from one already-discovered DICOM sample.

    Does **not** walk the dataset tree. Pixel data is never loaded.
    """
    if not sample_file:
        return {}
    path = Path(sample_file)
    if not path.is_file():
        return {}
    try:
        from pydicom import dcmread

        ds = dcmread(str(path), stop_before_pixels=True, force=True)
    except Exception as exc:  # noqa: BLE001
        LOGGER.debug("Optional tag read failed for %s: %s", path, exc)
        return {}

    out: dict[str, Any] = {}
    for tag in OPTIONAL_TAGS:
        if not hasattr(ds, tag):
            continue
        value = getattr(ds, tag, None)
        if value in (None, "", []):
            continue
        try:
            if hasattr(value, "__iter__") and not isinstance(value, (str, bytes)):
                out[tag] = "\\".join(str(x) for x in value)
            else:
                out[tag] = value
        except Exception:  # noqa: BLE001
            out[tag] = str(value)

    # Multiband / SMS factor — common Siemens private / public locations
    multiband = _multiband_factor(ds)
    if multiband is not None:
        out["MultibandFactor"] = multiband
    return out


def _multiband_factor(ds: Any) -> float | int | str | None:
    for attr in (
        "MultibandFactor",
        "EmultiBandFactor",
        "BandwidthPerPixelPhaseEncode",
    ):
        if hasattr(ds, attr) and getattr(ds, attr) not in (None, ""):
            return getattr(ds, attr)
    # Siemens CSA-ish text may appear in ImageComments / SequenceName
    blob = " ".join(
        str(getattr(ds, a, "") or "")
        for a in ("ImageComments", "SequenceName", "ProtocolName", "SeriesDescription")
    ).lower()
    if "mb" in blob:
        import re

        m = re.search(r"\bmb\s*([0-9]+(?:\.[0-9]+)?)", blob)
        if m:
            return m.group(1)
    return None
