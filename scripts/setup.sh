#!/usr/bin/env bash
# scripts/setup.sh — PrankCam v3 developer bootstrap (macOS / Linux)
# ─────────────────────────────────────────────────────────────────────────────
# What this does:
#   1. Installs Python 3.11 venv + all backend deps (onnxruntime, insightface…)
#   2. Installs Node 22 packages (@tauri-apps/cli 2.2.0, next 15…)
#   3. Installs Rust stable + Tauri Linux system libraries
#   4. Creates the weights/ directory structure
#   5. Prints clear next-step instructions
#
# Does NOT install torch (not needed for bundled builds).
# Does NOT download model weights (run the app and use the Models tab).
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

CYAN='\033[0;36m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
RED='\033[0;31m'; BOLD='\033[1m'; NC='\033[0m'

info()    { echo -e "${CYAN}[setup]${NC} $*"; }
success() { echo -e "${GREEN}[ok]${NC} $*"; }
warn()    { echo -e "${YELLOW}[warn]${NC} $*"; }
die()     { echo -e "${RED}[error]${NC} $*"; exit 1; }
step()    { echo; echo -e "${BOLD}${CYAN}── $* ──${NC}"; echo; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
BACKEND_DIR="$ROOT_DIR/backend"

echo
echo -e "  ${BOLD}🎭  PrankCam v3 — Developer Setup${NC}"
echo "  Tauri 2 · Next.js 15 · onnxruntime · insightface"
echo

# ─────────────────────────────────────────────────────────────────────────────
# 1. Python 3.10 or 3.11  (NOT 3.12 — insightface build wheels not yet available)
# ─────────────────────────────────────────────────────────────────────────────
step "Python"
PYTHON=""
for cmd in python3.11 python3.10 python3 python; do
    if command -v "$cmd" &>/dev/null; then
        VER=$("$cmd" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
        MAJOR=$(echo "$VER" | cut -d. -f1)
        MINOR=$(echo "$VER" | cut -d. -f2)
        if [[ $MAJOR -eq 3 && $MINOR -ge 10 && $MINOR -le 11 ]]; then
            PYTHON="$cmd"
            success "Found $cmd ($VER)"
            break
        fi
    fi
done

if [[ -z "$PYTHON" ]]; then
    die "Python 3.10 or 3.11 required.\n" \
        "  macOS:  brew install python@3.11\n" \
        "  Ubuntu: sudo apt install python3.11 python3.11-venv\n" \
        "  Or download from https://python.org"
fi

# ─────────────────────────────────────────────────────────────────────────────
# 2. Python virtual environment
# ─────────────────────────────────────────────────────────────────────────────
step "Python virtual environment"
VENV_DIR="$BACKEND_DIR/.venv"

if [[ -d "$VENV_DIR" ]]; then
    warn "venv exists at $VENV_DIR — skipping creation"
else
    info "Creating venv…"
    "$PYTHON" -m venv "$VENV_DIR"
    success "Created $VENV_DIR"
fi

PY="$VENV_DIR/bin/python"
PIP="$VENV_DIR/bin/pip"

# ─────────────────────────────────────────────────────────────────────────────
# 3. Python packages
# ─────────────────────────────────────────────────────────────────────────────
step "Python packages (runtime)"
"$PIP" install --upgrade pip --quiet
"$PIP" install -r "$BACKEND_DIR/requirements.txt"
success "Runtime packages installed"

step "Python packages (build tools — PyInstaller)"
"$PIP" install -r "$BACKEND_DIR/requirements-build.txt"
success "Build packages installed"

# Verify critical imports
info "Verifying key packages…"
"$PY" -c "import fastapi; print(f'  fastapi        {fastapi.__version__}')"
"$PY" -c "import onnxruntime as ort; print(f'  onnxruntime    {ort.__version__}')"
"$PY" -c "import cv2; print(f'  opencv         {cv2.__version__}')"
"$PY" -c "import insightface; print(f'  insightface    {insightface.__version__}')"
"$PY" -c "import sounddevice as sd; print(f'  sounddevice    {sd.__version__}')"
"$PY" -c "import pyvirtualcam; print(f'  pyvirtualcam   ok')"
success "All critical imports verified"

# ─────────────────────────────────────────────────────────────────────────────
# 4. Node.js (must be 20+)
# ─────────────────────────────────────────────────────────────────────────────
step "Node.js"
if ! command -v node &>/dev/null; then
    die "Node.js not found.\n" \
        "  macOS:  brew install node\n" \
        "  Ubuntu: sudo apt install nodejs npm  (or use nvm)\n" \
        "  Or download LTS from https://nodejs.org"
fi
NODE_VER=$(node --version)
NODE_MAJOR=$(echo "$NODE_VER" | tr -d 'v' | cut -d. -f1)
[[ $NODE_MAJOR -lt 20 ]] && die "Node.js 20+ required (got $NODE_VER). Upgrade at nodejs.org."
success "Node.js $NODE_VER"

step "Node packages"
cd "$ROOT_DIR"
npm install
success "Node packages installed (Tauri 2.2.0, Next.js 15.1.7)"

# ─────────────────────────────────────────────────────────────────────────────
# 5. Rust stable
# ─────────────────────────────────────────────────────────────────────────────
step "Rust"
if ! command -v cargo &>/dev/null; then
    warn "Rust not found — installing via rustup…"
    curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --quiet
    # shellcheck disable=SC1090
    source "$HOME/.cargo/env"
fi
RUST_VER=$(rustc --version)
success "$RUST_VER"

# ─────────────────────────────────────────────────────────────────────────────
# 6. Platform-specific system libraries
# ─────────────────────────────────────────────────────────────────────────────
OS="$(uname -s)"

if [[ "$OS" == "Linux" ]]; then
    step "Linux system libraries (Tauri 2 WebKit2GTK 4.1)"
    if command -v apt-get &>/dev/null; then
        sudo apt-get update -q
        sudo apt-get install -yq \
            libwebkit2gtk-4.1-dev \
            libayatana-appindicator3-dev \
            librsvg2-dev \
            libssl-dev \
            patchelf \
            libsoup-3.0-dev \
            libjavascriptcoregtk-4.1-dev \
            build-essential \
            curl wget \
            v4l2loopback-dkms \
            v4l2loopback-utils \
            2>/dev/null || true
        success "Apt system packages installed"

        # Load v4l2loopback for dev mode
        if ! lsmod | grep -q v4l2loopback; then
            info "Loading v4l2loopback for dev mode…"
            sudo modprobe v4l2loopback \
                devices=1 video_nr=10 card_label="PrankCam" exclusive_caps=1 \
                2>/dev/null || warn "v4l2loopback load failed — check kernel module support"
        else
            success "v4l2loopback already loaded"
        fi
    elif command -v dnf &>/dev/null; then
        sudo dnf install -yq \
            webkit2gtk4.1-devel \
            openssl-devel \
            librsvg2-devel \
            libsoup3-devel \
            javascriptcoregtk4.1-devel \
            libayatana-appindicator-gtk3-devel \
            2>/dev/null || true
        success "DNF system packages installed"
    else
        warn "Unsupported package manager. Install Tauri 2 deps manually:"
        warn "  https://v2.tauri.app/start/prerequisites/"
    fi

elif [[ "$OS" == "Darwin" ]]; then
    step "macOS prerequisites"
    # Xcode CLT
    xcode-select --install 2>/dev/null || true
    success "Xcode CLT present"
    warn "Virtual camera: Install OBS from https://obsproject.com/ (free)"
    warn "Virtual mic:    Install BlackHole from https://existential.audio/blackhole/ (free)"
    warn "  Or run:  bash scripts/download-drivers.sh"
fi

# ─────────────────────────────────────────────────────────────────────────────
# 7. Weights directory skeleton
# ─────────────────────────────────────────────────────────────────────────────
step "Weights directory"
mkdir -p "$BACKEND_DIR/weights/rvc"
mkdir -p "$BACKEND_DIR/weights/insightface"
success "Weights dirs ready at backend/weights/"
info "Note: buffalo_l face detector downloads automatically on first run."
info "      inswapper_128.onnx: use the Models tab in the app to download."

# ─────────────────────────────────────────────────────────────────────────────
# Done
# ─────────────────────────────────────────────────────────────────────────────
echo
echo "  ─────────────────────────────────────────────────────────────"
echo -e "  ${GREEN}${BOLD}Setup complete!${NC}"
echo
echo "  ── Dev mode (hot reload) ──────────────────────────────────────"
echo -e "  ${CYAN}Terminal 1:${NC}  cd backend && source .venv/bin/activate && python main.py"
echo -e "  ${CYAN}Terminal 2:${NC}  npm run tauri:dev"
echo
echo "  ── Or with one command ────────────────────────────────────────"
echo "    bash scripts/dev.sh"
echo
echo "  ── Release build (produces .dmg / .deb / .AppImage) ──────────"
echo "    bash scripts/download-drivers.sh   # first time only"
echo "    bash scripts/build-all.sh"
echo
