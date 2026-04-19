"""
audio_pipeline.py — PrankCam Audio Processing Pipeline  (no-torch edition)
============================================================================
BREAKING CHANGE FROM PREVIOUS VERSION:
  • torch / torchaudio REMOVED
  • Mock pitch-shift now uses scipy.signal.resample (already in requirements.txt)
  • RVC production path still supported — just load weights yourself and
    replace _forward() with a real RVC model call using onnxruntime

Dependencies: sounddevice==0.4.7, PyAudio==0.2.14, scipy==1.14.1, numpy==1.26.4
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np
import sounddevice as sd
from scipy.signal import resample as scipy_resample

try:
    import onnxruntime as ort
    _ORT_AVAILABLE = True
except ImportError:
    _ORT_AVAILABLE = False

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

@dataclass
class AudioConfig:
    input_device_index: Optional[int] = None   # None → system default mic
    output_device_index: Optional[int] = None  # None → system default out
    sample_rate: int = 44100
    channels: int = 1
    chunk_size: int = 1024   # frames/block (~23 ms at 44 100 Hz)
    model_path: Optional[str] = None
    # Built-in pitch shift override from content pack voices (-12 to +12 semitones)
    # Set when a built-in voice pack preset is selected instead of an ONNX model
    pitch_shift_semitones: int = 2  # default +2 (the existing mock behaviour)


# ---------------------------------------------------------------------------
# RVC Inference Engine
# ---------------------------------------------------------------------------

class RVCInferenceEngine:
    """
    Real-Time Voice Conversion inference wrapper.

    Production usage:
        1. Export your .pth model to .onnx using backend/rvc_export.py
        2. Place the .onnx file in backend/weights/rvc/
        3. Select it as the voice model in a persona.

    Mock: applies a semitone pitch shift via sinc-resampling to prove the
    pipeline throughput without requiring a GPU.
    """

    def __init__(self, model_path: Optional[str] = None, device: str = "cpu"):
        self.device = device
        self.model_loaded = False
        self._model = None
        self._session = None
        self._input_name: Optional[str] = None

        if model_path and Path(model_path).exists():
            self._load_model(model_path)
        else:
            if model_path:
                logger.warning(f"[RVC] Model not found at {model_path!r} — using pass-through mock")
            else:
                logger.info("[RVC] No model path supplied — mock pitch-shift active")

    # ------------------------------------------------------------------
    # Model loading  (fill in for production)
    # ------------------------------------------------------------------

    def _load_model(self, path: str) -> None:
        """
        Load a voice conversion model.
        .onnx  → loaded via onnxruntime (recommended for bundled builds).
        .pth   → PyTorch checkpoint; torch is NOT bundled, falls back to mock.
        """
        p = Path(path)
        if p.suffix.lower() == ".onnx" and _ORT_AVAILABLE:
            try:
                sess_opts = ort.SessionOptions()
                sess_opts.inter_op_num_threads = 2
                sess_opts.intra_op_num_threads = 4
                providers = (
                    ["CUDAExecutionProvider", "CPUExecutionProvider"]
                    if self.device == "cuda" else ["CPUExecutionProvider"]
                )
                self._session = ort.InferenceSession(
                    str(p), sess_options=sess_opts, providers=providers
                )
                self._input_name = self._session.get_inputs()[0].name
                self.model_loaded = True
                logger.info("[RVC] ONNX model loaded: %s", p.name)
            except Exception as exc:
                logger.warning("[RVC] ONNX load failed (%s) — mock active", exc)
                self.model_loaded = True
        elif p.suffix.lower() == ".pth":
            logger.warning(
                "[RVC] .pth detected (%s). Convert to .onnx for bundled builds. Mock active.",
                p.name,
            )
            self.model_loaded = True
        else:
            logger.info("[RVC] Unrecognised format or onnxruntime missing — mock active")
            self.model_loaded = True

    # ------------------------------------------------------------------
    # Forward pass  (fill in for production)
    # ------------------------------------------------------------------

    def _forward(self, audio: np.ndarray, sample_rate: int) -> np.ndarray:
        """
        audio  : 1-D float32 array, range [-1, 1]
        returns: 1-D float32 array, same length

        Production: load an RVC .onnx checkpoint and call
            self._session.run(None, {input_name: audio[None]})
        """
        # ── Real ONNX path ────────────────────────────────────────────────────────
        if self._session is not None and self._input_name is not None:
            try:
                inp = audio[None].astype(np.float32)   # (1, N)
                result = self._session.run(None, {self._input_name: inp})[0]
                return np.clip(result.squeeze().astype(np.float32), -1.0, 1.0)
            except Exception as exc:
                logger.debug("[RVC] ONNX forward failed: %s — falling back to mock", exc)

        # ── Pitch-shift fallback (configurable semitones from AudioConfig) ─────
        semitones = getattr(self, '_semitones', 2)
        pitch_ratio = 2 ** (semitones / 12)
        n_in   = len(audio)
        n_down = max(1, int(round(n_in / pitch_ratio)))
        downsampled = scipy_resample(audio, n_down).astype(np.float32)
        output = scipy_resample(downsampled, n_in).astype(np.float32)
        return np.clip(output, -1.0, 1.0)

    # ------------------------------------------------------------------
    # Public convert()
    # ------------------------------------------------------------------

    def convert(self, chunk_float32: np.ndarray, sample_rate: int) -> np.ndarray:
        """
        chunk_float32 : 1-D numpy float32, range [-1, 1]
        returns       : 1-D numpy float32, same length
        """
        if not self.model_loaded:
            return chunk_float32
        try:
            return self._forward(chunk_float32, sample_rate)
        except Exception as exc:
            logger.debug("[RVC] convert error: %s", exc)
            return chunk_float32


# ---------------------------------------------------------------------------
# Audio Processor
# ---------------------------------------------------------------------------

class AudioProcessor:
    """
    Orchestrates three concurrent pieces:
      1. _input_stream   — sounddevice InputStream, fills _in_q via callback
      2. _inference_loop — worker thread, drains _in_q → runs VC → fills _out_q
      3. _output_stream  — sounddevice OutputStream, drains _out_q via callback
    """

    # Keep queues short: prefer dropping over buffering (latency-first)
    _QUEUE_MAXSIZE = 16

    def __init__(self, config: AudioConfig):
        self.config = config
        self._engine = RVCInferenceEngine(config.model_path)
        self._engine._semitones = config.pitch_shift_semitones
        self._running = False
        self._worker: Optional[threading.Thread] = None
        self._in_q: queue.Queue[np.ndarray] = queue.Queue(maxsize=self._QUEUE_MAXSIZE)
        self._out_q: queue.Queue[np.ndarray] = queue.Queue(maxsize=self._QUEUE_MAXSIZE)
        self._lock = threading.Lock()
        self._latency_ms: float = 0.0
        self._input_stream: Optional[sd.InputStream] = None
        self._output_stream: Optional[sd.OutputStream] = None

    # ------------------------------------------------------------------
    # Model hot-swap
    # ------------------------------------------------------------------

    def load_model(self, model_path: str) -> None:
        device = "cuda" if torch.cuda.is_available() else "cpu"
        self._engine = RVCInferenceEngine(model_path, device=device)
        logger.info(f"[AudioProcessor] Voice model hot-loaded: {model_path!r}")

    # ------------------------------------------------------------------
    # Sounddevice callbacks (called on audio I/O thread — stay minimal)
    # ------------------------------------------------------------------

    def _input_callback(
        self,
        indata: np.ndarray,
        frames: int,
        time_info,
        status: sd.CallbackFlags,
    ) -> None:
        if status:
            logger.debug(f"[AudioInput] status={status}")
        try:
            self._in_q.put_nowait(indata[:, 0].copy())  # mono slice
        except queue.Full:
            pass  # drop oldest-style: just skip this chunk

    def _output_callback(
        self,
        outdata: np.ndarray,
        frames: int,
        time_info,
        status: sd.CallbackFlags,
    ) -> None:
        if status:
            logger.debug(f"[AudioOutput] status={status}")
        try:
            chunk = self._out_q.get_nowait()  # shape: (N,)
        except queue.Empty:
            outdata.fill(0.0)
            return

        # Ensure exact frame count (pad or trim)
        if chunk.shape[0] < frames:
            chunk = np.pad(chunk, (0, frames - chunk.shape[0]))
        elif chunk.shape[0] > frames:
            chunk = chunk[:frames]

        # Write to all output channels
        for ch in range(outdata.shape[1]):
            outdata[:, ch] = chunk

    # ------------------------------------------------------------------
    # Inference worker (separate thread, bounded latency)
    # ------------------------------------------------------------------

    def _inference_loop(self) -> None:
        logger.info("[AudioProcessor] Inference worker started")
        while self._running:
            try:
                chunk = self._in_q.get(timeout=0.1)
            except queue.Empty:
                continue

            t0 = time.perf_counter()
            try:
                converted = self._engine.convert(chunk.astype(np.float32), self.config.sample_rate)
            except Exception as exc:
                logger.error(f"[AudioProcessor] VC error: {exc}")
                converted = chunk

            with self._lock:
                self._latency_ms = (time.perf_counter() - t0) * 1000.0

            try:
                self._out_q.put_nowait(converted)
            except queue.Full:
                pass  # drop — output queue saturated, downstream is slow

        logger.info("[AudioProcessor] Inference worker exited")

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        if self._running:
            logger.warning("[AudioProcessor] Already running — ignoring start()")
            return
        self._running = True

        # Drain stale queue items
        for q in (self._in_q, self._out_q):
            while not q.empty():
                try:
                    q.get_nowait()
                except queue.Empty:
                    break

        # Launch inference worker
        self._worker = threading.Thread(
            target=self._inference_loop, daemon=True, name="VoiceConversionWorker"
        )
        self._worker.start()

        # Open I/O streams
        stream_kwargs = dict(
            channels=self.config.channels,
            samplerate=self.config.sample_rate,
            blocksize=self.config.chunk_size,
            dtype="float32",
        )
        self._input_stream = sd.InputStream(
            device=self.config.input_device_index,
            callback=self._input_callback,
            **stream_kwargs,
        )
        self._output_stream = sd.OutputStream(
            device=self.config.output_device_index,
            callback=self._output_callback,
            **stream_kwargs,
        )
        self._input_stream.start()
        self._output_stream.start()

        logger.info(
            f"[AudioProcessor] Streams open — in={self.config.input_device_index} "
            f"out={self.config.output_device_index} "
            f"sr={self.config.sample_rate} blocksize={self.config.chunk_size}"
        )

    def stop(self) -> None:
        self._running = False

        for stream_attr in ("_input_stream", "_output_stream"):
            stream = getattr(self, stream_attr, None)
            if stream is not None:
                try:
                    stream.stop()
                    stream.close()
                except Exception:
                    pass
                setattr(self, stream_attr, None)

        if self._worker:
            self._worker.join(timeout=3.0)

        logger.info("[AudioProcessor] Stopped")

    # ------------------------------------------------------------------
    # Status & device listing
    # ------------------------------------------------------------------

    def get_status(self) -> dict:
        with self._lock:
            return {"running": self._running, "latency_ms": round(self._latency_ms, 1)}

    @staticmethod
    def list_devices() -> list[dict]:
        result = []
        for idx, dev in enumerate(sd.query_devices()):
            result.append(
                {
                    "index": idx,
                    "name": dev["name"],
                    "max_input_channels": dev["max_input_channels"],
                    "max_output_channels": dev["max_output_channels"],
                    "default_samplerate": dev["default_samplerate"],
                }
            )
        return result
