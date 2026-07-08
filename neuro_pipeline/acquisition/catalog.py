"""Canonical expected acquisitions for study-specific BIDS consistency checks."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ExpectedAcquisition:
    """One acquisition that must be uniquely identifiable per session."""

    acquisition_id: str
    category: str
    series_patterns: tuple[str, ...]
    protocol_patterns: tuple[str, ...]
    expected_datatype: str
    expected_task: str | None
    expected_pe_direction: str | None
    expected_run: int | None
    required: bool = True
    paired_with: str | None = None


# All acquisitions expected for every participant/session in this study.
EXPECTED_ACQUISITIONS: tuple[ExpectedAcquisition, ...] = (
    # --- Structural ---
    ExpectedAcquisition(
        acquisition_id="T1w_MPR",
        category="structural",
        series_patterns=("t1w_mpr", "t1w mpr", "t1_mpr"),
        protocol_patterns=("t1w_mpr", "t1_mpr"),
        expected_datatype="anat",
        expected_task=None,
        expected_pe_direction=None,
        expected_run=None,
    ),
    ExpectedAcquisition(
        acquisition_id="Sag_Flair_3D_0.8",
        category="structural",
        series_patterns=("sag flair 3d", "flair 3d-0.8", "flair 3d 0.8", "sag_flair"),
        protocol_patterns=("flair",),
        expected_datatype="anat",
        expected_task=None,
        expected_pe_direction=None,
        expected_run=None,
    ),
    ExpectedAcquisition(
        acquisition_id="WMn_MPRAGE_sagittal",
        category="structural",
        series_patterns=("wmn_mprage", "wmn mprage", "mprage_sagittal", "mprage sagittal"),
        protocol_patterns=("wmn", "mprage"),
        expected_datatype="anat",
        expected_task=None,
        expected_pe_direction=None,
        expected_run=None,
    ),
    # --- Functional ---
    ExpectedAcquisition(
        acquisition_id="REST1_AP",
        category="functional",
        series_patterns=("rest1_ap", "rest1 ap", "rest1"),
        protocol_patterns=("rest",),
        expected_datatype="func",
        expected_task="rest",
        expected_pe_direction="AP",
        expected_run=1,
    ),
    # --- Movie ---
    ExpectedAcquisition(
        acquisition_id="Movie1_AP",
        category="movie",
        series_patterns=("movie1_ap", "movie1 ap", "movie1"),
        protocol_patterns=("movie1", "movie"),
        expected_datatype="func",
        expected_task="movie",
        expected_pe_direction="AP",
        expected_run=1,
    ),
    ExpectedAcquisition(
        acquisition_id="Movie2_AP",
        category="movie",
        series_patterns=("movie2_ap", "movie2 ap", "movie2"),
        protocol_patterns=("movie2", "movie"),
        expected_datatype="func",
        expected_task="movie",
        expected_pe_direction="AP",
        expected_run=2,
    ),
    ExpectedAcquisition(
        acquisition_id="Movie3_AP",
        category="movie",
        series_patterns=("movie3_ap", "movie3 ap", "movie3"),
        protocol_patterns=("movie3", "movie"),
        expected_datatype="func",
        expected_task="movie",
        expected_pe_direction="AP",
        expected_run=3,
    ),
    ExpectedAcquisition(
        acquisition_id="Movie4_AP",
        category="movie",
        series_patterns=("movie4_ap", "movie4 ap", "movie4"),
        protocol_patterns=("movie4", "movie"),
        expected_datatype="func",
        expected_task="movie",
        expected_pe_direction="AP",
        expected_run=4,
    ),
    # --- Task fMRI ---
    ExpectedAcquisition(
        acquisition_id="fMRI1_AP",
        category="task_fmri",
        series_patterns=("fmri1_ap", "fmri1 ap", "fmri1"),
        protocol_patterns=("fmri1",),
        expected_datatype="func",
        expected_task="fmri",
        expected_pe_direction="AP",
        expected_run=1,
    ),
    ExpectedAcquisition(
        acquisition_id="fMRI2_AP",
        category="task_fmri",
        series_patterns=("fmri2_ap", "fmri2 ap", "fmri2"),
        protocol_patterns=("fmri2",),
        expected_datatype="func",
        expected_task="fmri",
        expected_pe_direction="AP",
        expected_run=2,
    ),
    ExpectedAcquisition(
        acquisition_id="fMRI3_AP",
        category="task_fmri",
        series_patterns=("fmri3_ap", "fmri3 ap", "fmri3"),
        protocol_patterns=("fmri3",),
        expected_datatype="func",
        expected_task="fmri",
        expected_pe_direction="AP",
        expected_run=3,
    ),
    ExpectedAcquisition(
        acquisition_id="fMRI4_AP",
        category="task_fmri",
        series_patterns=("fmri4_ap", "fmri4 ap", "fmri4"),
        protocol_patterns=("fmri4",),
        expected_datatype="func",
        expected_task="fmri",
        expected_pe_direction="AP",
        expected_run=4,
    ),
    # --- Control ---
    ExpectedAcquisition(
        acquisition_id="Control1_PA",
        category="control",
        series_patterns=("control1_pa", "control1 pa", "control1"),
        protocol_patterns=("control1", "control"),
        expected_datatype="func",
        expected_task="control",
        expected_pe_direction="PA",
        expected_run=1,
    ),
    ExpectedAcquisition(
        acquisition_id="Control2_AP",
        category="control",
        series_patterns=("control2_ap", "control2 ap", "control2"),
        protocol_patterns=("control2", "control"),
        expected_datatype="func",
        expected_task="control",
        expected_pe_direction="AP",
        expected_run=2,
    ),
    ExpectedAcquisition(
        acquisition_id="Control3_AP",
        category="control",
        series_patterns=("control3_ap", "control3 ap", "control3"),
        protocol_patterns=("control3", "control"),
        expected_datatype="func",
        expected_task="control",
        expected_pe_direction="AP",
        expected_run=3,
    ),
    # --- Fieldmaps ---
    ExpectedAcquisition(
        acquisition_id="SpinEchoFieldMap_AP",
        category="fieldmap",
        series_patterns=("spinechofieldmap_ap", "spin echo fieldmap_ap", "spinechofieldmap ap"),
        protocol_patterns=("spinechofieldmap", "fieldmap"),
        expected_datatype="fmap",
        expected_task=None,
        expected_pe_direction="AP",
        expected_run=1,
        paired_with="SpinEchoFieldMap_PA",
    ),
    ExpectedAcquisition(
        acquisition_id="SpinEchoFieldMap_PA",
        category="fieldmap",
        series_patterns=("spinechofieldmap_pa", "spin echo fieldmap_pa", "spinechofieldmap pa"),
        protocol_patterns=("spinechofieldmap", "fieldmap"),
        expected_datatype="fmap",
        expected_task=None,
        expected_pe_direction="PA",
        expected_run=None,
        paired_with="SpinEchoFieldMap_AP",
    ),
    # --- Diffusion ---
    ExpectedAcquisition(
        acquisition_id="gsld_76dir_b2000_1mmiso_AP",
        category="diffusion",
        series_patterns=("gsld_76dir", "76dir_b2000", "76dir b2000", "gsld_76dir_b2000"),
        protocol_patterns=("gsld_76dir", "76dir"),
        expected_datatype="dwi",
        expected_task=None,
        expected_pe_direction="AP",
        expected_run=None,
        paired_with="gsld_75TE_PA_3b0",
    ),
    ExpectedAcquisition(
        acquisition_id="gsld_75TE_PA_3b0",
        category="diffusion",
        series_patterns=("gsld_75te", "75te_pa", "75te pa", "gsld_75te_pa"),
        protocol_patterns=("gsld_75te", "75te"),
        expected_datatype="dwi",
        expected_task=None,
        expected_pe_direction="PA",
        expected_run=None,
        paired_with="gsld_76dir_b2000_1mmiso_AP",
    ),
    # --- Additional ---
    ExpectedAcquisition(
        acquisition_id="tfl_b1map_1mmiso",
        category="additional",
        series_patterns=("tfl_b1map", "b1map_1mmiso", "b1map 1mmiso", "tfl b1map"),
        protocol_patterns=("b1map", "tfl_b1map"),
        expected_datatype="fmap",
        expected_task=None,
        expected_pe_direction=None,
        expected_run=None,
    ),
    ExpectedAcquisition(
        acquisition_id="Resolve_3scan_trace_tra_p3_160_1.4iso_AP",
        category="additional",
        series_patterns=(
            "resolve_3scan_trace_tra_p3_160_1.4iso_ap",
            "resolve_3scan_ap",
            "resolve ap",
            "resolve_3scan trace",
        ),
        protocol_patterns=("resolve",),
        expected_datatype="dwi",
        expected_task=None,
        expected_pe_direction="AP",
        expected_run=None,
        paired_with="Resolve_3scan_trace_tra_p3_160_1.4iso_PA",
    ),
    ExpectedAcquisition(
        acquisition_id="Resolve_3scan_trace_tra_p3_160_1.4iso_PA",
        category="additional",
        series_patterns=(
            "resolve_3scan_trace_tra_p3_160_1.4iso_pa",
            "resolve_3scan_pa",
            "resolve pa",
        ),
        protocol_patterns=("resolve",),
        expected_datatype="dwi",
        expected_task=None,
        expected_pe_direction="PA",
        expected_run=None,
        paired_with="Resolve_3scan_trace_tra_p3_160_1.4iso_AP",
    ),
)

# Modalities whose downstream preprocessing typically requires a T1 reference.
T1_DEPENDENT_MODALITIES: frozenset[str] = frozenset({"anat", "func", "dwi", "fmap"})

ACQUISITION_PAIRS: tuple[tuple[str, str], ...] = tuple(
    (item.acquisition_id, item.paired_with)
    for item in EXPECTED_ACQUISITIONS
    if item.paired_with and item.expected_pe_direction == "AP"
)

FIELDMAP_PAIRS = ACQUISITION_PAIRS

T1_ACQUISITION_ID = "T1w_MPR"

RUN_PATTERN = re.compile(r"(?:movie|fmri|control|rest)(\d+)", re.IGNORECASE)


def normalize_text(value: str) -> str:
    """Normalize DICOM text for pattern matching."""
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def extract_pe_direction(text: str) -> str | None:
    """Extract AP or PA from series/protocol text."""
    normalized = normalize_text(text)
    if "_ap" in normalized or normalized.endswith("ap"):
        return "AP"
    if "_pa" in normalized or normalized.endswith("pa"):
        return "PA"
    if re.search(r"\bap\b", text.lower()):
        return "AP"
    if re.search(r"\bpa\b", text.lower()):
        return "PA"
    return None


def score_series_match(
    series_description: str,
    protocol_name: str,
    expected: ExpectedAcquisition,
) -> float:
    """Return match score in [0, 1]; 0 means no match."""
    series_norm = normalize_text(series_description)
    protocol_norm = normalize_text(protocol_name)
    combined = f"{series_norm} {protocol_norm}"

    best = 0.0
    for pattern in expected.series_patterns:
        pattern_norm = normalize_text(pattern)
        if pattern_norm == series_norm:
            best = max(best, 1.0)
        elif pattern_norm in series_norm or series_norm in pattern_norm:
            best = max(best, 0.9)
        elif pattern_norm in combined:
            best = max(best, 0.75)

    for pattern in expected.protocol_patterns:
        pattern_norm = normalize_text(pattern)
        if pattern_norm and pattern_norm in protocol_norm:
            best = max(best, 0.6)

    if expected.expected_run is not None:
        run_match = RUN_PATTERN.search(series_description)
        if run_match and int(run_match.group(1)) == expected.expected_run:
            best = min(1.0, best + 0.05)

    if expected.expected_pe_direction:
        pe = extract_pe_direction(combined)
        if pe == expected.expected_pe_direction:
            best = min(1.0, best + 0.05)
        elif pe and pe != expected.expected_pe_direction:
            return 0.0

    return best if best >= 0.6 else 0.0
