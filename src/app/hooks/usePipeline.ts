"use client";

import { useState, useEffect, useCallback } from "react";
import { apiFetch } from "./useBackend";

export interface PipelineStatus {
  active: boolean;
  video: { running: boolean; fps: number };
  audio: { running: boolean; latency_ms: number };
  watchdog: { enabled: boolean; video_restarts: number; audio_restarts: number };
}

export interface Persona {
  id: string;
  name: string;
  face_image_path: string;
  voice_model_path: string | null;
  camera_index: number;
  input_audio_device: number | null;
  output_audio_device: number | null;
  virtual_cam_device: string | null;
  fps: number;
  width: number;
  height: number;
  created_at: number;
  last_used_at: number | null;
  thumbnail_path: string | null;
}

export interface StartConfig {
  face_image_path: string;
  voice_model_path?: string | null;
  camera_index?: number;
  input_audio_device?: number | null;
  output_audio_device?: number | null;
  virtual_cam_device?: string | null;
  fps?: number;
  width?: number;
  height?: number;
}

const EMPTY_STATUS: PipelineStatus = {
  active: false,
  video: { running: false, fps: 0 },
  audio: { running: false, latency_ms: 0 },
  watchdog: { enabled: false, video_restarts: 0, audio_restarts: 0 },
};

const SPARKLINE_LEN = 50;

export function usePipeline(
  backendReady: boolean,
  addLog: (msg: string, level?: "info" | "warn" | "error") => void,
) {
  const [status, setStatus] = useState<PipelineStatus>(EMPTY_STATUS);
  const [toggling, setToggling] = useState(false);
  const [activePersonaId, setActivePersonaId] = useState<string | null>(null);
  const [personas, setPersonas] = useState<Persona[]>([]);
  const [fpsHistory, setFpsHistory] = useState<number[]>([]);
  const [latencyHistory, setLatencyHistory] = useState<number[]>([]);
  const [appSettings, setAppSettings] = useState<Record<string, any>>({});

  // ── Settings ──────────────────────────────────────────────────────────────

  const loadSettings = useCallback(async () => {
    try {
      const s = await apiFetch<Record<string, any>>("/settings");
      setAppSettings(s);
    } catch { /* silent */ }
  }, []);

  const saveSettings = useCallback(async (patch: Record<string, any>) => {
    try {
      const updated = await apiFetch<Record<string, any>>("/settings", "PUT", patch);
      setAppSettings(updated);
      addLog("Settings saved.");
    } catch (e: any) { addLog(`Settings: ${e.message}`, "error"); }
  }, [addLog]);

  // ── Personas ─────────────────────────────────────────────────────────────

  const loadPersonas = useCallback(async () => {
    try {
      const d = await apiFetch<{ personas: Persona[] }>("/personas");
      setPersonas(d.personas);
    } catch { /* silent */ }
  }, []);

  const createPersona = useCallback(async (payload: Record<string, any>) => {
    const p = await apiFetch<Persona>("/personas", "POST", payload);
    setPersonas(prev => [p, ...prev]);
    addLog(`Persona "${p.name}" saved ✓`);
    return p;
  }, [addLog]);

  const deletePersona = useCallback(async (id: string, name: string) => {
    await apiFetch(`/personas/${id}`, "DELETE");
    setPersonas(p => p.filter(x => x.id !== id));
    if (activePersonaId === id) setActivePersonaId(null);
    addLog(`Persona "${name}" deleted.`);
  }, [addLog, activePersonaId]);

  const activatePersona = useCallback(async (p: Persona) => {
    setToggling(true);
    try {
      await apiFetch(`/personas/${p.id}/activate`, "POST");
      setActivePersonaId(p.id);
      addLog(`Persona "${p.name}" activated ✓`);
    } catch (e: any) {
      addLog(`Activate error: ${e.message}`, "error");
      throw e;
    } finally {
      setToggling(false);
    }
  }, [addLog]);

  // ── Pipeline ──────────────────────────────────────────────────────────────

  const start = useCallback(async (cfg: StartConfig) => {
    setToggling(true);
    try {
      await apiFetch("/start", "POST", {
        fps: appSettings.fps ?? 30,
        width: appSettings.width ?? 640,
        height: appSettings.height ?? 480,
        ...cfg,
      });
      addLog("Pipeline started — virtual cam & mic are live ✓");
    } catch (e: any) {
      addLog(`Start error: ${e.message}`, "error");
      throw e;
    } finally {
      setToggling(false);
    }
  }, [addLog, appSettings]);

  const stop = useCallback(async () => {
    setToggling(true);
    try {
      await apiFetch("/stop", "POST");
      addLog("Pipeline stopped.");
    } catch (e: any) {
      addLog(`Stop error: ${e.message}`, "error");
    } finally {
      setToggling(false);
    }
  }, [addLog]);

  // ── Status polling ────────────────────────────────────────────────────────

  useEffect(() => {
    if (!backendReady) return;
    loadSettings();
    loadPersonas();

    const id = setInterval(async () => {
      try {
        const s = await apiFetch<PipelineStatus>("/status");
        setStatus(s);
        setFpsHistory(p => [...p.slice(-(SPARKLINE_LEN - 1)), s.video.fps]);
        setLatencyHistory(p => [...p.slice(-(SPARKLINE_LEN - 1)), s.audio.latency_ms]);
      } catch { /* swallow */ }
    }, 1200);

    return () => clearInterval(id);
  }, [backendReady, loadSettings, loadPersonas]);

  return {
    status,
    toggling,
    activePersonaId,
    setActivePersonaId,
    personas,
    fpsHistory,
    latencyHistory,
    appSettings,
    loadPersonas,
    createPersona,
    deletePersona,
    activatePersona,
    saveSettings,
    start,
    stop,
  };
}
