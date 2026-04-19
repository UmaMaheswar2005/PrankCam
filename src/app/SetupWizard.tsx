"use client";

import type { SetupPhase, DriverStatus } from "./hooks/useBackend";

// ─────────────────────────────────────────────────────────────────────────────
// SetupWizard
//
// Rendered as a full-screen overlay while setupPhase is NOT "ready".
// Non-technical users see a friendly progress screen instead of a blank window.
// Once ready===true the overlay unmounts and the normal app UI appears.
// ─────────────────────────────────────────────────────────────────────────────

interface Props {
  phase:         SetupPhase;
  driverStatus:  DriverStatus;
  onRetry:       () => void;
}

const PHASE_COPY: Record<SetupPhase, { title: string; body: string; icon: string }> = {
  idle: {
    icon: "🎭",
    title: "Starting PrankCam…",
    body:  "Getting things ready.",
  },
  spawning: {
    icon: "⚙️",
    title: "Starting the engine…",
    body:  "Launching the processing backend. This takes a few seconds on first run.",
  },
  checking_drivers: {
    icon: "🔍",
    title: "Checking virtual devices…",
    body:  "Making sure your virtual camera and microphone are ready.",
  },
  installing_drivers: {
    icon: "📦",
    title: "Installing virtual devices…",
    body:  "Your computer will ask for permission once. This only happens on first launch.",
  },
  ready: {
    icon: "✅",
    title: "Ready!",
    body:  "All set.",
  },
  failed: {
    icon: "⚠️",
    title: "Something went wrong",
    body:  "PrankCam could not start its processing engine. Check that Python is installed, then try again.",
  },
};

const STEPS: { phase: SetupPhase; label: string }[] = [
  { phase: "spawning",            label: "Start engine"          },
  { phase: "checking_drivers",    label: "Check virtual devices" },
  { phase: "installing_drivers",  label: "Install drivers"       },
  { phase: "ready",               label: "Launch app"            },
];

const PHASE_ORDER: SetupPhase[] = [
  "idle", "spawning", "checking_drivers", "installing_drivers", "ready",
];

function phaseIndex(p: SetupPhase): number {
  return PHASE_ORDER.indexOf(p);
}

