#!/usr/bin/env bash
# =============================================================================
# finalize_private_github.sh
#
# FAIL-CLOSED final privacy/security audit, then (only if all checks pass):
#   commit staged files -> create PRIVATE GitHub repo -> push -> verify.
#
# Does NOT:
#   - git add (never stages new files)
#   - modify or delete project files to pass audits
#   - create a public repository
#   - push if any audit fails
#
# Target:
#   Owner:      AlexandreRees
#   Repository: DICOM_Converter_neuro-pipeline
#   Visibility: PRIVATE
#
# Usage (from repository root):
#   bash scripts/finalize_private_github.sh
# =============================================================================

set -euo pipefail

OWNER="AlexandreRees"
REPO_NAME="DICOM_Converter_neuro-pipeline"
FULL_REPO="${OWNER}/${REPO_NAME}"
COMMIT_MSG="Initial private release of DICOM Converter NeuroPipeline"

# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------

fail() {
  echo "" >&2
  echo "AUDIT FAILED — NO COMMIT OR PUSH PERFORMED" >&2
  echo "$*" >&2
  echo "" >&2
  exit 1
}

info() {
  echo "$*"
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || fail "Required command not found: $1"
}

# -----------------------------------------------------------------------------
# 1. Git verifications
# -----------------------------------------------------------------------------

info "========================================"
info "FINALIZE PRIVATE GITHUB — AUDIT START"
info "========================================"
info ""

ROOT="$(pwd)"
BASE="$(basename "$ROOT")"
if [[ "$BASE" != "$REPO_NAME" ]]; then
  fail "Must run from repository root named '${REPO_NAME}'. Current directory basename: '${BASE}'"
fi

require_cmd git
require_cmd python3

git rev-parse --is-inside-work-tree >/dev/null 2>&1 \
  || fail "Not inside a Git work tree."

INSIDE="$(git rev-parse --is-inside-work-tree 2>/dev/null || true)"
if [[ "$INSIDE" != "true" ]]; then
  fail "git rev-parse --is-inside-work-tree did not return true."
fi

CURRENT_BRANCH="$(git branch --show-current 2>/dev/null || true)"
if [[ -z "$CURRENT_BRANCH" ]]; then
  if git show-ref --verify --quiet refs/heads/main 2>/dev/null; then
    git checkout main >/dev/null 2>&1 || fail "Could not checkout existing branch main."
  elif git show-ref --verify --quiet refs/heads/master 2>/dev/null; then
    git branch -M main
  else
    git branch -M main 2>/dev/null || true
  fi
  CURRENT_BRANCH="$(git branch --show-current 2>/dev/null || true)"
fi

if [[ -n "$CURRENT_BRANCH" && "$CURRENT_BRANCH" != "main" ]]; then
  info "Current branch is '${CURRENT_BRANCH}' — renaming to main."
  git branch -M main
  CURRENT_BRANCH="$(git branch --show-current 2>/dev/null || true)"
fi

if [[ -z "$CURRENT_BRANCH" ]]; then
  git branch -M main 2>/dev/null || true
  CURRENT_BRANCH="$(git branch --show-current 2>/dev/null || echo main)"
fi

if [[ "$CURRENT_BRANCH" != "main" ]]; then
  fail "Branch must be 'main' (got: '${CURRENT_BRANCH:-<empty>}')."
fi

STAGED_COUNT="$(git diff --cached --name-only | wc -l | tr -d ' ')"
if [[ "$STAGED_COUNT" -eq 0 ]]; then
  fail "No staged files. Stage the intended release set manually, then re-run. (This script never runs git add.)"
fi

info "--- git status --short ---"
git status --short
info ""
info "--- git diff --cached --stat ---"
git diff --cached --stat
info ""
info "--- git diff --cached --name-status ---"
git diff --cached --name-status
info ""

info "Staged file count: ${STAGED_COUNT}"
info ""

# -----------------------------------------------------------------------------
# 2-7. Staged-file audits (embedded Python; values redacted; fail-closed)
# -----------------------------------------------------------------------------

info "[Audit] Scanning staged files (types, size, study paths, PHI values, secrets)..."

