#!/usr/bin/env bash
# Build NeuroPipeline / NeuroBIDS macOS app bundle with PyInstaller.
# Run on macOS only. Does not change application behavior.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "==> NeuroPipeline macOS build"
echo "Root: $ROOT"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "ERROR: macOS builds must run on macOS. This host is $(uname -s)." >&2
  echo "Copy this repo to a Mac and re-run: bash scripts/build_macos.sh" >&2
  exit 2
fi

echo "==> 1/5 Clean"
rm -rf build dist
mkdir -p release logs

echo "==> 2/5 Dependencies"
python3 -m pip install --upgrade pip
python3 -m pip install -r requirements.txt
python3 -m pip install -e ".[dev]"
python3 -m pip install pyinstaller

echo "==> 3/5 Tests"
export PYTHONPATH="$ROOT/src"
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests/ -q
PYTHONPATH="$ROOT/src" python3 -m neuro_pipeline.neurobids.copilot.benchmark --no-level3

echo "==> 4/5 PyInstaller"
# Prefer dedicated macOS spec when present; fall back to windows spec adapted offline.
SPEC="build_macos.spec"
if [[ ! -f "$SPEC" ]]; then
  SPEC="build_windows.spec"
  echo "NOTE: using $SPEC (create build_macos.spec for a dedicated .app layout)."
fi
python3 -m PyInstaller --noconfirm --clean "$SPEC"

echo "==> 5/5 Stage release/"
mkdir -p release
if [[ -d dist/NeuroPipeline.app ]]; then
  ditto dist/NeuroPipeline.app "release/NeuroPipeline.app"
elif [[ -d dist/NeuroPipeline_DICOM_Converter.app ]]; then
  ditto dist/NeuroPipeline_DICOM_Converter.app "release/NeuroPipeline_DICOM_Converter.app"
else
  echo "Built artifacts are under dist/. Copy the .app into release/ after reviewing."
  ls -la dist || true
fi

echo "Done. Notarization / Gatekeeper signing is intentionally not automated here."
echo "Next (on your Apple Developer account): codesign + notarytool as required for distribution."