export default function SetupWizard({ phase, driverStatus, onRetry }: Props) {
  if (phase === "ready") return null;

  const copy     = PHASE_COPY[phase];
  const curIdx   = phaseIndex(phase);
  const isFailed = phase === "failed";

  return (
    <div className="fixed inset-0 z-50 flex flex-col items-center justify-center bg-[#0b0d12]">

      {/* ── Background grid ──────────────────────────────────────────────── */}
      <div
        className="absolute inset-0 pointer-events-none opacity-[0.022]"
        style={{
          backgroundImage:
            "linear-gradient(#7c3aed 1px,transparent 1px)," +
            "linear-gradient(90deg,#7c3aed 1px,transparent 1px)",
          backgroundSize: "36px 36px",
        }}
      />

      <div className="relative w-full max-w-sm px-6 space-y-8">

        {/* ── Logo ───────────────────────────────────────────────────────── */}
        <div className="flex flex-col items-center gap-3">
          <div
            className={`w-20 h-20 rounded-2xl flex items-center justify-center text-4xl shadow-2xl ${
              isFailed ? "bg-red-900/60" : "bg-violet-700"
            } shadow-violet-900/40`}
          >
            {copy.icon}
          </div>
          <div className="text-center">
            <h1 className="text-2xl font-bold text-white tracking-tight">{copy.title}</h1>
            <p className="mt-1.5 text-sm text-slate-400 leading-relaxed max-w-xs mx-auto">
              {copy.body}
            </p>
          </div>
        </div>

        {/* ── Step progress ──────────────────────────────────────────────── */}
        {!isFailed && (
          <div className="space-y-2.5">
            {STEPS.map((step, i) => {
              const stepIdx = phaseIndex(step.phase);
              const done    = curIdx > stepIdx;
              const active  = curIdx === stepIdx;
              return (
                <div key={step.phase} className="flex items-center gap-3">
                  <div
                    className={`w-6 h-6 rounded-full flex items-center justify-center flex-shrink-0 text-xs font-bold transition-all duration-300 ${
                      done   ? "bg-emerald-500 text-white"
                      : active ? "bg-violet-600 text-white ring-2 ring-violet-400/40"
                      : "bg-slate-800 text-slate-600 border border-slate-700"
                    }`}
                  >
                    {done ? "✓" : i + 1}
                  </div>
                  <span
                    className={`text-sm transition-colors duration-300 ${
                      done   ? "text-emerald-400"
                      : active ? "text-white font-medium"
                      : "text-slate-600"
                    }`}
                  >
                    {step.label}
                  </span>
                  {active && (
                    <span className="ml-auto flex gap-1">
                      {[0, 1, 2].map(d => (
                        <span
                          key={d}
                          className="w-1.5 h-1.5 rounded-full bg-violet-500 animate-bounce"
                          style={{ animationDelay: `${d * 150}ms` }}
                        />
                      ))}
                    </span>
                  )}
                </div>
              );
            })}
          </div>
        )}

        {/* ── Driver status (shown during install phase) ──────────────────── */}
        {(phase === "installing_drivers" || phase === "checking_drivers") && (
          <div className="rounded-xl bg-slate-900/60 border border-slate-800 p-4 space-y-2">
            <p className="text-[10px] text-slate-600 tracking-widest uppercase mb-2">Virtual Devices</p>
            <DriverRow
              label="Virtual Camera"
              ok={driverStatus.virtual_camera}
              hint="Routes your processed video to Zoom, Discord, etc."
            />
            <DriverRow
              label="Virtual Microphone"
              ok={driverStatus.virtual_mic}
              hint="Routes your processed voice to any app."
            />
          </div>
        )}

        {/* ── Admin password note (macOS / Linux UAC) ─────────────────────── */}
        {phase === "installing_drivers" && (
          <div className="rounded-xl bg-amber-950/40 border border-amber-800/40 p-3.5 flex gap-3">
            <span className="text-amber-400 flex-shrink-0 text-lg">🔑</span>
            <div>
              <p className="text-xs font-semibold text-amber-300">Admin permission required</p>
              <p className="text-[11px] text-amber-600 mt-0.5 leading-snug">
                A system dialog will appear asking for your password. This is normal and only happens once.
              </p>
            </div>
          </div>
        )}

        {/* ── Error retry ────────────────────────────────────────────────── */}
        {isFailed && (
          <div className="space-y-3">
            <div className="rounded-xl bg-red-950/40 border border-red-800/40 p-3.5 text-sm text-red-300 leading-relaxed">
              The processing backend did not start. Make sure PrankCam was installed correctly and try relaunching the app.
            </div>
            <button
              onClick={onRetry}
              className="w-full py-3 rounded-xl font-semibold text-sm bg-violet-700 hover:bg-violet-600 text-white transition-colors"
            >
              Try Again
            </button>
          </div>
        )}

        {/* ── Version footnote ───────────────────────────────────────────── */}
        <p className="text-center text-[10px] text-slate-800">PrankCam v3.0.0</p>
      </div>
    </div>
  );
}

function DriverRow({
  label, ok, hint,
}: {
  label: string; ok: boolean; hint: string;
}) {
  return (
    <div className="flex items-start gap-2.5">
      <span className={`mt-0.5 text-base flex-shrink-0 ${ok ? "text-emerald-400" : "text-slate-600"}`}>
        {ok ? "✅" : "⏳"}
      </span>
      <div>
        <p className={`text-xs font-medium ${ok ? "text-emerald-300" : "text-slate-400"}`}>{label}</p>
        <p className="text-[10px] text-slate-600 mt-0.5">{hint}</p>
      </div>
    </div>
  );
}
