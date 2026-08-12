#!/usr/bin/env bash
# Install NeuroPipeline in a local virtualenv (generic Linux).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

PYTHON="${PYTHON:-python3}"
VENV_DIR="${VENV_DIR:-$ROOT/.venv}"

echo "== NeuroPipeline Linux install =="
echo "Root: $ROOT"

if ! command -v "$PYTHON" >/dev/null 2>&1; then
  echo "ERROR: $PYTHON not found" >&2
  exit 1
fi

"$PYTHON" -m venv "$VENV_DIR"
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"
python -m pip install -U pip
pip install -e ".[dev]"

if ! command -v dcm2niix >/dev/null 2>&1; then
  echo "WARNING: dcm2niix not found on PATH."
  echo "Install it system-wide or set configs/default.yaml dcm2niix_path."
else
  dcm2niix -v || true
fi

echo "Install complete."
echo "Activate with: source \"$VENV_DIR/bin/activate\""
echo "Run GUI with:   ./deployment/linux/run_neuropipeline.sh"
