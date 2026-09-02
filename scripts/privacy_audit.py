#!/usr/bin/env python3
"""Publication-oriented privacy / sensitivity audit for this repository.

Flags forbidden data files, absolute local/site paths, assigned secrets,
and assigned PHI *values*. DICOM keyword documentation (e.g. PatientName
as a tag name that must NOT be exported) is intentionally not treated as PHI.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SKIP_RELATIVE_PREFIXES = (
    "scripts/privacy_audit.py",
    "REPOSITORY_DATA_SAFETY.md",
    "PRIVACY_AUDIT_REPORT.txt",
    "SECONDARY_SECURITY_FINDINGS.txt",
)

FORBIDDEN_EXTENSIONS = {
    ".dcm",
    ".dicom",
    ".nii",
    ".bvec",
    ".bval",
    ".fif",
    ".edf",
    ".puls",
    ".resp",
    ".ecg",
    ".pem",
    ".key",
    ".p12",
    ".pfx",
    ".sqlite",
    ".sqlite3",
    ".db",
    ".exe",
}

FORBIDDEN_COMPOUND = (".nii.gz",)

FORBIDDEN_NAMES = {
    ".env",
    "credentials.json",
    "secrets.json",
}

SENSITIVE_PATH_PATTERNS = [
    r"\bmcgill\b",
    r"\bnarval\b",
    r"\bcomputecanada\b",
    r"\bcompute-canada\b",
    r"/project[_-]?data\b",
    r"/study[_-]?data\b",
    r"/raw[_-]?dicom\b",
    r"/deid[_-]?dicom\b",
]

LOCAL_PATH_PATTERNS = [
    r"[A-Za-z]:\\Users\\",
    r"[A-Za-z]:\\Data\\",
    r"[A-Za-z]:\\DICOM\\",
    # Absolute HPC / home paths (not product-name docs like dist\NeuroPipeline\)
    r"/home/[A-Za-z0-9_.-]+/",
    r"/Users/[A-Za-z0-9_.-]+/",
    r"/lustre\d*/",
    r"/scratch/[A-Za-z0-9_.-]+/",
]

SECRET_PATTERNS = [
    r"(?i)api[_-]?key\s*[:=]\s*['\"][^'\"]{10,}",
    r"(?i)secret[_-]?key\s*[:=]\s*['\"][^'\"]{10,}",
    r"(?i)password\s*[:=]\s*['\"][^'\"]+",
    r"(?i)token\s*[:=]\s*['\"][^'\"]{10,}",
    r"-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----",
    r"ghp_[A-Za-z0-9]{20,}",
    r"github_pat_[A-Za-z0-9_]{20,}",
    r"sk-[A-Za-z0-9]{20,}",
]

# Assigned PatientName / PatientID literals that are not synthetic markers.
PHI_VALUE_PATTERNS = [
    r'(?i)PatientName\s*=\s*["\'](?!SYNTHETIC|ANONYMOUS|TEST|DOE\^JOHN|UNKNOWN)[^"\']{2,}["\']',
    r'(?i)PatientID\s*=\s*["\'](?!SUB00|TEST|SYNTH|ANON|UNKNOWN)[^"\']{2,}["\']',
    r"(?i)\bmrn\s*[:=]\s*['\"][A-Za-z0-9-]{4,}['\"]",
    r"(?i)\bdate[_ -]?of[_ -]?birth\s*[:=]\s*['\"][^'\"]+['\"]",
]

BINARY_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".ico",
    ".pdf",
    ".exe",
    ".dll",
    ".pyd",
    ".whl",
    ".so",
    ".dylib",
}

AUDIT_SELF_NAMES = {
    "privacy_audit.py",
    "REPOSITORY_DATA_SAFETY.md",
    "PRIVACY_AUDIT_REPORT.txt",
    "SECONDARY_SECURITY_FINDINGS.txt",
    "prepare_publication_repo.ps1",
    "prepare_publication_repo.sh",
    ".gitignore",  # lists excluded study dir names such as mcgill/
}


def is_binary(path: Path) -> bool:
    return path.suffix.lower() in BINARY_EXTENSIONS


def should_skip(relative: Path) -> bool:
    rel = relative.as_posix()
    if any(rel == p or rel.startswith(p + "/") for p in SKIP_RELATIVE_PREFIXES):
        return True
    if relative.name in AUDIT_SELF_NAMES:
        return True
    return False


def scan_text(path: Path):
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return []

    findings = []
    for pattern in SENSITIVE_PATH_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            findings.append(("STUDY_PATH", pattern))
    for pattern in LOCAL_PATH_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            findings.append(("LOCAL_PATH", pattern))
    for pattern in SECRET_PATTERNS:
        if re.search(pattern, text):
            findings.append(("SECRET", pattern))
    for pattern in PHI_VALUE_PATTERNS:
        if re.search(pattern, text):
            findings.append(("PHI_VALUE", pattern))
    return findings


def main() -> int:
    findings: list[str] = []

    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(ROOT)
        if ".git" in relative.parts:
            continue
        if should_skip(relative):
            continue

        name_l = path.name.lower()
        suffix = path.suffix.lower()
        if suffix in FORBIDDEN_EXTENSIONS or name_l.endswith(FORBIDDEN_COMPOUND):
            findings.append(f"FORBIDDEN FILE TYPE: {relative}")
        if path.name in FORBIDDEN_NAMES:
            findings.append(f"FORBIDDEN FILE: {relative}")

        filename = str(relative)
        if re.search(r"(?i)(mrn|dob|medical[_-]?record|clinical[_-]?data)", filename):
            findings.append(f"SUSPICIOUS FILENAME: {relative}")
        if re.search(r"(?i)(mcgill|narval|computecanada)", filename):
            findings.append(f"STUDY/INFRASTRUCTURE PATH: {relative}")

        if not is_binary(path):
            for category, pattern in scan_text(path):
                findings.append(f"{category}: {relative} :: {pattern}")

    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        if ".git" in path.parts:
            continue
        size_mb = path.stat().st_size / (1024 * 1024)
        if size_mb > 50:
            findings.append(
                f"LARGE FILE (>50 MB): {path.relative_to(ROOT)} ({size_mb:.1f} MB)"
            )

    report = ROOT / "PRIVACY_AUDIT_REPORT.txt"
    if findings:
        report.write_text("\n".join(findings), encoding="utf-8")
        print("")
        print("=" * 70)
        print("PRIVACY AUDIT FAILED")
        print("=" * 70)
        print("")
        for item in findings:
            print(" -", item)
        print("")
        print(f"Full report: {report}")
        print("")
        print("DO NOT COMMIT OR PUBLISH THIS REPOSITORY.")
        print("")
        return 1

    report.write_text(
        "PASS\n"
        "No forbidden file types detected.\n"
        "No obvious McGill/research infrastructure paths detected.\n"
        "No obvious PHI *values* detected.\n"
        "No obvious secret patterns detected.\n"
        "No files larger than 50 MB detected.\n",
        encoding="utf-8",
    )
    print("")
    print("=" * 70)
    print("PRIVACY AUDIT PASSED")
    print("=" * 70)
    print("")
    print("No obvious sensitive material detected.")
    print(f"Report: {report}")
    print("")
    return 0


if __name__ == "__main__":
    sys.exit(main())