AUDIT_OUT="$(mktemp)"
AUDIT_PY="$(mktemp)"
trap 'rm -f "$AUDIT_OUT" "$AUDIT_PY"' EXIT

cat > "$AUDIT_PY" <<'PY'
import re
import subprocess
import sys
from pathlib import Path

report_path = Path(sys.argv[1])
root = Path(".").resolve()
max_bytes = 50 * 1024 * 1024

staged = subprocess.check_output(
    ["git", "diff", "--cached", "--name-only", "-z"],
    text=True,
).split("\0")
staged = [s for s in staged if s]

FORBIDDEN_SUFFIXES = (
    ".dcm", ".dicom", ".nii", ".nii.gz", ".bval", ".bvec",
    ".puls", ".resp", ".ecg", ".mat",
    ".mp4", ".mov", ".avi",
    ".zip", ".7z", ".rar",
)

FORBIDDEN_EXACT_NAMES = {
    ".env",
    "id_rsa",
    "id_rsa.pub",
    "credentials.json",
    "secrets.json",
}
FORBIDDEN_NAME_PREFIXES = ("credentials", "secrets")
FORBIDDEN_NAME_SUFFIXES = (".pem", ".key", ".sqlite", ".db", ".sqlite3")

# Policy / audit tooling may list forbidden terms; skip study-keyword hits only.
POLICY_SKIP_KEYWORDS = {
    "REPOSITORY_DATA_SAFETY.md",
    "scripts/privacy_audit.py",
    "scripts/finalize_private_github.sh",
    "scripts/prepare_publication_repo.ps1",
    "scripts/prepare_publication_repo.sh",
    ".gitignore",
    "PRIVACY_AUDIT_REPORT.txt",
}

BINARY_EXT = {
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf",
    ".exe", ".dll", ".pyd", ".whl", ".so", ".dylib",
    ".pptx", ".xlsx", ".xls",
}

STUDY_LITERALS = [
    "Data_TON",
    "Data_ON",
    "Glaucoma",
    "SUBT01",
    "SUBT02",
    "Amir",
    "Shmuel",
]

PATH_PATTERNS = [
    (r"/lustre\d*/", "HPC_PATH"),
    (r"/scratch/[A-Za-z0-9_.-]+/", "HPC_PATH"),
    (r"/home/[A-Za-z0-9_.-]+/", "HOME_PATH"),
    (r"/Users/[A-Za-z0-9_.-]+/", "HOME_PATH"),
    (r"(?i)C:\\Users\\", "WIN_USER_PATH"),
    (r"(?i)[DE]:\\", "WIN_DRIVE_PATH"),
    (r"(?i)\bmcgill\b", "STUDY_SITE"),
    (r"(?i)\bnarval\b", "STUDY_SITE"),
    (r"(?i)compute[ -]?canada", "STUDY_SITE"),
]

