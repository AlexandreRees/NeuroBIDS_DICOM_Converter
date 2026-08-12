"""BIDS filename / entity helpers (generic, non study-specific)."""

from __future__ import annotations

import re
from dataclasses import dataclass

from neuro_pipeline.models import DicomSeries

_NON_ALNUM = re.compile(r"[^a-zA-Z0-9]+")
_DESC_SAFE = re.compile(r"[^A-Za-z0-9]+")
_ADC_RE = re.compile(r"(?:^|[^A-Za-z0-9])ADC(?:[^A-Za-z0-9]|$)|_ADC\b|\bADC_", re.IGNORECASE)
_ADC_TOKEN_RE = re.compile(r"ADC", re.IGNORECASE)


def sanitize_bids_label(value: str, *, fallback: str = "unknown") -> str:
    """Return a BIDS-safe label (alphanumeric only)."""
    cleaned = _NON_ALNUM.sub("", (value or "").strip())
    return cleaned or fallback


def sanitize_filename_token(value: str, *, fallback: str = "series") -> str:
    """Filesystem-safe descriptive token (underscores allowed between words)."""
    cleaned = _DESC_SAFE.sub("_", (value or "").strip())
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    return cleaned or fallback


def subject_id_from_series(series: DicomSeries) -> str:
    """Legacy helper — prefer GUI Subject ID. Kept for non-BIDS tooling."""
    return sanitize_bids_label(series.patient_id or "unknown", fallback="unknown")


def is_adc_series(series: DicomSeries, *, nifti_name: str = "") -> bool:
    """Return True when a series / file looks like an ADC map (not raw DWI)."""
    blob = " ".join(
        [
            series.series_description or "",
            series.protocol_name or "",
            series.smart_name or "",
            nifti_name or "",
        ]
    )
    if _ADC_RE.search(blob):
        return True
    compact = re.sub(r"[^A-Za-z0-9]", "", blob).upper()
    return compact.endswith("ADC") or "ADC" in compact


def anat_suffix(series: DicomSeries) -> str:
    """Map generic series metadata to a BIDS anat suffix."""
    blob = f"{series.series_description} {series.protocol_name} {series.smart_name}".lower()
    if "flair" in blob:
        return "FLAIR"
    if "t2" in blob and "space" in blob:
        return "T2w"
    if "t2" in blob:
        return "T2w"
    if "t1" in blob or "mprage" in blob or "fl3d" in blob:
        return "T1w"
    return "T1w"


def dwi_acquisition(series: DicomSeries) -> str:
    """Build ``acq-<label>`` for DWI from series/protocol tokens.

    Labels are deterministic alphanumeric (no spaces / ``_`` / ``-``).
    ADC maps keep an explicit ``ADC`` token so they never collide with raw DWI.
    """
    blob = series.series_description or series.protocol_name or series.smart_name or "dwi"
    lower = blob.lower()
    compact = lower.replace(" ", "").replace("-", "").replace("_", "")
    tokens: list[str] = []
    for token in ("3scan", "4scan", "bipolar", "monopolar", "trace", "tracew", "dir64", "dir30"):
        if token in compact:
            tokens.append(re.sub(r"[^a-zA-Z0-9]", "", token))
    if _ADC_TOKEN_RE.search(blob):
        tokens.append("ADC")
    if not tokens:
        tokens.append(sanitize_bids_label(blob, fallback="dwi")[:24])
    return sanitize_bids_label("".join(tokens), fallback="dwi")


def func_task(series: DicomSeries) -> str:
    """Build ``task-<label>`` for BOLD/func series."""
    blob = f"{series.series_description} {series.protocol_name} {series.smart_name}"
    lower = blob.lower()
    if "rest" in lower:
        return "rest"
    if "movie" in lower:
        return "movie"
    match = re.search(r"task[_\-\s]?([a-zA-Z0-9]+)", blob, flags=re.I)
    if match:
        return sanitize_bids_label(match.group(1), fallback="unknown")
    return sanitize_bids_label(blob, fallback="unknown")[:24]


def fmap_direction(series: DicomSeries) -> str:
    """Infer phase-encode direction label for fmap EPI (AP/PA/unknown)."""
    blob = f"{series.series_description} {series.protocol_name} {series.smart_name}".lower()
    compact = re.sub(r"[^a-z0-9]", "", blob)
    if compact.endswith("ap") or "_ap" in blob or " ap" in blob or "dirap" in compact:
        return "AP"
    if compact.endswith("pa") or "_pa" in blob or " pa" in blob or "dirpa" in compact:
        return "PA"
    if "ap" in compact and "pa" not in compact:
        return "AP"
    if "pa" in compact:
        return "PA"
    return "unknown"


@dataclass(frozen=True, slots=True)
class BidsTarget:
    """Relative BIDS path components for one file."""

    datatype: str
    filename_stem: str  # without extension

    @property
    def relative_nii(self) -> str:
        return f"{self.datatype}/{self.filename_stem}.nii.gz"


