"use client";

import { useState, useEffect, useCallback } from "react";
import { API, apiFetch } from "./hooks/useBackend";

// ─────────────────────────────────────────────────────────────────────────────
// Types (mirroring backend dataclasses)
// ─────────────────────────────────────────────────────────────────────────────

interface FaceEntry {
  id: string; name: string; image_url: string;
  thumbnail_url: string; license: string;
  local_path: string | null; downloaded: boolean;
}
interface FacePack  { id: string; name: string; description: string; faces: FaceEntry[] }
interface VoiceEntry {
  id: string; name: string; description: string;
  model_url: string | null; size_mb: number; license: string;
  builtin: boolean; builtin_semitones: number;
  local_path: string | null; downloaded: boolean;
}
interface VoicePack  { id: string; name: string; description: string; voices: VoiceEntry[] }
interface DLProgress {
  item_id: string; percent: number; bytes_downloaded: number;
  total_bytes: number; done: boolean; error: string | null;
}

// ─────────────────────────────────────────────────────────────────────────────
// Main panel — two tabs: Faces / Voices
// ─────────────────────────────────────────────────────────────────────────────

interface Props {
  backendReady: boolean;
  onPersonaCreated: () => void;         // refresh personas list
  addLog: (m: string, l?: "info"|"warn"|"error") => void;
}

