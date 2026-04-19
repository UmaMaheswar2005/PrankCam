# scripts/build-all.ps1 — PrankCam full release build (Windows)
# Run from project root: powershell -ExecutionPolicy Bypass -File scripts\build-all.ps1
$ErrorActionPreference = "Stop"

$Root      = Split-Path $PSScriptRoot -Parent
$StartTime = Get-Date

function Step($msg)    { Write-Host "`n━━━  $msg" -ForegroundColor Cyan }
function Ok($msg)      { Write-Host "✓ $msg"    -ForegroundColor Green }
function Warn($msg)    { Write-Host "⚠ $msg"    -ForegroundColor Yellow }
function Fail($msg)    { Write-Host "✗ $msg"    -ForegroundColor Red; exit 1 }

Write-Host "`n  🎭  PrankCam — Full Release Build (Windows)" -ForegroundColor White
Write-Host "  $(Get-Date)`n"

# ── Preflight ─────────────────────────────────────────────────────────────────
Step "Preflight"
try { $nv = node --version;  Ok "Node.js $nv"   } catch { Fail "Node.js not found. Install from nodejs.org" }
try { $rv = rustc --version; Ok "Rust $rv"      } catch { Fail "Rust not found. Install from rustup.rs"    }
$nMajor = [int]($nv.TrimStart('v').Split('.')[0])
if ($nMajor -lt 20) { Fail "Node.js 20+ required (got $nv)" }

# ── Step 1: Python sidecar ────────────────────────────────────────────────────
Step "Step 1/4 — Build Python backend sidecar"
Set-Location $Root
& powershell -ExecutionPolicy Bypass -File "$PSScriptRoot\build-backend.ps1"
Ok "Python sidecar built"

# ── Step 2: npm install ───────────────────────────────────────────────────────
Step "Step 2/4 — Install Node packages"
Set-Location $Root
npm ci --silent
Ok "Node packages installed"

# ── Step 3: Next.js static export ────────────────────────────────────────────
Step "Step 3/4 — Build Next.js frontend"
npm run build
if (-not (Test-Path "$Root\out")) { Fail "Next.js build failed — out\ directory missing." }
Ok "Next.js exported to out\"

# ── Step 4: Tauri bundle ──────────────────────────────────────────────────────
Step "Step 4/4 — Tauri bundle"
npm run tauri:build

# ── Summary ───────────────────────────────────────────────────────────────────
Step "Build complete"
$Elapsed = [int]((Get-Date) - $StartTime).TotalSeconds
$BundleDir = "$Root\src-tauri\target\release\bundle"

Write-Host "All done in ${Elapsed}s." -ForegroundColor Green
Write-Host "`n  Installers in: $BundleDir`n"

if (Test-Path $BundleDir) {
    Get-ChildItem $BundleDir -Recurse -Include "*.exe","*.msi" | ForEach-Object {
        $size = "{0:N1} MB" -f ($_.Length / 1MB)
        Write-Host "    → $($_.Name)  ($size)" -ForegroundColor Green
    }
}
Write-Host ""
