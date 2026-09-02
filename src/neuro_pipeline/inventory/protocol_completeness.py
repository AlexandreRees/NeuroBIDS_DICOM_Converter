"""Protocol completeness from classified series (no DICOM re-parse)."""

from __future__ import annotations

import re
from collections import defaultdict

from neuro_pipeline.batch.input_analysis import sanitize_patient_id
from neuro_pipeline.bids.naming import fmap_direction, func_task
from neuro_pipeline.inventory.models import PROTOCOL_ACQUISITIONS, ProtocolCompletenessRow
from neuro_pipeline.models import DicomSeries

_SBREF_RE = re.compile(r"sb.?ref|single.?band.?ref", re.I)


def detect_acquisition_keys(series: DicomSeries) -> set[str]:
    """Map one classified series to zero or more protocol completeness keys.

    Uses pipeline fine types + existing BIDS naming helpers only.
    """
    keys: set[str] = set()
    fine = (series.fine_sequence_type or "").upper()
    blob = f"{series.series_description} {series.protocol_name} {series.smart_name}"
    lower = blob.lower()
    direction = fmap_direction(series)
    task = func_task(series)

    if _SBREF_RE.search(blob):
        keys.add("SBRef")

    if fine == "ANAT_T1" or ("t1" in lower and "flair" not in lower):
        if "wmn" not in lower:  # inventory completeness targets standard T1w
            keys.add("T1w")
    if fine == "FLAIR" or "flair" in lower:
        keys.add("FLAIR")

    if fine in {"DWI", "DTI"} or series.sequence_type == "dwi":
        if "adc" not in lower:
            keys.add("DWI")

    if fine == "FMRI_REST" or task == "rest" or "rest" in lower:
        if direction == "AP":
            keys.add("REST_AP")
        elif direction == "PA":
            keys.add("REST_PA")
        else:
            # Unknown PE direction: count as REST_AP by default for presence tracking
            keys.add("REST_AP")

    if fine == "FMRI_TASK" or task == "movie" or "movie" in lower:
        keys.add("_MOVIE")  # placeholder aggregated later into MOVIE_1..4

    if fine == "FMAP" or series.sequence_type == "fmap":
        if direction == "AP":
            keys.add("FieldMap_AP")
        elif direction == "PA":
            keys.add("FieldMap_PA")
        else:
            keys.add("FieldMap_AP")

    return keys


def build_protocol_rows(
    series_list: list[DicomSeries],
    *,
    subject_override: str = "",
    session_override: str = "",
) -> list[ProtocolCompletenessRow]:
    """Build subject/session completeness rows from classified series."""
    grouped: dict[tuple[str, str], list[DicomSeries]] = defaultdict(list)
    for series in series_list:
        if subject_override and len({s.patient_id for s in series_list}) == 1:
            subject = subject_override
        else:
            subject = sanitize_patient_id(series.patient_id)
        session = (session_override or "").strip()
        grouped[(subject, session)].append(series)

    rows: list[ProtocolCompletenessRow] = []
    for (subject, session), items in sorted(grouped.items()):
        flags = {key: False for key in PROTOCOL_ACQUISITIONS}
        movie_count = 0
        for series in sorted(
            items,
            key=lambda s: (
                s.series_number if s.series_number is not None else 10**9,
                s.series_description or "",
            ),
        ):
            keys = detect_acquisition_keys(series)
            if "_MOVIE" in keys:
                movie_count += 1
                keys.discard("_MOVIE")
            for key in keys:
                if key in flags:
                    flags[key] = True
        for idx in range(1, 5):
            flags[f"MOVIE_{idx}"] = movie_count >= idx
        complete = all(flags[k] for k in PROTOCOL_ACQUISITIONS)
        rows.append(
            ProtocolCompletenessRow(
                subject=subject,
                session=session,
                flags=flags,
                complete=complete,
            )
        )
    return rows
