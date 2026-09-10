#Requires -Version 5.1
<#
.SYNOPSIS
  Ensure tools\dcm2niix.exe exists, is a Windows PE binary, and print its version.

.DESCRIPTION
  Classic / Main packaging helper.

  Pinned source (only this URL is allowed for auto-download):
    https://github.com/rordenlab/dcm2niix/releases/download/v1.0.20250506/dcm2niix_win.zip

  The ZIP is SHA256-verified BEFORE extraction. tools\dcm2niix.exe is NOT
  versioned in Git; CI/local builds download it when absent.
#>

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

# ---------------------------------------------------------------------------
# Pinned official Windows release (do not change casually)
# Tag:  v1.0.20250506
# URL:  https://github.com/rordenlab/dcm2niix/releases/download/v1.0.20250506/dcm2niix_win.zip
# SHA256 of that exact ZIP (computed from the official download; verified twice):
#   04ebd85205380c2a78b4a77b3b032bd8d8ff8f6f7c09feaf47f246f2a9efd282
# ---------------------------------------------------------------------------
$PinnedUrl = "https://github.com/rordenlab/dcm2niix/releases/download/v1.0.20250506/dcm2niix_win.zip"
$PinnedTag = "v1.0.20250506"
$ExpectedZipSha256 = "04ebd85205380c2a78b4a77b3b032bd8d8ff8f6f7c09feaf47f246f2a9efd282"

$Target = Join-Path $Root "tools\dcm2niix.exe"
$ZipPath = Join-Path $Root "dcm2niix_win_pinned.zip"
$TmpDir = Join-Path $Root "_dcm2niix_extract"

function Test-IsWindowsPe([string]$Path) {
    if (-not (Test-Path $Path)) { return $false }
    $fs = [System.IO.File]::OpenRead($Path)
    try {
        $buf = New-Object byte[] 2
        if ($fs.Read($buf, 0, 2) -ne 2) { return $false }
        return ($buf[0] -eq 0x4D -and $buf[1] -eq 0x5A)
    } finally {
        $fs.Dispose()
    }
}

function Get-FileSha256Hex([string]$Path) {
    $hash = Get-FileHash -Algorithm SHA256 -Path $Path
    return $hash.Hash.ToLowerInvariant()
}

function Remove-IfExists([string]$Path) {
    if (Test-Path $Path) {
        Remove-Item -LiteralPath $Path -Recurse -Force -ErrorAction SilentlyContinue
    }
}

function Clear-DownloadArtifacts {
    Remove-IfExists $ZipPath
    Remove-IfExists $TmpDir
}

New-Item -ItemType Directory -Force -Path (Join-Path $Root "tools") | Out-Null

if (-not (Test-Path $Target)) {
    Write-Host "tools\dcm2niix.exe missing — downloading pinned Windows build..." -ForegroundColor Yellow
    Write-Host "Source: $PinnedUrl"
    Write-Host "Tag:    $PinnedTag"
    Write-Host "Expect SHA256: $ExpectedZipSha256"

    Clear-DownloadArtifacts
    try {
        Invoke-WebRequest -Uri $PinnedUrl -OutFile $ZipPath
        if (-not (Test-Path $ZipPath)) {
            throw "Download failed: ZIP not written to $ZipPath"
        }

        $actual = Get-FileSha256Hex $ZipPath
        Write-Host "Actual SHA256: $actual"
        if ($actual -ne $ExpectedZipSha256.ToLowerInvariant()) {
            throw "SHA256 mismatch for dcm2niix_win.zip. Expected $ExpectedZipSha256 but got $actual. Refusing to extract."
        }
        Write-Host "ZIP SHA256 verified OK" -ForegroundColor Green

        New-Item -ItemType Directory -Force -Path $TmpDir | Out-Null
        Expand-Archive -Path $ZipPath -DestinationPath $TmpDir -Force
        $found = Get-ChildItem -Path $TmpDir -Recurse -Filter "dcm2niix.exe" | Select-Object -First 1
        if (-not $found) {
            throw "Pinned zip did not contain dcm2niix.exe: $PinnedUrl"
        }
        Copy-Item -Force $found.FullName $Target
    }
    catch {
        Clear-DownloadArtifacts
        throw
    }
    finally {
        Clear-DownloadArtifacts
    }
}

if (-not (Test-Path $Target)) {
    throw "dcm2niix.exe still missing after download attempt: $Target"
}

$info = Get-Item $Target
if ($info.Length -lt 100KB) {
    throw ("dcm2niix.exe unexpectedly small ({0} bytes)" -f $info.Length)
}
if (-not (Test-IsWindowsPe $Target)) {
    throw "dcm2niix.exe is not a Windows PE executable (missing MZ header): $Target"
}

Write-Host "dcm2niix.exe OK" -ForegroundColor Green
Write-Host "  Path:   $($info.FullName)"
Write-Host "  Size:   $($info.Length) bytes"
Write-Host "  PE:     Windows MZ/PE header validated"
Write-Host "  Source: $PinnedUrl (tag $PinnedTag) when auto-downloaded"
Write-Host "  ZIP SHA256 (pinned): $ExpectedZipSha256"
Write-Host "  Git:    tools\dcm2niix.exe is NOT versioned in Git"
Write-Host "  License notes: third_party\licenses\README.md"

try {
    $verOut = & $Target 2>&1 | Select-Object -First 8
    Write-Host "  Version output:"
    foreach ($line in $verOut) { Write-Host "    $line" }
} catch {
    Write-Host "  Version: could not execute binary for version banner (file still PE-validated)" -ForegroundColor Yellow
}

Write-Host "DCM2NIIX_PINNED_URL=$PinnedUrl"
Write-Host "DCM2NIIX_PINNED_TAG=$PinnedTag"
Write-Host "DCM2NIIX_ZIP_SHA256=$ExpectedZipSha256"
