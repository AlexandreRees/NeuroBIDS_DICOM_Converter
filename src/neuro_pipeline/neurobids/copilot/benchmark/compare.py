"""Deterministic comparison helpers for Copilot benchmark evaluation."""

from __future__ import annotations

import json
import re
from typing import Any

_MISSING = object()


def normalize_label(value: Any, *, prefix: str = "sub-") -> str:
    text = str(value or "").strip()
    for pref in (prefix, "sub-", "ses-"):
        if text.lower().startswith(pref):
            text = text[len(pref) :]
    return text.strip()


def labels_equal(expected: Any, observed: Any) -> bool:
    return normalize_label(expected) == normalize_label(observed)


def as_label_set(values: list[Any] | tuple[Any, ...] | None) -> set[str]:
    return {normalize_label(v) for v in (values or []) if str(v).strip()}


def lookup(data: Any, path: str) -> Any:
    """Dotted-path lookup. ``a.b.c`` walks mappings."""
    current: Any = data
    for part in path.split("."):
        if current is None or current is _MISSING:
            return _MISSING
        if isinstance(current, dict):
            if part in current:
                current = current[part]
            else:
                return _MISSING
        else:
            return _MISSING
    return current


def values_equal(expected: Any, observed: Any) -> bool:
    if expected is _MISSING or observed is _MISSING:
        return False
    if isinstance(expected, bool) or isinstance(observed, bool):
        return expected == observed
    if isinstance(expected, (int, float)) and isinstance(observed, (int, float)):
        return expected == observed
    if isinstance(expected, list) and isinstance(observed, list):
        if all(_is_scalar(x) for x in expected + observed):
            return sorted(_norm_scalar(x) for x in expected) == sorted(
                _norm_scalar(x) for x in observed
            )
        if len(expected) != len(observed):
            return False
        return all(values_equal(a, b) for a, b in zip(expected, observed))
    if isinstance(expected, dict) and isinstance(observed, dict):
        for key, value in expected.items():
            if key not in observed or not values_equal(value, observed[key]):
                return False
        return True
    if isinstance(expected, str) and isinstance(observed, str):
        if _looks_like_label(expected) or _looks_like_label(observed):
            return labels_equal(expected, observed)
        return expected == observed
    return expected == observed


def arguments_match(expected: dict[str, Any], observed: dict[str, Any]) -> bool:
    """Subset match: every expected key/value must appear on the call."""
    if not isinstance(observed, dict):
        return False
    for key, value in expected.items():
        if key not in observed:
            return False
        if not values_equal(value, observed[key]):
            return False
    return True


def compare_answer(expected: dict[str, Any] | str, data: Any) -> list[str]:
    """Return mismatch descriptions (empty list means success)."""
    mismatches: list[str] = []
    if isinstance(expected, str):
        blob = _as_text(data)
        if expected.strip().lower() not in blob.lower():
            mismatches.append(f"expected answer text {expected!r} not found")
        return mismatches
    if not isinstance(expected, dict):
        mismatches.append("expected_answer must be an object or string")
        return mismatches
    for path, want in expected.items():
        got = lookup(data, path)
        if got is _MISSING:
            mismatches.append(f"{path}: missing (expected {want!r})")
        elif not values_equal(want, got):
            mismatches.append(f"{path}: expected {want!r}, observed {got!r}")
    return mismatches


def compare_id_list(expected: list[str], observed: list[Any], *, label: str) -> list[str]:
    want = as_label_set(expected)
    got = as_label_set(observed)
    if want != got:
        return [f"{label}: expected {sorted(want)}, observed {sorted(got)}"]
    return []


def contains_all(text: str, needles: list[str]) -> list[str]:
    blob = (text or "").lower()
    missing = [n for n in needles if n.lower() not in blob]
    return [f"response missing {n!r}" for n in missing]


def detect_numeric_hallucination(
    message: str,
    expected_answer: dict[str, Any] | None,
) -> list[str]:
    """Flag message counts that contradict explicit numeric expectations."""
    if not message or not isinstance(expected_answer, dict):
        return []
    flags: list[str] = []
    pairs = (
        ("n_subjects", r"(\d+)\s+subjects?"),
        ("summary.n_subjects", r"(\d+)\s+subjects?"),
        ("n_sessions", r"(\d+)\s+sessions?"),
        ("summary.n_sessions", r"(\d+)\s+sessions?"),
        ("n_matches", r"(\d+)\s+acquisitions?"),
        ("summary.n_acquisitions", r"(\d+)\s+acquisitions?"),
        ("n_acquisitions", r"(\d+)\s+acquisitions?"),
    )
    for key, pattern in pairs:
        if key not in expected_answer:
            continue
        want = expected_answer[key]
        if not isinstance(want, int):
            continue
        match = re.search(pattern, message, flags=re.I)
        if match is None:
            continue
        observed = int(match.group(1))
        if observed != want:
            flags.append(
                f"message claims {observed} for {key}, ground truth is {want}"
            )
    return flags


def json_preview(value: Any, *, limit: int = 400) -> str:
    try:
        text = json.dumps(value, ensure_ascii=False, default=str, sort_keys=True)
    except TypeError:
        text = str(value)
    if len(text) > limit:
        return text[: limit - 1] + "…"
    return text


def _is_scalar(value: Any) -> bool:
    return isinstance(value, (str, int, float, bool)) or value is None


def _norm_scalar(value: Any) -> Any:
    if isinstance(value, str) and _looks_like_label(value):
        return normalize_label(value)
    return value


def _looks_like_label(value: str) -> bool:
    text = value.strip()
    return text.startswith("sub-") or text.startswith("ses-") or text.isdigit()


def _as_text(data: Any) -> str:
    if isinstance(data, str):
        return data
    try:
        return json.dumps(data, ensure_ascii=False, default=str)
    except TypeError:
        return str(data)


__all__ = [
    "arguments_match",
    "as_label_set",
    "compare_answer",
    "compare_id_list",
    "contains_all",
    "detect_numeric_hallucination",
    "json_preview",
    "labels_equal",
    "lookup",
    "normalize_label",
    "values_equal",
]
