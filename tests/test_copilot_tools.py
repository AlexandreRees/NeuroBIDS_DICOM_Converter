"""Unit tests for NeuroBIDS Copilot tools + ChangeSet (synthetic data only)."""

from __future__ import annotations

from pathlib import Path

import pytest

from neuro_pipeline.bids.conversion_plan import BIDSConversionPlan
from neuro_pipeline.models import DicomSeries, SeriesStatus
from neuro_pipeline.neurobids.copilot import (
    ChangeSet,
    ChangeSetStatus,
    CopilotSession,
    default_registry,
)
from neuro_pipeline.neurobids.copilot.changeset import ChangeSetError


def _series(
    description: str,
    *,
    seq: str = "anat",
    fine: str = "ANAT_T1",
    patient_id: str = "SUBA",
    series_number: int = 1,
    uid: str = "",
    modality: str = "MR",
) -> DicomSeries:
    root = Path("synthetic_dicom") / patient_id
    return DicomSeries(
        patient_id=patient_id,
        study_description="Study",
        series_description=description,
        protocol_name=description,
        series_number=series_number,
        acquisition_number=1,
        modality=modality,
        num_images=10,
        source_dir=root,
        sample_file=root / "img.dcm",
        status=SeriesStatus.PENDING,
        sequence_type=seq,
        fine_sequence_type=fine,
        smart_name=description,
        series_instance_uid=uid or f"uid.{patient_id}.{series_number}",
        study_instance_uid="uid.study",
        sequence_confidence=0.85,
        source_subject_folder=str(root),
    )


@pytest.fixture
def session_two_subjects(tmp_path: Path) -> CopilotSession:
    dicom_root = tmp_path / "dicom"
    dicom_root.mkdir()
    # Create placeholder files to prove they are never modified
    for pid in ("patient_A", "patient_B"):
        d = dicom_root / pid
        d.mkdir()
        (d / "img.dcm").write_bytes(b"SYNTHETIC_DICOM_BYTES")

    series = [
        _series("t1_mprage", patient_id="patient_A", uid="uid-a-t1", series_number=1),
        _series(
            "rest_AP",
            seq="func",
            fine="FMRI_REST",
            patient_id="patient_A",
            uid="uid-a-rest",
            series_number=2,
        ),
        _series("t1_mprage", patient_id="patient_B", uid="uid-b-t1", series_number=1),
    ]
    for s in series:
        s.source_dir = dicom_root / s.patient_id
        s.sample_file = s.source_dir / "img.dcm"
        s.source_subject_folder = str(s.source_dir)

    plan = BIDSConversionPlan.from_series(
        series,
        dataset_root=dicom_root,
        output_root=tmp_path / "bids_out",
        session_override="01",
    )
    return CopilotSession(
        plan=plan,
        series_list=series,
        detection_method="patient_id",
        n_dicom_files=3,
    )


@pytest.fixture
def registry():
    return default_registry()


def _mtime_map(root: Path) -> dict[str, int]:
    return {str(p): p.stat().st_mtime_ns for p in root.rglob("*") if p.is_file()}


def test_registry_lists_expected_tools(registry) -> None:
    names = registry.names()
    for expected in (
        "inspect_dataset",
        "list_subjects",
        "inspect_subject",
        "find_acquisitions",
        "propose_bids_mapping",
        "rename_subjects",
        "rename_sessions",
        "exclude_acquisitions",
        "include_acquisitions",
        "apply_edit",
    ):
        assert expected in names
    schemas = registry.list_schemas()
    assert all("mutates_data" in s for s in schemas)


def test_inspect_dataset(session_two_subjects, registry) -> None:
    result = registry.execute("inspect_dataset", session_two_subjects)
    assert result.ok
    summary = result.data["summary"]
    assert summary["n_subjects"] == 2
    assert summary["n_acquisitions"] == 3
    assert "MR" in summary["modalities"]
    assert "llm_context" in result.data


def test_list_subjects(session_two_subjects, registry) -> None:
    result = registry.execute("list_subjects", session_two_subjects)
    assert result.ok
    assert result.data["n_subjects"] == 2
    ids = {s["subject_id"] for s in result.data["subjects"]}
    assert any("patientA" in i.replace("-", "").lower() or "patient_a" in i.lower() or "A" in i for i in ids) or len(ids) == 2


