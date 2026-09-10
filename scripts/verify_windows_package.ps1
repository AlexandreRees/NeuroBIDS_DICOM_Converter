#Requires -Version 5.1
<#
.SYNOPSIS
  Verify Classic/Main Windows packaging outputs before shipping to PI.

.NOTES
  File checks are HARD failures.
  GUI smoke on headless runners is INFORMATIONAL and must not fail the build
  solely because a windowed app exits early without a display.
#>

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

Write-Host "==> verify_windows_package.ps1" -ForegroundColor Cyan
Write-Host "Build channel: Classic / Main"
Write-Host "Copilot enabled: NO"

function Test-IsWindowsPe([string]$Path) {
    $fs = [System.IO.File]::OpenRead($Path)
    try {
        $buf = New-Object byte[] 2
        if ($fs.Read($buf, 0, 2) -ne 2) { return $false }
        return ($buf[0] -eq 0x4D -and $buf[1] -eq 0x5A)
    } finally {
        $fs.Dispose()
    }
}

$exe = Join-Path $Root "dist\NeuroPipeline_DICOM_Converter.exe"
$setup = Join-Path $Root "release\NeuroPipeline_DICOM_Converter_Setup.exe"
$dcmTools = Join-Path $Root "tools\dcm2niix.exe"
$issPath = Join-Path $Root "installer\setup.iss"
$specPath = Join-Path $Root "build_windows.spec"

# --- A/B/C required outputs ---
foreach ($p in @($exe, $setup, $dcmTools, $issPath, $specPath)) {
    if (-not (Test-Path $p)) { throw "Missing required file: $p" }
}

$exeInfo = Get-Item $exe
$setupInfo = Get-Item $setup
$dcmInfo = Get-Item $dcmTools

if ($exeInfo.Length -le 0) { throw "EXE size is 0: $exe" }
if ($setupInfo.Length -le 0) { throw "Setup size is 0: $setup" }
if ($dcmInfo.Length -le 0) { throw "dcm2niix size is 0: $dcmTools" }

if ($exeInfo.Length -lt 5MB) { throw "EXE unexpectedly small: $($exeInfo.Length) bytes" }
if ($setupInfo.Length -lt 5MB) { throw "Setup.exe unexpectedly small: $($setupInfo.Length) bytes" }
if ($dcmInfo.Length -lt 100KB) { throw "dcm2niix.exe unexpectedly small: $($dcmInfo.Length) bytes" }

if (-not (Test-IsWindowsPe $exe)) { throw "App EXE is not a Windows PE (MZ): $exe" }
if (-not (Test-IsWindowsPe $setup)) { throw "Setup.exe is not a Windows PE (MZ): $setup" }
if (-not (Test-IsWindowsPe $dcmTools)) { throw "dcm2niix.exe is not a Windows PE (MZ): $dcmTools" }

# --- D resources / installer contract ---
$iss = Get-Content -Raw $issPath
if ($iss -notmatch "dcm2niix\.exe") {
    throw "installer\setup.iss does not reference dcm2niix.exe"
}
if ($iss -notmatch "OutputBaseFilename=NeuroPipeline_DICOM_Converter_Setup") {
    throw "installer\setup.iss OutputBaseFilename mismatch"
}
if ($iss -notmatch "NeuroPipeline_DICOM_Converter\.exe") {
    throw "installer\setup.iss missing NeuroPipeline_DICOM_Converter.exe"
}
if ($iss -notmatch "Classic / Main") {
    throw "installer\setup.iss missing Classic / Main identity"
}
if ($iss -match "neurobids-copilot|Ollama") {
    throw "installer\setup.iss contains Copilot/Ollama markers"
}
# "Copilot" substring alone should not appear as a feature name
if ($iss -match "(?i)copilot") {
    throw "installer\setup.iss unexpectedly mentions Copilot"
}

$spec = Get-Content -Raw $specPath
if ($spec -notmatch 'name="NeuroPipeline_DICOM_Converter"') {
    throw "build_windows.spec does not name NeuroPipeline_DICOM_Converter"
}
if ($spec -notmatch "configs") {
    throw "build_windows.spec missing configs datas"
}

# --- E/F runtime independence ---
$req = (Get-Content -Raw (Join-Path $Root "requirements.txt")) + "`n" + (Get-Content -Raw (Join-Path $Root "pyproject.toml"))
if ($req -match "(?i)\bollama\b") {
    throw "Ollama dependency detected in project metadata"
}
Write-Host "Runtime Python required: NO (frozen onefile)" -ForegroundColor Green
Write-Host "Runtime Ollama required: NO" -ForegroundColor Green

# --- G absolute machine-specific paths ---
$scanTargets = @(
    $issPath,
    $specPath,
    (Join-Path $Root "scripts\build_windows.ps1"),
    (Join-Path $Root "configs\default.yaml")
)
$forbidden = @(
    "C:\\Users\\alexrees",
    "C:/Users/alexrees",
    "/lustre07/scratch/alexrees",
    "D:\\aim2",
    "D:/aim2"
)
foreach ($file in $scanTargets) {
    if (-not (Test-Path $file)) { continue }
    $text = Get-Content -Raw $file
    foreach ($bad in $forbidden) {
        if ($text.Contains($bad)) {
            throw "Machine-specific absolute path '$bad' found in $file"
        }
    }
}
Write-Host "Absolute local-path scan: OK" -ForegroundColor Green

