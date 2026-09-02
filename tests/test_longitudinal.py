"""Tests for longitudinal subject / session management."""

from __future__ import annotations

from pathlib import Path

from neuro_pipeline.bids.longitudinal import LongitudinalManager


def test_parse_subject_visit_token() -> None:
    mgr = LongitudinalManager()
    ent = mgr.parse_subject_session_token("Subject001_visit1")
    assert ent.subject_label == "Subject001"
    assert ent.session_label == "01"
    assert ent.subject_id == "sub-Subject001"
    assert ent.session_id == "ses-01"


def test_parse_subject_visit2() -> None:
    mgr = LongitudinalManager()
    ent = mgr.parse_subject_session_token("Subject001_visit2")
    assert ent.subject_id == "sub-Subject001"
    assert ent.session_id == "ses-02"


def test_parse_subject_and_session_separately() -> None:
    mgr = LongitudinalManager()
    assert mgr.parse_subject("sub-001") == "001"
    assert mgr.parse_session("ses-01") == "01"
    assert mgr.parse_session("") is None


def test_validate_structure_ok(tmp_path: Path) -> None:
    (tmp_path / "sub-001" / "ses-01" / "anat").mkdir(parents=True)
    (tmp_path / "sub-001" / "ses-02" / "anat").mkdir(parents=True)
    issues = LongitudinalManager().validate_structure(tmp_path)
    assert issues == []


def test_validate_structure_mixed(tmp_path: Path) -> None:
    (tmp_path / "sub-001" / "ses-01").mkdir(parents=True)
    (tmp_path / "sub-001" / "anat").mkdir(parents=True)
    issues = LongitudinalManager().validate_structure(tmp_path)
    assert any("mixed" in i.lower() for i in issues)


def test_detect_duplicates() -> None:
    mgr = LongitudinalManager()
    a = mgr.parse_subject_session_token("Subject001_visit1")
    b = mgr.parse_subject_session_token("Subject001_visit1")
    c = mgr.parse_subject_session_token("Subject001_visit2")
    dupes = mgr.detect_duplicates([a, b, c])
    assert len(dupes) == 1
    assert "ses-01" in dupes[0]


def test_queue_from_names() -> None:
    ids = LongitudinalManager().queue_from_names(
        ["Subject001_visit1", "Subject001_visit2"]
    )
    assert [x.subject_id for x in ids] == ["sub-Subject001", "sub-Subject001"]
    assert [x.session_id for x in ids] == ["ses-01", "ses-02"]
