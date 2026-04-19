// src-tauri/src/main.rs — PrankCam Tauri 2 Shell
//
// Tauri 2 breaking changes addressed here vs the old Tauri 1 code:
//   • Plugin imports:  tauri_plugin_shell::ShellExt (not built-in)
//   • Sidecar API:     app.shell().sidecar() (not Command::new_sidecar)
//   • Manager trait:   still needed for app.state() / app.path()
//   • Permissions live in capabilities/default.json (Tauri 2 model)
//   • No ureq as HTTP: kept for health-check only (compile-time simple)
//   • libc SIGTERM:    unchanged (unix only)
//   • setup() fn:      receives &mut App, auto-spawn sidecar there

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::sync::{Arc, Mutex};
use std::time::Duration;
use tauri::{AppHandle, Manager, State};
use tauri_plugin_shell::ShellExt;
use tauri_plugin_shell::process::CommandChild;

// ── Shared state: the running Python sidecar child ───────────────────────────

struct BackendChild(Arc<Mutex<Option<CommandChild>>>);

// ── Tauri commands ────────────────────────────────────────────────────────────

/// Spawn the Python backend sidecar.
/// The binary name must match the key in tauri.conf.json `bundle.externalBin`.
#[tauri::command]
async fn spawn_python_backend(
    app: AppHandle,
    state: State<'_, BackendChild>,
) -> Result<String, String> {
    let mut guard = state.0.lock().map_err(|e| e.to_string())?;

    // Already alive?
    if guard.is_some() {
        return Ok("already_running".to_owned());
    }

    let sidecar = app
        .shell()
        .sidecar("prankcam-backend")
        .map_err(|e| format!("sidecar not found: {e}"))?;

    // Tauri 2: spawn() returns (OneshotReceiver, CommandChild)
    let (_rx, child) = sidecar
        .spawn()
        .map_err(|e| format!("failed to spawn backend: {e}"))?;

    *guard = Some(child);
    log::info!("Python backend sidecar spawned");
    Ok("spawned".to_owned())
}

/// Kill the sidecar with SIGTERM (Unix) or TerminateProcess (Windows).
#[tauri::command]
async fn kill_python_backend(state: State<'_, BackendChild>) -> Result<String, String> {
    let mut guard = state.0.lock().map_err(|e| e.to_string())?;

    if let Some(child) = guard.take() {
        // Tauri 2 CommandChild has .kill() directly
        child
            .kill()
            .map_err(|e| format!("kill failed: {e}"))?;
        log::info!("Python backend sidecar killed");
    }
    Ok("killed".to_owned())
}

/// Poll /health — returns true when the backend is answering.
#[tauri::command]
async fn check_backend_ready() -> Result<bool, String> {
    let result = tokio::task::spawn_blocking(|| {
        ureq::get("http://127.0.0.1:8765/health")
            .timeout(Duration::from_millis(600))
            .call()
            .map(|r| r.status() == 200)
            .unwrap_or(false)
    })
    .await
    .map_err(|e| e.to_string())?;

    Ok(result)
}

/// Ask the backend to stop its pipeline before window close.
#[tauri::command]
async fn request_pipeline_stop() -> Result<(), String> {
    tokio::task::spawn_blocking(|| {
        let _ = ureq::post("http://127.0.0.1:8765/stop")
            .timeout(Duration::from_millis(500))
            .call();
    })
    .await
    .map_err(|e| e.to_string())?;
    Ok(())
}

/// Return Python version info (reads from the bundled sidecar's --version flag).
#[tauri::command]
async fn get_python_info(app: AppHandle) -> Result<serde_json::Value, String> {
    // Read the resource path so we know where the sidecar lives
    let resource_dir = app
        .path()
        .resource_dir()
        .map(|p| p.to_string_lossy().into_owned())
        .unwrap_or_else(|_| "unknown".to_owned());

    Ok(serde_json::json!({
        "mode":        "pyinstaller-sidecar",
        "resource_dir": resource_dir,
        "using_venv":  false,
        "version":     "embedded (PyInstaller)"
    }))
}

