@echo off
setlocal
cd /d "%~dp0\.."

if not exist "tools\dcm2niix.exe" if not exist "dcm2niix.exe" (
  echo WARNING: dcm2niix.exe not found under tools\ or repo root.
  echo Copy it before packaging, e.g.:
  echo   copy /Y <path-to-dcm2niix>\dcm2niix.exe tools\dcm2niix.exe
  echo.
)

python -m pip install -q -e ".[dev]"
python -m PyInstaller installer\neuro_pipeline.spec --noconfirm --clean

echo.
echo Build complete:
echo   dist\NeuroPipeline\NeuroPipeline.exe
if exist "dist\NeuroPipeline\dcm2niix.exe" (
  echo   dist\NeuroPipeline\dcm2niix.exe  [bundled OK]
) else (
  echo   WARNING: dcm2niix.exe missing from dist\NeuroPipeline\
)
endlocal
