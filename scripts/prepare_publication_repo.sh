#!/usr/bin/env bash
# ============================================================
# DICOM_Converter_neuro-pipeline
# PUBLICATION-SAFE REPOSITORY PREPARATION (Linux / HPC)
#
# Creates a clean sibling copy, audits it, initializes Git
# ONLY if audits pass. Does NOT push to GitHub.
#
# USAGE (from project root):
#   bash scripts/prepare_publication_repo.sh
#   bash scripts/prepare_publication_repo.sh --force   # recreate destination
# ============================================================

set -euo pipefail

SOURCE="$(pwd)"
PROJECT_NAME="DICOM_Converter_neuro-pipeline"
PARENT="$(dirname "$SOURCE")"
DESTINATION="$PARENT/$PROJECT_NAME"
FORCE=0

if [[ "${1:-}" == "--force" ]]; then
  FORCE=1
fi

echo ""
echo "============================================================"
echo " DICOM Converter NeuroPipeline - Repository Preparation"
echo "============================================================"
echo ""
echo "SOURCE      : $SOURCE"
echo "DESTINATION : $DESTINATION"
echo ""

if [[ "$SOURCE" == "$DESTINATION" ]]; then
  echo "Source and destination are identical. Aborting." >&2
  exit 1
fi

if [[ -e "$DESTINATION" ]]; then
  if [[ "$FORCE" -ne 1 ]]; then
    echo "WARNING: Destination already exists:"
    echo "  $DESTINATION"
    echo "Re-run with --force to delete and recreate."
    exit 1
  fi
  rm -rf "$DESTINATION"
fi

mkdir -p "$DESTINATION"

echo "[1/7] Copying project while excluding research/private data..."

# Directory basenames excluded anywhere in the tree (never source package names)
EXCLUDED_DIR_NAMES=(
  .git .venv .venv_win .gui_venv venv env
  __pycache__ .pytest_cache .mypy_cache .ruff_cache
  build dist
  raw_dicom deid_dicom derivatives staging scratch
  mcgill McGill study study_data project_data private secrets
  logs qc_reports audit_results
)

RSYNC_EXCLUDES=()
for d in "${EXCLUDED_DIR_NAMES[@]}"; do
  RSYNC_EXCLUDES+=(--exclude="$d/")
done

# Top-level research data dirs only (must not exclude src/neuro_pipeline/bids|metadata)
RSYNC_EXCLUDES+=(
  --exclude='/data/'
  --exclude='/raw/'
  --exclude='/bids/'
  --exclude='/metadata/'
)
RSYNC_EXCLUDES+=(
  --exclude='*.dcm' --exclude='*.dicom'
  --exclude='*.nii' --exclude='*.nii.gz'
  --exclude='*.bvec' --exclude='*.bval'
  --exclude='*.fif' --exclude='*.edf' --exclude='*.mat'
  --exclude='*.puls' --exclude='*.resp' --exclude='*.ecg'
  --exclude='*.log' --exclude='*.tmp' --exclude='*.temp' --exclude='*.bak'
  --exclude='.env' --exclude='.env.*'
  --exclude='*.pem' --exclude='*.key'
  --exclude='credentials.json' --exclude='secrets.json'
  --exclude='*.sqlite' --exclude='*.db'
  --exclude='*.zip' --exclude='*.7z' --exclude='*.rar'
  --exclude='*.exe'
)

rsync -a "${RSYNC_EXCLUDES[@]}" "$SOURCE"/ "$DESTINATION"/

echo "[2/7] Creating .gitignore..."
cat > "$DESTINATION/.gitignore" <<'EOF'
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
EOF

echo "[3/7] Creating repository safety documentation..."
cat > "$DESTINATION/REPOSITORY_DATA_SAFETY.md" <<'EOF'
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
2. Review `git diff`.
3. Review `git status`.
4. Review the complete Git history.
5. Verify that no study-specific data are included.
6. Verify that no credentials are included.
7. Verify that no local filesystem paths are included.
8. Verify that all example data are synthetic or redistributable.
EOF

echo "[4/7] Installing privacy audit script..."
mkdir -p "$DESTINATION/scripts"
# Prefer the maintained copy from the source tree if present.
if [[ -f "$SOURCE/scripts/privacy_audit.py" ]]; then
  cp "$SOURCE/scripts/privacy_audit.py" "$DESTINATION/scripts/privacy_audit.py"
