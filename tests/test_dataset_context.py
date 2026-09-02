"""Unit tests for NeuroBIDS DatasetContext (metadata-only, LLM-safe)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from neuro_pipeline.bids.conversion_plan import BIDSConversionPlan, PlanValidationIssue, PlanValidationResult
from neuro_pipeline.models import DicomSeries, SeriesStatus
from neuro_pipeline.neurobids import (
    AcquisitionContext,
    DatasetContext,
    MetadataIssue,
    SessionContext,
    SubjectContext,
)


def _series(
    description: str,
    *,
    seq: str = "anat",
    fine: str = "ANAT_T1",
    patient_id: str = "SUB001",
    series_number: int = 1,
    uid: str = "",
    modality: str = "MR",
    requires_manual: bool = False,
    convertible: bool = True,
) -> DicomSeries:
    root = Path("/tmp/fake_readonly_dataset") / patient_id
    return DicomSeries(
        patient_id=patient_id,
        study_description="Study",
        series_description=description,
        protocol_name=description,
        series_number=series_number,
        acquisition_number=1,
        modality=modality,
        num_images=12,
        source_dir=root,
        sample_file=root / "x.dcm",
        status=SeriesStatus.PENDING,
        sequence_type=seq,
        fine_sequence_type=fine,
        smart_name=description,
        series_instance_uid=uid or f"1.2.840.{patient_id}.{series_number}",
        study_instance_uid="1.2.840.0",
        sequence_confidence=0.9,
        source_subject_folder=str(root),
        requires_manual_mapping=requires_manual,
        convertible_to_nifti=convertible,
        convertibility="convertible" if convertible else "unsupported_sop",
    )


def test_from_plan_builds_subjects_sessions_acquisitions() -> None:
    series = [
        _series("t1_mprage", series_number=1, uid="uid-t1"),
        _series("rest_AP", seq="func", fine="FMRI_REST", series_number=2, uid="uid-rest"),
    ]
    plan = BIDSConversionPlan.from_series(
        series,
        dataset_root="/data/StudyA",
        output_root="/out/bids",
        subject_override="001",
        session_override="01",
    )
    ctx = DatasetContext.from_conversion_plan(
        plan,
        series_list=series,
        detection_method="patient_id",
        n_dicom_files=24,
    )
    assert ctx.n_subjects == 1
    assert ctx.n_series == 2
    assert ctx.dataset_label == "StudyA"
    assert ctx.output_label == "bids"
    assert len(ctx.subjects) == 1
    subj = ctx.subjects[0]
    assert subj.subject_id in {"001", "sub-001"} or "001" in subj.subject_id
    assert len(subj.sessions) == 1
    ses = subj.sessions[0]
    assert ses.session_id in {"01", "ses-01"} or "01" in ses.session_id
    acqs = ses.acquisitions
    assert len(acqs) == 2
    assert all(isinstance(a, AcquisitionContext) for a in acqs)
    assert all(a.bids is not None for a in acqs)
    assert {a.bids.datatype for a in acqs if a.bids} >= {"anat", "func"}
    assert "MR" in ctx.modalities
    # No absolute paths / pixel payloads in serialized form
    blob = ctx.to_dict()
    dumped = json.dumps(blob)
    assert "/data/StudyA" not in dumped
    assert "PixelData" not in dumped
    assert "sample_file" not in dumped
    assert "/tmp/fake_readonly_dataset" not in dumped


def test_to_json_roundtrip_structure() -> None:
    series = [_series("flair", fine="ANAT_FLAIR", uid="uid-flair")]
    plan = BIDSConversionPlan.from_series(series, subject_override="002")
    ctx = DatasetContext.from_conversion_plan(plan, series_list=series)
    raw = ctx.to_json()
    data = json.loads(raw)
    assert "subjects" in data
    assert "metadata_issues" in data
    assert data["n_series"] == 1


def test_to_llm_context_is_compact_and_omits_absolute_paths() -> None:
    series = [
        _series(
            "very_long_series_description_that_should_be_truncated_for_llm_payloads_ABCDEFG",
            uid="1.2.840.10008.1.2.1.99999999999999999999",
            requires_manual=True,
        )
    ]
    plan = BIDSConversionPlan.from_series(
        series,
        dataset_root="/lustre07/scratch/user/private_study",
        subject_override="010",
    )
    validation = PlanValidationResult(
        ok=False,
        issues=[
            PlanValidationIssue(level="error", message="Duplicate filename", series_uid=series[0].series_instance_uid),
        ],
    )
    ctx = DatasetContext.from_conversion_plan(
        plan,
        series_list=series,
        validation=validation,
        detection_method="folder",
    )
    llm = ctx.to_llm_context()
    assert llm["dataset"] == "private_study"
    assert "/lustre07" not in json.dumps(llm)
    assert "notes" in llm
    assert llm["counts"]["series"] == 1
    assert llm["counts"]["issues"] >= 1
    # Truncated description / short uid
    acq = llm["subjects"][0]["sessions"][0]["acquisitions"][0]
    assert len(acq["desc"]) <= 80
    assert "…" in acq["uid"] or len(acq["uid"]) <= 24
    assert "bids" in acq
    assert "PixelData" not in json.dumps(llm)


def test_excluded_and_manual_mapping_generate_issues() -> None:
    series = [
        _series("unknown_seq", seq="unknown", fine="", uid="uid-unk", requires_manual=True),
        _series("localizer", uid="uid-loc", convertible=False),
    ]
    plan = BIDSConversionPlan.from_series(series, subject_override="003")
    plan.apply_edit("uid-loc", include_in_conversion=False)
    ctx = DatasetContext.from_conversion_plan(plan, series_list=series)
    codes = {i.code for i in ctx.metadata_issues}
    assert "manual_mapping_required" in codes or any(
        a.requires_manual_mapping for a in ctx.iter_acquisitions()
    )
    assert any(i.code in {"excluded", "not_convertible"} for i in ctx.metadata_issues)


def test_multi_subject_grouping() -> None:
    series = [
        _series("t1", patient_id="A", uid="uid-a", series_number=1),
        _series("t1", patient_id="B", uid="uid-b", series_number=1),
    ]
    plan = BIDSConversionPlan.from_series(series)
    ctx = DatasetContext.from_conversion_plan(plan, series_list=series)
    assert ctx.n_subjects == 2
    assert len(ctx.subjects) == 2
    llm = ctx.to_llm_context()
    assert llm["counts"]["subjects"] == 2


def test_nested_context_types() -> None:
    subj = SubjectContext(
        subject_id="sub-01",
        sessions=[
            SessionContext(
                session_id="ses-01",
                acquisitions=[
                    AcquisitionContext(
                        series_uid="u1",
                        modality="MR",
                        series_description="T1",
                        metadata_issues=[MetadataIssue(level="info", message="ok", code="x")],
                    )
                ],
            )
        ],
    )
    ctx = DatasetContext(subjects=[subj], n_subjects=1, n_series=1)
    assert ctx.modalities == ["MR"]
    assert len(ctx.iter_acquisitions()) == 1
    assert ctx.to_dict()["subjects"][0]["sessions"][0]["acquisitions"][0]["series_uid"] == "u1"