export default function ContentPacksPanel({ backendReady, onPersonaCreated, addLog }: Props) {
  const [subTab, setSubTab]         = useState<"faces"|"voices">("faces");
  const [facePacks, setFacePacks]   = useState<FacePack[]>([]);
  const [voicePacks, setVoicePacks] = useState<VoicePack[]>([]);
  const [loading, setLoading]       = useState(false);
  const [dlMap, setDlMap]           = useState<Record<string, DLProgress>>({});
  const [polling, setPolling]       = useState<Set<string>>(new Set());

  const load = useCallback(async () => {
    if (!backendReady) return;
    setLoading(true);
    try {
      const [fd, vd] = await Promise.all([
        apiFetch<{ face_packs: FacePack[] }>("/packs/faces"),
        apiFetch<{ voice_packs: VoicePack[] }>("/packs/voices"),
      ]);
      setFacePacks(fd.face_packs);
      setVoicePacks(vd.voice_packs);
    } catch (e: any) { addLog(`Packs load: ${e.message}`, "warn"); }
    finally { setLoading(false); }
  }, [backendReady, addLog]);

  useEffect(() => { load(); }, [load]);

  // Poll download progress
  useEffect(() => {
    if (polling.size === 0) return;
    const id = setInterval(async () => {
      for (const itemId of Array.from(polling)) {
        try {
          const p = await apiFetch<DLProgress>(`/packs/download/${itemId}/progress`);
          setDlMap(prev => ({ ...prev, [itemId]: p }));
          if (p.done) {
            setPolling(prev => { const s = new Set(prev); s.delete(itemId); return s; });
            if (!p.error) { load(); }
            else { addLog(`Download failed: ${p.error}`, "error"); }
          }
        } catch { /* swallow */ }
      }
    }, 600);
    return () => clearInterval(id);
  }, [polling, addLog, load]);

  const startPoll = (id: string) =>
    setPolling(prev => new Set([...prev, id]));

  // ── Face actions ────────────────────────────────────────────────────────
  const useThisFace = async (face: FaceEntry) => {
    addLog(`Using face: ${face.name}…`);
    try {
      const r = await apiFetch<any>(
        `/packs/faces/${face.id}/use-as-persona?name=${encodeURIComponent(face.name)}`,
        "POST",
      );
      addLog(`Persona "${r.persona.name}" created ✓`);
      onPersonaCreated();
    } catch (e: any) { addLog(`Use face: ${e.message}`, "error"); }
  };

  const downloadFace = async (face: FaceEntry) => {
    try {
      await apiFetch(`/packs/faces/${face.id}/download`, "POST");
      startPoll(face.id);
    } catch (e: any) { addLog(`Download: ${e.message}`, "error"); }
  };

  // ── Voice actions ───────────────────────────────────────────────────────
  const useThisVoice = async (voice: VoiceEntry, personaId?: string) => {
    if (!personaId) {
      addLog("Select a persona first, then apply a voice to it.", "warn");
      return;
    }
    addLog(`Applying voice "${voice.name}"…`);
    try {
      const r = await apiFetch<any>(
        `/packs/voices/${voice.id}/use-as-voice?persona_id=${personaId}`,
        "POST",
      );
      addLog(`Voice "${voice.name}" applied ✓`);
    } catch (e: any) { addLog(`Apply voice: ${e.message}`, "error"); }
  };

  const downloadVoice = async (voice: VoiceEntry) => {
    try {
      await apiFetch(`/packs/voices/${voice.id}/download`, "POST");
      startPoll(voice.id);
    } catch (e: any) { addLog(`Download: ${e.message}`, "error"); }
  };

  // ─────────────────────────────────────────────────────────────────────────
  // Render
  // ─────────────────────────────────────────────────────────────────────────
  return (
    <div className="space-y-4">
      {/* Sub-tab */}
      <div className="flex items-center justify-between">
        <div className="flex gap-1 p-1 bg-slate-800/60 rounded-xl">
          {(["faces","voices"] as const).map(t => (
            <button key={t} onClick={() => setSubTab(t)}
              className={`px-4 py-1.5 rounded-lg text-[11px] font-semibold uppercase tracking-widest transition-all ${
                subTab === t
                  ? "bg-violet-700 text-white shadow"
                  : "text-slate-500 hover:text-slate-300"
              }`}>
              {t === "faces" ? "😀 Faces" : "🎙 Voices"}
            </button>
          ))}
        </div>
        <button onClick={load} disabled={!backendReady || loading}
          className="text-[11px] text-slate-500 hover:text-slate-300 disabled:opacity-30 transition-colors">
          {loading ? "loading…" : "↺ refresh"}
        </button>
      </div>

      {/* ── FACES ── */}
      {subTab === "faces" && (
        <div className="space-y-5">
          {facePacks.length === 0 && !loading && (
            <p className="text-center text-slate-700 text-sm py-8">No face packs available.</p>
          )}
          {facePacks.map(pack => (
            <div key={pack.id} className="rounded-2xl bg-slate-900/50 border border-slate-800 overflow-hidden">
              <div className="px-4 py-3 border-b border-slate-800/80">
                <p className="text-sm font-semibold text-slate-200">{pack.name}</p>
                <p className="text-[11px] text-slate-600 mt-0.5">{pack.description}</p>
              </div>
              <div className="grid grid-cols-2 gap-3 p-3">
                {pack.faces.map(face => {
                  const prog = dlMap[face.id];
                  const downloading = polling.has(face.id) && !prog?.done;
                  return (
                    <div key={face.id}
                      className="rounded-xl bg-slate-800/60 border border-slate-700/40 overflow-hidden">
                      {/* Thumbnail */}
                      <div className="relative w-full bg-slate-900" style={{ aspectRatio: "1" }}>
                        {/* eslint-disable-next-line @next/next/no-img-element */}
                        <img
                          src={face.thumbnail_url}
                          alt={face.name}
                          className="w-full h-full object-cover"
                          onError={e => { (e.target as HTMLImageElement).style.display = "none"; }}
                        />
                        {face.downloaded && (
                          <span className="absolute top-1.5 right-1.5 w-5 h-5 rounded-full bg-emerald-500/90 flex items-center justify-center text-[9px]">✓</span>
                        )}
                      </div>
                      <div className="p-2.5 space-y-2">
                        <p className="text-[11px] font-medium text-slate-300 truncate">{face.name}</p>
                        <p className="text-[9px] text-slate-700">{face.license}</p>

                        {/* Download progress */}
                        {downloading && prog && (
                          <div className="w-full h-1 bg-slate-700 rounded-full overflow-hidden">
                            <div className="h-full bg-violet-500 transition-all duration-300"
                              style={{ width: `${prog.percent}%` }} />
                          </div>
                        )}

                        {/* Action buttons */}
                        <div className="flex gap-1.5">
                          <button
                            onClick={() => useThisFace(face)}
                            className="flex-1 py-1.5 rounded-lg text-[10px] font-semibold bg-violet-700 hover:bg-violet-600 text-white transition-colors"
                          >
                            {face.downloaded ? "Use" : "Get & Use"}
                          </button>
                          {!face.downloaded && !downloading && (
                            <button
                              onClick={() => downloadFace(face)}
                              className="px-2 py-1.5 rounded-lg text-[10px] bg-slate-700 hover:bg-slate-600 text-slate-300 transition-colors"
                              title="Download only"
                            >↓</button>
                          )}
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* ── VOICES ── */}
      {subTab === "voices" && (
        <div className="space-y-4">
          <p className="text-[11px] text-slate-600 leading-relaxed">
            Built-in presets work immediately. ONNX voice models require a download and produce
            more realistic voice conversion. Apply a voice to a persona in the Personas tab.
          </p>
          {voicePacks.map(pack => (
            <div key={pack.id} className="rounded-2xl bg-slate-900/50 border border-slate-800 overflow-hidden">
              <div className="px-4 py-3 border-b border-slate-800/80">
                <p className="text-sm font-semibold text-slate-200">{pack.name}</p>
                <p className="text-[11px] text-slate-600 mt-0.5">{pack.description}</p>
              </div>
              <div className="p-3 space-y-2">
                {pack.voices.map(voice => {
                  const prog = dlMap[voice.id];
                  const downloading = polling.has(voice.id) && !prog?.done;
                  return (
                    <div key={voice.id}
                      className={`rounded-xl border p-3 flex items-center gap-3 ${
                        voice.builtin
                          ? "bg-violet-950/20 border-violet-800/30"
                          : "bg-slate-800/40 border-slate-700/40"
                      }`}>
                      <span className="text-xl flex-shrink-0">
                        {voice.builtin ? "🎛" : voice.downloaded ? "✅" : "🎤"}
                      </span>
                      <div className="flex-1 min-w-0">
                        <p className="text-[12px] font-semibold text-slate-200 truncate">{voice.name}</p>
                        <p className="text-[10px] text-slate-600">{voice.description}</p>
                        {!voice.builtin && (
                          <p className="text-[10px] text-slate-700">{voice.size_mb.toFixed(1)} MB · {voice.license}</p>
                        )}
                        {downloading && prog && (
                          <div className="mt-1 w-full h-1 bg-slate-700 rounded-full overflow-hidden">
                            <div className="h-full bg-violet-500 transition-all duration-300"
                              style={{ width: `${prog.percent}%` }} />
                          </div>
                        )}
                      </div>
                      {voice.builtin ? (
                        <span className="text-[9px] px-2 py-0.5 rounded-full bg-violet-800/40 text-violet-300 border border-violet-700/40 flex-shrink-0">
                          Built-in
                        </span>
                      ) : !voice.downloaded && !downloading ? (
                        <button onClick={() => downloadVoice(voice)}
                          className="flex-shrink-0 px-3 py-1.5 rounded-lg text-[11px] font-semibold bg-violet-700 hover:bg-violet-600 text-white transition-colors">
                          ↓ Download
                        </button>
                      ) : voice.downloaded ? (
                        <span className="text-[10px] text-emerald-400 flex-shrink-0">Ready</span>
                      ) : (
                        <span className="text-[10px] text-slate-500 flex-shrink-0">Downloading…</span>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
