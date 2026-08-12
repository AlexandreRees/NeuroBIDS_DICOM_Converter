# ============================================================
# DICOM_Converter_neuro-pipeline
# PUBLICATION-SAFE REPOSITORY PREPARATION
#
# PURPOSE:
#   Create a clean repository copy of the NeuroPipeline project,
#   exclude research data / PHI / local paths / credentials,
#   scan remaining files for sensitive information,
#   initialize Git ONLY if the audit passes.
#
# IMPORTANT:
#   This script does NOT publish anything to GitHub.
#   It only creates and audits the local repository.
#
# USAGE (from project root on Windows):
#   powershell -ExecutionPolicy Bypass -File .\scripts\prepare_publication_repo.ps1
# ============================================================

$ErrorActionPreference = "Stop"

# ------------------------------------------------------------
# 0. CONFIGURATION
# ------------------------------------------------------------

$Source = (Get-Location).Path
$ProjectName = "DICOM_Converter_neuro-pipeline"
$Parent = Split-Path $Source -Parent
$Destination = Join-Path $Parent $ProjectName

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host " DICOM Converter NeuroPipeline - Repository Preparation" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

Write-Host "SOURCE      : $Source"
Write-Host "DESTINATION : $Destination"
Write-Host ""

# ------------------------------------------------------------
# 1. SAFETY CHECK
# ------------------------------------------------------------

if ($Source -eq $Destination) {
    throw "Source and destination are identical. Aborting."
}

if (Test-Path $Destination) {
    Write-Host ""
    Write-Host "WARNING: Destination already exists:" -ForegroundColor Yellow
    Write-Host $Destination -ForegroundColor Yellow
    Write-Host ""

    $answer = Read-Host "Delete and recreate it? Type YES to continue"

    if ($answer -ne "YES") {
        Write-Host "Aborted." -ForegroundColor Red
        exit 1
    }

    Remove-Item $Destination -Recurse -Force
}

New-Item -ItemType Directory -Path $Destination | Out-Null

# ------------------------------------------------------------
# 2. FILES / DIRECTORIES THAT MUST NEVER ENTER THE REPO
# ------------------------------------------------------------

$ExcludedDirectories = @(
    ".git",
    ".venv",
    ".venv_win",
    ".gui_venv",
    "venv",
    "env",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "build",
    "dist",

    # Data (avoid excluding src package names like bids/metadata)
    "raw_dicom",
    "deid_dicom",
    "derivatives",
    "staging",
    "scratch",

    # Research-specific
    "mcgill",
    "McGill",
    "study",
    "study_data",
    "project_data",
    "private",
    "secrets",

    # Generated outputs
    "logs",
    "qc_reports",
    "audit_results"
)

$ExcludedFilePatterns = @(
    "*.dcm",
    "*.dicom",
    "*.nii",
    "*.nii.gz",
    "*.bvec",
    "*.bval",
    "*.fif",
    "*.edf",
    "*.mat",
    "*.puls",
    "*.resp",
    "*.ecg",

    "*.log",
    "*.tmp",
    "*.temp",
    "*.bak",

    ".env",
    ".env.*",

    "*.pem",
    "*.key",
    "credentials.json",
    "secrets.json",

    "*.sqlite",
    "*.db",

    "*.zip",
    "*.7z",
    "*.rar",

    "*.exe"
)

# ------------------------------------------------------------
# 3. COPY PROJECT WHILE EXCLUDING SENSITIVE MATERIAL
# ------------------------------------------------------------

Write-Host ""
Write-Host "[1/7] Copying project while excluding research/private data..." -ForegroundColor Cyan

$robocopyArgs = @(
    $Source
    $Destination
    "/E"
    "/R:1"
    "/W:1"
    "/NFL"
    "/NDL"
    "/NJH"
    "/NJS"
    "/NP"
)

foreach ($dir in $ExcludedDirectories) {
    $robocopyArgs += "/XD"
    $robocopyArgs += (Join-Path $Source $dir)
}

foreach ($pattern in $ExcludedFilePatterns) {
    $robocopyArgs += "/XF"
    $robocopyArgs += $pattern
}

robocopy @robocopyArgs | Out-Null

