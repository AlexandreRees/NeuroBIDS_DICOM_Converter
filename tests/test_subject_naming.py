"""Subject / session naming from GUI-provided labels only."""

from __future__ import annotations

import pytest

from neuro_pipeline.bids.naming import _prefix
from neuro_pipeline.bids.subject_manager import SubjectManager


def test_subject_001_becomes_sub_001() -> None:
    mgr = SubjectManager()
    assert mgr.validate_subject_id("001") == "001"
    assert mgr.parse("001").subject_id == "sub-001"


def test_session_01_becomes_ses_01() -> None:
    mgr = SubjectManager()
    assert mgr.validate_session_id("01") == "01"
    assert mgr.parse("001", "01").session_id == "ses-01"


def test_prefix_with_and_without_session() -> None:
    assert _prefix("001") == "sub-001"
    assert _prefix("001", "01") == "sub-001_ses-01"


def test_rejects_spaces() -> None:
    with pytest.raises(ValueError):
        SubjectManager().validate_subject_id("sub 001")
