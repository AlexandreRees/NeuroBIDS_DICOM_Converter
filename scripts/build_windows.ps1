#Requires -Version 5.1
<#
.SYNOPSIS
  Build NeuroPipeline_DICOM_Converter Windows EXE + Setup installer.

.DESCRIPTION
  1. Clean build artifacts (keeps release/*.md notes)
  2. Install dependencies
  3. Run tests
  4. Run PyInstaller (onedir)
  5. Create Inno Setup installer into .\release\
  6. Verify packaging layout

  Expected artifact:
    release\NeuroPipeline_DICOM_Converter_Setup.exe

  End users do not need Python, pip, Git, or a virtual environment.
  Ollama / LLM models are NOT bundled — Copilot remains optional.
#>

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

Write-Host "==> NeuroPipeline Windows build" -ForegroundColor Cyan
Write-Host "Root: $Root"

function Find-ISCC {
    $candidates = @(
        "ISCC.exe",
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
    )
    foreach ($c in $candidates) {
        if ($c -eq "ISCC.exe") {
            $cmd = Get-Command ISCC.exe -ErrorAction SilentlyContinue
            if ($cmd) { return $cmd.Source }
        } elseif (Test-Path $c) {
            return $c
        }
    }
    return $null
}

Write-Host "==> 1/6 Clean" -ForegroundColor Yellow
foreach ($path in @("build", "dist")) {
    if (Test-Path $path) {
        Remove-Item -Recurse -Force $path
    }
}
New-Item -ItemType Directory -Force -Path "release" | Out-Null
New-Item -ItemType Directory -Force -Path "logs" | Out-Null
# Remove prior installer binaries only — keep release notes markdown.
Get-ChildItem -Path "release" -File -ErrorAction SilentlyContinue |
    Where-Object { $_.Extension -in ".exe", ".msi", ".zip" } |
    Remove-Item -Force

Write-Host "==> 2/6 Install dependencies" -ForegroundColor Yellow
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install -e ".[dev]"
python -m pip install pyinstaller

Write-Host "==> 3/6 Run tests" -ForegroundColor Yellow
$env:PYTHONPATH = Join-Path $Root "src"
python -m pytest -q
if ($LASTEXITCODE -ne 0) {
    throw "Tests failed — aborting Windows build."
}

Write-Host "==> 4/6 PyInstaller (onedir)" -ForegroundColor Yellow
if (-not (Test-Path (Join-Path $Root "tools\dcm2niix.exe")) -and -not (Test-Path (Join-Path $Root "dcm2niix.exe"))) {
    Write-Warning "dcm2niix.exe not found under tools\ or repo root — package may miss the converter binary."
}
python -m PyInstaller installer\neuro_pipeline.spec --noconfirm --clean
$exe = Join-Path $Root "dist\NeuroPipeline\NeuroPipeline.exe"
$bundledDcm = Join-Path $Root "dist\NeuroPipeline\dcm2niix.exe"
if (-not (Test-Path $exe)) {
    throw "PyInstaller did not produce $exe"
}
if (-not (Test-Path $bundledDcm)) {
    Write-Warning "dcm2niix.exe missing from dist\NeuroPipeline\ — copy tools\dcm2niix.exe and rebuild."
} else {
    Write-Host "Bundled dcm2niix: $bundledDcm" -ForegroundColor Green
}
Write-Host "EXE ready: $exe" -ForegroundColor Green

Write-Host "==> 5/6 Inno Setup installer" -ForegroundColor Yellow
$iscc = Find-ISCC
if (-not $iscc) {
    Write-Warning "ISCC.exe not found. EXE was built, but Setup.exe was skipped."
    Write-Warning "Install Inno Setup 6 and re-run, or compile installer\setup.iss manually."
    Copy-Item $exe (Join-Path $Root "release\NeuroPipeline.exe") -Force
    if (Test-Path $bundledDcm) {
        Copy-Item $bundledDcm (Join-Path $Root "release\dcm2niix.exe") -Force
    }
    Write-Host "Portable onedir EXE copied to release\ (full folder remains under dist\NeuroPipeline\)" -ForegroundColor Yellow
} else {
    & $iscc (Join-Path $Root "installer\setup.iss")
    $setup = Join-Path $Root "release\NeuroPipeline_DICOM_Converter_Setup.exe"
    if (-not (Test-Path $setup)) {
        throw "Inno Setup did not produce $setup"
    }
    Write-Host "Installer: $setup" -ForegroundColor Green
}

Write-Host "==> 6/6 Packaging verification" -ForegroundColor Yellow
$env:PYTHONPATH = Join-Path $Root "src"
python (Join-Path $Root "scripts\verify_packaging.py")
if ($LASTEXITCODE -ne 0) {
    throw "Packaging verification failed."
}

Write-Host ""
Write-Host "Windows desktop application ready." -ForegroundColor Green
Write-Host "Build command: powershell -ExecutionPolicy Bypass -File .\scripts\build_windows.ps1"
Write-Host "Artifact:     release\NeuroPipeline_DICOM_Converter_Setup.exe"
Write-Host "Onedir EXE:   dist\NeuroPipeline\NeuroPipeline.exe"
Write-Host "Note: Ollama / LLM models are not bundled. Copilot stays optional."
