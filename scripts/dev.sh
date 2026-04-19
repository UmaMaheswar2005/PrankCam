#!/usr/bin/env bash
# scripts/dev.sh — Start backend + Tauri dev window concurrently
# Usage: bash scripts/dev.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
BACKEND_DIR="$ROOT_DIR/backend"

CYAN='\033[0;36m'; GREEN='\033[0;32m'; NC='\033[0m'

# Resolve Python from venv or system
if [[ -f "$BACKEND_DIR/.venv/bin/python3" ]]; then
  PY="$BACKEND_DIR/.venv/bin/python3"
elif [[ -f "$BACKEND_DIR/.venv/bin/python" ]]; then
  PY="$BACKEND_DIR/.venv/bin/python"
else
  PY="python3"
fi

echo -e "${CYAN}[dev]${NC} Python: $PY"
echo -e "${CYAN}[dev]${NC} Starting backend + Tauri…"
echo ""

# Kill child processes on CTRL+C
cleanup() {
  echo ""
  echo -e "${CYAN}[dev]${NC} Shutting down…"
  kill "$BACKEND_PID" "$TAURI_PID" 2>/dev/null || true
  wait "$BACKEND_PID" "$TAURI_PID" 2>/dev/null || true
  echo -e "${GREEN}[dev]${NC} Done."
}
trap cleanup INT TERM

# Start backend
cd "$BACKEND_DIR"
"$PY" main.py &
BACKEND_PID=$!
echo -e "${CYAN}[dev]${NC} Backend PID $BACKEND_PID"

# Brief pause so uvicorn starts before Tauri tries to ping it
sleep 1.5

# Start Tauri dev
cd "$ROOT_DIR"
npm run tauri:dev &
TAURI_PID=$!
echo -e "${CYAN}[dev]${NC} Tauri PID $TAURI_PID"

wait "$BACKEND_PID" "$TAURI_PID"
