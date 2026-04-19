"use client";

import { useState, useEffect, useCallback, useRef } from "react";

export const API = "http://127.0.0.1:8765";

export type LogEntry = { ts: string; msg: string; level: "info" | "warn" | "error" };

export interface Camera {
  index: number; name: string; width: number; height: number; fps: number;
}
export interface AudioDevice {
  index: number; name: string;
  max_input_channels: number; max_output_channels: number;
}

export type SetupPhase =
  | "idle"
  | "spawning"
  | "checking_drivers"
  | "installing_drivers"
  | "ready"
  | "failed";

export interface DriverStatus {
  virtual_camera: boolean;
  virtual_mic:    boolean;
}

// ── Universal fetch helper ────────────────────────────────────────────────────

export async function apiFetch<T>(
  path: string,
  method: "GET" | "POST" | "PUT" | "DELETE" = "GET",
  body?: object,
): Promise<T> {
  const res = await fetch(`${API}${path}`, {
    method,
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error((err as any).detail ?? res.statusText);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

// ── Tauri 2 invoke wrapper ────────────────────────────────────────────────────
// In Tauri 2, @tauri-apps/api exports a flat `invoke` (no change).
// But dialog / shell now come from separate plugin packages.

async function tauriInvoke<T>(cmd: string, args?: Record<string, unknown>): Promise<T> {
  const { invoke } = await import("@tauri-apps/api/core");
  return invoke<T>(cmd, args);
}

// ── useBackend hook ───────────────────────────────────────────────────────────

export function useBackend() {
  const [setupPhase, setSetupPhase]     = useState<SetupPhase>("idle");
  const [ready, setReady]               = useState(false);
  const [cameras, setCameras]           = useState<Camera[]>([]);
  const [audioDevices, setAudioDevices] = useState<AudioDevice[]>([]);
  const [logs, setLogs]                 = useState<LogEntry[]>([]);
  const [driverStatus, setDriverStatus] = useState<DriverStatus>({ virtual_camera: false, virtual_mic: false });
  const [pythonInfo, setPythonInfo]     = useState<Record<string, any>>({});
  const logRef  = useRef<HTMLDivElement>(null);
  const sseRef  = useRef<EventSource | null>(null);

  const addLog = useCallback((msg: string, level: LogEntry["level"] = "info") => {
    const ts = new Date().toLocaleTimeString("en-US", { hour12: false });
    setLogs(p => [...p.slice(-399), { ts, msg, level }]);
  }, []);

  // Auto-scroll log
  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [logs]);

  // ── SSE log bridge (backend → UI) ─────────────────────────────────────────

  const connectSSE = useCallback(() => {
    sseRef.current?.close();
    const es = new EventSource(`${API}/log/stream`);
    es.onmessage = e => {
      try {
        const d = JSON.parse(e.data) as { level: string; msg: string };
        const level =
          d.level === "WARNING"                          ? "warn"
          : d.level === "ERROR" || d.level === "CRITICAL" ? "error"
          : "info";
        addLog(d.msg, level as LogEntry["level"]);
      } catch { /* ignore malformed */ }
    };
    es.onerror = () => setTimeout(connectSSE, 3000);
    sseRef.current = es;
  }, [addLog]);

  // ── Device loading ────────────────────────────────────────────────────────

  const loadDevices = useCallback(async () => {
    try {
      const d = await apiFetch<{ cameras: Camera[]; audio: AudioDevice[] }>("/devices");
      setCameras(d.cameras);
      setAudioDevices(d.audio);
      addLog(`${d.cameras.length} camera(s), ${d.audio.length} audio device(s)`);
    } catch (e: any) { addLog(`Device scan: ${e.message}`, "warn"); }
  }, [addLog]);

  // ── Driver install (calls Tauri 2 command) ────────────────────────────────

  const installDrivers = useCallback(async (): Promise<boolean> => {
    setSetupPhase("installing_drivers");
    addLog("Installing virtual camera and audio drivers…");
    try {
      await tauriInvoke("install_virtual_drivers");
      const status = await tauriInvoke<DriverStatus>("check_virtual_drivers");
      setDriverStatus(status);
      const allOk = status.virtual_camera && status.virtual_mic;
      if (allOk) {
        addLog("Virtual drivers installed ✓");
      } else {
        if (!status.virtual_camera) addLog("Virtual camera driver not confirmed — check manually.", "warn");
        if (!status.virtual_mic)    addLog("Virtual mic driver not confirmed — check manually.", "warn");
      }
      return true;
    } catch (e: any) {
      addLog(`Driver install: ${e.message}`, "error");
      return false;
    }
  }, [addLog]);

  // ── Main bootstrap sequence ───────────────────────────────────────────────

  const bootstrap = useCallback(async () => {
    setSetupPhase("spawning");
    addLog("Launching PrankCam backend…");

    // 1. Spawn backend via Tauri 2 invoke
    try {
      await tauriInvoke("spawn_python_backend");
    } catch {
      addLog("Running outside Tauri — start: cd backend && python main.py", "warn");
    }

    // 2. Poll /health
    await new Promise<void>(resolve => {
      const pingId = setInterval(async () => {
        try {
          let alive = false;
          try {
            alive = await tauriInvoke<boolean>("check_backend_ready");
          } catch {
            const r = await fetch(`${API}/health`).catch(() => null);
            alive = r?.ok ?? false;
          }
          if (alive) {
            clearInterval(pingId);
            addLog("Backend ready on :8765 ✓");
            resolve();
          }
        } catch { /* keep polling */ }
      }, 900);
      setTimeout(() => { clearInterval(pingId); resolve(); }, 30_000);
    });

    // 3. Check virtual drivers
    setSetupPhase("checking_drivers");
    addLog("Checking virtual drivers…");
    try {
      const status = await tauriInvoke<DriverStatus>("check_virtual_drivers");
      setDriverStatus(status);
      const allOk = status.virtual_camera && status.virtual_mic;
      if (!allOk) {
        addLog("Some virtual drivers missing — installing now…", "warn");
        await installDrivers();
      } else {
        addLog("Virtual drivers present ✓");
      }
    } catch {
      // Outside Tauri — skip driver check
      addLog("Driver check skipped (browser mode).", "info");
    }

    // 4. Load Python info
    try {
      const info = await tauriInvoke<Record<string, any>>("get_python_info");
      setPythonInfo(info);
    } catch { /* browser */ }

    // 5. Load devices + connect SSE
    await loadDevices();
    connectSSE();

    setSetupPhase("ready");
    setReady(true);
  }, [addLog, loadDevices, connectSSE, installDrivers]);

  useEffect(() => {
    bootstrap();
    return () => {
      sseRef.current?.close();
      tauriInvoke("kill_python_backend").catch(() => {});
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return {
    ready,
    setupPhase,
    cameras,
    audioDevices,
    driverStatus,
    logs,
    logRef,
    addLog,
    loadDevices,
    installDrivers,
    pythonInfo,
  };
}