# Robocopy returns codes 0-7 for success/non-fatal differences.
if ($LASTEXITCODE -gt 7) {
    throw "Robocopy failed with exit code $LASTEXITCODE"
}

# ------------------------------------------------------------
# 4. CREATE STRONG .gitignore
# ------------------------------------------------------------

Write-Host "[2/7] Creating .gitignore..." -ForegroundColor Cyan

@"
# ============================================================
# Python
# ============================================================

__pycache__/
*.py[cod]
*.pyd

.pytest_cache/
.mypy_cache/
.ruff_cache/

*.egg-info/

# ============================================================
# Virtual environments
# ============================================================

.venv/
.venv_win/
.gui_venv/
venv/
env/

# ============================================================
# Build / packaging
# ============================================================

build/
dist/

# PyInstaller
*.toc
*.pyz
*.manifest
warn-*.txt

# ============================================================
# Logs / generated outputs
# ============================================================

*.log
logs/
qc_reports/
audit_results/

# ============================================================
# Research data (repo-root only — do NOT ignore src packages)
# ============================================================

/data/
/raw/
/raw_dicom/
/deid_dicom/
/derivatives/
/bids/
/staging/
/scratch/
/metadata/

*.dcm
*.dicom
*.nii
*.nii.gz
*.bvec
*.bval
*.fif
*.edf
*.mat
*.puls
*.resp
*.ecg

# ============================================================
# Study-specific material
# ============================================================

mcgill/
McGill/
study/
study_data/
project_data/
private/
secrets/

# ============================================================
# Local configuration
# ============================================================

.env
.env.*
*.local
*.local.*
config.local.*

# ============================================================
# Credentials
# ============================================================

credentials.json
secrets.json
*.pem
*.key
*.p12
*.pfx

# ============================================================
# Databases
# ============================================================

*.db
*.sqlite
*.sqlite3

# ============================================================
# Archives / binaries
# ============================================================

*.zip
*.7z
*.rar
*.exe

# ============================================================
# IDE
# ============================================================

.vscode/
.idea/

# ============================================================
# OS
# ============================================================

.DS_Store
Thumbs.db
desktop.ini
*.lnk

# ============================================================
# Temporary files
# ============================================================

*.tmp
*.temp
*.bak
*.swp

# ============================================================
# Local research metadata
# ============================================================

metadata/inventory.csv
metadata/inventory_summary.json
mapping*.csv
mapping*.tsv

# ============================================================
# Windows user-specific paths
# ============================================================

AppData/
"@ | Set-Content (Join-Path $Destination ".gitignore") -Encoding UTF8

# ------------------------------------------------------------
# 5. CREATE REPOSITORY SAFETY POLICY
# ------------------------------------------------------------

Write-Host "[3/7] Creating repository safety documentation..." -ForegroundColor Cyan

@"
# Repository Data Safety Policy

This repository contains software source code only.

Never commit:

- DICOM files
- NIfTI files
- participant identifiers
- patient names
- dates of birth
- medical record numbers
- research datasets
- clinical metadata
- study-specific mapping tables
- McGill internal paths
- Compute Canada / Narval paths
- SSH keys
- API tokens
- passwords
- credentials
- private configuration files
- generated logs containing local paths or identifiers

Research data must remain outside this repository.

Examples and tests must use synthetic or explicitly redistributable data.

Before any public release:

1. Run the repository audit.
2. Review ``git diff``.
3. Review ``git status``.
4. Review the complete Git history.
5. Verify that no study-specific data are included.
6. Verify that no credentials are included.
7. Verify that no local filesystem paths are included.
8. Verify that all example data are synthetic or redistributable.
"@ | Set-Content (Join-Path $Destination "REPOSITORY_DATA_SAFETY.md") -Encoding UTF8

# ------------------------------------------------------------
# 6. CREATE AUTOMATED SECURITY / PRIVACY AUDIT
# ------------------------------------------------------------

Write-Host "[4/7] Creating automated privacy audit..." -ForegroundColor Cyan

$AuditScript = @'
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]

