#!/usr/bin/env bash
# scripts/build-all.sh
# ─────────────────────────────────────────────────────────────────────────────
# Full release build:  Python sidecar → Next.js frontend → Tauri installers
#
# Usage:
#   bash scripts/build-all.sh              # build for current platform
#   bash scripts/build-all.sh --target mac # cross-compile hint (macOS only)
#
# Outputs (inside src-tauri/target/release/bundle/):
#   macOS  → PrankCam_3.0.0_aarch64.dmg  /  PrankCam_3.0.0_x64.dmg
#   Windows→ PrankCam_3.0.0_x64-setup.exe  /  PrankCam_3.0.0_x64_en-US.msi
#   Linux  → prankcam_3.0.0_amd64.deb  /  PrankCam_3.0.0_amd64.AppImage
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

CYAN='\033[0;36m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; BOLD='\033[1m'; NC='\033[0m'
step()    { echo; echo -e "${BOLD}${CYAN}━━━  $* ${NC}"; echo; }
success() { echo -e "${GREEN}✓${NC} $*"; }
warn()    { echo -e "${YELLOW}⚠${NC} $*"; }
die()     { echo -e "${RED}✗ $*${NC}"; exit 1; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
START_TS=$(date +%s)

echo
echo -e "${BOLD}  🎭  PrankCam — Full Release Build${NC}"
echo -e "  $(date)"
echo

# ── Preflight checks ──────────────────────────────────────────────────────────
step "Preflight"

command -v node    &>/dev/null || die "node not found. Install Node.js 22+."
command -v npm     &>/dev/null || die "npm not found."
command -v cargo   &>/dev/null || die "cargo not found. Install Rust via rustup."

NODE_MAJOR=$(node --version | cut -d. -f1 | tr -d v)
[[ $NODE_MAJOR -lt 20 ]] && die "Node.js 20+ required (got $(node --version))."
success "Node.js $(node --version)"
success "Rust $(rustc --version)"

# ── Step 1: Python sidecar ────────────────────────────────────────────────────
step "Step 1/4 — Build Python backend sidecar"
bash "$SCRIPT_DIR/build-backend.sh"
success "Python sidecar built"

# ── Step 2: npm install ───────────────────────────────────────────────────────
step "Step 2/4 — Install Node packages"
cd "$ROOT_DIR"
npm ci --silent
success "Node packages installed"

# ── Step 3: Next.js static export ────────────────────────────────────────────
step "Step 3/4 — Build Next.js frontend"
npm run build
[[ -d "$ROOT_DIR/out" ]] || die "Next.js build failed — out/ directory missing."
success "Next.js exported to out/"

# ── Step 4: Tauri bundle ──────────────────────────────────────────────────────
step "Step 4/4 — Tauri bundle (creates installers)"
npm run tauri:build

# ── Collect outputs ───────────────────────────────────────────────────────────
step "Build complete"
BUNDLE_DIR="$ROOT_DIR/src-tauri/target/release/bundle"
END_TS=$(date +%s)
ELAPSED=$((END_TS - START_TS))

echo -e "${GREEN}All done in ${ELAPSED}s.${NC}"
echo
echo -e "  Installers in: ${CYAN}${BUNDLE_DIR}/${NC}"
echo

if [[ -d "$BUNDLE_DIR" ]]; then
    find "$BUNDLE_DIR" -type f \( -name "*.dmg" -o -name "*.exe" -o -name "*.msi" -o -name "*.deb" -o -name "*.AppImage" \) \
        | while read -r f; do
            echo -e "    ${GREEN}→${NC} $(basename "$f")  ($(du -sh "$f" | cut -f1))"
          done
fi
echo
