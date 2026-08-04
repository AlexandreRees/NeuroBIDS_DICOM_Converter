#!/usr/bin/env python3
"""Fail-closed physiology conversion helpers for the Level-1 release.

The current Siemens PMU logs are not assigned a sampling frequency or run
alignment from undocumented constants. Files lacking explicit frequency and
relative start-time metadata are routed to manual review.
"""

from __future__ import annotations

import gzip
import json
import re
from dataclasses import dataclass
from pathlib import Path


CHANNELS = {
    ".ecg": "cardiac",
    ".puls": "cardiac",
    ".resp": "respiratory",
    ".ext": "trigger",
    ".ext1": "trigger",
    ".ext2": "trigger",
    ".pmu": "physio",
}

FREQUENCY_PATTERNS = (
    re.compile(
        r"(?i)\b(?:SamplingFrequency|SamplingRate|SampleRate)\s*[:=]\s*"
        r"(\d+(?:\.\d+)?)\s*(?:Hz)?\b"
    ),
)
INTERVAL_PATTERN = re.compile(
    r"(?i)\b(?:SampleInterval|SamplingInterval)\s*[:=]\s*"
    r"(\d+(?:\.\d+)?)\s*(ms|s)\b"
)
START_TIME_PATTERN = re.compile(
    r"(?i)\bStartTime\s*[:=]\s*(-?\d+(?:\.\d+)?)\s*(?:s|sec|seconds)?\b"
)


@dataclass(frozen=True)
class PhysioAssessment:
    status: str
    reason: str
    sampling_frequency: float | None = None
    start_time: float | None = None
    columns: tuple[str, ...] = ()


def _metadata_sample(path: Path, sample_bytes: int = 1024 * 1024) -> str:
    size = path.stat().st_size
    half = sample_bytes // 2
    with path.open("rb") as handle:
        if size <= sample_bytes:
            raw = handle.read()
        else:
            raw = handle.read(half)
            handle.seek(max(0, size - half))
            raw += handle.read(half)
    return raw.decode("utf-8", errors="replace")


def _explicit_frequency(text: str) -> float | None:
    values: list[float] = []
    for pattern in FREQUENCY_PATTERNS:
        values.extend(float(item) for item in pattern.findall(text))
    for value, unit in INTERVAL_PATTERN.findall(text):
        interval = float(value)
        if interval > 0:
            values.append((1000.0 if unit.lower() == "ms" else 1.0) / interval)
    unique = {round(value, 12) for value in values if value > 0}
    return unique.pop() if len(unique) == 1 else None


def _explicit_start_time(text: str) -> float | None:
    values = {float(item) for item in START_TIME_PATTERN.findall(text)}
    return values.pop() if len(values) == 1 else None


def assess_physio_group(sources: list[Path]) -> PhysioAssessment:
    if not sources:
        return PhysioAssessment("requires_manual_review", "no source files")
    channels: list[str] = []
    frequencies: set[float] = set()
    starts: set[float] = set()
    for source in sources:
        channel = CHANNELS.get(source.suffix.lower())
        if channel is None:
            return PhysioAssessment(
                "requires_manual_review",
                f"unsupported physiology extension {source.suffix}",
            )
        channels.append(channel)
        text = _metadata_sample(source)
        frequency = _explicit_frequency(text)
        start = _explicit_start_time(text)
        if frequency is None:
            return PhysioAssessment(
                "requires_manual_review",
                f"{source.name}: no unambiguous explicit sampling frequency",
            )
        if start is None:
            return PhysioAssessment(
                "requires_manual_review",
                f"{source.name}: no explicit BIDS-relative StartTime/run alignment",
            )
        frequencies.add(frequency)
        starts.add(start)
    if len(frequencies) != 1:
        return PhysioAssessment(
            "requires_manual_review", "channels have different sampling frequencies"
        )
    if len(starts) != 1:
        return PhysioAssessment(
            "requires_manual_review", "channels have different relative start times"
        )
    return PhysioAssessment(
        "requires_manual_review",
        "metadata is explicit, but vendor payload parsing requires validated format-specific tests",
        sampling_frequency=next(iter(frequencies)),
        start_time=next(iter(starts)),
        columns=tuple(channels),
    )


def write_physio(
    *,
    tsv_gz: Path,
    sidecar_json: Path,
    rows: list[list[float]],
    sampling_frequency: float,
    start_time: float,
    columns: list[str],
) -> None:
    """Write already validated numeric rows; input parsing is intentionally separate."""
    if sampling_frequency <= 0 or not columns:
        raise ValueError("invalid physiology metadata")
    if any(len(row) != len(columns) for row in rows):
        raise ValueError("physiology row width does not match Columns")
    tsv_gz.parent.mkdir(parents=True, exist_ok=True)
    with tsv_gz.open("xb") as raw:
        with gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as compressed:
            for row in rows:
                compressed.write(
                    ("\t".join(format(value, ".9g") for value in row) + "\n").encode(
                        "ascii"
                    )
                )
    metadata = {
        "SamplingFrequency": sampling_frequency,
        "StartTime": start_time,
        "Columns": columns,
        "Manufacturer": "unknown",
    }
    with sidecar_json.open("x", encoding="utf-8") as handle:
        json.dump(metadata, handle, indent=2)
        handle.write("\n")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Assess physiology conversion readiness.")
    parser.add_argument("sources", nargs="+", type=Path)
    args = parser.parse_args()
    result = assess_physio_group(args.sources)
    print(f"{result.status}: {result.reason}")
    raise SystemExit(0 if result.status == "ready" else 2)
