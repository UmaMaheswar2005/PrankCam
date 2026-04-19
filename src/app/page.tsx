"use client";

import { useState, useCallback, useMemo, useEffect } from "react";
import { useBackend, API, type LogEntry, type SetupPhase, type DriverStatus } from "./hooks/useBackend";
import { usePipeline, type Persona } from "./hooks/usePipeline";
import { apiFetch } from "./hooks/useBackend";
import SetupWizard from "./SetupWizard";
import ContentPacksPanel from "./ContentPacksPanel";
import CaptureButton from "./CaptureButton";

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────

type Tab = "monitor" | "personas" | "devices" | "models" | "settings";

interface ModelInfo {
  key: string;
  name: string;
  present: boolean;
  size_mb: number;
  checksum_ok: boolean | null;
  description: string;
  download_url: string | null;
}

interface DownloadProgress {
  key: string;
  percent: number;
  bytes_downloaded: number;
  total_bytes: number;
  done: boolean;
  error: string | null;
  status?: string;
}

// ─────────────────────────────────────────────────────────────────────────────
// Root component
// ─────────────────────────────────────────────────────────────────────────────

export default function Page() {
  const backend  = useBackend();
  const pipeline = usePipeline(backend.ready, backend.addLog);

  // ── UI state ──────────────────────────────────────────────────────────────
  const [tab, setTab]               = useState<Tab>("monitor");
  const [globalError, setGlobalError] = useState<string | null>(null);

  // ── Quick-start fields (used when no persona selected) ────────────────────
  const [faceImagePath, setFaceImagePath] = useState("");
  const [voiceModelPath, setVoiceModelPath] = useState("");

  // ── Device overrides (kept in sync with settings) ─────────────────────────
  const [selectedCamera, setSelectedCamera]     = useState(0);
  const [inputAudioIdx, setInputAudioIdx]       = useState<number | "">("");
  const [outputAudioIdx, setOutputAudioIdx]     = useState<number | "">("");
  const [virtualCamDevice, setVirtualCamDevice] = useState("");

  // ── Persona form ──────────────────────────────────────────────────────────
  const [showPersonaForm, setShowPersonaForm] = useState(false);
  const [newName, setNewName]   = useState("");
  const [newFace, setNewFace]   = useState("");
  const [newVoice, setNewVoice] = useState("");
  const [savingPersona, setSavingPersona] = useState(false);

  // ── Personas sub-tab (must be at component level — React Rules of Hooks) ──
  const [personasSubTab, setPersonasSubTab] = useState<"mine"|"browse"|"capture">("mine");

  // ─────────────────────────────────────────────────────────────────────────
  // Derived
  // ─────────────────────────────────────────────────────────────────────────

  const inputDevices  = useMemo(() => backend.audioDevices.filter(d => d.max_input_channels  > 0), [backend.audioDevices]);
  const outputDevices = useMemo(() => backend.audioDevices.filter(d => d.max_output_channels > 0), [backend.audioDevices]);

  const activePersona = useMemo(
    () => pipeline.personas.find(p => p.id === pipeline.activePersonaId) ?? null,
    [pipeline.personas, pipeline.activePersonaId],
  );

  // ─────────────────────────────────────────────────────────────────────────
  // Handlers
  // ─────────────────────────────────────────────────────────────────────────

  const handleStart = async () => {
    if (!faceImagePath.trim() && !pipeline.activePersonaId) {
      setGlobalError("Select a persona or enter a face image path.");
      return;
    }
    setGlobalError(null);
    try {
      await pipeline.start({
        face_image_path:    faceImagePath.trim(),
        voice_model_path:   voiceModelPath.trim() || null,
        camera_index:       selectedCamera,
        input_audio_device: inputAudioIdx  === "" ? null : Number(inputAudioIdx),
        output_audio_device: outputAudioIdx === "" ? null : Number(outputAudioIdx),
        virtual_cam_device: virtualCamDevice.trim() || null,
      });
    } catch (e: any) { setGlobalError(e.message); }
  };

  const handleActivatePersona = async (p: Persona) => {
    setGlobalError(null);
    try {
      await pipeline.activatePersona(p);
      setFaceImagePath(p.face_image_path);
      setVoiceModelPath(p.voice_model_path ?? "");
    } catch (e: any) { setGlobalError(e.message); }
  };

  const handleSavePersona = async () => {
    if (!newName.trim() || !newFace.trim()) return;
    setSavingPersona(true);
    try {
      await pipeline.createPersona({
        name: newName.trim(),
        face_image_path: newFace.trim(),
        voice_model_path: newVoice.trim() || null,
        camera_index: selectedCamera,
        input_audio_device:  inputAudioIdx  === "" ? null : Number(inputAudioIdx),
        output_audio_device: outputAudioIdx === "" ? null : Number(outputAudioIdx),
        virtual_cam_device: virtualCamDevice.trim() || null,
        fps: pipeline.appSettings.fps   ?? 30,
        width:  pipeline.appSettings.width  ?? 640,
        height: pipeline.appSettings.height ?? 480,
      });
      setShowPersonaForm(false);
      setNewName(""); setNewFace(""); setNewVoice("");
    } catch (e: any) { setGlobalError(e.message); }
    finally { setSavingPersona(false); }
  };

  const handleSaveDeviceDefaults = async () => {
    await pipeline.saveSettings({
      camera_index:        selectedCamera,
      virtual_cam_device:  virtualCamDevice || null,
      input_audio_device:  inputAudioIdx  === "" ? null : Number(inputAudioIdx),
      output_audio_device: outputAudioIdx === "" ? null : Number(outputAudioIdx),
    });
  };

  // ─────────────────────────────────────────────────────────────────────────
  // File picker
  // ─────────────────────────────────────────────────────────────────────────

  const pickFile = async (
    setter: (v: string) => void,
    filters?: { name: string; extensions: string[] }[],
  ) => {
    try {
      const { open } = await import("@tauri-apps/plugin-dialog");
      const result = await open({ multiple: false, filters });
      if (result && typeof result === "string") setter(result);
    } catch {
      const input = document.createElement("input");
      input.type = "file";
      if (filters) input.accept = filters.flatMap(f => f.extensions.map(e => `.${e}`)).join(",");
      input.onchange = e => {
        const f = (e.target as HTMLInputElement).files?.[0];
        if (f) setter((f as any).path ?? f.name);
      };
      input.click();
    }
  };

  // ─────────────────────────────────────────────────────────────────────────
  // Header status
  // ─────────────────────────────────────────────────────────────────────────

  const backendDot = backend.ready
    ? "bg-emerald-400"
    : backend.setupPhase === "spawning" || backend.setupPhase === "checking_drivers"
    ? "bg-amber-400 animate-pulse"
    : backend.setupPhase === "installing_drivers"
    ? "bg-blue-400 animate-pulse"
    : backend.setupPhase === "failed"
    ? "bg-red-500"
    : "bg-slate-600";

  const backendLabel =
    backend.ready                                 ? "Ready"
    : backend.setupPhase === "spawning"           ? "Starting…"
    : backend.setupPhase === "checking_drivers"   ? "Checking drivers…"
    : backend.setupPhase === "installing_drivers" ? "Installing drivers…"
    : backend.setupPhase === "failed"             ? "Failed"
    : "Offline";

  const logColour: Record<LogEntry["level"], string> = {
    info:  "text-slate-400",
    warn:  "text-amber-400",
    error: "text-red-400",
  };

  // ─────────────────────────────────────────────────────────────────────────
  // Render
  // ─────────────────────────────────────────────────────────────────────────

  return (
    <div className="min-h-screen bg-[#0b0d12] text-slate-200 font-['IBM_Plex_Mono',monospace]">

      {/* ── First-run setup wizard (unmounts when ready) ───────────────────── */}
      <SetupWizard
        phase={backend.setupPhase}
        driverStatus={backend.driverStatus}
        onRetry={() => window.location.reload()}
      />

      {/* ── background grid ───────────────────────────────────────────────── */}
      <div
        className="fixed inset-0 pointer-events-none opacity-[0.022]"
        style={{
          backgroundImage:
            "linear-gradient(#7c3aed 1px,transparent 1px)," +
            "linear-gradient(90deg,#7c3aed 1px,transparent 1px)",
          backgroundSize: "36px 36px",
        }}
      />

      <div className="relative max-w-[740px] mx-auto px-4 py-6 space-y-4">

        {/* ═══════════ TOPBAR ══════════════════════════════════════════════ */}
        <header className="flex items-center gap-3">
          <div className="relative w-10 h-10 rounded-xl bg-violet-600 flex items-center justify-center text-xl shadow-lg shadow-violet-900/60 flex-shrink-0">
            🎭
            {pipeline.status.active && (
              <span className="absolute -top-1 -right-1 w-3 h-3 rounded-full bg-emerald-400 border-2 border-[#0b0d12] animate-pulse" />
            )}
          </div>
          <div className="flex-1 min-w-0">
            <h1 className="text-lg font-bold tracking-tight text-white leading-none">PrankCam</h1>
            <p className="text-[10px] text-slate-600 mt-0.5 truncate">
              {pipeline.status.active
                ? `▶ LIVE — ${pipeline.status.video.fps.toFixed(1)} fps · ${pipeline.status.audio.latency_ms.toFixed(0)} ms audio`
                : "face swap + voice conversion · idle"}
            </p>
          </div>
          <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-slate-800/80 border border-slate-700/60 text-[11px] flex-shrink-0">
            <span className={`w-2 h-2 rounded-full ${backendDot}`} />
            <span className="text-slate-400">{backendLabel}</span>
          </div>
        </header>

        {/* ═══════════ GLOBAL ERROR ════════════════════════════════════════ */}
        {globalError && (
          <div className="flex items-start gap-2.5 bg-red-950/60 border border-red-800/50 rounded-xl p-3 text-[12px] text-red-300">
            <span className="flex-shrink-0 mt-0.5">⚠</span>
            <span className="flex-1 leading-snug">{globalError}</span>
            <button onClick={() => setGlobalError(null)} className="text-red-600 hover:text-red-300 flex-shrink-0 ml-2">✕</button>
          </div>
        )}

        {/* ═══════════ TABS ════════════════════════════════════════════════ */}
        <nav className="flex gap-1 p-1 bg-slate-900/60 border border-slate-800 rounded-xl">
          {(["monitor","personas","devices","models","settings"] as Tab[]).map(t => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`flex-1 py-2 rounded-lg text-[10px] font-semibold tracking-widest uppercase transition-all ${
                tab === t
                  ? "bg-violet-700 text-white shadow-md shadow-violet-900/40"
                  : "text-slate-500 hover:text-slate-300"
              }`}
            >
              { t === "monitor"  ? "⬛ Monitor"
              : t === "personas" ? "🧬 Personas"
              : t === "devices"  ? "📡 Devices"
              : t === "models"   ? "📦 Models"
              :                    "⚙ Settings" }
            </button>
          ))}
        </nav>

        {/* ═══════════════════════════════════════════════════════════════════
            TAB: MONITOR
        ═══════════════════════════════════════════════════════════════════ */}
        {tab === "monitor" && (
          <div className="space-y-4">

            {/* Live MJPEG preview */}
            <div className="rounded-2xl overflow-hidden border border-slate-800 bg-[#0b0d12] relative">
              <div className="absolute top-2.5 left-3 z-10 flex items-center gap-2">
                {pipeline.status.active ? (
                  <span className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-red-600/90 text-[10px] font-bold text-white tracking-wider">
                    <span className="w-1.5 h-1.5 rounded-full bg-white animate-pulse" />LIVE
                  </span>
                ) : (
                  <span className="px-2.5 py-1 rounded-full bg-slate-800/80 text-[10px] text-slate-500 border border-slate-700">IDLE</span>
                )}
                {pipeline.status.watchdog.enabled && (
                  <span className="px-2 py-1 rounded-full bg-slate-800/70 text-[9px] text-slate-600 border border-slate-700/50">
                    watchdog ✓ · {pipeline.status.watchdog.video_restarts + pipeline.status.watchdog.audio_restarts} restarts
                  </span>
                )}
              </div>
              {backend.ready ? (
                /* eslint-disable-next-line @next/next/no-img-element */
                <img
                  src={`${API}/preview`}
                  alt="Live processed preview"
                  style={{ width: "100%", aspectRatio: "4/3", objectFit: "cover", background: "#0b0d12", display: "block" }}
                />
              ) : (
                <div className="flex items-center justify-center" style={{ aspectRatio: "4/3", background: "#0b0d12" }}>
                  <p className="text-slate-700 text-sm">Waiting for backend…</p>
                </div>
              )}
            </div>

            {/* Stats row */}
            <div className="grid grid-cols-3 gap-3">
              <StatCard
                label="FPS"
                value={pipeline.status.video.fps.toFixed(1)}
                accent="text-violet-300"
                bg="bg-violet-950/30 border-violet-800/30"
              />
              <StatCard
                label="LATENCY"
                value={`${pipeline.status.audio.latency_ms.toFixed(0)} ms`}
                accent="text-cyan-300"
                bg="bg-cyan-950/30 border-cyan-800/30"
              />
              <StatCard
                label="STATUS"
                value={pipeline.status.active ? "LIVE" : "IDLE"}
                accent={pipeline.status.active ? "text-emerald-300" : "text-slate-600"}
                bg={pipeline.status.active
                  ? "bg-emerald-950/30 border-emerald-800/30"
                  : "bg-slate-800/30 border-slate-700/40"}
              />
            </div>

            {/* Sparklines — only shown once data accumulates */}
            {pipeline.fpsHistory.length > 3 && (
              <div className="grid grid-cols-2 gap-3">
                <SparkCard title="FPS history"     data={pipeline.fpsHistory}     color="#a78bfa" unit="fps" />
                <SparkCard title="Latency history" data={pipeline.latencyHistory} color="#67e8f9" unit="ms"  />
              </div>
            )}

            {/* Active persona badge */}
            {activePersona && (
              <div className="flex items-center gap-3 px-4 py-3 rounded-xl bg-violet-950/40 border border-violet-800/40">
                <PersonaAvatar persona={activePersona} size={40} />
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-semibold text-violet-200 truncate">{activePersona.name}</p>
                  <p className="text-[10px] text-slate-500 truncate">
                    {activePersona.face_image_path.split(/[/\\]/).pop()}
                    {activePersona.voice_model_path && " · voice ✓"}
                  </p>
                </div>
                <button
                  onClick={() => { pipeline.setActivePersonaId(null); setFaceImagePath(""); setVoiceModelPath(""); }}
                  className="text-slate-600 hover:text-slate-400 text-xs ml-2"
                >
                  ✕ clear
                </button>
              </div>
            )}

            {/* Quick-start fields (only when no persona active) */}
            {!activePersona && (
              <div className="rounded-2xl bg-slate-900/60 border border-slate-800 p-4 space-y-3">
                <p className="text-[10px] text-slate-600 tracking-widest uppercase">
                  Quick Start — or pick a Persona from the Personas tab
                </p>
                <Field label="Face image  (.jpg / .png)">
                  <PathRow
                    value={faceImagePath}
                    onChange={setFaceImagePath}
                    placeholder="/path/to/face.jpg"
                    onBrowse={() => pickFile(setFaceImagePath, [{ name: "Images", extensions: ["jpg","jpeg","png","webp"] }])}
                  />
                </Field>
                <Field label="Voice model  (.pth) — optional">
                  <PathRow
                    value={voiceModelPath}
                    onChange={setVoiceModelPath}
                    placeholder="/path/to/voice.pth"
                    onBrowse={() => pickFile(setVoiceModelPath, [{ name: "PyTorch", extensions: ["pth","pt"] }])}
                  />
                </Field>
              </div>
            )}

            {/* Start / Stop */}
            {!pipeline.status.active ? (
              <button
                onClick={handleStart}
                disabled={pipeline.toggling || !backend.ready}
                className="w-full py-3.5 rounded-xl font-bold text-sm tracking-[0.15em] uppercase bg-violet-600 hover:bg-violet-500 disabled:bg-slate-800 disabled:text-slate-600 shadow-lg shadow-violet-900/40 transition-all duration-150"
              >
                {pipeline.toggling ? "Starting…" : "▶  Start Routing"}
              </button>
            ) : (
              <button
                onClick={pipeline.stop}
                disabled={pipeline.toggling}
                className="w-full py-3.5 rounded-xl font-bold text-sm tracking-[0.15em] uppercase bg-red-700 hover:bg-red-600 disabled:bg-slate-800 disabled:text-slate-600 shadow-lg shadow-red-900/40 transition-all duration-150"
              >
                {pipeline.toggling ? "Stopping…" : "⏹  Stop Routing"}
              </button>
            )}

            {/* Output log */}
            <LogPanel logs={backend.logs} logRef={backend.logRef} colour={logColour} onClear={() => {}} />
          </div>
        )}

        {/* ═══════════════════════════════════════════════════════════════════
            TAB: PERSONAS
        ═══════════════════════════════════════════════════════════════════ */}
        {tab === "personas" && (
          <div className="space-y-4">

            {/* Sub-navigation: My Personas / Browse Online / Capture */}
            <div className="flex gap-1 p-1 bg-slate-800/60 rounded-xl">
              {(["mine", "browse", "capture"] as const).map(t => (
                <button
                  key={t}
                  onClick={() => setPersonasSubTab(t)}
                  className={`flex-1 py-2 rounded-lg text-[10px] font-semibold uppercase tracking-widest transition-all ${
                    personasSubTab === t
                      ? "bg-violet-700 text-white shadow"
                      : "text-slate-500 hover:text-slate-300"
                  }`}
                >
                  {t === "mine" ? "🎭 My Personas" : t === "browse" ? "🌐 Browse Online" : "📸 Capture"}
                </button>
              ))}
            </div>

            {/* ── Browse Online sub-tab ── */}
            {personasSubTab === "browse" && (
              <ContentPacksPanel
                backendReady={backend.ready}
                onPersonaCreated={pipeline.loadPersonas}
                addLog={backend.addLog}
              />
            )}

            {/* ── Capture sub-tab ── */}
            {personasSubTab === "capture" && (
              <CaptureButton
                backendReady={backend.ready}
                onCaptureSaved={(_path, _name) => {
                  pipeline.loadPersonas();
                  setPersonasSubTab("mine");
                }}
                addLog={backend.addLog}
              />
            )}

            {/* ── My Personas sub-tab ── */}
            {personasSubTab === "mine" && (
              <div className="space-y-4">

                {/* Header + new persona toggle */}
                <div className="flex items-center gap-2">
                  <p className="text-[11px] text-slate-500 tracking-widest uppercase flex-1">
                    Saved Personas
                  </p>
                  <button
                    onClick={() => setShowPersonaForm(v => !v)}
                    className="text-[11px] px-3 py-1.5 rounded-lg bg-violet-700 hover:bg-violet-600 text-white transition-colors"
                  >
                    {showPersonaForm ? "✕ Cancel" : "+ New Persona"}
                  </button>
                </div>

                {/* New persona form — only shown when toggled */}
                {showPersonaForm && (
                  <div className="rounded-2xl bg-slate-900/60 border border-violet-800/40 p-4 space-y-3">
                    <p className="text-[10px] tracking-widest text-violet-400 uppercase">New Persona</p>
                    <Field label="Display name">
                      <StyledInput
                        value={newName}
                        onChange={e => setNewName(e.target.value)}
                        placeholder="e.g. Nicolas Cage"
                      />
                    </Field>
                    <Field label="Face image  (.jpg / .png)">
                      <PathRow
                        value={newFace}
                        onChange={setNewFace}
                        placeholder="/path/to/face.jpg"
                        onBrowse={() =>
                          pickFile(setNewFace, [{ name: "Images", extensions: ["jpg","jpeg","png","webp"] }])
                        }
                      />
                    </Field>
                    <Field label="Voice model  (.onnx / .pth) — optional">
                      <PathRow
                        value={newVoice}
                        onChange={setNewVoice}
                        placeholder="/path/to/voice.onnx"
                        onBrowse={() =>
                          pickFile(setNewVoice, [{ name: "Voice model", extensions: ["onnx","pth","pt"] }])
                        }
                      />
                    </Field>
                    <button
                      onClick={handleSavePersona}
                      disabled={savingPersona || !newName.trim() || !newFace.trim()}
                      className="w-full py-2.5 rounded-lg text-sm font-semibold bg-violet-600 hover:bg-violet-500 disabled:bg-slate-800 disabled:text-slate-600 transition-colors"
                    >
                      {savingPersona ? "Saving…" : "Save Persona"}
                    </button>
                  </div>
                )}

                {/* Persona grid — empty state or cards */}
                {pipeline.personas.length === 0 ? (
                  <div className="py-16 text-center text-slate-700 text-sm space-y-2">
                    <div className="text-4xl">🎭</div>
                    <p>No personas yet.</p>
                    <p className="text-xs text-slate-800">
                      Create one above, browse online, or snap from your webcam.
                    </p>
                  </div>
                ) : (
                  <div className="grid grid-cols-2 gap-3">
                    {pipeline.personas.map(p => (
                      <PersonaCard
                        key={p.id}
                        persona={p}
                        isActive={p.id === pipeline.activePersonaId}
                        isRunning={pipeline.toggling}
                        onActivate={() => handleActivatePersona(p)}
                        onDelete={() => pipeline.deletePersona(p.id, p.name)}
                      />
                    ))}
                  </div>
                )}

              </div>
            )}

          </div>
        )}

        {/* ═══════════════════════════════════════════════════════════════════
            TAB: DEVICES
        ═══════════════════════════════════════════════════════════════════ */}
        {tab === "devices" && (
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <p className="text-[11px] text-slate-500 tracking-widest uppercase">I/O Devices</p>
              <button
                onClick={backend.loadDevices}
                disabled={!backend.ready}
                className="text-[11px] text-slate-500 hover:text-slate-300 disabled:opacity-30 transition-colors"
              >
                ↺ rescan
              </button>
            </div>

            {/* Video */}
            <div className="rounded-2xl bg-slate-900/60 border border-slate-800 p-4 space-y-3">
              <SectionLabel icon="📹" text="Video" />
              <div className="grid grid-cols-2 gap-3">
                <Field label="Webcam source">
                  <StyledSelect value={selectedCamera} onChange={v => setSelectedCamera(Number(v))}>
                    {backend.cameras.length === 0 && <option value={0}>Camera 0 (default)</option>}
                    {backend.cameras.map(c => (
                      <option key={c.index} value={c.index}>
                        {c.name} — {c.width}×{c.height}
                      </option>
                    ))}
                  </StyledSelect>
                </Field>
                <Field label="Virtual cam device">
                  <StyledInput
                    value={virtualCamDevice}
                    onChange={e => setVirtualCamDevice(e.target.value)}
                    placeholder="/dev/video10 or empty = auto"
                  />
                </Field>
              </div>
            </div>

            {/* Audio */}
            <div className="rounded-2xl bg-slate-900/60 border border-slate-800 p-4 space-y-3">
              <SectionLabel icon="🎙" text="Audio" />
              <div className="grid grid-cols-2 gap-3">
                <Field label="Mic input">
                  <StyledSelect value={inputAudioIdx} onChange={v => setInputAudioIdx(v === "" ? "" : Number(v))}>
                    <option value="">System default</option>
                    {inputDevices.map(d => <option key={d.index} value={d.index}>{d.name}</option>)}
                  </StyledSelect>
                </Field>
                <Field label="Virtual audio out">
                  <StyledSelect value={outputAudioIdx} onChange={v => setOutputAudioIdx(v === "" ? "" : Number(v))}>
                    <option value="">System default</option>
                    {outputDevices.map(d => <option key={d.index} value={d.index}>{d.name}</option>)}
                  </StyledSelect>
                </Field>
              </div>
              <p className="text-[10px] text-slate-700">
                Windows: select "CABLE Input" (VB-Audio) · macOS: select "BlackHole 2ch" · Linux: PulseAudio null sink
              </p>
            </div>

            <button
              onClick={handleSaveDeviceDefaults}
              disabled={!backend.ready}
              className="w-full py-2.5 rounded-xl text-sm font-semibold bg-slate-700 hover:bg-slate-600 disabled:opacity-40 transition-colors"
            >
              Save as Defaults
            </button>
          </div>
        )}

        {/* ═══════════════════════════════════════════════════════════════════
            TAB: MODELS
        ═══════════════════════════════════════════════════════════════════ */}
        {tab === "models" && (
          <ModelsPanel backendReady={backend.ready} addLog={backend.addLog} />
        )}

        {/* ═══════════════════════════════════════════════════════════════════
            TAB: SETTINGS
        ═══════════════════════════════════════════════════════════════════ */}
        {tab === "settings" && (
          <SettingsPanel
            settings={pipeline.appSettings}
            onSave={pipeline.saveSettings}
            pythonInfo={backend.pythonInfo}
          />
        )}

      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Models panel (lazy-loaded model inventory + one-click download)