/// Install platform virtual drivers on first run.
/// Returns "ok" when drivers are already present or installation succeeded.
/// The frontend calls this during its setup wizard.
#[tauri::command]
async fn install_virtual_drivers(app: AppHandle) -> Result<String, String> {
    #[cfg(target_os = "windows")]
    {
        install_drivers_windows(&app).await?;
    }
    #[cfg(target_os = "macos")]
    {
        install_drivers_macos(&app).await?;
    }
    #[cfg(target_os = "linux")]
    {
        install_drivers_linux().await?;
    }
    Ok("ok".to_owned())
}

/// Check whether virtual drivers are installed without installing them.
#[tauri::command]
async fn check_virtual_drivers() -> Result<serde_json::Value, String> {
    let cam_ok;
    let mic_ok;

    #[cfg(target_os = "windows")]
    {
        cam_ok = check_obs_vcam_windows();
        mic_ok = check_vbcable_windows();
    }
    #[cfg(target_os = "macos")]
    {
        cam_ok = check_obs_vcam_macos();
        mic_ok = check_blackhole_macos();
    }
    #[cfg(target_os = "linux")]
    {
        cam_ok = check_v4l2loopback_linux();
        mic_ok = check_pulseaudio_linux();
    }
    #[cfg(not(any(target_os = "windows", target_os = "macos", target_os = "linux")))]
    {
        cam_ok = false;
        mic_ok = false;
    }

    Ok(serde_json::json!({
        "virtual_camera": cam_ok,
        "virtual_mic":    mic_ok,
    }))
}

// ── Driver installation helpers ───────────────────────────────────────────────

#[cfg(target_os = "windows")]
fn check_obs_vcam_windows() -> bool {
    // OBS Virtual Camera registers a DShow filter
    use std::process::Command;
    Command::new("reg")
        .args(["query", r"HKLM\SOFTWARE\Classes\CLSID\{A3FCE0F5-3493-419F-958A-ABA1D1C56AB8}"])
        .output()
        .map(|o| o.status.success())
        .unwrap_or(false)
}

#[cfg(target_os = "windows")]
fn check_vbcable_windows() -> bool {
    use std::process::Command;
    // VB-Cable installs "CABLE Input" as a MMDevice
    let out = Command::new("powershell")
        .args(["-Command", "Get-AudioDevice -List | Where-Object {$_.Name -like '*CABLE*'}"])
        .output();
    match out {
        Ok(o) => !o.stdout.is_empty(),
        Err(_) => {
            // Fallback: check registry
            Command::new("reg")
                .args(["query", r"HKLM\SYSTEM\CurrentControlSet\Services\VBAudioVACWDM"])
                .output()
                .map(|o| o.status.success())
                .unwrap_or(false)
        }
    }
}

#[cfg(target_os = "windows")]
async fn install_drivers_windows(app: &AppHandle) -> Result<(), String> {
    use std::path::PathBuf;

    let res_dir = app.path().resource_dir().map_err(|e| e.to_string())?;
    let drivers_dir = res_dir.join("drivers").join("windows");

    // ── OBS Virtual Camera ────────────────────────────────────────────────────
    if !check_obs_vcam_windows() {
        let installer = drivers_dir.join("obs-virtualcam-setup.exe");
        if installer.exists() {
            log::info!("Installing OBS Virtual Camera…");
            tokio::process::Command::new(&installer)
                .args(["/S"])  // silent NSIS installer
                .status()
                .await
                .map_err(|e| format!("OBS vcam install failed: {e}"))?;
        } else {
            log::warn!("OBS vcam installer not bundled — skipping.");
        }
    }

    // ── VB-Audio Virtual Cable ────────────────────────────────────────────────
    if !check_vbcable_windows() {
        let installer = drivers_dir.join("VBCABLE_Setup_x64.exe");
        if installer.exists() {
            log::info!("Installing VB-Audio Virtual Cable…");
            tokio::process::Command::new(&installer)
                .args(["/S"])
                .status()
                .await
                .map_err(|e| format!("VB-Cable install failed: {e}"))?;
        } else {
            log::warn!("VB-Cable installer not bundled — skipping.");
        }
    }

    Ok(())
}

