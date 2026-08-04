#!/usr/bin/env python3
"""Fail-closed PHI scanner for generated Level-1 release files.

Source files are never edited. Conversion code creates a minimal derivative
containing only scientific values, then this module scans that derivative.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PhiFinding:
    phi_type: str
    location: str


PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "subject_or_patient_identifier",
        re.compile(
            r"(?i)(?:patient|subject|participant|hospital)[\s_.-]*"
            r"(?:id|name|identifier|number)"
        ),
    ),
    (
        "local_subject_id",
        re.compile(
            r"(?i)(?<![A-Za-z0-9])SUB(?:TON|ON|G|C|T)"
            r"[\s_-]?0*\d{1,4}(?![A-Za-z0-9])"
        ),
    ),
    (
        "operator_or_institution",
        re.compile(r"(?i)(?:operator|institution|hospital|site[\s_.-]*name)"),
    ),
    (
        "calendar_date",
        re.compile(
            r"(?<!\d)(?:19|20)\d{2}[-_/]?(?:0[1-9]|1[0-2])[-_/]?"
            r"(?:0[1-9]|[12]\d|3[01])(?!\d)"
        ),
    ),
    (
        "absolute_local_path",
        re.compile(r"(?i)(?:[A-Z]:\\Users\\[^\\\s]+|/(?:home|Users)/[^/\s]+/)"),
    ),
    (
        "email",
        re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b"),
    ),
    (
        "scanner_serial",
        re.compile(r"(?i)(?:scanner|device|station)[\s_.-]*serial"),
    ),
    (
        "dicom_uid",
        re.compile(
            r"(?i)(?:studyinstanceuid|seriesinstanceuid|frameofreferenceuid|"
            r"(?<![A-Za-z])UID(?![A-Za-z]))"
        ),
    ),
    (
        "accession_number",
        re.compile(r"(?i)accession[\s_.-]*(?:number|no|num)?"),
    ),
)


def scan_text(text: str, location: str) -> list[PhiFinding]:
    return [
        PhiFinding(phi_type=label, location=location)
        for label, pattern in PATTERNS
        if pattern.search(text)
    ]


def scan_generated_file(path: Path) -> list[PhiFinding]:
    """Scan a generated TSV/JSON/text file and its BIDS-relative filename."""
    findings = scan_text(path.name, "filename")
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return findings + [PhiFinding("unreadable_binary_output", "content")]
    findings.extend(scan_text(text, "content"))
    return findings


def assert_phi_pass(path: Path) -> None:
    findings = scan_generated_file(path)
    if findings:
        labels = ", ".join(sorted({item.phi_type for item in findings}))
        raise ValueError(f"PHI scan failed for generated output {path}: {labels}")


def source_phi_labels(path: Path, sample_bytes: int = 1024 * 1024) -> list[str]:
    """Conservative source screening for audit only; never modifies the source."""
    findings = scan_text(path.name, "filename")
    if path.suffix.lower() in {
        ".resp",
        ".puls",
        ".ecg",
        ".pmu",
        ".ext",
        ".ext1",
        ".ext2",
        ".txt",
        ".log",
        ".csv",
        ".tsv",
        ".m",
    }:
        size = path.stat().st_size
        half = sample_bytes // 2
        with path.open("rb") as handle:
            if size <= sample_bytes:
                raw = handle.read()
            else:
                raw = handle.read(half)
                handle.seek(max(0, size - half))
                raw += handle.read(half)
        text = raw.decode("utf-8", errors="replace")
        findings.extend(scan_text(text, "source content"))
    return sorted({finding.phi_type for finding in findings})


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Scan generated release files for PHI.")
    parser.add_argument("files", nargs="+", type=Path)
    args = parser.parse_args()
    failed = False
    for item in args.files:
        findings = scan_generated_file(item)
        print(f"{item}\t{'PASS' if not findings else 'FAIL'}")
        failed |= bool(findings)
    raise SystemExit(1 if failed else 0)
