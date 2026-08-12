# Build NeuroPipeline for Windows (PowerShell)
# Usage: pwsh -File deployment/windows/build.ps1

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location $Root

Write-Host "== NeuroPipeline Windows build =="

function Assert-Command($Name) {
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Required command not found on PATH: $Name"
    }
}

Assert-Command python
python -c "import sys; print(sys.version)"

Write-Host "Installing package + PyInstaller..."
python -m pip install -U pip
python -m pip install -e ".[dev]"

Write-Host "Checking dcm2niix..."
if (-not (Get-Command dcm2niix -ErrorAction SilentlyContinue)) {
    Write-Warning "dcm2niix not found on PATH. Bundle or install before shipping."
} else {
    dcm2niix -v
}

Write-Host "Running tests..."
python -m pytest -q

Write-Host "Building with PyInstaller..."
if (Test-Path "build_windows.spec") {
    python -m PyInstaller --noconfirm build_windows.spec
} elseif (Test-Path "installer\neuro_pipeline.spec") {
    python -m PyInstaller --noconfirm installer\neuro_pipeline.spec
} else {
    python -m PyInstaller --noconfirm --windowed --name NeuroPipeline `
        --paths src `
        src\neuro_pipeline\__main__.py
}

Write-Host "Windows build finished."
Write-Host "See installer/ and dist/ for artifacts."