#[cfg(target_os = "macos")]
fn check_obs_vcam_macos() -> bool {
    // OBS on macOS installs a DAL plugin
    std::path::Path::new(
        "/Library/CoreMediaIO/Plug-Ins/DAL/obs-mac-virtualcam.plugin"
    )
    .exists()
    || std::path::Path::new(
        "/Library/CoreMediaIO/Plug-Ins/DAL/com.obsproject.obs-studio.plugin"
    )
    .exists()
}

#[cfg(target_os = "macos")]
fn check_blackhole_macos() -> bool {
    std::path::Path::new(
        "/Library/Audio/Plug-Ins/HAL/BlackHole2ch.driver"
    )
    .exists()
}

#[cfg(target_os = "macos")]
async fn install_drivers_macos(app: &AppHandle) -> Result<(), String> {
    let res_dir = app.path().resource_dir().map_err(|e| e.to_string())?;
    let drivers_dir = res_dir.join("drivers").join("macos");

    // ── BlackHole virtual audio ───────────────────────────────────────────────
    if !check_blackhole_macos() {
        let pkg = drivers_dir.join("BlackHole2ch.pkg");
        if pkg.exists() {
            log::info!("Installing BlackHole virtual audio…");
            // installer -pkg requires sudo; request via osascript
            tokio::process::Command::new("osascript")
                .args([
                    "-e",
                    &format!(
                        r#"do shell script "installer -pkg '{}' -target /" with administrator privileges"#,
                        pkg.display()
                    ),
                ])
                .status()
                .await
                .map_err(|e| format!("BlackHole install failed: {e}"))?;
        }
    }

    // ── OBS Virtual Camera (optional — user may install OBS manually) ─────────
    if !check_obs_vcam_macos() {
        log::warn!(
            "OBS Virtual Camera not found. \
             The app will attempt to use system camera directly."
        );
    }

    Ok(())
}

#[cfg(target_os = "linux")]
fn check_v4l2loopback_linux() -> bool {
    std::process::Command::new("lsmod")
        .output()
        .map(|o| String::from_utf8_lossy(&o.stdout).contains("v4l2loopback"))
        .unwrap_or(false)
}

#[cfg(target_os = "linux")]
fn check_pulseaudio_linux() -> bool {
    // Check for null sink named prankcam_virtual
    std::process::Command::new("pactl")
        .args(["list", "sinks", "short"])
        .output()
        .map(|o| String::from_utf8_lossy(&o.stdout).contains("prankcam_virtual"))
        .unwrap_or(false)
}

#[cfg(target_os = "linux")]
async fn install_drivers_linux() -> Result<(), String> {
    // ── v4l2loopback ──────────────────────────────────────────────────────────
    if !check_v4l2loopback_linux() {
        log::info!("Loading v4l2loopback…");
        let status = tokio::process::Command::new("pkexec")
            .args([
                "modprobe", "v4l2loopback",
                "devices=1",
                "video_nr=10",
                "card_label=PrankCam",
                "exclusive_caps=1",
            ])
            .status()
            .await
            .map_err(|e| format!("v4l2loopback: {e}"))?;

        if !status.success() {
            return Err(
                "v4l2loopback failed to load. Install it with: \
                 sudo apt install v4l2loopback-dkms"
                    .to_owned(),
            );
        }
    }

    // ── PulseAudio null sink ──────────────────────────────────────────────────
    if !check_pulseaudio_linux() {
        log::info!("Creating PulseAudio virtual mic sink…");
        let _ = tokio::process::Command::new("pactl")
            .args([
                "load-module",
                "module-null-sink",
                "sink_name=prankcam_virtual",
                "sink_properties=device.description=PrankCam-VirtualMic",
            ])
            .status()
            .await;
    }

    Ok(())
}

// ── PyInstaller onedir unpacker ───────────────────────────────────────────────
// PyInstaller onedir mode produces:
//   resources/backend-libs/<triple>/  ← all .so/.dll and Python bytecode
// We copy those next to the sidecar exe on first run so the OS loader finds them.