// ─────────────────────────────────────────────────────────────────────────────

function ModelsPanel({
  backendReady,
  addLog,
}: {
  backendReady: boolean;
  addLog: (m: string, l?: "info" | "warn" | "error") => void;
}) {
  const [models, setModels]       = useState<ModelInfo[]>([]);
  const [loading, setLoading]     = useState(false);
  const [progMap, setProgMap]     = useState<Record<string, DownloadProgress>>({});
  const [pollingKeys, setPollingKeys] = useState<Set<string>>(new Set());

  const loadModels = useCallback(async () => {
    if (!backendReady) return;
    setLoading(true);
    try {
      const d = await apiFetch<{ models: ModelInfo[] }>("/models");
      setModels(d.models);
    } catch (e: any) { addLog(`Models load: ${e.message}`, "warn"); }
    finally { setLoading(false); }
  }, [backendReady, addLog]);

  // Load on mount and when backend becomes ready
  useEffect(() => { loadModels(); }, [loadModels]);

  // Poll progress for in-flight downloads
  const pollProgress = useCallback(async (key: string) => {
    try {
      const p = await apiFetch<DownloadProgress>(`/models/${key}/progress`);
      setProgMap(prev => ({ ...prev, [key]: p }));
      if (p.done) {
        setPollingKeys(prev => { const s = new Set(prev); s.delete(key); return s; });
        if (!p.error) {
          addLog(`Model "${key}" downloaded ✓`);
          loadModels();
        } else {
          addLog(`Download error for ${key}: ${p.error}`, "error");
        }
      }
    } catch { /* swallow */ }
  }, [addLog, loadModels]);

  useEffect(() => {
    if (pollingKeys.size === 0) return;
    const id = setInterval(() => {
      pollingKeys.forEach(k => pollProgress(k));
    }, 800);
    return () => clearInterval(id);
  }, [pollingKeys, pollProgress]);

  const startDownload = async (key: string) => {
    try {
      const r = await apiFetch<{ status: string }>(`/models/${key}/download`, "POST");
      if (r.status === "already_present") {
        addLog(`Model ${key} already present.`);
        return;
      }
      addLog(`Downloading ${key}…`);
      setPollingKeys(prev => new Set([...prev, key]));
    } catch (e: any) { addLog(`Download start: ${e.message}`, "error"); }
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-[11px] text-slate-500 tracking-widest uppercase">ML Model Weights</p>
        <button
          onClick={loadModels}
          disabled={!backendReady || loading}
          className="text-[11px] text-slate-500 hover:text-slate-300 disabled:opacity-30 transition-colors"
        >
          {loading ? "scanning…" : "↺ rescan"}
        </button>
      </div>

      {models.length === 0 && !loading && (
        <p className="text-center text-slate-700 text-sm py-10">
          {backendReady ? "No models found — click rescan." : "Backend offline."}
        </p>
      )}

      <div className="space-y-3">
        {models.map(m => {
          const prog = progMap[m.key];
          const polling = pollingKeys.has(m.key);
          return (
            <div
              key={m.key}
              className={`rounded-2xl border p-4 space-y-2.5 ${
                m.present
                  ? "bg-emerald-950/20 border-emerald-800/30"
                  : "bg-slate-900/60 border-slate-800"
              }`}
            >
              <div className="flex items-start gap-3">
                <span className="text-xl mt-0.5">{m.present ? "✅" : "📭"}</span>
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-semibold text-slate-200 leading-snug">{m.name}</p>
                  <p className="text-[11px] text-slate-600 mt-0.5 leading-snug">{m.description}</p>
                </div>
                {m.present && (
                  <span className="text-[10px] text-emerald-500 font-semibold flex-shrink-0">
                    {m.size_mb.toFixed(0)} MB
                  </span>
                )}
              </div>

              {/* Checksum badge */}
              {m.present && m.checksum_ok !== null && (
                <span className={`text-[10px] px-2 py-0.5 rounded-full border ${
                  m.checksum_ok
                    ? "bg-emerald-900/30 border-emerald-700/40 text-emerald-400"
                    : "bg-red-900/30 border-red-700/40 text-red-400"
                }`}>
                  {m.checksum_ok ? "checksum ✓" : "checksum mismatch — re-download"}
                </span>
              )}

              {/* Download progress bar */}
              {polling && prog && !prog.done && (
                <div className="space-y-1">
                  <div className="w-full h-1.5 bg-slate-800 rounded-full overflow-hidden">
                    <div
                      className="h-full bg-violet-500 rounded-full transition-all duration-300"
                      style={{ width: `${prog.percent}%` }}
                    />
                  </div>
                  <p className="text-[10px] text-slate-600">
                    {prog.percent.toFixed(1)}% · {(prog.bytes_downloaded / 1e6).toFixed(1)} / {(prog.total_bytes / 1e6).toFixed(1)} MB
                  </p>
                </div>
              )}

              {/* Download error */}
              {prog?.error && (
                <p className="text-[11px] text-red-400">Error: {prog.error}</p>
              )}

              {/* Action button */}
              {!m.present && m.download_url && (
                <button
                  onClick={() => startDownload(m.key)}
                  disabled={polling}
                  className="w-full py-2 rounded-lg text-[11px] font-semibold bg-violet-700 hover:bg-violet-600 disabled:bg-slate-800 disabled:text-slate-600 transition-colors"
                >
                  {polling ? "Downloading…" : "↓ Download"}
                </button>
              )}
              {!m.present && !m.download_url && (
                <p className="text-[10px] text-slate-700 italic">
                  Install manually — no auto-download available for this model.
                </p>
              )}
            </div>
          );
        })}
      </div>

      {/* Installation guide */}
      <div className="rounded-2xl bg-slate-900/40 border border-slate-800 p-4 space-y-2">
        <p className="text-[10px] text-slate-600 tracking-widest uppercase">Quick Setup Guide</p>
        <p className="text-[11px] text-slate-500 leading-relaxed">
          <span className="text-slate-400">Face swap:</span> Download inswapper_128.onnx above, then{" "}
          <code className="text-violet-400">pip install insightface onnxruntime-gpu</code> and uncomment
          the production blocks in <code className="text-violet-400">ml_pipeline.py</code>.
        </p>
        <p className="text-[11px] text-slate-500 leading-relaxed">
          <span className="text-slate-400">Voice:</span> Place any RVC{" "}
          <code className="text-violet-400">.pth</code> file in{" "}
          <code className="text-violet-400">backend/weights/rvc/</code>, then select it via a persona.
        </p>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Settings panel
// ─────────────────────────────────────────────────────────────────────────────

function SettingsPanel({
  settings,
  onSave,
  pythonInfo,
}: {
  settings: Record<string, any>;
  onSave: (patch: Record<string, any>) => void;
  pythonInfo: Record<string, any>;
}) {
  const [fps,      setFps]      = useState(settings.fps ?? 30);
  const [width,    setWidth]    = useState(settings.width  ?? 640);
  const [height,   setHeight]   = useState(settings.height ?? 480);
  const [previewQ, setPreviewQ] = useState(settings.preview_quality ?? 60);
  const [watchdog, setWatchdog] = useState(settings.watchdog_enabled ?? true);

  return (
    <div className="space-y-4">
      <p className="text-[11px] text-slate-500 tracking-widest uppercase">Application Settings</p>

      {/* Pipeline */}
      <div className="rounded-2xl bg-slate-900/60 border border-slate-800 p-4 space-y-4">
        <SectionLabel icon="⚙" text="Pipeline" />
        <div className="grid grid-cols-3 gap-4">
          <Field label={`FPS target: ${fps}`}>
            <input type="range" min={15} max={60} step={5} value={fps}
              onChange={e => setFps(Number(e.target.value))}
              className="w-full accent-violet-500 h-1.5 cursor-pointer" />
          </Field>
          <Field label="Width">
            <StyledSelect value={width} onChange={v => setWidth(Number(v))}>
              {[320,480,640,1280].map(w => <option key={w} value={w}>{w}px</option>)}
            </StyledSelect>
          </Field>
          <Field label="Height">
            <StyledSelect value={height} onChange={v => setHeight(Number(v))}>
              {[240,360,480,720].map(h => <option key={h} value={h}>{h}px</option>)}
            </StyledSelect>
          </Field>
        </div>
      </div>

      {/* Preview */}
      <div className="rounded-2xl bg-slate-900/60 border border-slate-800 p-4 space-y-3">
        <SectionLabel icon="👁" text="Preview" />
        <Field label={`JPEG quality: ${previewQ}%`}>
          <input type="range" min={20} max={90} step={5} value={previewQ}
            onChange={e => setPreviewQ(Number(e.target.value))}
            className="w-full accent-violet-500 h-1.5 cursor-pointer" />
        </Field>
        <p className="text-[10px] text-slate-700">Lower quality = less CPU on preview encode. Does not affect virtual cam output.</p>
      </div>

      {/* Watchdog */}
      <div className="rounded-2xl bg-slate-900/60 border border-slate-800 p-4">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm font-semibold text-slate-300">Pipeline Watchdog</p>
            <p className="text-[11px] text-slate-600 mt-0.5">
              Auto-restarts stalled video or audio loops with exponential backoff.
            </p>
          </div>
          <button
            onClick={() => setWatchdog((v: boolean) => !v)}
            className={`relative w-11 h-6 rounded-full transition-colors duration-200 ${watchdog ? "bg-violet-600" : "bg-slate-700"}`}
          >
            <span className={`absolute top-1 left-1 w-4 h-4 rounded-full bg-white shadow transition-transform duration-200 ${watchdog ? "translate-x-5" : ""}`} />
          </button>
        </div>
      </div>

      <button
        onClick={() => onSave({ fps, width, height, preview_quality: previewQ, watchdog_enabled: watchdog })}
        className="w-full py-2.5 rounded-xl text-sm font-semibold bg-violet-700 hover:bg-violet-600 transition-colors"
      >
        Save Settings
      </button>

      {/* About */}
      <div className="rounded-2xl bg-slate-900/40 border border-slate-800 p-4 space-y-2">
        <SectionLabel icon="ℹ" text="About" />
        <InfoRow label="App version" value="3.0.0" />
        <InfoRow label="Stack"       value="Tauri · Next.js 14 · FastAPI · PyTorch" />
        {pythonInfo.version && <InfoRow label="Python" value={pythonInfo.version} />}
        {pythonInfo.using_venv !== undefined && (
          <InfoRow label="Using venv" value={pythonInfo.using_venv ? "Yes ✓" : "No (system Python)"} />
        )}
        {pythonInfo.backend_dir && (
          <InfoRow label="Backend dir" value={String(pythonInfo.backend_dir).split(/[/\\]/).slice(-2).join("/")} />
        )}
        <InfoRow label="Virtual cam"  value="pyvirtualcam → OBS Virtual Camera / v4l2loopback" />
        <InfoRow label="Virtual mic"  value="sounddevice → VB-Cable / BlackHole / PulseAudio null sink" />
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Persona sub-components
// ─────────────────────────────────────────────────────────────────────────────

function PersonaAvatar({ persona, size = 40 }: { persona: Persona; size?: number }) {
  const [err, setErr] = useState(false);
  return (
    <div
      className="rounded-lg bg-slate-800 border border-slate-700 flex items-center justify-center overflow-hidden flex-shrink-0"
      style={{ width: size, height: size }}
    >
      {persona.thumbnail_path && !err ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={`${API}/personas/${persona.id}/thumbnail`}
          alt={persona.name}
          style={{ width: "100%", height: "100%", objectFit: "cover" }}
          onError={() => setErr(true)}
        />
      ) : (
        <span style={{ fontSize: size * 0.44 }}>🎭</span>
      )}
    </div>
  );
}

function PersonaCard({
  persona, isActive, isRunning, onActivate, onDelete,
}: {
  persona: Persona; isActive: boolean; isRunning: boolean;
  onActivate: () => void; onDelete: () => void;
}) {
  const lastUsed = persona.last_used_at
    ? new Date(persona.last_used_at * 1000).toLocaleDateString(undefined, { month:"short", day:"numeric" })
    : "Never";

  return (
    <div className={`rounded-2xl border p-3.5 flex flex-col gap-2.5 transition-all ${
      isActive
        ? "bg-violet-950/40 border-violet-700/60 shadow-lg shadow-violet-900/20"
        : "bg-slate-900/50 border-slate-800"
    }`}>
      <div className="flex items-center gap-2.5">
        <PersonaAvatar persona={persona} size={44} />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-1.5">
            <p className={`text-sm font-semibold truncate ${isActive ? "text-violet-200" : "text-slate-200"}`}>
              {persona.name}
            </p>
            {isActive && (
              <span className="text-[8px] px-1.5 py-0.5 rounded bg-violet-700 text-violet-100 font-bold tracking-wide flex-shrink-0">
                ACTIVE
              </span>
            )}
          </div>
          <p className="text-[10px] text-slate-600 truncate mt-0.5">
            {persona.face_image_path.split(/[/\\]/).pop()}
          </p>
        </div>
      </div>

      <div className="flex flex-wrap gap-1.5 text-[10px]">
        <Pill>{persona.fps} fps</Pill>
        <Pill>{persona.width}×{persona.height}</Pill>
        {persona.voice_model_path && <Pill colour="emerald">voice ✓</Pill>}
        {persona.virtual_cam_device && <Pill>{persona.virtual_cam_device.split("/").pop()}</Pill>}
      </div>

      <div className="flex gap-2">
        <button
          onClick={onActivate}
          disabled={isRunning}
          className={`flex-1 py-2 rounded-lg text-[11px] font-semibold transition-colors disabled:opacity-40 ${
            isActive
              ? "bg-violet-700 hover:bg-violet-600 text-white"
              : "bg-slate-700 hover:bg-slate-600 text-slate-300"
          }`}
        >
          {isActive ? "Reactivate" : "Activate"}
        </button>
        <button
          onClick={onDelete}
          className="px-3 py-2 rounded-lg text-[11px] text-slate-600 hover:text-red-400 hover:bg-red-950/30 transition-colors"
          title="Delete persona"
        >
          🗑
        </button>
      </div>
      <p className="text-[10px] text-slate-700">Last used: {lastUsed}</p>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Shared primitives
// ─────────────────────────────────────────────────────────────────────────────

function StatCard({ label, value, accent, bg }: { label: string; value: string; accent: string; bg: string }) {
  return (
    <div className={`rounded-xl border p-3 flex flex-col gap-0.5 ${bg}`}>
      <span className="text-[10px] text-slate-600 tracking-widest">{label}</span>
      <span className={`text-lg font-bold tabular-nums ${accent}`}>{value}</span>
    </div>
  );
}

function SparkCard({ title, data, color, unit }: { title: string; data: number[]; color: string; unit: string }) {
  const W = 200, H = 52, PAD = 4;
  const max = Math.max(...data, 1);
  const min = Math.min(...data, 0);
  const range = max - min || 1;
  const pts = data.map((v, i) => {
    const x = PAD + (i / (data.length - 1 || 1)) * (W - PAD * 2);
    const y = H - PAD - ((v - min) / range) * (H - PAD * 2);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
  const last = data[data.length - 1] ?? 0;

  return (
    <div className="rounded-xl bg-slate-900/50 border border-slate-800 p-3">
      <div className="flex items-center justify-between mb-1">
        <span className="text-[10px] text-slate-600">{title}</span>
        <span className="text-[11px] font-bold tabular-nums" style={{ color }}>
          {last.toFixed(1)} {unit}
        </span>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", height: 44 }}>
        <defs>
          <linearGradient id={`g${color.replace("#","")}`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity="0.15" />
            <stop offset="100%" stopColor={color} stopOpacity="0" />
          </linearGradient>
        </defs>
        {data.length > 1 && (
          <>
            <polygon
              points={`${PAD},${H} ${pts} ${W - PAD},${H}`}
              fill={`url(#g${color.replace("#","")})`}
            />
            <polyline
              points={pts}
              fill="none"
              stroke={color}
              strokeWidth={1.5}
              strokeLinejoin="round"
              opacity={0.85}
            />
          </>
        )}
      </svg>
    </div>
  );
}

function LogPanel({
  logs, logRef, colour, onClear,
}: {
  logs: LogEntry[];
  logRef: React.RefObject<HTMLDivElement>;
  colour: Record<LogEntry["level"], string>;
  onClear: () => void;
}) {
  return (
    <div className="rounded-2xl bg-slate-900/60 border border-slate-800 overflow-hidden">
      <div className="flex items-center px-4 py-2 border-b border-slate-800/80">
        <span className="text-[10px] tracking-widest text-slate-600 uppercase">Output</span>
        <button onClick={onClear} className="ml-auto text-[10px] text-slate-700 hover:text-slate-500 transition-colors">
          clear
        </button>
      </div>
      <div ref={logRef} className="h-36 overflow-y-auto px-4 py-2.5 space-y-0.5">
        {logs.length === 0 ? (
          <p className="text-slate-800 text-[11px]">No output yet.</p>
        ) : (
          logs.map((l, i) => (
            <div key={i} className={`text-[11px] leading-5 ${colour[l.level]}`}>
              <span className="text-slate-700 select-none mr-2">{l.ts}</span>
              {l.msg}
            </div>
          ))
        )}
      </div>
    </div>
  );
}

function SectionLabel({ icon, text }: { icon: string; text: string }) {
  return (
    <div className="flex items-center gap-2">
      <span>{icon}</span>
      <span className="text-[10px] font-semibold tracking-[0.18em] text-slate-500 uppercase">{text}</span>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1.5">
      <label className="text-[11px] text-slate-500">{label}</label>
      {children}
    </div>
  );
}

function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-start gap-2 text-[11px]">
      <span className="text-slate-600 flex-shrink-0 w-28">{label}</span>
      <span className="text-slate-400 flex-1">{value}</span>
    </div>
  );
}

function Pill({ children, colour = "slate" }: { children: React.ReactNode; colour?: "slate" | "emerald" }) {
  const cls = colour === "emerald"
    ? "bg-emerald-900/30 border-emerald-800/40 text-emerald-500"
    : "bg-slate-800/60 border-slate-700/40 text-slate-600";
  return (
    <span className={`px-1.5 py-0.5 rounded border text-[9px] font-medium ${cls}`}>
      {children}
    </span>
  );
}

function StyledInput(props: React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      {...props}
      className="w-full bg-slate-800/70 border border-slate-700 rounded-lg px-3 py-2 text-[13px] text-slate-200 placeholder-slate-600 focus:outline-none focus:border-violet-500 focus:ring-1 focus:ring-violet-500/30 transition-colors"
    />
  );
}

function StyledSelect({
  value, onChange, children,
}: {
  value: number | string;
  onChange: (v: string) => void;
  children: React.ReactNode;
}) {
  return (
    <select
      value={value}
      onChange={e => onChange(e.target.value)}
      className="w-full bg-slate-800/70 border border-slate-700 rounded-lg px-3 py-2 text-[13px] text-slate-200 focus:outline-none focus:border-violet-500 focus:ring-1 focus:ring-violet-500/30 transition-colors cursor-pointer"
    >
      {children}
    </select>
  );
}

function PathRow({
  value, onChange, placeholder, onBrowse,
}: {
  value: string; onChange: (v: string) => void; placeholder: string; onBrowse: () => void;
}) {
  return (
    <div className="flex gap-2">
      <StyledInput value={value} onChange={e => onChange(e.target.value)} placeholder={placeholder} />
      <button
        onClick={onBrowse}
        className="flex-shrink-0 px-3 py-2 text-[11px] font-medium bg-slate-700 hover:bg-slate-600 border border-slate-600 rounded-lg text-slate-300 transition-colors whitespace-nowrap"
      >
        Browse
      </button>
    </div>
  );
}