SECRET_PATTERNS = [
    (r"ghp_[A-Za-z0-9]{20,}", "GITHUB_TOKEN"),
    (r"github_pat_[A-Za-z0-9_]{20,}", "GITHUB_TOKEN"),
    (r"sk-[A-Za-z0-9]{20,}", "OPENAI_STYLE_KEY"),
    (r"AKIA[0-9A-Z]{16}", "AWS_KEY"),
    (r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----", "PRIVATE_KEY"),
    (r"(?i)api[_-]?key\s*[:=]\s*['\"][^'\"]{8,}", "API_KEY_ASSIGN"),
    (r"(?i)secret[_-]?key\s*[:=]\s*['\"][^'\"]{8,}", "SECRET_ASSIGN"),
    (r"(?i)password\s*[:=]\s*['\"][^'\"]+", "PASSWORD_ASSIGN"),
    (r"(?i)access[_-]?token\s*[:=]\s*['\"][^'\"]{8,}", "TOKEN_ASSIGN"),
]

PHI_VALUE_PATTERNS = [
    (
        r'(?i)PatientName\s*=\s*["\'](?!SYNTHETIC|ANONYMOUS|TEST|DOE\^JOHN|UNKNOWN|Anonymous)[^"\']{2,}["\']',
        "PATIENT_NAME_VALUE",
    ),
    (
        r'(?i)PatientID\s*=\s*["\'](?!SUB00|TEST|SYNTH|ANON|UNKNOWN)[^"\']{2,}["\']',
        "PATIENT_ID_VALUE",
    ),
    (
        r'(?i)\b(?:mrn|medical[_ -]?record(?:_number)?)\s*[:=]\s*["\'][A-Za-z0-9-]{3,}["\']',
        "MRN_VALUE",
    ),
    (
        r'(?i)\b(?:date[_ -]?of[_ -]?birth|dob)\s*[:=]\s*["\'][^"\']+["\']',
        "DOB_VALUE",
    ),
    (
        r"(?i)\b[A-Z0-9._%+-]+@(?!example\.com|test\.local)[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
        "EMAIL",
    ),
    (
        r"(?<!\d)(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}(?!\d)",
        "PHONE",
    ),
]

SYNTHETIC_MARKERS = re.compile(
    r"(?i)(DOE\^JOHN|SUB00\d*|SYNTHETIC|ANONYMOUS|Anonymous|TEST_SUBJECT|fixture)"
)


def redact(s: str) -> str:
    s = s.strip().replace("\n", " ")
    if len(s) <= 8:
        return "****"
    return f"{s[:3]}…{s[-2:]} (len={len(s)})"


def ends_with_forbidden_data_ext(rel: str) -> bool:
    low = rel.lower()
    return any(low.endswith(suf) for suf in FORBIDDEN_SUFFIXES)


def is_forbidden_credential_name(rel: str) -> bool:
    name = Path(rel).name
    low = name.lower()
    if name in FORBIDDEN_EXACT_NAMES or low in FORBIDDEN_EXACT_NAMES:
        return True
    if low.startswith(FORBIDDEN_NAME_PREFIXES):
        return True
    if low.endswith(FORBIDDEN_NAME_SUFFIXES):
        return True
    return False


findings: list[str] = []
counters = {
    "data": 0,
    "large": 0,
    "phi": 0,
    "study": 0,
    "hpc": 0,
    "secret": 0,
}


def add(kind: str, rel: str, detail: str) -> None:
    findings.append(f"{kind}: {rel} :: {detail}")
    if kind in {"DATA_FILE", "CREDENTIAL_FILE"}:
        counters["data"] += 1
    elif kind == "LARGE_FILE":
        counters["large"] += 1
    elif kind.startswith("PHI"):
        counters["phi"] += 1
    elif kind in {"STUDY_SITE", "STUDY_LITERAL"}:
        counters["study"] += 1
    elif kind in {"HPC_PATH", "HOME_PATH", "WIN_USER_PATH", "WIN_DRIVE_PATH"}:
        counters["hpc"] += 1
    else:
        counters["secret"] += 1


for rel in staged:
    path = root / rel
    norm = rel.replace("\\", "/")

    if ends_with_forbidden_data_ext(rel):
        add("DATA_FILE", rel, "forbidden research/media/archive extension")
    elif is_forbidden_credential_name(rel):
        add("CREDENTIAL_FILE", rel, "forbidden credential/secret filename")

    if not path.is_file():
        continue

    try:
        size = path.stat().st_size
    except OSError:
        size = 0
    if size > max_bytes:
        add("LARGE_FILE", rel, f"{size / (1024 * 1024):.1f} MB")

    if path.suffix.lower() in BINARY_EXT:
        continue
    try:
        raw = path.read_bytes()
    except OSError:
        continue
    if b"\x00" in raw[:8192]:
        continue
    text = raw.decode("utf-8", errors="ignore")

    skip_keywords = norm in POLICY_SKIP_KEYWORDS

    if not skip_keywords:
        for lit in STUDY_LITERALS:
            if lit in text:
                add("STUDY_LITERAL", rel, f"literal={lit}")

        for pat, kind in PATH_PATTERNS:
            if re.search(pat, text):
                add(kind, rel, f"pattern={pat}")

        for pat, kind in PHI_VALUE_PATTERNS:
            for m in re.finditer(pat, text):
                snippet = m.group(0)
                if kind in {"PATIENT_NAME_VALUE", "PATIENT_ID_VALUE"} and SYNTHETIC_MARKERS.search(
                    snippet
                ):
                    continue
                add(f"PHI_{kind}", rel, f"match={redact(snippet)}")

    for pat, kind in SECRET_PATTERNS:
        m = re.search(pat, text)
        if m:
            add(kind, rel, f"match={redact(m.group(0))}")

lines = []
if findings:
    lines.append("STATUS=FAIL")
    for f in findings:
        lines.append(f"FINDING={f}")
else:
    lines.append("STATUS=PASS")
lines.append(f"STAGED={len(staged)}")
lines.append(f"DATA_HITS={counters['data']}")
lines.append(f"LARGE_HITS={counters['large']}")
lines.append(f"PHI_HITS={counters['phi']}")
lines.append(f"STUDY_HITS={counters['study']}")
lines.append(f"HPC_HITS={counters['hpc']}")
lines.append(f"SECRET_HITS={counters['secret']}")
report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
sys.exit(1 if findings else 0)
PY

AUDIT_RC=0
python3 "$AUDIT_PY" "$AUDIT_OUT" || AUDIT_RC=$?

if [[ "$AUDIT_RC" -ne 0 ]]; then
  echo "" >&2
  echo "Staged-content audit findings (values redacted):" >&2
  grep '^FINDING=' "$AUDIT_OUT" 2>/dev/null | sed 's/^FINDING=/ - /' >&2 || true
  fail "Staged file audit failed."
fi

STAGED_N="$(grep '^STAGED=' "$AUDIT_OUT" | cut -d= -f2)"
DATA_HITS="$(grep '^DATA_HITS=' "$AUDIT_OUT" | cut -d= -f2)"
LARGE_HITS="$(grep '^LARGE_HITS=' "$AUDIT_OUT" | cut -d= -f2)"
PHI_HITS="$(grep '^PHI_HITS=' "$AUDIT_OUT" | cut -d= -f2)"
STUDY_HITS="$(grep '^STUDY_HITS=' "$AUDIT_OUT" | cut -d= -f2)"
HPC_HITS="$(grep '^HPC_HITS=' "$AUDIT_OUT" | cut -d= -f2)"
SECRET_HITS="$(grep '^SECRET_HITS=' "$AUDIT_OUT" | cut -d= -f2)"

# -----------------------------------------------------------------------------
# 8. Existing PRIVACY_AUDIT_REPORT.txt
# -----------------------------------------------------------------------------

info "[Audit] Checking PRIVACY_AUDIT_REPORT.txt..."

REPORT="PRIVACY_AUDIT_REPORT.txt"
if [[ ! -f "$REPORT" ]]; then
  fail "Missing ${REPORT}"
fi

if ! grep -q 'PASS' "$REPORT"; then
  fail "${REPORT} does not contain PASS"
fi

if grep -Eiq '/lustre[0-9]*/|/scratch/[A-Za-z0-9_.-]+/|/home/[A-Za-z0-9_.-]+/|C:\\Users\\|ghp_|github_pat_|sk-[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY|Data_TON|Data_ON|SUBT01|SUBT02|Glaucoma' "$REPORT"; then
  fail "${REPORT} appears to contain sensitive path/PHI/secret indicators (not a clean PASS report)."
fi

if grep -Eq '^(FORBIDDEN|LOCAL_PATH|SECRET|PHI|STUDY_PATH|SUSPICIOUS)' "$REPORT"; then
  fail "${REPORT} contains finding-style lines; refusing to proceed."
fi

# -----------------------------------------------------------------------------
# 9. GitHub CLI + auth + repo must not already exist
# -----------------------------------------------------------------------------

info "[Audit] Checking GitHub CLI authentication and target repo absence..."

require_cmd gh

if ! gh auth status >/dev/null 2>&1; then
  fail "GitHub CLI is not authenticated. Run: gh auth login"
fi

gh auth status || fail "gh auth status failed."

if gh repo view "$FULL_REPO" >/dev/null 2>&1; then
  fail "GitHub repository ${FULL_REPO} already exists. Refusing to overwrite, delete, or modify it."
fi

info "Confirmed: ${FULL_REPO} does not exist yet."
info ""

# -----------------------------------------------------------------------------
# 10. Summary (all audits passed)
# -----------------------------------------------------------------------------

info "========================================"
info "FINAL PRIVACY AUDIT PASSED"
info "========================================"
info ""
info "Repository:"
info "${REPO_NAME}"
info ""
info "Owner:"
info "${OWNER}"
info ""
info "Visibility:"
info "PRIVATE"
info ""
info "Staged files:"
info "${STAGED_N}"
info ""
info "DICOM files:"
info "NONE"
info ""
info "PHI:"
info "NOT DETECTED"
info ""
info "Study-specific data:"
info "NOT DETECTED"
info ""
info "HPC/local paths:"
info "NOT DETECTED"
info ""
info "Secrets:"
info "NOT DETECTED"
info ""
info "Large files > 50 MB:"
info "NONE"
info ""
info "========================================"
info ""
info "Creating private GitHub repository..."
info ""

if [[ "${DATA_HITS}" != "0" || "${LARGE_HITS}" != "0" || "${PHI_HITS}" != "0" || "${STUDY_HITS}" != "0" || "${HPC_HITS}" != "0" || "${SECRET_HITS}" != "0" ]]; then
  fail "Internal counter mismatch after PASS (fail-closed)."
fi

# -----------------------------------------------------------------------------
# 11. Commit (staged only — never git add)
# -----------------------------------------------------------------------------

info "[Git] Creating commit from already-staged files only..."

git commit -m "${COMMIT_MSG}" || fail "git commit failed."

# -----------------------------------------------------------------------------
# 12. Create PRIVATE GitHub repo and push
# -----------------------------------------------------------------------------

info "[GitHub] Creating PRIVATE repository ${FULL_REPO} and pushing..."

# Explicitly private — never --public.
gh repo create "$FULL_REPO" \
  --private \
  --source=. \
  --remote=origin \
  --push \
  || fail "gh repo create / push failed. Local commit may exist; remote was not confirmed."

# -----------------------------------------------------------------------------
# 13. Post-push verification
# -----------------------------------------------------------------------------

info "[Verify] Remotes and branch..."
git remote -v
BRANCH_NOW="$(git branch --show-current)"
info "Current branch: ${BRANCH_NOW}"
if [[ "$BRANCH_NOW" != "main" ]]; then
  fail "CRITICAL: current branch is '${BRANCH_NOW}', expected 'main'."
fi

info "[Verify] gh repo view ${FULL_REPO}..."
VIEW_JSON="$(gh repo view "$FULL_REPO" --json nameWithOwner,visibility,url,isPrivate)"
info "$VIEW_JSON"

VISIBILITY="$(printf '%s' "$VIEW_JSON" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("visibility",""))')"
IS_PRIVATE="$(printf '%s' "$VIEW_JSON" | python3 -c 'import json,sys; v=json.load(sys.stdin).get("isPrivate", False); print("true" if v else "false")')"
REPO_URL="$(printf '%s' "$VIEW_JSON" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("url", ""))')"

if [[ "$IS_PRIVATE" != "true" ]]; then
  echo "" >&2
  echo "CRITICAL ERROR: Repository is NOT private (visibility=${VISIBILITY}, isPrivate=${IS_PRIVATE})." >&2
  echo "Stop and inspect GitHub settings immediately." >&2
  exit 2
fi

case "${VISIBILITY}" in
  PRIVATE|private|Private) ;;
  *)
    echo "CRITICAL ERROR: GitHub visibility is '${VISIBILITY}' (expected PRIVATE)." >&2
    exit 2
    ;;
esac

# -----------------------------------------------------------------------------
# 14. Success
# -----------------------------------------------------------------------------

info ""
info "========================================"
info "SUCCESS"
info "========================================"
info ""
info "Private GitHub repository created successfully."
info ""
info "Repository:"
info "${FULL_REPO}"
info ""
info "Visibility:"
info "PRIVATE"
info ""
info "Branch:"
info "main"
info ""
info "Remote:"
info "origin"
info ""
info "URL:"
info "${REPO_URL}"
info ""
info "Commit:"
info "${COMMIT_MSG}"
info ""
info "========================================"
info ""
info "--- git status ---"
git status
info ""
