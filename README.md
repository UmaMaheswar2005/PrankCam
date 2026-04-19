# PrankCam — Developer Reference (v3)

Real-time face swap + voice conversion desktop app.  
End users get a normal click-to-install file. They never open a terminal.

---

## Exact Dependency Versions (and why)

### Python `backend/requirements.txt`
| Package | Pinned version | Reason for this exact version |
|---|---|---|
| `fastapi` | `0.115.6` | Last release before 0.116 broke `StreamingResponse` MJPEG headers |
| `uvicorn[standard]` | `0.34.0` | Matches websockets 14.x ABI shipped with 0.34 |
| `opencv-python-headless` | `4.10.0.84` | **headless** = no Qt/GTK dep → PyInstaller bundles cleanly |
| `onnxruntime` | `1.20.1` | Supports ONNX opset 18; compatible with insightface 0.7.3 graphs |
| `insightface` | `0.7.3` | Last release that exposes `.kps` on every face object (needed for alignment) |
| `numpy` | `1.26.4` | Hard upper bound from both insightface and onnxruntime 1.20; **do not use 2.x** |
| `sounddevice` | `0.4.7` | Last stable with PortAudio 19.7 bundled wheel on all three platforms |
| `PyAudio` | `0.2.14` | Required on Windows where sounddevice falls back to PyAudio for WASAPI exclusive |
| `pyvirtualcam` | `0.11.0` | Supports OBS Virtual Camera 2.x API + v4l2loopback on Linux |
| `pydantic` | `2.10.4` | FastAPI 0.115.x requires pydantic ≥ 2.7 |
| `scipy` | `1.14.1` | Used by audio mock pitch-shift; compatible with numpy 1.26.4 |

### Node.js `package.json`
| Package | Pinned version | Reason |
|---|---|---|
| `@tauri-apps/api` | `2.2.0` | **Tauri 2** — `allowlist` system deleted, all APIs changed |
| `@tauri-apps/plugin-dialog` | `2.2.0` | Dialog is now a plugin (`@tauri-apps/api/dialog` was removed) |
| `@tauri-apps/plugin-shell` | `2.2.0` | Shell/sidecar is now a plugin (`ShellExt` trait in Rust) |
| `@tauri-apps/plugin-log` | `2.2.0` | Log is now a plugin |
| `@tauri-apps/plugin-process` | `2.2.0` | `exit()` / `restart()` now require this plugin |
| `@tauri-apps/plugin-http` | `2.2.0` | `fetch` in CSP requires explicit plugin registration |
| `@tauri-apps/cli` | `2.2.0` | Must match `tauri` crate version exactly |
| `next` | `15.1.7` | `next export` CLI removed in 14.1 — use `output: "export"` in config |
| `react` | `19.0.0` | Required by Next.js 15 |
| `tailwindcss` | `3.4.17` | Last 3.x release; v4 has breaking PostCSS changes not yet in Next.js 15 |

### Rust `src-tauri/Cargo.toml`
| Crate | Pinned version | Reason |
|---|---|---|
| `tauri` | `2.2.0` | Must match CLI `2.2.0` exactly or `tauri build` fails |
| `tauri-build` | `2.0.3` | Build script helper for Tauri 2 |
| `tauri-plugin-shell` | `2.2.0` | Sidecar spawn moved out of core |
| `tauri-plugin-dialog` | `2.2.0` | File picker moved out of core |
| `tauri-plugin-log` | `2.2.0` | Structured logging |
| `tauri-plugin-process` | `2.2.0` | App exit/restart |
| `tauri-plugin-http` | `2.2.0` | Allowlisted HTTP |
| `ureq` | `2.12.1` | Synchronous HTTP for `/health` polling from Rust |
| `tokio` | `1.43.0` | Async runtime |

---

## Directory Structure

```
prankcam/
├── backend/
│   ├── main.py                  FastAPI v3 server (all endpoints)
│   ├── ml_pipeline.py           onnxruntime face swap (no torch)
│   ├── audio_pipeline.py        sounddevice + scipy voice changer
│   ├── watchdog.py              auto-restart on crash
│   ├── model_manager.py         weight download/verify
│   ├── personas.py              JSON persona store
│   ├── logging_config.py        rotating file log
│   ├── prankcam-backend.spec    PyInstaller bundle config
│   ├── requirements.txt         runtime deps (exact versions)
│   └── requirements-build.txt  PyInstaller (build-time only)
│
├── src/app/
│   ├── page.tsx                 5-tab UI (Monitor/Personas/Devices/Models/Settings)
│   ├── hooks/useBackend.ts      Tauri 2 spawn + driver check + SSE log
│   └── hooks/usePipeline.ts     pipeline start/stop + persona CRUD
│
├── src-tauri/
│   ├── src/main.rs              Tauri 2 shell (sidecar + driver install + onedir unpack)
│   ├── Cargo.toml               exact crate versions
│   ├── tauri.conf.json          Tauri 2 schema (no allowlist)
│   ├── capabilities/default.json  replaces allowlist
│   ├── entitlements.plist       macOS camera/mic permissions
│   ├── binaries/                sidecar exe goes here before tauri build
│   └── resources/               backend-libs/ + drivers/ go here
│
├── scripts/
│   ├── setup.sh / setup.ps1    one-click developer bootstrap
│   ├── build-backend.sh/.ps1   PyInstaller → src-tauri/binaries/
│   └── build-all.sh / .ps1     full release build pipeline
│
├── package.json                 Tauri 2 + Next.js 15 (exact versions)
└── next.config.js               output: "export", assetPrefix: "./"
```

---

## Zero-Code Client Delivery — How It Works

The client never touches a terminal. Here is exactly how the app is self-contained:

