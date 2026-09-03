#!/usr/bin/env bash
# Build NeuroBIDS.app with PyInstaller (macOS only).
# Does not bundle Ollama or LLM models. Copilot remains optional.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "==> NeuroBIDS macOS build"
echo "Root: $ROOT"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "ERROR: macOS builds must run on macOS. This host is $(uname -s)." >&2
  echo "Copy this repo to a Mac and re-run:" >&2
  echo "  bash scripts/build_macos.sh" >&2
  exit 2
fi

echo "==> 1/6 Clean"
rm -rf build dist
mkdir -p release logs
# Keep release notes; remove prior app bundles / archives only.
find release -maxdepth 1 \( -name '*.app' -o -name '*.dmg' -o -name '*.zip' \) -exec rm -rf {} + 2>/dev/null || true

echo "==> 2/6 Dependencies"
python3 -m pip install --upgrade pip
python3 -m pip install -r requirements.txt
python3 -m pip install -e ".[dev]"
python3 -m pip install pyinstaller

echo "==> 3/6 Tests"
export PYTHONPATH="$ROOT/src"
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests/ -q
PYTHONPATH="$ROOT/src" python3 -m neuro_pipeline.neurobids.copilot.benchmark --no-level3

echo "==> 4/6 PyInstaller"
if [[ ! -f tools/dcm2niix && ! -f dcm2niix ]]; then
  echo "WARNING: dcm2niix not found under tools/ or repo root — package may miss the converter binary." >&2
fi
python3 -m PyInstaller --noconfirm --clean build_macos.spec

echo "==> 5/6 Stage release/"
mkdir -p release
if [[ -d dist/NeuroBIDS.app ]]; then
  ditto dist/NeuroBIDS.app "release/NeuroBIDS.app"
  echo "Staged: release/NeuroBIDS.app"
elif [[ -d dist/NeuroPipeline.app ]]; then
  ditto dist/NeuroPipeline.app "release/NeuroPipeline.app"
  echo "Staged: release/NeuroPipeline.app"
else
  echo "ERROR: expected dist/NeuroBIDS.app was not produced." >&2
  ls -la dist || true
  exit 1
fi

echo "==> 6/6 Packaging verification"
PYTHONPATH="$ROOT/src" python3 "$ROOT/scripts/verify_packaging.py"

echo ""
echo "macOS application ready."
echo "Build command: bash scripts/build_macos.sh"
echo "Artifact:      release/NeuroBIDS.app"
echo "Notarization / Gatekeeper signing is intentionally not automated."
echo "Note: Ollama / LLM models are not bundled. Copilot stays optional."
