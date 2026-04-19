"use client";

import { useState } from "react";
import { apiFetch } from "./hooks/useBackend";

interface CaptureResult {
  success: boolean;
  path: string | null;
  thumbnail_b64: string | null;
  face_found: boolean;
  message: string;
}

interface Props {
  backendReady: boolean;
  onCaptureSaved: (path: string, name: string) => void; // called after saving as persona
  addLog: (m: string, l?: "info"|"warn"|"error") => void;
}

export default function CaptureButton({ backendReady, onCaptureSaved, addLog }: Props) {
  const [capturing, setCapturing]     = useState(false);
  const [lastCapture, setLastCapture] = useState<CaptureResult | null>(null);
  const [saving, setSaving]           = useState(false);
  const [personaName, setPersonaName] = useState("");
  const [showNameInput, setShowNameInput] = useState(false);

  const capture = async () => {
    if (!backendReady || capturing) return;
    setCapturing(true);
    setLastCapture(null);
    try {
      const result = await apiFetch<CaptureResult>("/capture/face", "POST");
      setLastCapture(result);
      if (result.success) {
        addLog(result.message, result.face_found ? "info" : "warn");
        setShowNameInput(true);
        setPersonaName("Captured Face");
      } else {
        addLog(result.message, "error");
      }
    } catch (e: any) {
      addLog(`Capture failed: ${e.message}`, "error");
    } finally {
      setCapturing(false);
    }
  };

  const saveAsPersona = async () => {
    if (!lastCapture?.path || saving) return;
    setSaving(true);
    try {
      const filename = lastCapture.path.split(/[/\\]/).pop() ?? "";
      const r = await apiFetch<any>(
        `/capture/${filename}/use-as-persona?name=${encodeURIComponent(personaName || "Captured Face")}`,
        "POST",
      );
      addLog(`Persona "${r.persona.name}" created from capture ✓`);
      onCaptureSaved(lastCapture.path, personaName);
      setShowNameInput(false);
      setLastCapture(null);
    } catch (e: any) {
      addLog(`Save persona: ${e.message}`, "error");
    } finally {
      setSaving(false);
    }
  };

  const discard = () => {
    setLastCapture(null);
    setShowNameInput(false);
    setPersonaName("");
  };

  return (
    <div className="rounded-2xl bg-slate-900/60 border border-slate-800 p-4 space-y-3">
      <div className="flex items-center gap-2">
        <span className="text-base">📸</span>
        <div>
          <p className="text-sm font-semibold text-slate-200">Capture Face from Webcam</p>
          <p className="text-[11px] text-slate-600">
            Point your camera at a photo or screen — snap it to use as a swap target instantly.
          </p>
        </div>
      </div>

      {/* Capture result preview */}
      {lastCapture && lastCapture.thumbnail_b64 && (
        <div className="flex items-start gap-3">
          <div className="w-20 h-20 rounded-xl overflow-hidden border border-slate-700 flex-shrink-0">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={`data:image/jpeg;base64,${lastCapture.thumbnail_b64}`}
              alt="Captured face"
              className="w-full h-full object-cover"
            />
          </div>
          <div className="flex-1 space-y-2">
            <p className={`text-[11px] ${lastCapture.face_found ? "text-emerald-400" : "text-amber-400"}`}>
              {lastCapture.face_found ? "✓ Face detected and cropped" : "⚠ No face detected — full frame saved"}
            </p>
            {showNameInput && (
              <div className="space-y-2">
                <input
                  value={personaName}
                  onChange={e => setPersonaName(e.target.value)}
                  placeholder="Persona name…"
                  className="w-full bg-slate-800/70 border border-slate-700 rounded-lg px-3 py-1.5 text-[12px] text-slate-200 placeholder-slate-600 focus:outline-none focus:border-violet-500 transition-colors"
                />
                <div className="flex gap-2">
                  <button
                    onClick={saveAsPersona}
                    disabled={saving}
                    className="flex-1 py-2 rounded-lg text-[11px] font-semibold bg-violet-700 hover:bg-violet-600 disabled:opacity-40 text-white transition-colors"
                  >
                    {saving ? "Saving…" : "Save as Persona"}
                  </button>
                  <button
                    onClick={discard}
                    className="px-3 py-2 rounded-lg text-[11px] text-slate-600 hover:text-slate-400 hover:bg-slate-800 transition-colors"
                  >
                    Discard
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Capture button */}
      {!lastCapture && (
        <button
          onClick={capture}
          disabled={!backendReady || capturing}
          className="w-full py-2.5 rounded-xl text-sm font-semibold bg-slate-700 hover:bg-slate-600 disabled:bg-slate-800 disabled:text-slate-600 text-slate-200 transition-colors flex items-center justify-center gap-2"
        >
          {capturing ? (
            <><span className="w-3 h-3 rounded-full bg-violet-500 animate-ping" />Capturing…</>
          ) : (
            <>📸  Snap Current Camera Frame</>
          )}
        </button>
      )}

      {lastCapture && !showNameInput && (
        <button
          onClick={capture}
          disabled={capturing}
          className="w-full py-2 rounded-xl text-[11px] text-slate-500 hover:text-slate-300 transition-colors"
        >
          ↺ Capture again
        </button>
      )}
    </div>
  );
}
