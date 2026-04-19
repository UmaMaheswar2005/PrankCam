# prankcam-backend.spec
# ─────────────────────────────────────────────────────────────────────────────
# Run from inside backend/:
#   pyinstaller prankcam-backend.spec
#
# Output:
#   dist/prankcam-backend/   ← onedir bundle (fast startup, Tauri sidecar mode)
#
# The build-backend.sh script copies dist/prankcam-backend/prankcam-backend
# into src-tauri/binaries/ and the rest of the folder into
# src-tauri/resources/backend-libs/<triple>/ for Tauri to bundle.
# ─────────────────────────────────────────────────────────────────────────────

import sys
import os
from pathlib import Path
from PyInstaller.utils.hooks import collect_all

BACKEND_DIR = Path(SPECPATH)

# ── Collect data/binaries for packages PyInstaller cannot auto-discover ───────
datas_if,  binaries_if,  hidden_if  = collect_all("insightface")
datas_ort, binaries_ort, hidden_ort = collect_all("onnxruntime")
datas_cv2, binaries_cv2, hidden_cv2 = collect_all("cv2")
datas_pvc, binaries_pvc, hidden_pvc = collect_all("pyvirtualcam")

a = Analysis(
    [str(BACKEND_DIR / "main.py")],
    pathex=[str(BACKEND_DIR)],
    binaries=(
        binaries_if +
        binaries_ort +
        binaries_cv2 +
        binaries_pvc
    ),
    datas=(
        datas_if +
        datas_ort +
        datas_cv2 +
        datas_pvc
        # Uncomment to pre-bundle weights (large — only if distributing with models):
        # + [(str(BACKEND_DIR / "weights"), "weights")]
    ),
    hiddenimports=(
        hidden_if +
        hidden_ort +
        hidden_cv2 +
        hidden_pvc +
        [
            # ── Local PrankCam modules ─────────────────────────────────────────
            "content_packs",
            "capture_face",
            "watchdog",
            "personas",
            "model_manager",
            "logging_config",
            "audio_pipeline",
            "ml_pipeline",

            # ── uvicorn internals ──────────────────────────────────────────────
            "uvicorn.logging",
            "uvicorn.loops",
            "uvicorn.loops.auto",
            "uvicorn.protocols",
            "uvicorn.protocols.http",
            "uvicorn.protocols.http.auto",
            "uvicorn.protocols.http.h11_impl",
            "uvicorn.protocols.http.httptools_impl",
            "uvicorn.protocols.websockets",
            "uvicorn.protocols.websockets.auto",
            "uvicorn.protocols.websockets.websockets_impl",
            "uvicorn.lifespan",
            "uvicorn.lifespan.on",
            "uvicorn.lifespan.off",

            # ── FastAPI / Starlette internals ──────────────────────────────────
            "starlette.routing",
            "starlette.middleware",
            "starlette.responses",
            "starlette.background",
            "fastapi.routing",
            "fastapi.middleware.cors",

            # ── Pydantic v2 ────────────────────────────────────────────────────
            "pydantic.v1",
            "pydantic_core",

            # ── Audio ──────────────────────────────────────────────────────────
            "sounddevice",
            "_sounddevice_data",
            "scipy.signal",
            "scipy.fft",

            # ── Async helpers ──────────────────────────────────────────────────
            "aiofiles.os",
            "aiofiles.threadpool",
            "httpx._transports.default",
            "httpx._transports.asgi",
        ]
    ),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # torch is NOT used — onnxruntime handles all inference
        "torch", "torchvision", "torchaudio",
        # Dev / doc packages
        "pytest", "sphinx", "IPython", "matplotlib",
        "tkinter", "PyQt5", "PyQt6", "wx",
    ],
    noarchive=False,
    optimize=1,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="prankcam-backend",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,      # No terminal window on Windows
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="prankcam-backend",
)
