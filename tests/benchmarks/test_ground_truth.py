"""Ground-truth checks for the synthetic benchmark dataset."""

from __future__ import annotations

from neuro_pipeline.neurobids.copilot.benchmark.dataset import (
    AMBIGUOUS_UIDS,
    DWI_UIDS,
    EXCLUDED_UIDS,
    FUNC_UIDS,
    LOCALIZER_UIDS,
    T1W_UIDS,
    acquisition_spec,
    dicom_payload_map,
)
from neuro_pipeline.neurobids.copilot.tools.registry import default_registry


def test_dataset_counts(benchmark_ground_truth) -> None:
    gt = benchmark_ground_truth
    assert gt["n_subjects"] == 3
    assert gt["subject_ids"] == ["001", "002", "003"]
    assert gt["n_sessions"] == 4
    assert gt["multi_session_subjects"] == ["001"]
    assert gt["single_session_subjects"] == ["002", "003"]
    assert gt["n_acquisitions"] == 14
    assert gt["modalities"] == ["MR"]
    assert gt["n_excluded"] == 1
    assert gt["n_included"] == 13


def test_dataset_covers_required_structure(benchmark_ground_truth) -> None:
    gt = benchmark_ground_truth
    assert set(gt["t1w_uids"]) == set(T1W_UIDS)
    assert set(gt["func_uids"]) == set(FUNC_UIDS)
    assert set(gt["dwi_uids"]) == set(DWI_UIDS)
    assert set(gt["localizer_uids"]) == set(LOCALIZER_UIDS)
    assert set(gt["ambiguous_uids"]) == set(AMBIGUOUS_UIDS)
    assert set(gt["excluded_uids"]) == set(EXCLUDED_UIDS)
    assert "dwi" in gt["longitudinal_inconsistencies"][0]["datatype"]
    assert gt["longitudinal_inconsistencies"][0]["missing_in_session"] == "02"


def test_placeholder_dicom_is_not_real_pixels(benchmark_session) -> None:
    payloads = dicom_payload_map(benchmark_session)
    assert payloads
    for data in payloads.values():
        assert data == b"SYNTHETIC_DICOM_BYTES_NOT_PIXELS"


def test_spec_has_fourteen_acquisitions() -> None:
    assert len(acquisition_spec()) == 14


def test_cases_reference_existing_uids(benchmark_cases, benchmark_ground_truth) -> None:
    known = {row["series_uid"] for row in benchmark_ground_truth["acquisitions"]}
    known_subjects = set(benchmark_ground_truth["subject_ids"])
    for case in benchmark_cases:
        for uid in case.expected_acquisitions or []:
            assert uid in known, f"{case.id} references unknown uid {uid}"
        for sid in case.expected_subjects or []:
            assert sid.removeprefix("sub-") in known_subjects or case.category == "mutations"


def test_static_ground_truth_json_matches_live(benchmark_ground_truth) -> None:
    import json
    from pathlib import Path

    path = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "neuro_pipeline"
        / "neurobids"
        / "copilot"
        / "benchmark"
        / "data"
        / "ground_truth.json"
    )
    static = json.loads(path.read_text(encoding="utf-8"))
    for key in (
        "n_subjects",
        "n_sessions",
        "n_acquisitions",
        "subject_ids",
        "multi_session_subjects",
        "t1w_uids",
        "func_uids",
        "dwi_uids",
        "ambiguous_uids",
        "excluded_uids",
    ):
        assert static[key] == benchmark_ground_truth[key], key


def test_level1_tools_are_registered_or_intentionally_absent(benchmark_cases) -> None:
    names = set(default_registry().names())
    for case in benchmark_cases:
        if "level1" not in case.levels:
            continue
        if case.level1_check == "tool_not_registered":
            for tool in case.expected_tools:
                assert tool not in names, f"{case.id}: {tool} should not be registered"
        elif case.level1_check == "execute":
            assert case.level1_tool in names, f"{case.id}: {case.level1_tool} is not registered"
