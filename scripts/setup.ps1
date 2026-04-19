# scripts/setup.ps1 — PrankCam v3 developer bootstrap (Windows)
# ─────────────────────────────────────────────────────────────────────────────
# Run from the project root:
#   powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
#
# Requires:
#   • Python 3.10 or 3.11 (NOT 3.12) — download from python.org
#   • Node.js 20+ — download from nodejs.org
#   • Rust stable — download from rustup.rs
#   • Visual Studio Build Tools 2022 (C++ workload) — for Rust/Tauri
# ─────────────────────────────────────────────────────────────────────────────
$ErrorActionPreference = "Stop"

$Root       = Split-Path $PSScriptRoot -Parent
$BackendDir = "$Root\backend"

function Step($msg)    { Write-Host "`n── $msg ──" -ForegroundColor Cyan }
function Ok($msg)      { Write-Host "  ✓ $msg"    -ForegroundColor Green }
function Warn($msg)    { Write-Host "  ⚠ $msg"    -ForegroundColor Yellow }
function Fail($msg)    { Write-Host "  ✗ $msg"    -ForegroundColor Red; exit 1 }
function Info($msg)    { Write-Host "    $msg"     -ForegroundColor Gray }

Write-Host ""
Write-Host "  🎭  PrankCam v3 — Developer Setup (Windows)" -ForegroundColor White
Write-Host "  Tauri 2 · Next.js 15 · onnxruntime · insightface"
Write-Host ""

# ─────────────────────────────────────────────────────────────────────────────
# 1. Python 3.10 or 3.11
# ─────────────────────────────────────────────────────────────────────────────
Step "Python"
$PyCmd = $null
foreach ($cmd in @("python3.11", "python3.10", "python3", "python")) {
    try {
        $ver = & $cmd -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null
        if ($ver -match "^3\.(10|11)$") {
            $PyCmd = $cmd
            Ok "Found $cmd ($ver)"
            break
        } elseif ($ver -match "^3\.1[2-9]") {
            Warn "$cmd is Python $ver — insightface needs 3.10 or 3.11, skipping."
        }
    } catch {}
}
if (-not $PyCmd) {
    Fail "Python 3.10 or 3.11 not found.`n  Download from: https://python.org/downloads/ (tick 'Add to PATH')"
}

# ─────────────────────────────────────────────────────────────────────────────
# 2. Virtual environment
# ─────────────────────────────────────────────────────────────────────────────
Step "Python virtual environment"
$VenvDir = "$BackendDir\.venv"
if (Test-Path $VenvDir) {
    Warn "venv exists — skipping creation"
} else {
    Info "Creating venv at $VenvDir …"
    & $PyCmd -m venv $VenvDir
    Ok "Created $VenvDir"
}
$PyVenv  = "$VenvDir\Scripts\python.exe"
$PipVenv = "$VenvDir\Scripts\pip.exe"

# ─────────────────────────────────────────────────────────────────────────────
# 3. Python packages
# ─────────────────────────────────────────────────────────────────────────────
Step "Python packages (runtime)"
& $PipVenv install --upgrade pip --quiet
& $PipVenv install -r "$BackendDir\requirements.txt"
Ok "Runtime packages installed"

Step "Python packages (build tools)"
& $PipVenv install -r "$BackendDir\requirements-build.txt"
Ok "Build packages installed"

Step "Verifying critical imports"
foreach ($pkg in @(
    "import fastapi; print(f'  fastapi        {fastapi.__version__}')",
    "import onnxruntime as ort; print(f'  onnxruntime    {ort.__version__}')",
    "import cv2; print(f'  opencv         {cv2.__version__}')",
    "import insightface; print(f'  insightface    {insightface.__version__}')",
    "import sounddevice as sd; print(f'  sounddevice    {sd.__version__}')",
    "import pyvirtualcam; print(f'  pyvirtualcam   ok')"
)) {
    & $PyVenv -c $pkg
}
Ok "All critical imports verified"

# ─────────────────────────────────────────────────────────────────────────────
# 4. Node.js
# ─────────────────────────────────────────────────────────────────────────────
Step "Node.js"
try {
    $nv = node --version
    $nMajor = [int]($nv.TrimStart('v').Split('.')[0])
    if ($nMajor -lt 20) { Fail "Node.js 20+ required (got $nv). Download from nodejs.org." }
    Ok "Node.js $nv"
} catch {
    Fail "Node.js not found. Download from: https://nodejs.org/en/download"
}

Step "Node packages"
Set-Location $Root
npm install
Ok "Node packages installed (Tauri 2.2.0, Next.js 15.1.7)"

# ─────────────────────────────────────────────────────────────────────────────
# 5. Rust
# ─────────────────────────────────────────────────────────────────────────────
Step "Rust"
try {
    $rv = rustc --version
    Ok "$rv"
} catch {
    Warn "Rust not found."
    Info "Install from: https://rustup.rs"
    Info "Or run:       winget install Rustlang.Rustup"
    Info "Then re-run this script."
    # Don't exit — user may install Rust separately
}

# ─────────────────────────────────────────────────────────────────────────────
# 6. Weights directory
# ─────────────────────────────────────────────────────────────────────────────
Step "Weights directory"
New-Item -ItemType Directory -Force -Path "$BackendDir\weights\rvc"          | Out-Null
New-Item -ItemType Directory -Force -Path "$BackendDir\weights\insightface"  | Out-Null
Ok "Weights dirs ready at backend\weights\"
Info "buffalo_l face detector auto-downloads on first run."
Info "inswapper_128.onnx: use the Models tab in the app."

# ─────────────────────────────────────────────────────────────────────────────
# 7. Windows virtual device reminders
# ─────────────────────────────────────────────────────────────────────────────
Step "Windows virtual devices"
Warn "Virtual camera: Install OBS Studio from https://obsproject.com/"
Warn "Virtual mic:    Install VB-Audio Virtual Cable from https://vb-audio.com/Cable/"
Info "Or run:  powershell scripts\download-drivers.ps1  (downloads them automatically)"

# ─────────────────────────────────────────────────────────────────────────────
# Done
# ─────────────────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "  ─────────────────────────────────────────────────────────────"
Write-Host "  Setup complete!" -ForegroundColor Green
Write-Host ""
Write-Host "  Dev mode:" -ForegroundColor Cyan
Write-Host "    Terminal 1:  cd backend; .\.venv\Scripts\Activate.ps1; python main.py"
Write-Host "    Terminal 2:  npm run tauri:dev"
Write-Host ""
Write-Host "  Release build:" -ForegroundColor Cyan
Write-Host "    powershell scripts\download-drivers.ps1   # first time only"
Write-Host "    powershell scripts\build-all.ps1"
Write-Host ""