# --- H identity ---
Write-Host "Identity: NeuroBIDS DICOM Converter — Classic / Main" -ForegroundColor Green
Write-Host "Application version: 1.0.0"
Write-Host "Copilot enabled: NO"

# --- GUI smoke (informational on headless CI) ---
Write-Host "Smoke-launching frozen EXE (informational on headless runners)..." -ForegroundColor Yellow
$smokeStatus = "NOT_RUN"
try {
    $proc = Start-Process -FilePath $exe -PassThru -WindowStyle Hidden
    Start-Sleep -Seconds 6
    if ($null -eq $proc) {
        $smokeStatus = "FAILED_TO_START"
        Write-Host "SMOKE: FAILED_TO_START (informational)" -ForegroundColor Yellow
    } elseif (-not $proc.HasExited) {
        Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
        $smokeStatus = "STARTED_OK"
        Write-Host "SMOKE: STARTED_OK (process launched; terminated by verifier)" -ForegroundColor Green
    } else {
        $smokeStatus = "EARLY_EXIT_HEADLESS_OR_GUI"
        Write-Host "SMOKE: EARLY_EXIT_HEADLESS_OR_GUI (exit=$($proc.ExitCode)) — not a hard failure on CI" -ForegroundColor Yellow
    }
} catch {
    $smokeStatus = "EXCEPTION"
    Write-Host "SMOKE: EXCEPTION ($($_.Exception.Message)) — not a hard failure; file checks already passed" -ForegroundColor Yellow
}
Write-Host "SMOKE_RESULT=$smokeStatus"

# --- Optional silent install smoke (best-effort) ---
$installStatus = "SKIPPED"
$tmpInstall = Join-Path $env:TEMP ("NeuroPipelineClassicInstall_" + [guid]::NewGuid().ToString("N"))
try {
    Write-Host "Attempting silent Setup install into: $tmpInstall" -ForegroundColor Yellow
    New-Item -ItemType Directory -Force -Path $tmpInstall | Out-Null
    $p = Start-Process -FilePath $setup -ArgumentList @(
        "/VERYSILENT",
        "/SUPPRESSMSGBOXES",
        "/NORESTART",
        "/DIR=$tmpInstall"
    ) -PassThru -Wait
    $appExe = Join-Path $tmpInstall "NeuroPipeline_DICOM_Converter.exe"
    $appDcm = Join-Path $tmpInstall "dcm2niix.exe"
    if (($p.ExitCode -eq 0) -and (Test-Path $appExe) -and (Test-Path $appDcm)) {
        $installStatus = "OK"
        Write-Host "SILENT_INSTALL: OK (app + dcm2niix present under temp dir)" -ForegroundColor Green
    } else {
        $installStatus = "INCONCLUSIVE"
        Write-Host "SILENT_INSTALL: INCONCLUSIVE (exit=$($p.ExitCode); app=$(Test-Path $appExe); dcm=$(Test-Path $appDcm))" -ForegroundColor Yellow
        Write-Host "Manual install test on a real Windows desktop is still required before sending to PI." -ForegroundColor Yellow
    }
} catch {
    $installStatus = "FAILED_OR_UNSUPPORTED"
    Write-Host "SILENT_INSTALL: FAILED_OR_UNSUPPORTED ($($_.Exception.Message))" -ForegroundColor Yellow
    Write-Host "Manual install test on a real Windows desktop is still required before sending to PI." -ForegroundColor Yellow
} finally {
    try {
        $unins = Get-ChildItem -Path $tmpInstall -Filter "unins*.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($unins) {
            Start-Process -FilePath $unins.FullName -ArgumentList "/VERYSILENT","/SUPPRESSMSGBOXES","/NORESTART" -Wait -ErrorAction SilentlyContinue
        }
    } catch { }
    if (Test-Path $tmpInstall) {
        Remove-Item -Recurse -Force $tmpInstall -ErrorAction SilentlyContinue
    }
}
Write-Host "SILENT_INSTALL_RESULT=$installStatus"

Write-Host "Verified (hard checks):" -ForegroundColor Green
Write-Host "  EXE:        $exe  ($([math]::Round($exeInfo.Length/1MB,1)) MB) PE=OK"
Write-Host "  Setup:      $setup  ($([math]::Round($setupInfo.Length/1MB,1)) MB) PE=OK"
Write-Host "  dcm2niix:   $dcmTools  ($([math]::Round($dcmInfo.Length/1KB,0)) KB) PE=OK"
Write-Host "  Channel:    Classic / Main"
Write-Host "  Copilot:    NO"
Write-Host "  Ollama:     NOT REQUIRED"
Write-Host "  Python:     NOT REQUIRED at runtime (frozen)"