# Files / dirs produced by this prep flow (self-references are expected)
SKIP_RELATIVE_PREFIXES = (
    "scripts/privacy_audit.py",
    "REPOSITORY_DATA_SAFETY.md",
    "PRIVACY_AUDIT_REPORT.txt",
    "SECONDARY_SECURITY_FINDINGS.txt",
)

# ------------------------------------------------------------
# Files that should never be present
# ------------------------------------------------------------

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

# .nii.gz ends with .gz; allow non-imaging .gz only if none expected
FORBIDDEN_COMPOUND = {
    ".nii.gz",
}

FORBIDDEN_NAMES = {
    ".env",
    "credentials.json",
    "secrets.json",
}

# ------------------------------------------------------------
# Sensitive path indicators (absolute / site-specific)
# ------------------------------------------------------------

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

# ------------------------------------------------------------
# Local filesystem indicators
# ------------------------------------------------------------

LOCAL_PATH_PATTERNS = [
    r"[A-Za-z]:\\Users\\",
    r"[A-Za-z]:\\Data\\",
    r"[A-Za-z]:\\DICOM\\",
    r"/home/[A-Za-z0-9_.-]+/",
    r"/Users/[A-Za-z0-9_.-]+/",
    r"/lustre\d*/",
    r"/scratch/[A-Za-z0-9_.-]+/",
]

# ------------------------------------------------------------
# Secret indicators (assigned values, not keyword docs)
# ------------------------------------------------------------

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

# ------------------------------------------------------------
# PHI-like indicators: real values, not DICOM keyword docs
# ------------------------------------------------------------

PHI_VALUE_PATTERNS = [
    # Assigned PatientName / PatientID string literals that are not synthetic markers
    r'(?i)PatientName\s*=\s*["\'](?!SYNTHETIC|ANONYMOUS|TEST|DOE\^JOHN|UNKNOWN)[^"\']{2,}["\']',
    r'(?i)PatientID\s*=\s*["\'](?!SUB00|TEST|SYNTH|ANON|UNKNOWN)[^"\']{2,}["\']',
    r"(?i)\bmrn\s*[:=]\s*['\"][A-Za-z0-9-]{4,}['\"]",
    r"(?i)\bdate[_ -]?of[_ -]?birth\s*[:=]\s*['\"][^'\"]+['\"]",
]

BINARY_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".ico",
    ".pdf", ".exe", ".dll", ".pyd",
    ".whl", ".so", ".dylib",
}

