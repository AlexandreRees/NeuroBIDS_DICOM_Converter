"""Tests for advanced sequence recognition."""

from __future__ import annotations

from neuro_pipeline.dicom.metadata import DicomSeriesMetadata
from neuro_pipeline.dicom.sequence_classifier import (
    FineSequenceType,
    SequenceClassifier,
    SequenceType,
)
from neuro_pipeline.config.paths import project_root


def test_classifier_basic_types() -> None:
    clf = SequenceClassifier()
    assert clf.classify(series_description="t1_mprage_sag") == SequenceType.ANAT
    assert clf.classify(series_description="REST_AP") == SequenceType.FUNC
    assert clf.classify(series_description="ep2d_diff_3scan") == SequenceType.DWI
    assert clf.classify(series_description="gre_field_mapping") == SequenceType.FMAP
    assert clf.classify(series_description="weird_custom") == SequenceType.UNKNOWN


def test_detailed_dwi_with_confidence() -> None:
    clf = SequenceClassifier(project_root() / "configs" / "sequence_rules.yaml")
    meta = DicomSeriesMetadata(
        series_description="ep2d_diff_4scan",
        protocol_name="ep2d_diff",
        b_values=[0, 1000],
        diffusion_present=True,
    )
    result = clf.classify_detailed(meta)
    assert result.type == FineSequenceType.DWI
    assert result.confidence >= 0.9
    assert any("ep2d_diff" in r or "b-values" in r.lower() or "diffusion" in r.lower() for r in result.reason)
    data = result.to_dict()
    assert data["type"] == "DWI"
    assert 0 <= data["confidence"] <= 1


def test_detailed_t1_mprage() -> None:
    clf = SequenceClassifier(project_root() / "configs" / "sequence_rules.yaml")
    result = clf.classify_detailed(series_description="t1_mprage_sag", protocol_name="MPRAGE")
    assert result.type == FineSequenceType.ANAT_T1
    assert result.coarse == SequenceType.ANAT


def test_detailed_fmri_rest() -> None:
    clf = SequenceClassifier(project_root() / "configs" / "sequence_rules.yaml")
    result = clf.classify_detailed(series_description="bold_rest_AP")
    assert result.type == FineSequenceType.FMRI_REST
    assert result.coarse == SequenceType.FUNC


def test_localizer_from_image_type() -> None:
    clf = SequenceClassifier(project_root() / "configs" / "sequence_rules.yaml")
    result = clf.classify_detailed(
        series_description="localizer",
        image_type=["ORIGINAL", "PRIMARY", "LOCALIZER"],
    )
    assert result.type == FineSequenceType.LOCALIZER


def test_dti_pattern() -> None:
    clf = SequenceClassifier(project_root() / "configs" / "sequence_rules.yaml")
    result = clf.classify_detailed(series_description="ep2d_dti_dir64", diffusion_present=True)
    assert result.type in {FineSequenceType.DTI, FineSequenceType.DWI}
