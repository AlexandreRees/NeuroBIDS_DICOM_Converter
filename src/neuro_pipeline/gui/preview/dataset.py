"""Tiny deterministic synthetic dataset for NeuroBIDS UI Preview/Demo Mode.

No real DICOM, no patient PHI, no pixel data. Placeholder paths only.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from neuro_pipeline.bids.conversion_plan import BIDSConversionPlan
from neuro_pipeline.models import DicomSeries, SeriesStatus

# Stable UIDs for inspector / scenario scripting
UID_001_01_T1 = "preview.001.01.t1w"
UID_001_01_FUNC = "preview.001.01.func"
UID_001_02_T1 = "preview.001.02.t1w"
UID_002_01_T1 = "preview.002.01.t1w"
UID_002_01_LOC = "preview.002.01.loc"


def build_preview_series(*, root: Path | None = None) -> list[DicomSeries]:
    """Return a tiny in-memory series list (2 subjects, 2 sessions, 5 acquisitions)."""
    base = Path(root) if root is not None else Path("preview_demo")
    dicom = base / "dicom"
    specs: list[dict[str, Any]] = [
        dict(
            uid=UID_001_01_T1,
            patient="demoA",
            folder="sub-demoA",
            desc="t1_mprage",
            seq="anat",
            fine="ANAT_T1",
            n=1,
            study="study.demoA.01",
        ),
        dict(
            uid=UID_001_01_FUNC,
            patient="demoA",
            folder="sub-demoA",
            desc="rest_bold",
            seq="func",
            fine="FMRI_REST",
            n=2,
            study="study.demoA.01",
        ),
        dict(
            uid=UID_001_02_T1,
            patient="demoA",
            folder="sub-demoA",
            desc="t1_mprage",
            seq="anat",
            fine="ANAT_T1",
            n=3,
            study="study.demoA.02",
        ),
        dict(
            uid=UID_002_01_T1,
            patient="demoB",
            folder="sub-demoB",
            desc="t1_mprage",
            seq="anat",
            fine="ANAT_T1",
            n=1,
            study="study.demoB.01",
        ),
        dict(
            uid=UID_002_01_LOC,
            patient="demoB",
            folder="sub-demoB",
            desc="localizer",
            seq="unknown",
            fine="LOCALIZER",
            n=2,
            study="study.demoB.01",
            confidence=0.35,
            requires_manual=True,
        ),
    ]
    out: list[DicomSeries] = []
    for spec in specs:
        src = dicom / str(spec["folder"])
        out.append(
            DicomSeries(
                patient_id=str(spec["patient"]),
                study_description="PreviewDemo",
                series_description=str(spec["desc"]),
                protocol_name=str(spec["desc"]),
                series_number=int(spec["n"]),
                acquisition_number=1,
                modality="MR",
                num_images=2,
                source_dir=src,
                sample_file=src / f"{spec['desc']}.dcm",
                status=SeriesStatus.PENDING,
                sequence_type=str(spec["seq"]),
                fine_sequence_type=str(spec["fine"]),
                smart_name=str(spec["desc"]),
                series_instance_uid=str(spec["uid"]),
                study_instance_uid=str(spec["study"]),
                sequence_confidence=float(spec.get("confidence", 0.9)),
                source_subject_folder=str(src),
                subject_detection_method="preview_demo",
                requires_manual_mapping=bool(spec.get("requires_manual", False)),
                convertible_to_nifti=True,
                convertibility="convertible",
            )
        )
    return out


def build_preview_plan(
    series: list[DicomSeries] | None = None,
    *,
    root: Path | None = None,
    with_audit_issues: bool = False,
) -> tuple[list[DicomSeries], BIDSConversionPlan]:
    """Build series + :class:`BIDSConversionPlan` for UI preview.

    When ``with_audit_issues`` is True, the localizer stays included (review item).
    Otherwise it is excluded from conversion so the normal scenario stays clean.
    """
    base = Path(root) if root is not None else Path("preview_demo")
    series = list(series or build_preview_series(root=base))
    plan = BIDSConversionPlan.from_series(
        series,
        dataset_root=str(base / "dicom"),
        output_root=str(base / "bids_out"),
    )
    # Longitudinal sessions for subject 001
    for item in plan.items:
        if item.source_series_uid in {UID_001_01_T1, UID_001_01_FUNC}:
            plan.apply_edit(item.source_series_uid, session="01")
        elif item.source_series_uid == UID_001_02_T1:
            plan.apply_edit(item.source_series_uid, session="02")
        elif item.source_series_uid in {UID_002_01_T1, UID_002_01_LOC}:
            plan.apply_edit(item.source_series_uid, session="01")
        if item.source_series_uid == UID_002_01_LOC and not with_audit_issues:
            plan.apply_edit(item.source_series_uid, include_in_conversion=False)
        if item.source_series_uid == UID_001_01_FUNC:
            plan.apply_edit(item.source_series_uid, datatype="func", suffix="bold", task="rest")
    plan.refresh_filenames()
    return series, plan
