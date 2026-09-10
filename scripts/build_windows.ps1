#Requires -Version 5.1
<#
.SYNOPSIS
  Build NeuroPipeline_DICOM_Converter Windows EXE + Setup installer.

.DESCRIPTION
  1. Clean build artifacts
  2. Install dependencies
  3. Run tests
  4. Run PyInstaller
  5. Create Inno Setup installer into .\release\
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

Write-Host "==> 1/5 Clean" -ForegroundColor Yellow
foreach ($path in @("build", "dist", "release")) {
    if (Test-Path $path) {
        Remove-Item -Recurse -Force $path
    }
}
New-Item -ItemType Directory -Force -Path "release" | Out-Null
New-Item -ItemType Directory -Force -Path "logs" | Out-Null

Write-Host "==> 2/5 Install dependencies" -ForegroundColor Yellow
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install -e ".[dev]"
python -m pip install pyinstaller

Write-Host "==> 3/5 Run tests" -ForegroundColor Yellow
$env:PYTHONPATH = Join-Path $Root "src"
python -m pytest -q
if ($LASTEXITCODE -ne 0) {
    throw "Tests failed — aborting Windows build."
}

Write-Host "==> 4/5 PyInstaller" -ForegroundColor Yellow
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

Write-Host "==> 5/5 Inno Setup installer" -ForegroundColor Yellow
$iscc = Find-ISCC
if (-not $iscc) {
    Write-Warning "ISCC.exe not found. EXE was built, but Setup.exe was skipped."
    Write-Warning "Install Inno Setup 6 and re-run, or compile installer\setup.iss manually."
    Copy-Item $exe (Join-Path $Root "release\NeuroPipeline.exe") -Force
    if (Test-Path $bundledDcm) {
        Copy-Item $bundledDcm (Join-Path $Root "release\dcm2niix.exe") -Force
    }
    Write-Host "Portable onedir artifacts copied to release\" -ForegroundColor Yellow
    exit 0
}

& $iscc (Join-Path $Root "installer\setup.iss")
$setup = Join-Path $Root "release\NeuroPipeline_DICOM_Converter_Setup.exe"
if (-not (Test-Path $setup)) {
    throw "Inno Setup did not produce $setup"
}

Write-Host ""
Write-Host "Windows desktop application ready." -ForegroundColor Green
Write-Host "Installer: $setup"
Write-Host "Executable: $exe"