def _prefix(subject_label: str, session_label: str | None = None) -> str:
    parts = [f"sub-{subject_label}"]
    if session_label:
        parts.append(f"ses-{session_label}")
    return "_".join(parts)


def _inject_run(stem: str, run: str | None) -> str:
    """Insert ``run-<label>`` before the final BIDS suffix token when requested."""
    raw = (run or "").strip()
    if not raw:
        return stem
    if raw.lower().startswith("run-"):
        raw = raw[4:]
    label = sanitize_bids_label(raw, fallback="")
    if not label:
        return stem
    token = f"run-{label}"
    if f"_{token}_" in stem or stem.endswith(f"_{token}"):
        return stem
    parts = stem.rsplit("_", 1)
    if len(parts) == 2:
        return f"{parts[0]}_{token}_{parts[1]}"
    return f"{stem}_{token}"


def build_bids_target(
    series: DicomSeries,
    subject_label: str,
    session_label: str | None = None,
    *,
    entity_overrides: dict[str, str] | None = None,
    nifti_name: str = "",
) -> BidsTarget | None:
    """Return the intended BIDS relative target for a classified series.

    ADC maps return ``None`` (exclude from raw BIDS).

    ADC exclusion from raw BIDS naming does NOT imply exclusion
    from DICOM -> NIfTI conversion.
    """
    # ADC exclusion from raw BIDS naming does NOT imply exclusion
    # from DICOM -> NIfTI conversion.
    if is_adc_series(series, nifti_name=nifti_name):
        return None

    overrides = dict(entity_overrides or {})
    seq = (overrides.get("datatype") or series.sequence_type or "unknown").lower()
    prefix = _prefix(subject_label, session_label)
    run = overrides.get("run")

    if seq == "anat":
        suffix = overrides.get("suffix") or anat_suffix(series)
        stem = _inject_run(f"{prefix}_{suffix}", run)
        return BidsTarget(datatype="anat", filename_stem=stem)

    if seq == "dwi":
        acq = overrides.get("acquisition") or dwi_acquisition(series)
        stem = _inject_run(f"{prefix}_acq-{acq}_dwi", run)
        return BidsTarget(datatype="dwi", filename_stem=stem)

    if seq == "func":
        task = overrides.get("task") or func_task(series)
        suffix = overrides.get("suffix") or "bold"
        stem = _inject_run(f"{prefix}_task-{task}_{suffix}", run)
        return BidsTarget(datatype="func", filename_stem=stem)

    if seq == "fmap":
        direction = overrides.get("direction") or fmap_direction(series)
        suffix = overrides.get("suffix") or "epi"
        stem = _inject_run(
            f"{prefix}_dir-{sanitize_bids_label(direction, fallback='unknown')}_{suffix}",
            run,
        )
        return BidsTarget(datatype="fmap", filename_stem=stem)

    return None


def build_fallback_nifti_target(
    series: DicomSeries,
    subject_label: str,
    session_label: str | None = None,
    *,
    run: str | None = None,
    nifti_name: str = "",
) -> BidsTarget:
    """Deterministic NIfTI stem when no valid raw-BIDS target exists.

    Used for ADC maps and unclassified / non-BIDS series so DICOM→NIfTI
    conversion always has a usable output name.
    """
    sub = sanitize_bids_label(subject_label, fallback="unknown")
    ses = sanitize_bids_label(session_label or "", fallback="") if session_label else ""
    prefix = _prefix(sub, ses or None)

    desc = (
        series.series_description
        or series.protocol_name
        or series.smart_name
        or ""
    ).strip()
    token = sanitize_filename_token(desc, fallback="")
    if not token:
        uid = (series.series_instance_uid or "").replace(".", "")
        frag = sanitize_bids_label(uid[-12:] if uid else "", fallback="series")
        token = f"series-{frag}"

    # Keep ADC identifiable in the stem
    if is_adc_series(series, nifti_name=nifti_name) and "adc" not in token.lower():
        token = f"{token}_ADC"

    datatype = "derivatives" if is_adc_series(series, nifti_name=nifti_name) else "unknown"
    stem = _inject_run(f"{prefix}_{token}", run)
    # Never produce an empty / all-separator stem
    if not sanitize_bids_label(stem.replace("_", "").replace("-", ""), fallback=""):
        frag = sanitize_bids_label(
            (series.series_instance_uid or "x").replace(".", "")[-12:],
            fallback="series",
        )
        stem = f"{prefix}_series-{frag}"
    return BidsTarget(datatype=datatype, filename_stem=stem)


def unique_stem(existing: set[str], stem: str) -> str:
    """Avoid collisions by appending ``run-<n>`` when needed."""
    if stem not in existing:
        return stem
    run = 1
    while True:
        candidate = f"{stem}_run-{run:02d}"
        parts = stem.rsplit("_", 1)
        if len(parts) == 2:
            candidate = f"{parts[0]}_run-{run:02d}_{parts[1]}"
        if candidate not in existing:
            return candidate
        run += 1