AUDIT_SELF_NAMES = {
    "privacy_audit.py",
    "REPOSITORY_DATA_SAFETY.md",
    "PRIVACY_AUDIT_REPORT.txt",
    "SECONDARY_SECURITY_FINDINGS.txt",
    "prepare_publication_repo.ps1",
    "prepare_publication_repo.sh",
    ".gitignore",
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


def main():
    findings = []

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

        if suffix in FORBIDDEN_EXTENSIONS or name_l.endswith(tuple(FORBIDDEN_COMPOUND)):
            findings.append(f"FORBIDDEN FILE TYPE: {relative}")

        if path.name in FORBIDDEN_NAMES:
            findings.append(f"FORBIDDEN FILE: {relative}")

        filename = str(relative)
        if re.search(
            r"(?i)(mrn|dob|medical[_-]?record|clinical[_-]?data)",
            filename,
        ):
            findings.append(f"SUSPICIOUS FILENAME: {relative}")

        if re.search(
            r"(?i)(mcgill|narval|computecanada)",
            filename,
        ):
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
'@

New-Item -ItemType Directory -Force `
    (Join-Path $Destination "scripts") | Out-Null

$AuditScript | Set-Content `
    (Join-Path $Destination "scripts\privacy_audit.py") `
    -Encoding UTF8

# ------------------------------------------------------------
# 7. RUN PRIVACY AUDIT
# ------------------------------------------------------------

Write-Host "[5/7] Running privacy audit..." -ForegroundColor Cyan

Push-Location $Destination

python ".\scripts\privacy_audit.py"

if ($LASTEXITCODE -ne 0) {

    Pop-Location

    Write-Host ""
    Write-Host "============================================================" -ForegroundColor Red
    Write-Host "REPOSITORY CREATION STOPPED" -ForegroundColor Red
    Write-Host "============================================================" -ForegroundColor Red
    Write-Host ""
    Write-Host "Sensitive material was detected." -ForegroundColor Red
    Write-Host "Review:" -ForegroundColor Yellow
    Write-Host "$Destination\PRIVACY_AUDIT_REPORT.txt" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "NO GIT REPOSITORY WAS INITIALIZED." -ForegroundColor Red

    exit 1
}

# ------------------------------------------------------------
# 8. SECONDARY MANUAL-STYLE SCAN
# ------------------------------------------------------------

Write-Host "[6/7] Running secondary path/content scan..." -ForegroundColor Cyan

# Match site-specific / credential indicators (not DICOM keyword documentation).
$Patterns = @(
    "McGill",
    "mcgill",
    "Narval",
    "narval",
    "ComputeCanada",
    "compute-canada",
    "C:\Users\",
    "/lustre",
    "/scratch/",
    "-----BEGIN",
    "ghp_",
    "github_pat_",
    "api_key=",
    "api_key =",
    "secret_key=",
    "secret_key =",
    "password=",
    "password =",
    "access_token=",
    "access_token ="
)

$SecondaryFindings = @()

Get-ChildItem $Destination -Recurse -File -Force |
    Where-Object {
        $_.FullName -notmatch "\\\.git\\" -and
        $_.Name -notin @(
            "privacy_audit.py",
            "REPOSITORY_DATA_SAFETY.md",
            "PRIVACY_AUDIT_REPORT.txt",
            "SECONDARY_SECURITY_FINDINGS.txt",
            "prepare_publication_repo.ps1",
            "prepare_publication_repo.sh",
            ".gitignore"
        ) -and
        $_.Extension -notmatch "\.(png|jpg|jpeg|gif|ico|pdf|exe|dll|pyd|whl|so|dylib)$"
    } |
    ForEach-Object {

        try {

            $content = Get-Content $_.FullName `
                -Raw `
                -ErrorAction Stop

            foreach ($pattern in $Patterns) {

                if ($content -match [regex]::Escape($pattern)) {

                    $SecondaryFindings += `
                        "$($_.FullName) -> $pattern"
                }
            }

        }
        catch {
            # Ignore files that cannot be decoded as text.
        }
    }

if ($SecondaryFindings.Count -gt 0) {

    $SecondaryFindings |
        Set-Content `
        (Join-Path $Destination "SECONDARY_SECURITY_FINDINGS.txt")

    Pop-Location

    Write-Host ""
    Write-Host "============================================================" -ForegroundColor Red
    Write-Host "SECONDARY SECURITY SCAN FAILED" -ForegroundColor Red
    Write-Host "============================================================" -ForegroundColor Red
    Write-Host ""
    Write-Host "Potential sensitive information detected." -ForegroundColor Red
    Write-Host ""
    Write-Host "Review:" -ForegroundColor Yellow
    Write-Host "$Destination\SECONDARY_SECURITY_FINDINGS.txt" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "NO GIT REPOSITORY WAS INITIALIZED." -ForegroundColor Red

    exit 1
}

# ------------------------------------------------------------
# 9. INITIALIZE GIT ONLY AFTER AUDIT PASSES
# ------------------------------------------------------------

Write-Host "[7/7] Initializing Git repository..." -ForegroundColor Cyan

git init
git branch -M main

git add .

git status --short

Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host "REPOSITORY CREATED AND AUDITED" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host ""
Write-Host "Location:"
Write-Host $Destination
Write-Host ""
Write-Host "IMPORTANT:"
Write-Host "The repository has NOT been pushed to GitHub."
Write-Host ""
Write-Host "Before the first commit, manually inspect:"
Write-Host ""
Write-Host "  PRIVACY_AUDIT_REPORT.txt"
Write-Host "  REPOSITORY_DATA_SAFETY.md"
Write-Host "  git status"
Write-Host ""
Write-Host "Recommended next command:"
Write-Host ""
Write-Host "  git diff --cached --stat"
Write-Host ""
Write-Host "Then review the complete staged file list."
Write-Host ""
Write-Host "DO NOT PUSH TO GITHUB YET."
Write-Host ""

Pop-Location
