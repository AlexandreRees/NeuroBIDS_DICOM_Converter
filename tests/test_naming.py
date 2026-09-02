"""Tests for the smart filename engine."""

from __future__ import annotations

from pathlib import Path

from neuro_pipeline.utils.naming import SmartFilenameEngine


def test_named_examples(naming_rules_file: Path) -> None:
    engine = SmartFilenameEngine.from_yaml(naming_rules_file)
    assert engine.resolve("MPRAGE") == "T1w"
    assert engine.resolve("t1_mprage_sag") == "T1w"
    assert engine.resolve("FLAIR") == "FLAIR"
    assert engine.resolve("REST_AP") == "REST_AP"
    assert engine.resolve("DWI") == "DWI"
    assert engine.resolve("Movie") == "Movie"


def test_fallback_keeps_original(naming_rules_file: Path) -> None:
    engine = SmartFilenameEngine.from_yaml(naming_rules_file)
    assert engine.resolve("Custom_Weird_Sequence") == "Custom_Weird_Sequence"


def test_sanitize_invalid_chars(naming_rules_file: Path) -> None:
    engine = SmartFilenameEngine.from_yaml(naming_rules_file)
    assert ":" not in engine.resolve("Weird:Name?/Series")