else
  echo "Missing scripts/privacy_audit.py in source." >&2
  exit 1
fi

# Scrub known local absolute path if still present in the copy.
PRES_SCRIPT="$DESTINATION/docs/assets/presentation/generate_presentation_assets.py"
if [[ -f "$PRES_SCRIPT" ]]; then
  python3 - <<'PY'
from pathlib import Path
p = Path("docs/assets/presentation/generate_presentation_assets.py")
# run relative to destination via chdir below
PY
fi

echo "[5/7] Scrubbing local absolute paths in the copy (if any)..."
cd "$DESTINATION"
python3 - <<'PY'
from pathlib import Path
import re

root = Path(".").resolve()
replacements = [
    (
        Path("docs/assets/presentation/generate_presentation_assets.py"),
        r'ROOT = Path\("/lustre[^"]+"\)',
        'ROOT = Path(__file__).resolve().parents[3]',
    ),
]
for path, pattern, repl in replacements:
    if not path.is_file():
        continue
    text = path.read_text(encoding="utf-8")
    new = re.sub(pattern, repl, text)
    if new != text:
        path.write_text(new, encoding="utf-8")
        print(f"  scrubbed: {path}")
PY

echo "[6/7] Running privacy audit..."
python3 ./scripts/privacy_audit.py
AUDIT_RC=$?
if [[ "$AUDIT_RC" -ne 0 ]]; then
  echo ""
  echo "============================================================"
  echo "REPOSITORY CREATION STOPPED"
  echo "============================================================"
  echo "Sensitive material was detected."
  echo "Review: $DESTINATION/PRIVACY_AUDIT_REPORT.txt"
  echo "NO GIT REPOSITORY WAS INITIALIZED."
  exit 1
fi

echo "[7/7] Running secondary path/content scan..."
python3 - <<'PY'
from pathlib import Path
import sys

root = Path(".").resolve()
patterns = [
    "McGill", "mcgill", "Narval", "narval",
    "ComputeCanada", "compute-canada",
    r"C:\Users\\",
    "/lustre", "/scratch/",
    "-----BEGIN", "ghp_", "github_pat_",
    "api_key=", "api_key =",
    "secret_key=", "secret_key =",
    "password=", "password =",
    "access_token=", "access_token =",
]
skip_names = {
    "privacy_audit.py",
    "REPOSITORY_DATA_SAFETY.md",
    "PRIVACY_AUDIT_REPORT.txt",
    "SECONDARY_SECURITY_FINDINGS.txt",
    "prepare_publication_repo.ps1",
    "prepare_publication_repo.sh",
    ".gitignore",
}
binary_ext = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf",
              ".exe", ".dll", ".pyd", ".whl", ".so", ".dylib"}
findings = []
for path in root.rglob("*"):
    if not path.is_file():
        continue
    if ".git" in path.parts:
        continue
    if path.name in skip_names:
        continue
    if path.suffix.lower() in binary_ext:
        continue
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        continue
    for pattern in patterns:
        if pattern in text:
            findings.append(f"{path.relative_to(root)} -> {pattern}")

out = root / "SECONDARY_SECURITY_FINDINGS.txt"
if findings:
    out.write_text("\n".join(findings) + "\n", encoding="utf-8")
    print("")
    print("=" * 70)
    print("SECONDARY SECURITY SCAN FAILED")
    print("=" * 70)
    for item in findings:
        print(" -", item)
    print(f"Review: {out}")
    print("NO GIT REPOSITORY WAS INITIALIZED.")
    sys.exit(1)
print("Secondary scan: PASS")
sys.exit(0)
PY

echo "[8/8] Initializing Git repository..."
git init
git branch -M main
git add .
git status --short | head -80 || true

echo ""
echo "============================================================"
echo "REPOSITORY CREATED AND AUDITED"
echo "============================================================"
echo ""
echo "Location:"
echo "  $DESTINATION"
echo ""
echo "IMPORTANT:"
echo "  The repository has NOT been pushed to GitHub."
echo "  DO NOT PUSH TO GITHUB YET."
echo ""
echo "Before the first commit, manually inspect:"
echo "  PRIVACY_AUDIT_REPORT.txt"
echo "  REPOSITORY_DATA_SAFETY.md"
echo "  git status"
echo "  git diff --cached --stat"
echo ""