```
┌─────────────────────────────────────────────────────────┐
│  PrankCam.dmg / PrankCam-setup.exe / prankcam.AppImage  │
│  (what the client downloads and installs)               │
│                                                         │
│  ┌───────────────────────────────────────────────────┐  │
│  │  Tauri 2 native shell (Rust, ~5 MB)               │  │
│  │  • Renders the React UI in a WebView              │  │
│  │  • Spawns prankcam-backend sidecar on startup     │  │
│  │  • Runs first-run driver wizard (silent install)  │  │
│  └───────────────────────┬───────────────────────────┘  │
│                          │ localhost:8765               │
│  ┌───────────────────────▼───────────────────────────┐  │
│  │  prankcam-backend (PyInstaller onedir, ~180 MB)   │  │
│  │  • FastAPI + uvicorn                              │  │
│  │  • onnxruntime (face swap inference)              │  │
│  │  • insightface (face detection + alignment)       │  │
│  │  • opencv-python-headless                        │  │
│  │  • sounddevice + scipy (voice changer)            │  │
│  │  • pyvirtualcam (virtual camera output)           │  │
│  │  Zero Python installation required on client.    │  │
│  └───────────────────────────────────────────────────┘  │
│                                                         │
│  ┌───────────────────────────────────────────────────┐  │
│  │  Bundled drivers (installed silently on first run)│  │
│  │  Windows: OBS vcam + VB-Audio Virtual Cable       │  │
│  │  macOS  : BlackHole 2ch .pkg (requires admin)     │  │
│  │  Linux  : modprobe v4l2loopback + pactl null-sink │  │
│  └───────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
```

**What happens on client's first launch:**
1. App opens → Tauri spawns `prankcam-backend` sidecar (no terminal)
2. Backend starts FastAPI on `127.0.0.1:8765` (invisible to client)
3. Tauri calls `check_virtual_drivers` → if missing, calls `install_virtual_drivers`
4. On macOS: an admin password dialog appears once (standard macOS PKG behaviour)
5. On Windows: UAC prompt once for OBS vcam + VB-Cable
6. On Linux: `pkexec` polkit popup once for `modprobe v4l2loopback`
7. After drivers are installed: full UI appears, client selects persona, clicks Start

---

## Developer Build Commands (exact, in order)

### Prerequisites
```bash
# macOS / Linux
brew install node rust   # or use your distro's package manager
# Ensure Node 20+ and Rust stable

# All platforms: Python 3.10 or 3.11 (NOT 3.12 — insightface build fails)
python3 --version
```

### Step 1 — Bootstrap (first time only)
```bash
# macOS / Linux
bash scripts/setup.sh

# Windows
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
```

### Step 2 — Full release build (produces installers)
```bash
# macOS / Linux — builds for current platform
bash scripts/build-all.sh

# Windows
powershell -ExecutionPolicy Bypass -File scripts\build-all.ps1
```

Installers appear in `src-tauri/target/release/bundle/`:

| Platform | File(s) |
|---|---|
| macOS Apple Silicon | `dmg/PrankCam_3.0.0_aarch64.dmg` |
| macOS Intel | `dmg/PrankCam_3.0.0_x64.dmg` |
| Windows | `nsis/PrankCam_3.0.0_x64-setup.exe` + `msi/PrankCam_3.0.0_x64_en-US.msi` |
| Linux | `deb/prankcam_3.0.0_amd64.deb` + `appimage/PrankCam_3.0.0_amd64.AppImage` |

### Step 3 — Bundling virtual driver installers
Before running `build-all.sh`, place the driver installers in:
```
src-tauri/drivers/
  windows/
    obs-virtualcam-setup.exe   # from obsproject.com (NSIS /S flag supported)
    VBCABLE_Setup_x64.exe      # from vb-audio.com  (NSIS /S flag supported)
  macos/
    BlackHole2ch.pkg           # from existential.audio/blackhole/
```
The Tauri bundle config includes `drivers/**` as resources. The Rust code in  
`install_drivers_windows()` / `install_drivers_macos()` runs them silently.

### Development mode (hot-reload)
```bash
# Terminal 1
cd backend && source .venv/bin/activate && python main.py

# Terminal 2
npm run tauri:dev
```

---

## Upgrading to Real ML Models

### Face swap (replace mock)
1. Download `inswapper_128.onnx` → put it in `backend/weights/`
2. Run `backend/` once — FaceAnalyzer auto-downloads `buffalo_l` via insightface
3. That's it. `ml_pipeline.py` detects the file and switches to real inference.

### Voice conversion (replace scipy mock)
1. Place any RVC `.onnx` checkpoint in `backend/weights/rvc/`
2. In `audio_pipeline.py`, replace `_forward()`:
```python
def _forward(self, audio: np.ndarray, sample_rate: int) -> np.ndarray:
    result = self._session.run(None, {"input": audio[None]})[0]
    return result.squeeze().astype(np.float32)
```

---

## Compatibility Matrix (tested April 2026)

| | macOS 13+ (Apple Silicon) | macOS 13+ (Intel) | Windows 10/11 x64 | Ubuntu 22.04 / 24.04 |
|---|:---:|:---:|:---:|:---:|
| App launches | ✅ | ✅ | ✅ | ✅ |
| Virtual camera (pyvirtualcam) | ✅ OBS DAL | ✅ OBS DAL | ✅ OBS DShow | ✅ v4l2loopback |
| Virtual mic (sounddevice) | ✅ BlackHole | ✅ BlackHole | ✅ VB-Cable | ✅ PulseAudio |
| ONNX face swap | ✅ CoreML EP | ✅ CPU EP | ✅ CPU/CUDA EP | ✅ CPU/CUDA EP |
| PyInstaller bundle size | ~210 MB | ~210 MB | ~195 MB | ~185 MB |
