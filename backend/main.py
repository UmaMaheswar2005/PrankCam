"""
main.py — PrankCam FastAPI Backend  (v3 — final)
=================================================
Endpoints
─────────
Core pipeline
  GET  /health
  GET  /devices
  POST /start
  POST /stop
  GET  /status

Preview
  GET  /preview          → MJPEG stream
  GET  /preview/snapshot → single JPEG

Personas CRUD
  GET    /personas
  POST   /personas
  GET    /personas/{id}
  PUT    /personas/{id}
  DELETE /personas/{id}
  GET    /personas/{id}/thumbnail
  POST   /personas/{id}/activate

Models
  GET  /models           → inventory of face/voice weights
  POST /models/{key}/download  → start download (background)
  GET  /models/{key}/progress  → poll download progress

Settings
  GET  /settings
  PUT  /settings

Log stream
  GET  /log/stream       → Server-Sent Events of backend log lines
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from queue import Empty, Queue
from typing import AsyncGenerator, Optional

import cv2
import numpy as np
from fastapi import FastAPI, HTTPException, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from audio_pipeline import AudioConfig, AudioProcessor
from capture_face import capture_face_from_frame, capture_from_camera, list_captures, delete_capture
from content_packs import content_packs
from logging_config import configure_logging
from ml_pipeline import FaceSwapConfig, VideoProcessor
from model_manager import model_manager
from personas import DATA_DIR, PersonaStore
from watchdog import PipelineWatchdog

# ── Bootstrap logging ─────────────────────────────────────────────────────────
configure_logging(log_dir=DATA_DIR / "logs")
logger = logging.getLogger("prankcam.main")

# ── Settings ──────────────────────────────────────────────────────────────────
SETTINGS_FILE = DATA_DIR / "settings.json"
_DEFAULT_SETTINGS: dict = {
    "fps": 30,
    "width": 640,
    "height": 480,
    "camera_index": 0,
    "input_audio_device": None,
    "output_audio_device": None,
    "virtual_cam_device": None,
    "theme": "dark",
    "preview_quality": 60,
    "watchdog_enabled": True,
}


def _load_settings() -> dict:
    try:
        if SETTINGS_FILE.exists():
            return {**_DEFAULT_SETTINGS, **json.loads(SETTINGS_FILE.read_text())}
    except Exception:
        pass
    return dict(_DEFAULT_SETTINGS)


def _save_settings(s: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(json.dumps(s, indent=2))


# ── SSE log sink ──────────────────────────────────────────────────────────────

class _SSELogHandler(logging.Handler):
    """Feeds log records into a bounded queue for the /log/stream endpoint."""

    _MAX_SUBSCRIBERS = 8

    def __init__(self) -> None:
        super().__init__()
        self._queues: list[Queue] = []
        self._lock = threading.Lock()

    def subscribe(self) -> Queue:
        q: Queue = Queue(maxsize=200)
        with self._lock:
            if len(self._queues) >= self._MAX_SUBSCRIBERS:
                # evict oldest subscriber
                self._queues.pop(0)
            self._queues.append(q)
        return q

    def unsubscribe(self, q: Queue) -> None:
        with self._lock:
            try:
                self._queues.remove(q)
            except ValueError:
                pass

    def emit(self, record: logging.LogRecord) -> None:
        msg = self.format(record)
        payload = json.dumps({"level": record.levelname, "msg": msg, "ts": record.created})
        with self._lock:
            for q in self._queues:
                try:
                    q.put_nowait(payload)
                except Exception:
                    pass


_sse_handler = _SSELogHandler()
_sse_handler.setFormatter(logging.Formatter("%(name)s — %(message)s"))
logging.getLogger().addHandler(_sse_handler)

# ── Global state ──────────────────────────────────────────────────────────────
_video_proc: Optional[VideoProcessor] = None
_audio_proc: Optional[AudioProcessor] = None
_store = PersonaStore()
_settings: dict = _load_settings()
_watchdog: Optional[PipelineWatchdog] = None

# Cached factories (set on /start so watchdog can recreate processors)
_video_factory_fn = None
_audio_factory_fn = None


# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("PrankCam backend v3 starting (pid=%d)", os.getpid())
    yield
    logger.info("PrankCam backend shutting down")
    global _watchdog
    if _watchdog:
        _watchdog.stop()
    if _video_proc and _video_proc._running:
        _video_proc.stop()
    if _audio_proc and _audio_proc._running:
        _audio_proc.stop()


app = FastAPI(title="PrankCam API", version="3.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"],
)

# ── Pydantic models ───────────────────────────────────────────────────────────

class PipelineStartRequest(BaseModel):
    face_image_path: str
    voice_model_path: Optional[str] = None
    camera_index: int = Field(0, ge=0)
    input_audio_device: Optional[int] = None
    output_audio_device: Optional[int] = None
    fps: int = Field(30, ge=1, le=120)
    width: int = Field(640, ge=160, le=3840)
    height: int = Field(480, ge=120, le=2160)
    virtual_cam_device: Optional[str] = None


class PipelineStatus(BaseModel):
    active: bool
    video: dict
    audio: dict
    watchdog: dict


class PersonaCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    face_image_path: str
    voice_model_path: Optional[str] = None
    camera_index: int = 0
    input_audio_device: Optional[int] = None
    output_audio_device: Optional[int] = None
    virtual_cam_device: Optional[str] = None
    fps: int = Field(30, ge=1, le=120)
    width: int = Field(640, ge=160, le=3840)
    height: int = Field(480, ge=120, le=2160)


class PersonaUpdateRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=64)
    face_image_path: Optional[str] = None
    voice_model_path: Optional[str] = None
    camera_index: Optional[int] = None
    input_audio_device: Optional[int] = None
    output_audio_device: Optional[int] = None
    virtual_cam_device: Optional[str] = None
    fps: Optional[int] = None
    width: Optional[int] = None
    height: Optional[int] = None


class SettingsRequest(BaseModel):
    fps: Optional[int] = Field(None, ge=1, le=120)
    width: Optional[int] = Field(None, ge=160, le=3840)
    height: Optional[int] = Field(None, ge=120, le=2160)
    camera_index: Optional[int] = Field(None, ge=0)
    input_audio_device: Optional[int] = None
    output_audio_device: Optional[int] = None
    virtual_cam_device: Optional[str] = None
    theme: Optional[str] = None
    preview_quality: Optional[int] = Field(None, ge=10, le=95)
    watchdog_enabled: Optional[bool] = None


# ═════════════════════════════════════════════════════════════════════════════
# Core pipeline
# ═════════════════════════════════════════════════════════════════════════════

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "pid": os.getpid(),
        "pipeline_active": bool(_video_proc and _video_proc._running),
        "version": "3.0.0",
    }


@app.get("/devices")
async def list_devices():
    loop = asyncio.get_event_loop()
    cameras = await loop.run_in_executor(None, _enumerate_cameras)
    audio = AudioProcessor.list_devices()
    return {"cameras": cameras, "audio": audio}


@app.post("/start")
async def start_pipeline(req: PipelineStartRequest):
    global _video_proc, _audio_proc, _watchdog, _video_factory_fn, _audio_factory_fn

    if _video_proc and _video_proc._running:
        raise HTTPException(409, "Pipeline already running — call /stop first.")

    # Build config objects
    v_cfg = FaceSwapConfig(
        target_face_path=req.face_image_path,
        camera_index=req.camera_index,
        fps=req.fps,
        width=req.width,
        height=req.height,
        virtual_cam_device=req.virtual_cam_device,
    )
    a_cfg = AudioConfig(
        input_device_index=req.input_audio_device,
        output_device_index=req.output_audio_device,
        model_path=req.voice_model_path,
    )

    # Store factories so the watchdog can recreate processors
    def make_video():
        vp = VideoProcessor(v_cfg)
        vp.load_persona(req.face_image_path)
        return vp

    def make_audio():
        return AudioProcessor(a_cfg)

    _video_factory_fn = make_video
    _audio_factory_fn = make_audio

    # Create + start processors
    loop = asyncio.get_event_loop()
    try:
        vp = await loop.run_in_executor(None, make_video)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(400, str(exc))

    ap = make_audio()

    await asyncio.gather(
        loop.run_in_executor(None, vp.start),
        loop.run_in_executor(None, ap.start),
    )

    _video_proc = vp
    _audio_proc = ap

    # Start watchdog if enabled
    if _settings.get("watchdog_enabled", True):
        if _watchdog:
            _watchdog.stop()

        def on_video_replace(new_vp):
            global _video_proc
            _video_proc = new_vp

        def on_audio_replace(new_ap):
            global _audio_proc
            _audio_proc = new_ap

        def on_wd_event(component, event, detail):
            logger.warning(f"[Watchdog] {component} {event}: {detail}")

        _watchdog = PipelineWatchdog(
            video_factory=_video_factory_fn,
            audio_factory=_audio_factory_fn,
            on_video_replace=on_video_replace,
            on_audio_replace=on_audio_replace,
            on_event=on_wd_event,
        )
        _watchdog.update_procs(vp, ap)
        _watchdog.start()

    logger.info("Pipeline started (watchdog=%s)", _settings.get("watchdog_enabled", True))
    return {"status": "started"}


@app.post("/stop")
async def stop_pipeline():
    global _video_proc, _audio_proc, _watchdog

    if _watchdog:
        _watchdog.stop()
        _watchdog = None

    loop = asyncio.get_event_loop()
    tasks = []
    if _video_proc:
        tasks.append(loop.run_in_executor(None, _video_proc.stop))
    if _audio_proc:
        tasks.append(loop.run_in_executor(None, _audio_proc.stop))
    if tasks:
        await asyncio.gather(*tasks)

    logger.info("Pipeline stopped")
    return {"status": "stopped"}


@app.get("/status", response_model=PipelineStatus)
async def get_status():
    v = _video_proc.get_status() if _video_proc else {"running": False, "fps": 0.0}
    a = _audio_proc.get_status() if _audio_proc else {"running": False, "latency_ms": 0.0}
    wd: dict = {"enabled": False, "video_restarts": 0, "audio_restarts": 0}
    if _watchdog:
        wd = {
            "enabled": True,
            "video_restarts": _watchdog._video_health.restart_count,
            "audio_restarts": _watchdog._audio_health.restart_count,
        }
    return PipelineStatus(
        active=bool(_video_proc and _video_proc._running),
        video=v,
        audio=a,
        watchdog=wd,
    )


# ═════════════════════════════════════════════════════════════════════════════
# MJPEG Preview
# ═════════════════════════════════════════════════════════════════════════════

_BOUNDARY = b"--prankcamframe"
_NO_SIGNAL_JPEG: Optional[bytes] = None


def _make_no_signal_jpeg(w: int = 320, h: int = 240) -> bytes:
    img = np.zeros((h, w, 3), dtype=np.uint8)
    img[:] = (18, 18, 26)
    font = cv2.FONT_HERSHEY_SIMPLEX
    cv2.putText(img, "NO SIGNAL", (w // 2 - 72, h // 2), font, 0.95, (70, 70, 95), 2, cv2.LINE_AA)
    cv2.putText(img, "Start routing to preview", (w // 2 - 90, h // 2 + 26), font, 0.36, (45, 45, 65), 1, cv2.LINE_AA)
    _, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 70])
    return buf.tobytes()


async def _mjpeg_gen() -> AsyncGenerator[bytes, None]:
    global _NO_SIGNAL_JPEG
    if _NO_SIGNAL_JPEG is None:
        _NO_SIGNAL_JPEG = _make_no_signal_jpeg()
    while True:
        payload = (_video_proc.get_preview_jpeg() if _video_proc else None) or _NO_SIGNAL_JPEG
        yield (
            _BOUNDARY
            + b"\r\nContent-Type: image/jpeg\r\nContent-Length: "
            + str(len(payload)).encode()
            + b"\r\n\r\n"
            + payload
            + b"\r\n"
        )
        await asyncio.sleep(1 / 30)


@app.get("/preview")
async def mjpeg_preview():
    return StreamingResponse(
        _mjpeg_gen(),
        media_type=f"multipart/x-mixed-replace; boundary={_BOUNDARY.decode().lstrip('-')}",
        headers={"Cache-Control": "no-cache, no-store"},
    )


@app.get("/preview/snapshot")
async def snapshot():
    global _NO_SIGNAL_JPEG
    if _NO_SIGNAL_JPEG is None:
        _NO_SIGNAL_JPEG = _make_no_signal_jpeg()
    payload = (_video_proc.get_preview_jpeg() if _video_proc else None) or _NO_SIGNAL_JPEG
    return Response(content=payload, media_type="image/jpeg",
                    headers={"Cache-Control": "no-cache"})


# ═════════════════════════════════════════════════════════════════════════════
# Personas
# ═════════════════════════════════════════════════════════════════════════════

@app.get("/personas")
async def list_personas():
    return {"personas": [p.to_dict() for p in _store.list()]}


@app.post("/personas", status_code=201)
async def create_persona(req: PersonaCreateRequest):
    if not Path(req.face_image_path).exists():
        raise HTTPException(400, f"Face image not found: {req.face_image_path}")
    loop = asyncio.get_event_loop()
    p = await loop.run_in_executor(None, lambda: _store.create(
        name=req.name, face_image_path=req.face_image_path,
        voice_model_path=req.voice_model_path, camera_index=req.camera_index,
        input_audio_device=req.input_audio_device,
        output_audio_device=req.output_audio_device,
        virtual_cam_device=req.virtual_cam_device,
        fps=req.fps, width=req.width, height=req.height,
    ))
    return p.to_dict()


@app.get("/personas/{persona_id}")
async def get_persona(persona_id: str):
    p = _store.get(persona_id)
    if not p:
        raise HTTPException(404, "Persona not found")
    return p.to_dict()


@app.put("/personas/{persona_id}")
async def update_persona(persona_id: str, req: PersonaUpdateRequest):
    updates = {k: v for k, v in req.model_dump().items() if v is not None}
    loop = asyncio.get_event_loop()
    p = await loop.run_in_executor(None, lambda: _store.update(persona_id, **updates))
    if not p:
        raise HTTPException(404, "Persona not found")
    return p.to_dict()


@app.delete("/personas/{persona_id}", status_code=204)
async def delete_persona(persona_id: str):
    if not _store.delete(persona_id):
        raise HTTPException(404, "Persona not found")


@app.get("/personas/{persona_id}/thumbnail")
async def persona_thumbnail(persona_id: str):
    thumb = _store.get_thumbnail_path(persona_id)
    if not thumb:
        raise HTTPException(404, "Thumbnail not available")
    return Response(content=thumb.read_bytes(), media_type="image/jpeg")


@app.post("/personas/{persona_id}/activate")
async def activate_persona(persona_id: str):
    p = _store.get(persona_id)
    if not p:
        raise HTTPException(404, "Persona not found")
    _store.touch(persona_id)
    if _video_proc and _video_proc._running:
        await stop_pipeline()
        await asyncio.sleep(0.25)
    await start_pipeline(PipelineStartRequest(
        face_image_path=p.face_image_path,
        voice_model_path=p.voice_model_path,
        camera_index=p.camera_index,
        input_audio_device=p.input_audio_device,
        output_audio_device=p.output_audio_device,
        fps=p.fps, width=p.width, height=p.height,
        virtual_cam_device=p.virtual_cam_device,
    ))
    return {"status": "activated", "persona_id": persona_id, "name": p.name}


# ═════════════════════════════════════════════════════════════════════════════
# Models
# ═════════════════════════════════════════════════════════════════════════════

@app.get("/models")
async def list_models():
    loop = asyncio.get_event_loop()
    inv = await loop.run_in_executor(None, model_manager.inventory_dict)
    return {"models": inv}


@app.post("/models/{key}/download")
async def download_model(key: str):
    inv = {m["key"]: m for m in model_manager.inventory_dict()}
    if key not in inv:
        raise HTTPException(404, f"Unknown model key: {key}")
    if inv[key]["present"]:
        return {"status": "already_present"}
    if inv[key].get("download_url") is None:
        raise HTTPException(400, "This model has no automatic download — install manually.")

    # Launch download in background thread
    def _run():
        model_manager.download(key)

    t = threading.Thread(target=_run, daemon=True, name=f"Download-{key}")
    t.start()
    return {"status": "download_started", "key": key}


@app.get("/models/{key}/progress")
async def model_download_progress(key: str):
    prog = model_manager.get_download_progress(key)
    if prog is None:
        return {"key": key, "status": "not_started"}
    return {
        "key": key,
        "percent": round(prog.percent, 1),
        "bytes_downloaded": prog.bytes_downloaded,
        "total_bytes": prog.total_bytes,
        "done": prog.done,
        "error": prog.error,
    }


# ═════════════════════════════════════════════════════════════════════════════
# Settings
# ═════════════════════════════════════════════════════════════════════════════

@app.get("/settings")
async def get_settings():
    return _settings


@app.put("/settings")
async def update_settings(req: SettingsRequest):
    global _settings
    updates = {k: v for k, v in req.model_dump().items() if v is not None}
    _settings.update(updates)
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _save_settings, dict(_settings))
    return _settings


# ═════════════════════════════════════════════════════════════════════════════
# SSE Log stream  — GET /log/stream
# ═════════════════════════════════════════════════════════════════════════════

async def _sse_gen(q: "Queue") -> AsyncGenerator[str, None]:
    yield "data: {\"msg\": \"Log stream connected\"}\n\n"
    try:
        while True:
            await asyncio.sleep(0.1)
            while True:
                try:
                    payload = q.get_nowait()
                    yield f"data: {payload}\n\n"
                except Empty:
                    break
    except asyncio.CancelledError:
        pass
    finally:
        _sse_handler.unsubscribe(q)


@app.get("/log/stream")
async def log_stream():
    q = _sse_handler.subscribe()
    return StreamingResponse(
        _sse_gen(q),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


# ═════════════════════════════════════════════════════════════════════════════
# Helpers
# ═════════════════════════════════════════════════════════════════════════════

def _enumerate_cameras(max_indices: int = 6) -> list[dict]:
    cameras = []
    for idx in range(max_indices):
        cap = cv2.VideoCapture(idx, cv2.CAP_ANY)
        if cap.isOpened():
            cameras.append({
                "index": idx,
                "name": f"Camera {idx}",
                "width": int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
                "height": int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
                "fps": float(cap.get(cv2.CAP_PROP_FPS)),
            })
            cap.release()
    return cameras


# ═════════════════════════════════════════════════════════════════════════════
# Content Packs  — online face & voice gallery
# ═════════════════════════════════════════════════════════════════════════════

@app.get("/packs/faces")
async def list_face_packs():
    """Return all available face packs (built-in + remote registry)."""
    loop = asyncio.get_event_loop()
    packs = await loop.run_in_executor(None, content_packs.get_face_packs)
    return {"face_packs": [p.to_dict() for p in packs]}


@app.get("/packs/voices")
async def list_voice_packs():
    """Return all available voice packs (built-in presets + downloadable ONNX models)."""
    loop = asyncio.get_event_loop()
    packs = await loop.run_in_executor(None, content_packs.get_voice_packs)
    return {"voice_packs": [p.to_dict() for p in packs]}


@app.post("/packs/faces/{face_id}/download")
async def download_face(face_id: str):
    """Start downloading a face image from the registry."""
    # Find this face in any pack
    all_packs = content_packs.get_face_packs()
    face_entry = None
    for pack in all_packs:
        for face in pack.faces:
            if face.id == face_id:
                face_entry = face
                break

    if face_entry is None:
        raise HTTPException(404, f"Face ID {face_id!r} not found in registry")

    if face_entry.is_downloaded():
        return {"status": "already_downloaded", "path": face_entry.local_path}

    # Launch download in background
    def _run():
        try:
            content_packs.download_face(
                face_id,
                face_entry.image_url,
                face_entry.thumbnail_url,
            )
        except Exception as exc:
            logger.error("[Packs] Face download error: %s", exc)

    threading.Thread(target=_run, daemon=True, name=f"FaceDownload-{face_id}").start()
    return {"status": "download_started", "face_id": face_id}


@app.post("/packs/voices/{voice_id}/download")
async def download_voice(voice_id: str):
    """Start downloading a voice .onnx model from the registry."""
    all_packs = content_packs.get_voice_packs()
    voice_entry = None
    for pack in all_packs:
        for voice in pack.voices:
            if voice.id == voice_id:
                voice_entry = voice
                break

    if voice_entry is None:
        raise HTTPException(404, f"Voice ID {voice_id!r} not found in registry")

    if voice_entry.builtin:
        return {"status": "builtin", "voice_id": voice_id}

    if voice_entry.is_downloaded():
        return {"status": "already_downloaded", "path": voice_entry.local_path}

    if not voice_entry.model_url:
        raise HTTPException(400, "This voice has no download URL")

    def _run():
        try:
            content_packs.download_voice(voice_id, voice_entry.model_url)
        except Exception as exc:
            logger.error("[Packs] Voice download error: %s", exc)

    threading.Thread(target=_run, daemon=True, name=f"VoiceDownload-{voice_id}").start()
    return {"status": "download_started", "voice_id": voice_id}


@app.get("/packs/download/{item_id}/progress")
async def pack_download_progress(item_id: str):
    """Poll download progress for a face or voice item."""
    prog = content_packs.get_download_progress(item_id)
    if prog is None:
        return {"item_id": item_id, "status": "not_started"}
    return prog.to_dict()


@app.post("/packs/faces/{face_id}/use-as-persona")
async def use_face_as_persona(face_id: str, name: str = ""):
    """
    Download a face (if not already) and immediately create a persona from it.
    This is the one-click 'Use This Face' button action.
    """
    all_packs = content_packs.get_face_packs()
    face_entry = None
    for pack in all_packs:
        for face in pack.faces:
            if face.id == face_id:
                face_entry = face
                break

    if face_entry is None:
        raise HTTPException(404, f"Face ID {face_id!r} not found")

    # Download synchronously if needed (faces are small JPEGs, fast)
    loop = asyncio.get_event_loop()
    if not face_entry.is_downloaded():
        try:
            await loop.run_in_executor(
                None,
                lambda: content_packs.download_face(
                    face_id, face_entry.image_url, face_entry.thumbnail_url
                ),
            )
        except Exception as exc:
            raise HTTPException(500, f"Download failed: {exc}")

    local_path = face_entry.local_path or str(
        Path(content_packs._face_local_path(face_id) or "")
    )
    if not local_path or not Path(local_path).exists():
        raise HTTPException(500, "Face image not available after download")

    persona_name = name or face_entry.name
    persona = _store.create(
        name=persona_name,
        face_image_path=local_path,
    )
    return {"status": "created", "persona": persona.to_dict()}


@app.post("/packs/voices/{voice_id}/use-as-voice")
async def use_voice_for_persona(voice_id: str, persona_id: str):
    """
    Attach a voice pack entry to an existing persona.
    For built-in pitch-shift voices, sets a special builtin_voice field.
    """
    all_packs = content_packs.get_voice_packs()
    voice_entry = None
    for pack in all_packs:
        for voice in pack.voices:
            if voice.id == voice_id:
                voice_entry = voice
                break

    if voice_entry is None:
        raise HTTPException(404, f"Voice ID {voice_id!r} not found")

    if voice_entry.builtin:
        # Built-in pitch shift — store semitone value in settings instead of a file path
        p = _store.update(persona_id, voice_model_path=None)
        # Persist semitone override in settings keyed by persona
        pitches = _settings.get("persona_pitch_overrides", {})
        pitches[persona_id] = voice_entry.builtin_semitones
        _settings["persona_pitch_overrides"] = pitches
        _save_settings(dict(_settings))
        if not p:
            raise HTTPException(404, "Persona not found")
        return {
            "status": "applied",
            "type": "builtin_pitch",
            "semitones": voice_entry.builtin_semitones,
            "persona": p.to_dict(),
        }

    # Real ONNX voice — ensure it's downloaded first
    if not voice_entry.is_downloaded():
        if not voice_entry.model_url:
            raise HTTPException(400, "No download URL for this voice")
        loop = asyncio.get_event_loop()
        try:
            await loop.run_in_executor(
                None,
                lambda: content_packs.download_voice(voice_id, voice_entry.model_url),
            )
        except Exception as exc:
            raise HTTPException(500, f"Download failed: {exc}")

    local_path = voice_entry.local_path
    if not local_path:
        raise HTTPException(500, "Voice model not available after download")

    p = _store.update(persona_id, voice_model_path=local_path)
    if not p:
        raise HTTPException(404, "Persona not found")

    return {"status": "applied", "type": "onnx", "persona": p.to_dict()}


# ═════════════════════════════════════════════════════════════════════════════
# Face Capture  — snapshot from live webcam
# ═════════════════════════════════════════════════════════════════════════════

@app.post("/capture/face")
async def capture_face():
    """
    Capture the current webcam frame, detect and crop the face,
    save it, and return the path + base64 thumbnail.

    If the pipeline is running, uses the latest processed preview frame.
    If not, opens the camera directly for one shot.
    """
    loop = asyncio.get_event_loop()

    # Prefer the live pipeline frame (already captured, zero extra camera open)
    if _video_proc and _video_proc._running:
        preview_bytes = _video_proc.get_preview_jpeg()
        if preview_bytes:
            frame_arr = np.frombuffer(preview_bytes, dtype=np.uint8)
            frame_bgr = cv2.imdecode(frame_arr, cv2.IMREAD_COLOR)
            if frame_bgr is not None:
                analyzer = _video_proc._analyzer
                result = await loop.run_in_executor(
                    None,
                    lambda: capture_face_from_frame(frame_bgr, analyzer),
                )
                return result

    # No pipeline running — open camera directly
    cam_idx = _settings.get("camera_index", 0)
    # Create a temporary analyzer for detection
    from ml_pipeline import FaceAnalyzer
    analyzer = FaceAnalyzer("cpu")
    result = await loop.run_in_executor(
        None,
        lambda: capture_from_camera(cam_idx, analyzer),
    )
    return result


@app.get("/capture/list")
async def list_face_captures():
    """List all previously captured face images."""
    loop = asyncio.get_event_loop()
    captures = await loop.run_in_executor(None, list_captures)
    return {"captures": captures}


@app.delete("/capture/{filename}")
async def delete_face_capture(filename: str):
    """Delete a captured face image by filename."""
    loop = asyncio.get_event_loop()
    deleted = await loop.run_in_executor(None, lambda: delete_capture(filename))
    if not deleted:
        raise HTTPException(404, f"Capture {filename!r} not found")
    return {"status": "deleted"}


@app.post("/capture/{filename}/use-as-persona")
async def use_capture_as_persona(filename: str, name: str = "Captured Face"):
    """Create a persona directly from a captured face image."""
    from capture_face import CAPTURES_DIR
    if not filename.endswith(".jpg"):
        filename += ".jpg"
    path = CAPTURES_DIR / filename
    if not path.exists():
        raise HTTPException(404, f"Capture {filename!r} not found")

    persona = _store.create(name=name, face_image_path=str(path))
    return {"status": "created", "persona": persona.to_dict()}


# ═════════════════════════════════════════════════════════════════════════════
# Entry point
# ═════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8765, log_level="info", reload=False)

