"""Synthetic NeuroBIDS Copilot benchmark dataset (never a real research dataset).

The dataset is small, fully specified, and constructed in memory from
:class:`DicomSeries` + :class:`PlannedAcquisition` objects. Placeholder DICOM
files contain no pixel data and are never used as ground truth for research.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from neuro_pipeline.bids.conversion_plan import BIDSConversionPlan, PlannedAcquisition
from neuro_pipeline.models import DicomSeries, SeriesStatus
from neuro_pipeline.neurobids.copilot.plan_ops import clone_plan
from neuro_pipeline.neurobids.copilot.session import CopilotSession

# Stable series UIDs — referenced by benchmark JSON cases.
UID_001_01_T1W = "uid.001.01.t1w"
UID_001_01_FUNC = "uid.001.01.func"
UID_001_01_DWI = "uid.001.01.dwi"
UID_001_01_LOC = "uid.001.01.loc"
UID_001_02_T1W = "uid.001.02.t1w"
UID_001_02_FUNC = "uid.001.02.func"
UID_002_01_T1W = "uid.002.01.t1w"
UID_002_01_FUNC = "uid.002.01.func"
UID_002_01_DWI = "uid.002.01.dwi"
UID_002_01_AMBIG = "uid.002.01.ambig"
UID_002_01_PHOENIX = "uid.002.01.phoenix"
UID_003_01_T1W = "uid.003.01.t1w"
UID_003_01_LOC = "uid.003.01.loc"
UID_003_01_UNMAP = "uid.003.01.unmap"
UID_004_01_T2W = "uid.004.01.t2w"
UID_004_01_FLAIR = "uid.004.01.flair"
UID_004_01_TASK = "uid.004.01.task"
UID_004_01_SBREF = "uid.004.01.sbref"
UID_004_01_FMAP_AP = "uid.004.01.fmap_ap"
UID_004_01_FMAP_PA = "uid.004.01.fmap_pa"
UID_004_01_ME1 = "uid.004.01.mecho1"
UID_004_01_ME2 = "uid.004.01.mecho2"
UID_004_01_RUN02 = "uid.004.01.run02"
UID_004_01_MIXED = "uid.004.01.mixed"

T1W_UIDS = (UID_001_01_T1W, UID_001_02_T1W, UID_002_01_T1W, UID_003_01_T1W)
T2W_UIDS = (UID_004_01_T2W,)
FLAIR_UIDS = (UID_004_01_FLAIR,)
FUNC_UIDS = (
    UID_001_01_FUNC,
    UID_001_02_FUNC,
    UID_002_01_FUNC,
    UID_004_01_TASK,
    UID_004_01_SBREF,
    UID_004_01_ME1,
    UID_004_01_ME2,
    UID_004_01_RUN02,
)
TASK_FUNC_UIDS = (UID_004_01_TASK,)
SBREF_UIDS = (UID_004_01_SBREF,)
FMAP_UIDS = (UID_004_01_FMAP_AP, UID_004_01_FMAP_PA)
MULTIECHO_UIDS = (UID_004_01_ME1, UID_004_01_ME2)
DWI_UIDS = (UID_001_01_DWI, UID_002_01_DWI)
LOCALIZER_UIDS = (UID_001_01_LOC, UID_003_01_LOC)
AMBIGUOUS_UIDS = (UID_002_01_AMBIG, UID_003_01_UNMAP)
CONFLICT_UIDS = (UID_004_01_MIXED,)
UNMAPPED_UIDS = (UID_002_01_AMBIG, UID_003_01_UNMAP, UID_001_01_LOC, UID_003_01_LOC, UID_002_01_PHOENIX)
EXCLUDED_UIDS = (UID_002_01_PHOENIX,)
SUBJECT_002_UIDS = (
    UID_002_01_T1W,
    UID_002_01_FUNC,
    UID_002_01_DWI,
    UID_002_01_AMBIG,
    UID_002_01_PHOENIX,
)
SESSION_02_UIDS = (UID_001_02_T1W, UID_001_02_FUNC)
SUBJECT_001_SES01_UIDS = (UID_001_01_T1W, UID_001_01_FUNC, UID_001_01_DWI, UID_001_01_LOC)

# Explicit acquisition table. Datatype/suffix here are the *intended* plan
# fields before filename refresh; included unknown series become datatype
# "unknown" after refresh_filenames (fallback NIfTI naming).
_ACQ_SPEC: tuple[dict[str, Any], ...] = (
    # Subject 001 — longitudinal (ses-01 has DWI; ses-02 does not).
    dict(
        uid=UID_001_01_T1W,
        subject="001",
        session="01",
        description="t1_mprage",
        sequence_type="anat",
        fine="ANAT_T1",
        datatype="anat",
        suffix="T1w",
        include=True,
    ),
    dict(
        uid=UID_001_01_FUNC,
        subject="001",
        session="01",
        description="rest_bold",
        sequence_type="func",
        fine="FMRI_REST",
        datatype="func",
        suffix="bold",
        task="rest",
        include=True,
    ),
    dict(
        uid=UID_001_01_DWI,
        subject="001",
        session="01",
        description="dwi_dir64",
        sequence_type="dwi",
        fine="DWI_MULTI",
        datatype="dwi",
        suffix="dwi",
        include=True,
    ),
    dict(
        uid=UID_001_01_LOC,
        subject="001",
        session="01",
        description="localizer",
        sequence_type="unknown",
        fine="LOCALIZER",
        datatype="",
        suffix="",
        include=True,
        confidence=0.4,
    ),
    dict(
        uid=UID_001_02_T1W,
        subject="001",
        session="02",
        description="t1_mprage",
        sequence_type="anat",
        fine="ANAT_T1",
        datatype="anat",
        suffix="T1w",
        include=True,
    ),
    dict(
        uid=UID_001_02_FUNC,
        subject="001",
        session="02",
        description="rest_bold",
        sequence_type="func",
        fine="FMRI_REST",
        datatype="func",
        suffix="bold",
        task="rest",
        include=True,
    ),
    # Subject 002 — single session, plus ambiguous + excluded scout.
    dict(
        uid=UID_002_01_T1W,
        subject="002",
        session="01",
        description="t1_mprage",
        sequence_type="anat",
        fine="ANAT_T1",
        datatype="anat",
        suffix="T1w",
        include=True,
    ),
    dict(
        uid=UID_002_01_FUNC,
        subject="002",
        session="01",
        description="rest_bold",
        sequence_type="func",
        fine="FMRI_REST",
        datatype="func",
        suffix="bold",
        task="rest",
        include=True,
    ),
    dict(
        uid=UID_002_01_DWI,
        subject="002",
        session="01",
        description="dwi_dir64",
        sequence_type="dwi",
        fine="DWI_MULTI",
        datatype="dwi",
        suffix="dwi",
        include=True,
    ),
    dict(
        uid=UID_002_01_AMBIG,
        subject="002",
        session="01",
        description="ep2d_mixed",
        sequence_type="unknown",
        fine="UNKNOWN",
        datatype="",
        suffix="",
        include=True,
        manual=True,
        confidence=0.25,
    ),
    dict(
        uid=UID_002_01_PHOENIX,
        subject="002",
        session="01",
        description="PhoenixZIPReport",
        sequence_type="unknown",
        fine="SCOUT",
        datatype="",
        suffix="",
        include=False,
        confidence=0.2,
    ),
    # Subject 003 — single session; unmapped acquisition; localizer.
    dict(
        uid=UID_003_01_T1W,
        subject="003",
        session="01",
        description="t1_mprage",
        sequence_type="anat",
        fine="ANAT_T1",
        datatype="anat",
        suffix="T1w",
        include=True,
    ),
    dict(
        uid=UID_003_01_LOC,
        subject="003",
        session="01",
        description="localizer",
        sequence_type="unknown",
        fine="LOCALIZER",
        datatype="",
        suffix="",
        include=True,
        confidence=0.4,
    ),
    dict(
        uid=UID_003_01_UNMAP,
        subject="003",
        session="01",
        description="unknown_protocol",
        sequence_type="unknown",
        fine="UNKNOWN",
        datatype="",
        suffix="",
        include=True,
        manual=True,
        confidence=0.15,
    ),
    # Subject 004 — extra modalities for Copilot reasoning tools (additive).
    dict(
        uid=UID_004_01_T2W,
        subject="004",
        session="01",
        description="t2_tse",
        sequence_type="anat",
        fine="ANAT_T2",
        datatype="anat",
        suffix="T2w",
        acquisition="tse",
        include=True,
        series_number=1,
    ),
    dict(
        uid=UID_004_01_FLAIR,
        subject="004",
        session="01",
        description="t2_flair",
        sequence_type="anat",
        fine="FLAIR",
        datatype="anat",
        suffix="FLAIR",
        include=True,
        series_number=2,
    ),
    dict(
        uid=UID_004_01_TASK,
        subject="004",
        session="01",
        description="task_nback_bold",
        sequence_type="func",
        fine="FMRI_TASK",
        datatype="func",
        suffix="bold",
        task="nback",
        include=True,
        series_number=3,
    ),
    dict(
        uid=UID_004_01_SBREF,
        subject="004",
        session="01",
        description="func_sbref",
        sequence_type="func",
        fine="FMRI_REST",
        datatype="func",
        suffix="sbref",
        include=True,
        series_number=4,
    ),
    dict(
        uid=UID_004_01_FMAP_AP,
        subject="004",
        session="01",
        description="fmap_AP",
        sequence_type="fmap",
        fine="FMAP",
        datatype="fmap",
        suffix="epi",
        direction="AP",
        include=True,
        series_number=5,
    ),
    dict(
        uid=UID_004_01_FMAP_PA,
        subject="004",
        session="01",
        description="fmap_PA",
        sequence_type="fmap",
        fine="FMAP",
        datatype="fmap",
        suffix="epi",
        direction="PA",
        include=True,
        series_number=6,
    ),
    dict(
        uid=UID_004_01_ME1,
        subject="004",
        session="01",
        description="multiecho_bold_echo-1",
        sequence_type="func",
        fine="FMRI_TASK",
        datatype="func",
        suffix="bold",
        task="rest",
        include=True,
        series_number=7,
    ),
    dict(
        uid=UID_004_01_ME2,
        subject="004",
        session="01",
        description="multiecho_bold_echo-2",
        sequence_type="func",
        fine="FMRI_TASK",
        datatype="func",
        suffix="bold",
        task="rest",
        include=True,
        series_number=8,
    ),
    dict(
        uid=UID_004_01_RUN02,
        subject="004",
        session="01",
        description="rest_bold_run-02",
        sequence_type="func",
        fine="FMRI_REST",
        datatype="func",
        suffix="bold",
        task="rest",
        run="02",
        include=True,
        series_number=9,
    ),
    dict(
        uid=UID_004_01_MIXED,
        subject="004",
        session="01",
        description="mprage",
        protocol="tse",
        sequence_type="anat",
        fine="ANAT_CONFLICT",
        datatype="anat",
        suffix="T1w",
        include=True,
        confidence=0.45,
        series_number=10,
    ),
)


def acquisition_spec() -> tuple[dict[str, Any], ...]:
    """Return the immutable acquisition specification table."""
    return _ACQ_SPEC


def build_benchmark_session(root: Path | None = None) -> CopilotSession:
    """Build a CopilotSession over the synthetic benchmark dataset.

    Placeholder DICOM files are written under ``root/dicom`` so tests can
    prove they are never modified. No real imaging data is used.
    """
    if root is None:
        root = Path(tempfile.mkdtemp(prefix="neurobids_copilot_benchmark_"))
    root = Path(root)
    dicom_root = root / "dicom"
    output_root = root / "bids_out"
    dicom_root.mkdir(parents=True, exist_ok=True)
    output_root.mkdir(parents=True, exist_ok=True)

    series_list: list[DicomSeries] = []
    items: list[PlannedAcquisition] = []
    for spec in _ACQ_SPEC:
        series, item = _build_acquisition(spec, dicom_root)
        series_list.append(series)
        items.append(item)

    plan = BIDSConversionPlan(
        items=items,
        dataset_root=str(dicom_root),
        output_root=str(output_root),
    )
    plan._series_by_uid = {s.series_instance_uid: s for s in series_list}
    plan._baseline = [item.clone() for item in items]
    plan.refresh_filenames()

    n_files = sum(1 for _ in dicom_root.rglob("*.dcm"))
    return CopilotSession(
        plan=plan,
        series_list=series_list,
        detection_method="patient_id",
        detection_reason="synthetic benchmark dataset",
        n_dicom_files=n_files,
        curation_rules_path=root / "curation_rules.json",
    )


def clone_benchmark_session(session: CopilotSession) -> CopilotSession:
    """Independent session copy so mutation cases cannot leak state."""
    return CopilotSession(
        plan=clone_plan(session.plan),
        series_list=list(session.series_list),
        conversion_busy=False,
        detection_method=session.detection_method,
        detection_reason=session.detection_reason,
        n_dicom_files=session.n_dicom_files,
        curation_rules_path=session.curation_rules_path,
    )


def compute_ground_truth(session: CopilotSession) -> dict[str, Any]:
    """Derive explicit dataset facts from the live plan/context."""
    ctx = session.dataset_context(refresh=True)
    subjects = list(ctx.subjects)
    subject_ids = [s.subject_id for s in subjects]
    n_sessions = sum(len(s.sessions) for s in subjects)
    multi = [s.subject_id for s in subjects if len(s.sessions) > 1]
    single = [s.subject_id for s in subjects if len(s.sessions) == 1]

    acq_rows: list[dict[str, Any]] = []
    for subj in subjects:
        for ses in subj.sessions:
            for acq in ses.acquisitions:
                datatype = (acq.bids.datatype if acq.bids else "") or ""
                included = True if acq.bids is None else bool(acq.bids.include)
                acq_rows.append(
                    {
                        "series_uid": acq.series_uid,
                        "subject_id": subj.subject_id,
                        "session_id": ses.session_id,
                        "description": acq.series_description,
                        "sequence_type": acq.sequence_type,
                        "datatype": datatype,
                        "suffix": (acq.bids.suffix if acq.bids else "") or "",
                        "include": included,
                        "requires_manual_mapping": bool(acq.requires_manual_mapping),
                    }
                )

    by_uid = {row["series_uid"]: row for row in acq_rows}
    datatypes = sorted({row["datatype"] for row in acq_rows if row["datatype"]})
    issue_codes = sorted({i.code for i in ctx.metadata_issues if i.code})

    return {
        "n_subjects": len(subjects),
        "subject_ids": subject_ids,
        "n_sessions": n_sessions,
        "multi_session_subjects": multi,
        "single_session_subjects": single,
        "n_acquisitions": len(acq_rows),
        "n_dicom_files": session.n_dicom_files,
        "modalities": list(ctx.modalities),
        "datatypes": datatypes,
        "datatype_summary": dict(ctx.datatype_summary),
        "t1w_uids": [u for u in T1W_UIDS if u in by_uid],
        "func_uids": [
            row["series_uid"]
            for row in acq_rows
            if row["datatype"] == "func" or row["sequence_type"] == "func"
        ],
        "dwi_uids": [
            row["series_uid"]
            for row in acq_rows
            if row["datatype"] == "dwi" or row["sequence_type"] == "dwi"
        ],
        "localizer_uids": [
            row["series_uid"]
            for row in acq_rows
            if "localizer" in (row["description"] or "").lower()
        ],
        "ambiguous_uids": [
            row["series_uid"] for row in acq_rows if row["requires_manual_mapping"]
        ],
        "unmapped_uids": [
            row["series_uid"]
            for row in acq_rows
            if row["datatype"] in {"", "unknown"}
        ],
        "excluded_uids": [row["series_uid"] for row in acq_rows if not row["include"]],
        "included_uids": [row["series_uid"] for row in acq_rows if row["include"]],
        "subject_002_uids": [
            row["series_uid"] for row in acq_rows if _bare(row["subject_id"]) == "002"
        ],
        "session_02_uids": [
            row["series_uid"] for row in acq_rows if _bare(row["session_id"], "ses-") == "02"
        ],
        "issue_codes": issue_codes,
        "n_included": sum(1 for row in acq_rows if row["include"]),
        "n_excluded": sum(1 for row in acq_rows if not row["include"]),
        "acquisitions": acq_rows,
        "longitudinal_inconsistencies": [
            {
                "subject": "001",
                "present_in_session": "01",
                "missing_in_session": "02",
                "datatype": "dwi",
            }
        ],
        "notes": (
            "Subject 001 is longitudinal: ses-01 has DWI, ses-02 does not. "
            "uid.002.01.ambig and uid.003.01.unmap require manual mapping. "
            "uid.002.01.phoenix is excluded from conversion. "
            "Subject 004 holds T2w, FLAIR, task BOLD, SBRef, fmap AP/PA, "
            "multi-echo, run-02, and a conflicting mprage/tse pair (description vs protocol)."
        ),
    }


def dicom_mtime_map(session: CopilotSession) -> dict[str, int]:
    root = Path(session.plan.dataset_root)
    return {str(p): p.stat().st_mtime_ns for p in root.rglob("*") if p.is_file()}


def dicom_payload_map(session: CopilotSession) -> dict[str, bytes]:
    root = Path(session.plan.dataset_root)
    return {str(p): p.read_bytes() for p in root.rglob("*.dcm")}


def _bare(value: str, prefix: str = "sub-") -> str:
    return (value or "").removeprefix(prefix).strip()


def _build_acquisition(
    spec: dict[str, Any],
    dicom_root: Path,
) -> tuple[DicomSeries, PlannedAcquisition]:
    subject = str(spec["subject"])
    session = str(spec["session"])
    uid = str(spec["uid"])
    description = str(spec["description"])
    protocol = str(spec.get("protocol") or description)
    source = dicom_root / f"sub-{subject}" / f"ses-{session}" / description
    source.mkdir(parents=True, exist_ok=True)
    sample = source / "IM0001.dcm"
    if not sample.exists():
        sample.write_bytes(b"SYNTHETIC_DICOM_BYTES_NOT_PIXELS")

    series = DicomSeries(
        patient_id=subject,
        study_description="NeuroBIDSBenchmark",
        series_description=description,
        protocol_name=protocol,
        series_number=int(spec.get("series_number") or 1),
        acquisition_number=1,
        modality="MR",
        num_images=10,
        source_dir=source,
        sample_file=sample,
        status=SeriesStatus.PENDING,
        sequence_type=str(spec.get("sequence_type") or "unknown"),
        fine_sequence_type=str(spec.get("fine") or ""),
        smart_name=description,
        series_instance_uid=uid,
        study_instance_uid=f"uid.study.{subject}.{session}",
        sequence_confidence=float(spec.get("confidence") or 0.9),
        source_subject_folder=str(source.parent),
        requires_manual_mapping=bool(spec.get("manual", False)),
        convertible_to_nifti=bool(spec.get("convertible", True)),
    )
    item = PlannedAcquisition(
        source_series_uid=uid,
        source_series_number=series.series_number,
        source_series_description=description,
        source_patient_id=subject,
        source_protocol_name=protocol,
        source_sequence_type=series.sequence_type,
        source_smart_name=description,
        source_subject_folder=str(source),
        original_patient_id=subject,
        subject=subject,
        session=session,
        datatype=str(spec.get("datatype") or ""),
        suffix=str(spec.get("suffix") or ""),
        task=str(spec.get("task") or ""),
        run=str(spec.get("run") or ""),
        acquisition=str(spec.get("acquisition") or ""),
        direction=str(spec.get("direction") or ""),
        include_in_conversion=bool(spec.get("include", True)),
        confidence_score=float(spec.get("confidence") or 0.9),
        classification_source=f"benchmark:{series.fine_sequence_type or series.sequence_type}",
    )
    return series, item


__all__ = [
    "AMBIGUOUS_UIDS",
    "DWI_UIDS",
    "EXCLUDED_UIDS",
    "FUNC_UIDS",
    "LOCALIZER_UIDS",
    "SESSION_02_UIDS",
    "SUBJECT_001_SES01_UIDS",
    "SUBJECT_002_UIDS",
    "T1W_UIDS",
    "UID_001_01_DWI",
    "UID_001_01_FUNC",
    "UID_001_01_LOC",
    "UID_001_01_T1W",
    "UID_001_02_FUNC",
    "UID_001_02_T1W",
    "UID_002_01_AMBIG",
    "UID_002_01_DWI",
    "UID_002_01_FUNC",
    "UID_002_01_PHOENIX",
    "UID_002_01_T1W",
    "UID_003_01_LOC",
    "UID_003_01_T1W",
    "UID_003_01_UNMAP",
    "UNMAPPED_UIDS",
    "UID_004_01_FLAIR",
    "UID_004_01_FMAP_AP",
    "UID_004_01_FMAP_PA",
    "UID_004_01_ME1",
    "UID_004_01_ME2",
    "UID_004_01_MIXED",
    "UID_004_01_RUN02",
    "UID_004_01_SBREF",
    "UID_004_01_T2W",
    "UID_004_01_TASK",
    "CONFLICT_UIDS",
    "FLAIR_UIDS",
    "FMAP_UIDS",
    "MULTIECHO_UIDS",
    "SBREF_UIDS",
    "T2W_UIDS",
    "TASK_FUNC_UIDS",
    "acquisition_spec",
    "build_benchmark_session",
    "clone_benchmark_session",
    "compute_ground_truth",
    "dicom_mtime_map",
    "dicom_payload_map",
]
