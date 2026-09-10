#Requires -Version 5.1
<#
.SYNOPSIS
  Build NeuroPipeline DICOM Converter Windows EXE + Setup installer.

.DESCRIPTION
  Classic / Main packaging only (NO Copilot, NO Ollama).

  Product identity:
    NeuroBIDS DICOM Converter — Classic / Main

  Expected artifact:
    release\NeuroPipeline_DICOM_Converter_Setup.exe

  Refuses neurobids-copilot-* refs and Copilot source trees.
#>

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$AppVersion = "1.0.0"
$BuildChannel = "Classic / Main"

function Get-GitRevParse([string]$Arg) {
    try {
        $out = & git rev-parse $Arg 2>$null
        if ($LASTEXITCODE -eq 0 -and $out) { return ($out | Select-Object -First 1).ToString().Trim() }
    } catch { }
    return ""
}

$Branch = $env:GITHUB_REF_NAME
if (-not $Branch) { $Branch = Get-GitRevParse "--abbrev-ref HEAD" }
if (-not $Branch) { $Branch = "(unknown)" }

$Commit = Get-GitRevParse "HEAD"
if (-not $Commit) { $Commit = $env:GITHUB_SHA }
if (-not $Commit) { $Commit = "(unknown)" }

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "NeuroBIDS DICOM Converter" -ForegroundColor Cyan
Write-Host "Windows Installer Build" -ForegroundColor Cyan
Write-Host "Classic / Main" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Branch:              $Branch"
Write-Host "Commit SHA:          $Commit"
Write-Host "Application version: $AppVersion"
Write-Host "Build channel:       $BuildChannel"
Write-Host "Copilot enabled:     NO"
Write-Host "Ollama required:     NO"
Write-Host "Root:                $Root"
Write-Host "========================================" -ForegroundColor Cyan

# --- Guard: refuse Copilot / wrong product line ---
$refBlob = (@($Branch, $Commit, $env:GITHUB_REF, $env:GITHUB_HEAD_REF, $env:GITHUB_BASE_REF) -join " ").ToLowerInvariant()
if ($refBlob -match "neurobids-copilot-v1\.0\.0" -or $refBlob -match "neurobids-copilot-v1\b") {
    throw "Refused: this Classic/Main Windows build must not run on neurobids-copilot-v1.0.0 (or neurobids-copilot-v1)."
}
if (Test-Path (Join-Path $Root "src\neuro_pipeline\neurobids")) {
    throw "Refused: src\neuro_pipeline\neurobids detected — Copilot tree, not Classic/Main."
}
$navFile = Join-Path $Root "src\neuro_pipeline\gui\main_window.py"
if (Test-Path $navFile) {
    $navText = Get-Content -Raw $navFile
    if ($navText -match "Copilot|DiscoverPage|neurobids") {
        throw "Refused: main_window.py contains Copilot/Discover markers — not Classic/Main."
    }
    if ($navText -notmatch '"Convert"' -or $navText -notmatch '"Queue"' -or $navText -notmatch '"Settings"' -or $navText -notmatch '"Logs"') {
        throw "Refused: Classic navigation (Convert/Queue/Settings/Logs) not found in main_window.py."
    }
}

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
        }
        elseif (Test-Path $c) {
            return $c
        }
    }
    return $null
}

Write-Host "==> 1/6 Clean (no reuse of old dist/build/release binaries)" -ForegroundColor Yellow
foreach ($path in @("build", "dist")) {
    if (Test-Path $path) {
        Remove-Item -Recurse -Force $path
    }
}
New-Item -ItemType Directory -Force -Path "release" | Out-Null
New-Item -ItemType Directory -Force -Path "logs" | Out-Null
Get-ChildItem -Path "release" -File -ErrorAction SilentlyContinue |
    Where-Object { $_.Extension -in ".exe", ".msi", ".zip" } |
    Remove-Item -Force

Write-Host "==> 2/6 Install dependencies" -ForegroundColor Yellow
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install -e ".[dev]"
python -m pip install pyinstaller

try {
    $py = python -c "from neuro_pipeline import __version__; print(__version__)"
    if ($LASTEXITCODE -eq 0 -and $py) { $AppVersion = $py.Trim() }
} catch { }

python -c @"
import pathlib
text = pathlib.Path('requirements.txt').read_text(encoding='utf-8').lower()
text += pathlib.Path('pyproject.toml').read_text(encoding='utf-8').lower()
if 'ollama' in text:
    raise SystemExit('Refused: ollama dependency found in project metadata')
print('Dependency check OK (no Ollama package required)')
"@
if ($LASTEXITCODE -ne 0) { throw "Dependency guard failed." }

Write-Host "==> 3/6 Run tests" -ForegroundColor Yellow
$env:PYTHONPATH = Join-Path $Root "src"
python -m pytest -q
if ($LASTEXITCODE -ne 0) {
    throw "Tests failed — aborting Windows build."
}

Write-Host "==> 4/6 dcm2niix + PyInstaller" -ForegroundColor Yellow
& powershell -ExecutionPolicy Bypass -File (Join-Path $Root "scripts\ensure_dcm2niix.ps1")
if ($LASTEXITCODE -ne 0) { throw "ensure_dcm2niix.ps1 failed." }
$dcm = Join-Path $Root "tools\dcm2niix.exe"
if (-not (Test-Path $dcm)) {
    throw "Missing required tools\dcm2niix.exe"
}

python -m PyInstaller build_windows.spec --noconfirm --clean
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed."
}
$exe = Join-Path $Root "dist\NeuroPipeline_DICOM_Converter.exe"
if (-not (Test-Path $exe)) {
    throw "PyInstaller did not produce $exe"
}
Write-Host "EXE ready: $exe" -ForegroundColor Green

Write-Host "==> 5/6 Inno Setup installer (required)" -ForegroundColor Yellow
$iscc = Find-ISCC
if (-not $iscc) {
    throw "ISCC.exe not found. Install Inno Setup 6 — Classic build requires NeuroPipeline_DICOM_Converter_Setup.exe."
}
& $iscc (Join-Path $Root "installer\setup.iss")
if ($LASTEXITCODE -ne 0) {
    throw "Inno Setup compilation failed."
}
$setup = Join-Path $Root "release\NeuroPipeline_DICOM_Converter_Setup.exe"
if (-not (Test-Path $setup)) {
    throw "Inno Setup did not produce $setup"
}

Write-Host "==> 6/6 Verify packaging" -ForegroundColor Yellow
& powershell -ExecutionPolicy Bypass -File (Join-Path $Root "scripts\verify_windows_package.ps1")
if ($LASTEXITCODE -ne 0) {
    throw "Package verification failed."
}

Write-Host ""
Write-Host "Windows Classic/Main installer ready." -ForegroundColor Green
Write-Host "Branch:              $Branch"
Write-Host "Commit SHA:          $Commit"
Write-Host "Application version: $AppVersion"
Write-Host "Build channel:       $BuildChannel"
Write-Host "Copilot enabled:     NO"
Write-Host "Installer:           $setup"
Write-Host "Executable:          $exe"
Write-Host "Bundled converter:   $dcm"
