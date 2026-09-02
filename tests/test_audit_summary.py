"""Unit tests for audit presentation (no Qt, no fake scores)."""

from __future__ import annotations

from pathlib import Path

from neuro_pipeline.bids.conversion_plan import BIDSConversionPlan
from neuro_pipeline.gui.audit_summary import build_audit_report, dataset_overview
from neuro_pipeline.models import DicomSeries, SeriesStatus
from neuro_pipeline.neurobids.copilot.session import CopilotSession


def _series(
    description: str,
    *,
    patient_id: str = "SUBA",
    series_number: int = 1,
    uid: str = "",
    seq: str = "anat",
    manual: bool = False,
) -> DicomSeries:
    root = Path("synthetic_dicom") / patient_id
    return DicomSeries(
        patient_id=patient_id,
        study_description="Study",
        series_description=description,
        protocol_name=description,
        series_number=series_number,
        acquisition_number=1,
        modality="MR",
        num_images=10,
        source_dir=root,
        sample_file=root / "img.dcm",
        status=SeriesStatus.PENDING,
        sequence_type=seq,
        series_instance_uid=uid or f"uid.{patient_id}.{series_number}",
        requires_manual_mapping=manual,
        source_subject_folder=str(root),
    )


def test_audit_report_counts_issues(tmp_path: Path) -> None:
    dicom_root = tmp_path / "dicom"
    dicom_root.mkdir()
    series = [
        _series("t1", patient_id="A", uid="uid-a"),
        _series("mystery", patient_id="A", uid="uid-m", seq="unknown", manual=True),
    ]
    plan = BIDSConversionPlan.from_series(series, dataset_root=dicom_root, output_root=tmp_path / "out")
    session = CopilotSession(plan=plan, series_list=series)
    ctx = session.dataset_context()
    report = build_audit_report(ctx=ctx, plan=plan)
    assert not report.empty
    assert "94" not in report.headline
    assert report.n_warnings >= 1
    mapping = next(c for c in report.checks if c.key == "mappings")
    assert mapping.level in {"REVIEW", "PASS"}
    overview = dataset_overview(ctx)
    assert overview["subjects"] >= 1
    assert overview["acquisitions"] >= 2


def test_empty_and_scanning_states() -> None:
    empty = build_audit_report(ctx=None, plan=None)
    assert empty.empty
    assert "No dataset" in empty.headline or "Scan" in empty.message
    scanning = build_audit_report(ctx=None, plan=None, scanning=True)
    assert scanning.scanning
    assert "scanning" in scanning.headline.lower()