fn unpack_backend_libs(app: &AppHandle) -> Result<(), String> {
    use std::fs;

    let triple = get_target_triple();
    let res_dir = app.path().resource_dir().map_err(|e| e.to_string())?;
    let libs_src = res_dir.join("backend-libs").join(&triple);

    if !libs_src.exists() {
        // Nothing to unpack (dev mode or already extracted)
        return Ok(());
    }

    // Destination: same directory as the sidecar binary
    let bin_dir = std::env::current_exe()
        .map_err(|e| e.to_string())?
        .parent()
        .ok_or("no parent dir")?
        .to_path_buf();

    let dest_dir = bin_dir.join("prankcam-backend-libs");
    if dest_dir.exists() {
        // Already unpacked — skip (idempotent)
        return Ok(());
    }

    log::info!("Unpacking backend libs to {:?}", dest_dir);
    copy_dir_all(&libs_src, &dest_dir).map_err(|e| e.to_string())?;
    log::info!("Backend libs unpacked");
    Ok(())
}

fn copy_dir_all(src: &std::path::Path, dst: &std::path::Path) -> std::io::Result<()> {
    use std::fs;
    fs::create_dir_all(dst)?;
    for entry in fs::read_dir(src)? {
        let entry = entry?;
        let ty = entry.file_type()?;
        let dest_path = dst.join(entry.file_name());
        if ty.is_dir() {
            copy_dir_all(&entry.path(), &dest_path)?;
        } else {
            fs::copy(entry.path(), dest_path)?;
        }
    }
    Ok(())
}

fn get_target_triple() -> String {
    let arch = std::env::consts::ARCH;
    let os   = std::env::consts::OS;
    match (arch, os) {
        ("x86_64", "macos")   => "x86_64-apple-darwin".into(),
        ("aarch64","macos")   => "aarch64-apple-darwin".into(),
        ("x86_64", "linux")   => "x86_64-unknown-linux-gnu".into(),
        ("aarch64","linux")   => "aarch64-unknown-linux-gnu".into(),
        ("x86_64", "windows") => "x86_64-pc-windows-msvc".into(),
        _                     => format!("{arch}-unknown-{os}"),
    }
}

// ── Main ──────────────────────────────────────────────────────────────────────

fn main() {
    tauri::Builder::default()
        // ── Plugins (Tauri 2: each is explicitly initialised here) ────────────
        .plugin(
            tauri_plugin_log::Builder::new()
                .level(log::LevelFilter::Info)
                .build(),
        )
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_process::init())
        .plugin(tauri_plugin_http::init())
        // ── Managed state ─────────────────────────────────────────────────────
        .manage(BackendChild(Arc::new(Mutex::new(None))))
        // ── IPC commands exposed to the frontend ──────────────────────────────
        .invoke_handler(tauri::generate_handler![
            spawn_python_backend,
            kill_python_backend,
            check_backend_ready,
            request_pipeline_stop,
            get_python_info,
            install_virtual_drivers,
            check_virtual_drivers,
        ])
        // ── App setup (runs once at startup) ──────────────────────────────────
        .setup(|app| {
            let handle = app.handle().clone();

            // Unpack the PyInstaller onedir libs next to the sidecar, then spawn
            tauri::async_runtime::spawn(async move {
                tokio::time::sleep(Duration::from_millis(200)).await;

                // Unpack backend-libs/<triple>/ into the same dir as the sidecar
                if let Err(e) = unpack_backend_libs(&handle) {
                    log::warn!("Backend lib unpack: {e} (may already be unpacked)");
                }

                tokio::time::sleep(Duration::from_millis(100)).await;

                let state: State<BackendChild> = handle.state();
                match spawn_python_backend(handle.clone(), state).await {
                    Ok(s)  => log::info!("Backend auto-spawn: {s}"),
                    Err(e) => log::error!("Backend auto-spawn failed: {e}"),
                }
            });

            Ok(())
        })
        // ── Window close → clean up backend ───────────────────────────────────
        .on_window_event(|_window, event| {
            if let tauri::WindowEvent::Destroyed = event {
                // Best-effort graceful stop
                let _ = ureq::post("http://127.0.0.1:8765/stop")
                    .timeout(Duration::from_millis(400))
                    .call();
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running PrankCam");
}
