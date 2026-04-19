# scripts/download-drivers.ps1 — Download Windows virtual driver installers
$ErrorActionPreference = "Stop"
$Root       = Split-Path $PSScriptRoot -Parent
$DriversDir = "$Root\src-tauri\drivers\windows"

function Ok($m)   { Write-Host "  ✓ $m" -ForegroundColor Green }
function Info($m) { Write-Host "    $m" -ForegroundColor Gray }
function Warn($m) { Write-Host "  ⚠ $m" -ForegroundColor Yellow }

New-Item -ItemType Directory -Force -Path $DriversDir | Out-Null

Write-Host "`n  📦  PrankCam — Windows Driver Downloader" -ForegroundColor Cyan
Write-Host "  ─────────────────────────────────────────`n"

# ── OBS Studio (includes Virtual Camera DirectShow filter) ────────────────────
$ObsVersion = "30.2.2"
$ObsDest    = "$DriversDir\obs-virtualcam-setup.exe"
if (Test-Path $ObsDest) {
    Ok "OBS Studio already downloaded"
} else {
    $ObsUrl = "https://github.com/obsproject/obs-studio/releases/download/$ObsVersion/OBS-Studio-$ObsVersion-Windows-Installer.exe"
    Info "Downloading OBS Studio $ObsVersion…"
    try {
        Invoke-WebRequest $ObsUrl -OutFile $ObsDest -UseBasicParsing
        Ok "OBS Studio $ObsVersion downloaded ($('{0:N1} MB' -f ((Get-Item $ObsDest).Length / 1MB)))"
    } catch {
        Warn "OBS download failed: $_"
        Warn "Download manually from https://obsproject.com/ and place at:"
        Warn "  $ObsDest"
    }
}

# ── VB-Audio Virtual Cable ────────────────────────────────────────────────────
$VbDest = "$DriversDir\VBCABLE_Setup_x64.exe"
if (Test-Path $VbDest) {
    Ok "VB-Audio Virtual Cable already downloaded"
} else {
    $VbUrl = "https://download.vb-audio.com/Download_CABLE/VBCABLE_Driver_Pack43.zip"
    $VbZip = "$DriversDir\vbcable_tmp.zip"
    Info "Downloading VB-Audio Virtual Cable…"
    try {
        $wc = New-Object System.Net.WebClient
        $wc.Headers.Add("Referer", "https://vb-audio.com/Cable/")
        $wc.DownloadFile($VbUrl, $VbZip)
        # Extract
        $VbExtract = "$DriversDir\vbcable_extracted"
        Expand-Archive -Path $VbZip -DestinationPath $VbExtract -Force
        $Setup = Get-ChildItem $VbExtract -Recurse -Filter "VBCABLE_Setup_x64.exe" | Select-Object -First 1
        if ($Setup) {
            Copy-Item $Setup.FullName $VbDest
            Remove-Item $VbExtract -Recurse -Force
            Remove-Item $VbZip -Force
            Ok "VB-Audio Virtual Cable extracted ($('{0:N1} MB' -f ((Get-Item $VbDest).Length / 1MB)))"
        } else {
            Warn "VBCABLE_Setup_x64.exe not found in archive."
        }
    } catch {
        Warn "VB-Audio download failed: $_"
        Warn "Download manually from https://vb-audio.com/Cable/ and place at:"
        Warn "  $VbDest"
    }
}

Write-Host ""
Write-Host "  Drivers in $DriversDir :" -ForegroundColor Cyan
Get-ChildItem $DriversDir | ForEach-Object {
    Write-Host ("    → {0,-45} {1}" -f $_.Name, ('{0:N1} MB' -f ($_.Length / 1MB))) -ForegroundColor Green
}
Write-Host ""
Write-Host "  Now run:  powershell scripts\build-all.ps1" -ForegroundColor Cyan
Write-Host ""
