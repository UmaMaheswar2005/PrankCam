# Changelog

## [3.0.0] — 2026-04-17

### Breaking Changes
- **Tauri 1 → Tauri 2**: Complete rewrite of Rust shell. `allowlist` removed; replaced by `capabilities/`. All plugin imports updated.
- **PyTorch removed**: Inference now uses `onnxruntime==1.20.1` (50× smaller binary). No CUDA required for CPU inference.
- **`next export` removed**: Use `output: "export"` in `next.config.js` (Next.js 14.1+ change).
- **`@tauri-apps/api/dialog` removed**: Now `@tauri-apps/plugin-dialog`.

### New Features
- **First-run setup wizard**: Full-screen overlay guides non-technical users through driver installation.
- **Automatic virtual driver install**: OBS Virtual Camera (Windows/macOS), VB-Audio Virtual Cable (Windows), BlackHole (macOS), v4l2loopback (Linux) installed silently on first launch.
- **PyInstaller sidecar**: Python backend is fully self-contained — users never install Python.
- **CI/CD pipeline**: GitHub Actions builds signed installers for all platforms on every git tag.
- **ONNX voice model support**: `.onnx` RVC models work natively; `.pth` → `.onnx` export helper included.
- **Model tab**: Download `inswapper_128.onnx` directly from within the app.

### Fixed
- `insightface` now uses its own `INSIGHTFACE_HOME` env var to write models inside the app bundle, not `~/.insightface`.
- `pyvirtualcam` virtual camera context manager properly closed on VideoProcessor stop.
- Audio pipeline `_forward()` properly chains real ONNX session when available, falls back to scipy mock.

## [2.0.0] — 2025-12-01

- Tauri 1.6 + Next.js 14 + PyTorch 2.3 (initial release)
