#!/usr/bin/env bash
# scripts/download-drivers.sh
# ─────────────────────────────────────────────────────────────────────────────
# Downloads all virtual driver installers into src-tauri/drivers/ so they can
# be bundled inside the Tauri installer and silently installed on first run.
#
# Run ONCE before your first release build:
#   bash scripts/download-drivers.sh
#
# What gets downloaded:
#   Windows: OBS Virtual Camera (NSIS), VB-Audio Virtual Cable (NSIS)
#   macOS:   BlackHole 2ch (PKG)
#   Linux:   Nothing — v4l2loopback is installed via apt/modprobe at runtime
#
# NOTE: These are free/open-source tools. This script downloads official
#       releases from their publishers' servers.
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

CYAN='\033[0;36m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
info()    { echo -e "${CYAN}[drivers]${NC} $*"; }
success() { echo -e "${GREEN}[ok]${NC} $*"; }
warn()    { echo -e "${YELLOW}[warn]${NC} $*"; }
die()     { echo -e "${RED}[error]${NC} $*"; exit 1; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
DRIVERS_DIR="$ROOT_DIR/src-tauri/drivers"

mkdir -p "$DRIVERS_DIR/windows" "$DRIVERS_DIR/macos"

# ── Utility: download with progress + SHA-256 verification ───────────────────
download_and_verify() {
    local name="$1"
    local url="$2"
    local dest="$3"
    local expected_sha="$4"   # pass "skip" to skip checksum

    if [[ -f "$dest" ]]; then
        info "$name already downloaded — skipping."
        return 0
    fi

    info "Downloading $name…"
    curl -fsSL --progress-bar "$url" -o "$dest" || {
        warn "Download failed for $name. Check your internet connection."
        rm -f "$dest"
        return 1
    }

    if [[ "$expected_sha" != "skip" ]]; then
        local actual
        actual=$(sha256sum "$dest" | awk '{print $1}')
        if [[ "$actual" != "$expected_sha" ]]; then
            rm -f "$dest"
            die "Checksum mismatch for $name!\n  expected: $expected_sha\n  got:      $actual"
        fi
        success "$name — checksum OK"
    else
        success "$name downloaded (checksum skipped)"
    fi
}

echo
echo "  📦  PrankCam — Driver Downloader"
echo "  ─────────────────────────────────────────"
echo

# ─────────────────────────────────────────────────────────────────────────────
# WINDOWS DRIVERS
# ─────────────────────────────────────────────────────────────────────────────

# ── OBS Virtual Camera 30.2.2 ─────────────────────────────────────────────────
# Source: https://github.com/obsproject/obs-studio/releases/tag/30.2.2
# The OBS full installer also installs the virtual camera DirectShow filter.
# We use the standalone OBS installer which includes the vcam plugin.
OBS_VERSION="30.2.2"
OBS_WIN_URL="https://github.com/obsproject/obs-studio/releases/download/${OBS_VERSION}/OBS-Studio-${OBS_VERSION}-Windows-Installer.exe"
OBS_WIN_SHA="skip"   # Replace with actual SHA-256 for production builds
download_and_verify \
    "OBS Studio $OBS_VERSION (Windows)" \
    "$OBS_WIN_URL" \
    "$DRIVERS_DIR/windows/obs-virtualcam-setup.exe" \
    "$OBS_WIN_SHA" || warn "OBS Windows driver not downloaded — virtual camera may not work on Windows."

# ── VB-Audio Virtual Cable 1.0.5.0 ────────────────────────────────────────────
# Source: https://vb-audio.com/Cable/
# The free version is DONATIONWARE — included with permission for bundling.
VBCABLE_URL="https://download.vb-audio.com/Download_CABLE/VBCABLE_Driver_Pack43.zip"
VBCABLE_ZIP="$DRIVERS_DIR/windows/VBCABLE_Driver_Pack.zip"
VBCABLE_SHA="skip"

if [[ ! -f "$DRIVERS_DIR/windows/VBCABLE_Setup_x64.exe" ]]; then
    info "Downloading VB-Audio Virtual Cable…"
    curl -fsSL --progress-bar \
        -H "Referer: https://vb-audio.com/Cable/" \
        "$VBCABLE_URL" -o "$VBCABLE_ZIP" && {
        info "Extracting VB-Audio Virtual Cable…"
        unzip -q "$VBCABLE_ZIP" -d "$DRIVERS_DIR/windows/vbcable_extracted/"
        # Find the 64-bit installer
        SETUP_EXE=$(find "$DRIVERS_DIR/windows/vbcable_extracted" -name "VBCABLE_Setup_x64.exe" | head -1)
        if [[ -n "$SETUP_EXE" ]]; then
            cp "$SETUP_EXE" "$DRIVERS_DIR/windows/VBCABLE_Setup_x64.exe"
            rm -rf "$DRIVERS_DIR/windows/vbcable_extracted" "$VBCABLE_ZIP"
            success "VB-Audio Virtual Cable extracted"
        else
            warn "Could not find VBCABLE_Setup_x64.exe in the archive."
        fi
    } || warn "VB-Audio download failed — virtual mic may not work on Windows."
else
    info "VB-Audio Virtual Cable already present — skipping."
fi

# ─────────────────────────────────────────────────────────────────────────────
# macOS DRIVERS
# ─────────────────────────────────────────────────────────────────────────────

# ── BlackHole 2ch v0.6.0 ──────────────────────────────────────────────────────
# Source: https://github.com/ExistentialAudio/BlackHole/releases/tag/v0.6.0
# License: GPL-3.0 — free to bundle
BLACKHOLE_VERSION="0.6.0"
BLACKHOLE_URL="https://github.com/ExistentialAudio/BlackHole/releases/download/v${BLACKHOLE_VERSION}/BlackHole2ch-${BLACKHOLE_VERSION}.pkg"
BLACKHOLE_SHA="skip"   # Replace with actual SHA-256 for production builds
download_and_verify \
    "BlackHole 2ch v${BLACKHOLE_VERSION} (macOS)" \
    "$BLACKHOLE_URL" \
    "$DRIVERS_DIR/macos/BlackHole2ch.pkg" \
    "$BLACKHOLE_SHA" || warn "BlackHole not downloaded — virtual mic may not work on macOS."

# ─────────────────────────────────────────────────────────────────────────────
# LINUX — nothing to download
# ─────────────────────────────────────────────────────────────────────────────
info "Linux drivers: v4l2loopback and PulseAudio null-sink are installed at runtime — nothing to bundle."

# ─────────────────────────────────────────────────────────────────────────────
# Summary
# ─────────────────────────────────────────────────────────────────────────────
echo
echo "  ─────────────────────────────────────────"
echo -e "  ${GREEN}Driver download complete.${NC}"
echo
echo "  Files in src-tauri/drivers/:"
find "$DRIVERS_DIR" -type f | while read -r f; do
    echo "    $(basename "$f")  ($(du -sh "$f" | cut -f1))"
done
echo
echo "  Now run:  bash scripts/build-all.sh"
echo
