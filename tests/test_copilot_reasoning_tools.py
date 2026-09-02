"""Read-only neuroimaging reasoning tools — evidence, no invented metadata."""

from __future__ import annotations

from pathlib import Path

import pytest

from neuro_pipeline.neurobids.copilot.benchmark.dataset import (
    UID_001_01_T1W,
    UID_002_01_AMBIG,
    UID_004_01_FLAIR,
    UID_004_01_FMAP_AP,
    UID_004_01_FMAP_PA,
    UID_004_01_ME1,
    UID_004_01_MIXED,
    UID_004_01_RUN02,
    UID_004_01_SBREF,
    UID_004_01_T2W,
    UID_004_01_TASK,
    build_benchmark_session,
)
from neuro_pipeline.neurobids.copilot.tools.registry import default_registry
from neuro_pipeline.neurobids.copilot.tools.reasoning import reason_acquisition


@pytest.fixture
def session(tmp_path: Path):
    return build_benchmark_session(tmp_path / "ds")


@pytest.fixture
def registry():
    return default_registry()


def _mtime_map(root: Path) -> dict[str, int]:
    return {str(p): p.stat().st_mtime_ns for p in root.rglob("*") if p.is_file()}


def test_reasoning_tools_are_read_only(registry) -> None:
    names = {
        "classify_acquisition",
        "classify_acquisitions",
        "list_anatomical",
        "list_functional",
        "list_dwi",
        "list_fieldmaps",
        "list_sbref",
        "list_multiecho",
        "inspect_entities",
        "list_ambiguous_acquisitions",
        "explain_mapping",
    }
    llm = {t["name"]: t for t in registry.to_llm_tools()}
    for name in names:
        tool = registry.get(name)
        assert tool is not None
        assert tool.kind.value == "read_only"
        assert tool.mutates_data is False
        assert "execute" not in llm[name]


def test_classify_modalities_return_evidence(session, registry) -> None:
    cases = [
        (UID_001_01_T1W, "T1w", "anat"),
        (UID_004_01_T2W, "T2w", "anat"),
        (UID_004_01_FLAIR, "FLAIR", "anat"),
        (UID_004_01_TASK, "BOLD_task", "func"),
        (UID_004_01_FMAP_AP, "fieldmap_AP", "fmap"),
        (UID_004_01_FMAP_PA, "fieldmap_PA", "fmap"),
        (UID_004_01_SBREF, "SBRef", "func"),
    ]
    for uid, label, datatype in cases:
        result = registry.execute("classify_acquisition", session, {"series_uid": uid})
        assert result.ok, result.error
        rec = result.data["classification"]
        assert rec["label"] == label
        assert rec["datatype"] == datatype
        assert 0.0 <= float(rec["confidence"]) <= 1.0
        assert rec["evidence"]
        assert rec["reasoning"]
        assert rec["observed"]["series_description"]
        assert "inferred" in rec


def test_rest_bold_not_task(session, registry) -> None:
    result = registry.execute("list_functional", session, {"subtype": "rest"})
    uids = {a["series_uid"] for a in result.data["classifications"]}
    assert "uid.001.01.func" in uids
    assert UID_004_01_TASK not in uids
    assert UID_004_01_SBREF not in uids
    rest = registry.execute("classify_acquisition", session, {"series_uid": "uid.001.01.func"})
    assert rest.data["classification"]["label"] == "BOLD_rest"
    assert rest.data["classification"]["task_kind"] == "rest"


def test_dwi_and_fieldmap_pe(session, registry) -> None:
    dwi = registry.execute("list_dwi", session)
    assert dwi.data["n_matches"] == 2
    fmaps = registry.execute("list_fieldmaps", session)
    assert fmaps.data["n_matches"] == 2
    by_uid = {r["series_uid"]: r for r in fmaps.data["classifications"]}
    assert by_uid[UID_004_01_FMAP_AP]["phase_encoding"] == "AP"
    assert by_uid[UID_004_01_FMAP_PA]["phase_encoding"] == "PA"