def test_inspect_subject(session_two_subjects, registry) -> None:
    listed = registry.execute("list_subjects", session_two_subjects)
    subject_id = listed.data["subjects"][0]["subject_id"]
    result = registry.execute("inspect_subject", session_two_subjects, {"subject_id": subject_id})
    assert result.ok
    assert "sessions" in result.data["subject"]
    assert result.data["subject"]["sessions"]


def test_find_acquisitions_filters(session_two_subjects, registry) -> None:
    by_datatype = registry.execute(
        "find_acquisitions",
        session_two_subjects,
        {"datatype": "func"},
    )
    assert by_datatype.ok
    assert by_datatype.data["n_matches"] >= 1
    assert all(a.get("bids", {}).get("datatype") == "func" for a in by_datatype.data["acquisitions"])

    by_seq = registry.execute(
        "find_acquisitions",
        session_two_subjects,
        {"sequence": "mprage"},
    )
    assert by_seq.ok
    assert by_seq.data["n_matches"] >= 1


def test_propose_bids_mapping(session_two_subjects, registry) -> None:
    result = registry.execute(
        "propose_bids_mapping",
        session_two_subjects,
        {"series_uid": "uid-a-rest"},
    )
    assert result.ok
    prop = result.data["proposals"][0]
    assert prop["series_uid"] == "uid-a-rest"
    assert prop["proposed"]["datatype"] in {"func", "anat", "dwi", "fmap", "unknown"}
    assert "evidence" in prop
    assert "current" in prop


def test_rename_subjects_changeset_preview_apply_rollback(session_two_subjects, registry, tmp_path) -> None:
    dicom_root = Path(session_two_subjects.plan.dataset_root)
    before_mtime = _mtime_map(dicom_root)
    before_subjects = {i.subject for i in session_two_subjects.plan.items}

    result = registry.execute(
        "rename_subjects",
        session_two_subjects,
        {"mode": "sequential", "start": 1, "width": 3, "reason": "Rename subjects sequentially."},
    )
    assert result.ok
    cs: ChangeSet = result.data["changeset"]
    assert cs.status == ChangeSetStatus.DRAFT
    preview = cs.preview()
    assert preview["subject_renames"]
    # Plan unchanged until apply
    assert {i.subject for i in session_two_subjects.plan.items} == before_subjects

    validation = cs.validate(session_two_subjects.plan)
    assert cs.status == ChangeSetStatus.VALIDATED
    assert validation is not None

    cs.apply(session_two_subjects.plan)
    assert cs.status == ChangeSetStatus.APPLIED
    after_subjects = {i.subject for i in session_two_subjects.plan.items}
    assert after_subjects != before_subjects
    assert any(s in {"001", "sub-001"} or s.endswith("001") or s == "001" for s in after_subjects)

    # DICOM untouched
    assert _mtime_map(dicom_root) == before_mtime
    for p in dicom_root.rglob("*.dcm"):
        assert p.read_bytes() == b"SYNTHETIC_DICOM_BYTES"

    cs.rollback(session_two_subjects.plan)
    assert cs.status == ChangeSetStatus.ROLLED_BACK
    assert {i.subject for i in session_two_subjects.plan.items} == before_subjects
    assert _mtime_map(dicom_root) == before_mtime


def test_rename_sessions(session_two_subjects, registry) -> None:
    session_two_subjects.plan.apply_edit("uid-a-rest", session="02")
    session_two_subjects.plan.refresh_filenames()

    result = registry.execute(
        "rename_sessions",
        session_two_subjects,
        {
            "mode": "mapping",
            "mapping": {"01": "pre", "02": "post"},
            "reason": "normalize sessions",
        },
    )
    assert result.ok, result.error
    cs: ChangeSet = result.data["changeset"]
    preview = cs.preview()
    assert preview["session_renames"] or cs.edits
    cs.validate(session_two_subjects.plan)
    cs.apply(session_two_subjects.plan)
    sessions = {i.session for i in session_two_subjects.plan.items}
    assert "pre" in sessions or "post" in sessions


