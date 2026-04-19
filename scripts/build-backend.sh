#!/usr/bin/env bash
# scripts/build-backend.sh
# ─────────────────────────────────────────────────────────────────────────────
# Compiles the Python backend into a self-contained PyInstaller bundle and
# places it where Tauri expects a sidecar binary.
#
# Must be run BEFORE `tauri build`.  Called automatically by `build-all.sh`.
#
# Output layout:
#   src-tauri/binaries/
#     prankcam-backend-x86_64-unknown-linux-gnu   ← Linux x86_64
#     prankcam-backend-aarch64-apple-darwin        ← macOS Apple Silicon
#     prankcam-backend-x86_64-apple-darwin         ← macOS Intel
#     prankcam-backend-x86_64-pc-windows-msvc.exe ← Windows x86_64
#
# Tauri sidecar naming convention:
#   <name>-<target-triple>[.exe]
#   where <name> matches tauri.conf.json  bundle.externalBin[0]
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

CYAN='\033[0;36m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
info()    { echo -e "${CYAN}[backend-build]${NC} $*"; }
success() { echo -e "${GREEN}[ok]${NC} $*"; }
warn()    { echo -e "${YELLOW}[warn]${NC} $*"; }
die()     { echo -e "${RED}[error]${NC} $*"; exit 1; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
BACKEND_DIR="$ROOT_DIR/backend"
BINARIES_DIR="$ROOT_DIR/src-tauri/binaries"
DIST_DIR="$BACKEND_DIR/dist/prankcam-backend"

mkdir -p "$BINARIES_DIR"

# ── Detect target triple ──────────────────────────────────────────────────────
detect_triple() {
    local arch os triple
    arch="$(uname -m)"
    os="$(uname -s)"
    case "$os" in
        Darwin)
            case "$arch" in
                arm64)  triple="aarch64-apple-darwin"   ;;
                x86_64) triple="x86_64-apple-darwin"    ;;
                *)      die "Unsupported macOS arch: $arch" ;;
            esac ;;
        Linux)
            case "$arch" in
                x86_64)  triple="x86_64-unknown-linux-gnu"   ;;
                aarch64) triple="aarch64-unknown-linux-gnu"  ;;
                *)       die "Unsupported Linux arch: $arch" ;;
            esac ;;
        MINGW*|MSYS*|CYGWIN*)
            triple="x86_64-pc-windows-msvc" ;;
        *)
            die "Unknown OS: $os" ;;
    esac
    echo "$triple"
}

TRIPLE="$(detect_triple)"
info "Target triple: $TRIPLE"

# ── Resolve Python (venv preferred) ──────────────────────────────────────────
if [[ -f "$BACKEND_DIR/.venv/bin/python3" ]]; then
    PY="$BACKEND_DIR/.venv/bin/python3"
elif [[ -f "$BACKEND_DIR/.venv/Scripts/python.exe" ]]; then
    PY="$BACKEND_DIR/.venv/Scripts/python.exe"
elif command -v python3 &>/dev/null; then
    PY="python3"
elif command -v python &>/dev/null; then
    PY="python"
else
    die "Python not found. Run scripts/setup.sh first."
fi
info "Python: $PY"

# ── Ensure build deps ─────────────────────────────────────────────────────────
info "Checking PyInstaller…"
if ! "$PY" -c "import PyInstaller" 2>/dev/null; then
    warn "PyInstaller not found — installing…"
    "$PY" -m pip install --quiet -r "$BACKEND_DIR/requirements-build.txt"
fi

# ── Run PyInstaller ───────────────────────────────────────────────────────────
info "Running PyInstaller (this takes 2–5 minutes on first run)…"
cd "$BACKEND_DIR"
"$PY" -m PyInstaller prankcam-backend.spec \
    --noconfirm \
    --clean \
    --log-level WARN

if [[ ! -d "$DIST_DIR" ]]; then
    die "PyInstaller failed — dist/prankcam-backend/ not created."
fi
success "PyInstaller bundle created at $DIST_DIR"

# ── Package into a zip the Tauri sidecar can unpack, OR copy the exe directly ─
# Tauri sidecar mode: the ENTIRE onedir folder must be shipped.
# We zip it and add an unpacker stub, but the simplest production approach is
# to rename the main executable and place it in src-tauri/binaries/.
# The rest of the dist folder goes into bundle.resources.

EXE_NAME="prankcam-backend"
[[ "$TRIPLE" == *windows* ]] && EXE_NAME="prankcam-backend.exe"

SRC_EXE="$DIST_DIR/$EXE_NAME"
if [[ ! -f "$SRC_EXE" ]]; then
    die "Expected executable not found: $SRC_EXE"
fi

# Target filename Tauri expects: name-triple[.exe]
if [[ "$TRIPLE" == *windows* ]]; then
    DEST="$BINARIES_DIR/prankcam-backend-${TRIPLE}.exe"
else
    DEST="$BINARIES_DIR/prankcam-backend-${TRIPLE}"
fi

cp "$SRC_EXE" "$DEST"
chmod +x "$DEST"
success "Sidecar binary: $DEST  ($(du -sh "$DEST" | cut -f1))"

# ── Copy onedir libs into resources/backend-libs/<triple>/ ───────────────────
# This is how we ship the rest of the PyInstaller onedir to end users.
LIBS_DEST="$ROOT_DIR/src-tauri/resources/backend-libs/$TRIPLE"
mkdir -p "$LIBS_DEST"
rsync -a --delete "$DIST_DIR/" "$LIBS_DEST/"
# Remove the main exe from resources (it's already in binaries/)
rm -f "$LIBS_DEST/$EXE_NAME"
success "Backend libs copied to resources/backend-libs/$TRIPLE/ ($(du -sh "$LIBS_DEST" | cut -f1))"

info ""
info "Backend build complete. Now run:  npm run tauri:build"
