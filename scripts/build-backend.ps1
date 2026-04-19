# scripts/build-backend.ps1 — Windows Python sidecar build
$ErrorActionPreference = "Stop"
$Root       = Split-Path $PSScriptRoot -Parent
$BackendDir = "$Root\backend"
$BinariesDir= "$Root\src-tauri\binaries"
$Triple     = "x86_64-pc-windows-msvc"

function Ok($m)   { Write-Host "✓ $m" -ForegroundColor Green }
function Info($m) { Write-Host "  $m" -ForegroundColor Cyan }
function Fail($m) { Write-Host "✗ $m" -ForegroundColor Red; exit 1 }

New-Item -ItemType Directory -Force -Path $BinariesDir | Out-Null

# Resolve Python
$PyPaths = @(
    "$BackendDir\.venv\Scripts\python.exe",
    "python3", "python"
)
$PY = $null
foreach ($p in $PyPaths) {
    if (Test-Path $p -ErrorAction SilentlyContinue) { $PY = $p; break }
    try { & $p --version 2>$null | Out-Null; $PY = $p; break } catch {}
}
if (-not $PY) { Fail "Python not found. Run scripts\setup.ps1 first." }
Info "Python: $PY"

# Ensure PyInstaller
try { & $PY -c "import PyInstaller" 2>$null } catch {
    Info "Installing PyInstaller…"
    & $PY -m pip install --quiet -r "$BackendDir\requirements-build.txt"
}

Info "Running PyInstaller…"
Set-Location $BackendDir
& $PY -m PyInstaller prankcam-backend.spec --noconfirm --clean --log-level WARN

$DistDir = "$BackendDir\dist\prankcam-backend"
if (-not (Test-Path $DistDir)) { Fail "PyInstaller failed — dist not created." }

# Copy sidecar executable
$SrcExe  = "$DistDir\prankcam-backend.exe"
$DestExe = "$BinariesDir\prankcam-backend-${Triple}.exe"
Copy-Item $SrcExe $DestExe -Force
Ok "Sidecar: $DestExe"

# Copy onedir libs to resources
$LibsDest = "$Root\src-tauri\resources\backend-libs\$Triple"
New-Item -ItemType Directory -Force -Path $LibsDest | Out-Null
robocopy $DistDir $LibsDest /MIR /NFL /NDL /NJH /NJS /NC /NS | Out-Null
Remove-Item "$LibsDest\prankcam-backend.exe" -ErrorAction SilentlyContinue
Ok "Backend libs → $LibsDest"