def test_exclude_include_acquisitions(session_two_subjects, registry) -> None:
    result = registry.execute(
        "exclude_acquisitions",
        session_two_subjects,
        {"series_uids": ["uid-a-rest"], "reason": "exclude func"},
    )
    assert result.ok
    cs: ChangeSet = result.data["changeset"]
    cs.validate(session_two_subjects.plan)
    cs.apply(session_two_subjects.plan)
    item = session_two_subjects.plan.get("uid-a-rest")
    assert item is not None
    assert item.include_in_conversion is False

    result2 = registry.execute(
        "include_acquisitions",
        session_two_subjects,
        {"series_uids": ["uid-a-rest"]},
    )
    assert result2.ok
    cs2: ChangeSet = result2.data["changeset"]
    cs2.validate(session_two_subjects.plan)
    cs2.apply(session_two_subjects.plan)
    assert session_two_subjects.plan.get("uid-a-rest").include_in_conversion is True


def test_apply_edit_tool(session_two_subjects, registry) -> None:
    result = registry.execute(
        "apply_edit",
        session_two_subjects,
        {"series_uid": "uid-a-rest", "task": "movie", "run": "03"},
    )
    assert result.ok
    cs: ChangeSet = result.data["changeset"]
    assert any(e.field == "task" and e.after == "movie" for e in cs.edits)
    cs.validate(session_two_subjects.plan)
    cs.apply(session_two_subjects.plan)
    item = session_two_subjects.plan.get("uid-a-rest")
    assert item.task == "movie"
    assert item.run == "03"


def test_stale_changeset_rejected(session_two_subjects, registry) -> None:
    result = registry.execute(
        "rename_subjects",
        session_two_subjects,
        {"mode": "sequential", "start": 10, "width": 3},
    )
    cs: ChangeSet = result.data["changeset"]
    # Mutate plan underneath
    session_two_subjects.plan.apply_edit("uid-b-t1", run="99")
    session_two_subjects.plan.refresh_filenames()
    with pytest.raises(ChangeSetError, match="Stale"):
        cs.validate(session_two_subjects.plan)


def test_conversion_busy_rejection(session_two_subjects, registry) -> None:
    session_two_subjects.set_conversion_busy(True)
    result = registry.execute(
        "rename_subjects",
        session_two_subjects,
        {"mode": "sequential"},
    )
    assert result.ok is False
    assert "conversion" in result.error.lower()

    session_two_subjects.set_conversion_busy(False)
    result = registry.execute(
        "exclude_acquisitions",
        session_two_subjects,
        {"series_uids": ["uid-b-t1"]},
    )
    cs: ChangeSet = result.data["changeset"]
    cs.validate(session_two_subjects.plan)
    session_two_subjects.set_conversion_busy(True)
    with pytest.raises(ChangeSetError, match="conversion"):
        cs.apply(session_two_subjects.plan, conversion_busy=True)


def test_invalid_changeset_empty_edits(session_two_subjects) -> None:
    with pytest.raises(ChangeSetError):
        ChangeSet.from_edit_batches(
            session_two_subjects.plan,
            [],
            tool_name="apply_edit",
        )


def test_dicom_never_modified_by_tools(session_two_subjects, registry) -> None:
    dicom_root = Path(session_two_subjects.plan.dataset_root)
    before = _mtime_map(dicom_root)
    payloads = {str(p): p.read_bytes() for p in dicom_root.rglob("*.dcm")}

    for tool_name, params in (
        ("inspect_dataset", {}),
        ("list_subjects", {}),
        ("propose_bids_mapping", {"series_uids": ["uid-a-t1", "uid-b-t1"]}),
        ("rename_subjects", {"mode": "sequential", "start": 1, "width": 2}),
        ("exclude_acquisitions", {"series_uids": ["uid-a-t1"]}),
        ("apply_edit", {"series_uid": "uid-b-t1", "run": "02"}),
    ):
        registry.execute(tool_name, session_two_subjects, params)

    assert _mtime_map(dicom_root) == before
    for path, data in payloads.items():
        assert Path(path).read_bytes() == data


def test_changeset_reject(session_two_subjects, registry) -> None:
    result = registry.execute(
        "rename_subjects",
        session_two_subjects,
        {"mode": "sequential"},
    )
    cs: ChangeSet = result.data["changeset"]
    cs.reject()
    assert cs.status == ChangeSetStatus.REJECTED
    with pytest.raises(ChangeSetError):
        cs.apply(session_two_subjects.plan)