def test_sbref_multiecho_entities(session, registry) -> None:
    sbref = registry.execute("list_sbref", session)
    assert sbref.data["n_matches"] == 1
    assert sbref.data["classifications"][0]["series_uid"] == UID_004_01_SBREF

    me = registry.execute("list_multiecho", session)
    assert me.data["n_matches"] == 2
    echoes = {
        r["series_uid"]: (r.get("inferred") or {}).get("echo") for r in me.data["classifications"]
    }
    assert echoes[UID_004_01_ME1] == "1"

    run = registry.execute("inspect_entities", session, {"series_uid": UID_004_01_RUN02})
    assert result_ok(run)
    assert run.data["entities"][0]["run"] == "02"

    echo = registry.execute("inspect_entities", session, {"series_uid": UID_004_01_ME1})
    assert echo.data["entities"][0]["echo"] == "1"

    acq = registry.execute("inspect_entities", session, {"series_uid": UID_004_01_T2W})
    assert acq.data["entities"][0]["acquisition"] == "tse"


def result_ok(result) -> bool:
    assert result.ok, result.error
    return True


def test_does_not_invent_echo_on_t1(session, registry) -> None:
    rec = reason_acquisition(session, UID_001_01_T1W)
    assert rec is not None
    assert "echo" not in rec["inferred"]
    assert "echo" not in (rec["inferred"].get("entities") or {})
    ents = registry.execute("inspect_entities", session, {"series_uid": UID_001_01_T1W})
    assert result_ok(ents)
    assert not ents.data["entities"][0]["echo"]


def test_ambiguous_and_unclassified(session, registry) -> None:
    ambig = registry.execute(
        "list_ambiguous_acquisitions",
        session,
        {"include_unclassified": False},
    )
    uids = {r["series_uid"] for r in ambig.data["classifications"]}
    assert UID_002_01_AMBIG in uids
    assert UID_004_01_MIXED in uids
    mixed = registry.execute("classify_acquisition", session, {"series_uid": UID_004_01_MIXED})
    assert mixed.data["classification"]["ambiguous"] is True
    assert mixed.data["classification"]["label"] == "ambiguous_anat"

    unknown = registry.execute(
        "list_ambiguous_acquisitions",
        session,
        {"only_unclassified": True},
    )
    uids = {r["series_uid"] for r in unknown.data["classifications"]}
    assert "uid.001.01.loc" in uids
    assert UID_004_01_MIXED not in uids
    assert UID_001_01_T1W not in uids


def test_unknown_uid_fails(session, registry) -> None:
    result = registry.execute("classify_acquisition", session, {"series_uid": "uid.missing"})
    assert result.ok is False
    assert "unknown" in result.error.lower()


def test_reasoning_does_not_mutate_plan_or_dicom(session, registry) -> None:
    dicom_root = Path(session.plan.dataset_root)
    before_mtime = _mtime_map(dicom_root)
    payloads = {str(p): p.read_bytes() for p in dicom_root.rglob("*.dcm")}
    fingerprint = [item.to_user_dict() for item in session.plan.items]

    for name, params in (
        ("classify_acquisition", {"series_uid": UID_001_01_T1W}),
        ("classify_acquisitions", {"kind": "fmap"}),
        ("list_anatomical", {"subtype": "flair"}),
        ("list_functional", {"subtype": "task"}),
        ("list_dwi", {}),
        ("list_fieldmaps", {}),
        ("list_sbref", {}),
        ("list_multiecho", {}),
        ("inspect_entities", {"series_uid": UID_004_01_RUN02}),
        ("list_ambiguous_acquisitions", {}),
    ):
        result = registry.execute(name, session, params)
        assert result.ok, f"{name}: {result.error}"
        assert "changeset" not in result.data

    assert [item.to_user_dict() for item in session.plan.items] == fingerprint
    assert _mtime_map(dicom_root) == before_mtime
    for path, data in payloads.items():
        assert Path(path).read_bytes() == data
        assert data == b"SYNTHETIC_DICOM_BYTES_NOT_PIXELS"
