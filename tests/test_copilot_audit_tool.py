"""Read-only audit_dataset tool — findings only, never mutates."""

from __future__ import annotations

from pathlib import Path

import pytest

from neuro_pipeline.bids.conversion_plan import BIDSConversionPlan
from neuro_pipeline.models import DicomSeries, SeriesStatus
from neuro_pipeline.neurobids.copilot.benchmark.dataset import (
    UID_001_01_LOC,
    UID_002_01_PHOENIX,
    UID_003_01_T1W,
    UID_004_01_SBREF,
    build_benchmark_session,
)
from neuro_pipeline.neurobids.copilot.session import CopilotSession
from neuro_pipeline.neurobids.copilot.tools.registry import default_registry


@pytest.fixture
def session(tmp_path: Path):
    return build_benchmark_session(tmp_path / "ds")


@pytest.fixture
def registry():
    return default_registry()


def _mtime_map(root: Path) -> dict[str, int]:
    return {str(p): p.stat().st_mtime_ns for p in root.rglob("*") if p.is_file()}


def test_audit_dataset_is_registered_read_only(registry) -> None:
    tool = registry.get("audit_dataset")
    assert tool is not None
    assert tool.kind.value == "read_only"
    assert tool.mutates_data is False
    llm = {t["name"]: t for t in registry.to_llm_tools()}
    assert "execute" not in llm["audit_dataset"]


def test_benchmark_audit_covers_all_requested_codes(session, registry) -> None:
    result = registry.execute("audit_dataset", session)
    assert result.ok, result.error
    assert result.data["auto_applied"] is False
    assert "changeset" not in result.data
    codes = set(result.data["codes"])
    assert codes == {
        "unmapped",
        "ambiguous_mapping",
        "missing_expected_modality",
        "inconsistent_structure",
        "missing_metadata",
        "suspicious_entity",
        "fieldmap_association",
        "excluded",
    }
    by_code = {f["code"]: f for f in result.data["findings"]}
    for finding in result.data["findings"]:
        assert finding["severity"] in {"error", "warning", "info"}
        assert finding["evidence"]
        assert finding["recommendation"]
        assert finding["n_affected"] == len(finding["affected"])
        assert finding["n_affected"] >= 1
    assert UID_001_01_LOC in {a["series_uid"] for a in by_code["unmapped"]["affected"]}
    assert UID_002_01_PHOENIX in {a["series_uid"] for a in by_code["excluded"]["affected"]}
    assert UID_003_01_T1W in {a["series_uid"] for a in by_code["missing_expected_modality"]["affected"]}
    assert UID_004_01_SBREF in {a["series_uid"] for a in by_code["suspicious_entity"]["affected"]}


def test_audit_filter_and_no_mutation(session, registry) -> None:
    dicom_root = Path(session.plan.dataset_root)
    before = _mtime_map(dicom_root)
    fingerprint = [item.to_user_dict() for item in session.plan.items]
    result = registry.execute("audit_dataset", session, {"code": "excluded"})
    assert result.ok
    assert result.data["n_findings"] == 1
    assert result.data["findings"][0]["code"] == "excluded"
    assert result.data["findings"][0]["severity"] == "info"
    assert [item.to_user_dict() for item in session.plan.items] == fingerprint
    assert _mtime_map(dicom_root) == before


def _series(description: str, **kwargs) -> DicomSeries:
    patient = kwargs.pop("patient_id", "A")
    uid = kwargs.pop("uid", "uid.a")
    seq = kwargs.pop("seq", "anat")
    root = Path("synthetic_dicom") / patient
    return DicomSeries(
        patient_id=patient,
        study_description="Study",
        series_description=description,
        protocol_name=kwargs.get("protocol", description),
        series_number=kwargs.get("series_number", 1),
        acquisition_number=1,
        modality=kwargs.get("modality", "MR"),
        num_images=kwargs.get("num_images", 10),
        source_dir=root,
        sample_file=root / "img.dcm",
        status=SeriesStatus.PENDING,
        sequence_type=seq,
        fine_sequence_type=kwargs.get("fine", ""),
        series_instance_uid=uid,
        sequence_confidence=0.8,
        source_subject_folder=str(root),
        requires_manual_mapping=kwargs.get("manual", False),
    )


def test_unpaired_fieldmap_and_empty_description(tmp_path: Path, registry) -> None:
    dicom_root = tmp_path / "dicom"
    dicom_root.mkdir()
    (dicom_root / "img.dcm").write_bytes(b"SYNTHETIC_DICOM_BYTES")
    series = [
        _series("t1_mprage", uid="uid-t1", seq="anat", fine="ANAT_T1"),
        _series("rest_bold", uid="uid-func", seq="func", fine="FMRI_REST"),
        _series("fmap_AP", uid="uid-fmap", seq="fmap", fine="FMAP"),
        _series("", uid="uid-empty", seq="unknown", protocol="", num_images=0),
    ]
    plan = BIDSConversionPlan.from_series(
        series,
        dataset_root=dicom_root,
        output_root=tmp_path / "out",
        session_override="01",
    )
    if plan.get("uid-fmap") is not None:
        plan.apply_edit("uid-fmap", datatype="fmap", suffix="epi", direction="AP")
        plan.refresh_filenames()
    copilot = CopilotSession(plan=plan, series_list=series)
    result = registry.execute("audit_dataset", copilot)
    assert result.ok
    by_code = {f["code"]: f for f in result.data["findings"]}
    assert "fieldmap_association" in by_code
    fmap_uids = {a["series_uid"] for a in by_code["fieldmap_association"]["affected"]}
    assert "uid-fmap" in fmap_uids
    assert "missing_metadata" in by_code
    empty_uids = {a["series_uid"] for a in by_code["missing_metadata"]["affected"]}
    assert "uid-empty" in empty_uids
    assert result.data["auto_applied"] is False
    assert (dicom_root / "img.dcm").read_bytes() == b"SYNTHETIC_DICOM_BYTES"
