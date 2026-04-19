"""
watchdog.py — PrankCam Process Supervisor
==========================================
Monitors the VideoProcessor and AudioProcessor threads.
If either crashes or stalls (no new frames / audio chunks within a deadline),
the watchdog restarts the failing component with exponential backoff.

Usage (integrated into main.py — do not run standalone):
    from watchdog import PipelineWatchdog
    wd = PipelineWatchdog(video_proc, audio_proc, on_restart=lambda c, e: ...)
    wd.start()
    ...
    wd.stop()
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable, Optional

logger = logging.getLogger(__name__)

# ── Tuning constants ─────────────────────────────────────────────────────────
_VIDEO_STALL_THRESHOLD_S = 5.0   # seconds without a new FPS reading → stall
_AUDIO_STALL_THRESHOLD_S = 8.0
_POLL_INTERVAL_S = 2.0
_MAX_BACKOFF_S = 60.0
_BASE_BACKOFF_S = 1.0
_BACKOFF_MULTIPLIER = 2.0
# ─────────────────────────────────────────────────────────────────────────────


class ComponentHealth:
    """Tracks restart attempts and backoff for one pipeline component."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.restart_count: int = 0
        self.last_healthy: float = time.monotonic()
        self._backoff: float = _BASE_BACKOFF_S

    def record_healthy(self) -> None:
        self.last_healthy = time.monotonic()
        self._backoff = _BASE_BACKOFF_S  # reset on success

    def next_backoff(self) -> float:
        b = self._backoff
        self._backoff = min(self._backoff * _BACKOFF_MULTIPLIER, _MAX_BACKOFF_S)
        self.restart_count += 1
        return b

    def seconds_since_healthy(self) -> float:
        return time.monotonic() - self.last_healthy


class PipelineWatchdog:
    """
    Supervises VideoProcessor and AudioProcessor.

    Parameters
    ----------
    video_factory : callable → VideoProcessor
        Called with no args to create a fresh VideoProcessor.
    audio_factory : callable → AudioProcessor
        Called with no args to create a fresh AudioProcessor.
    on_video_replace : callable(VideoProcessor)
        Called after a new VideoProcessor is started — lets main.py swap
        the global reference.
    on_audio_replace : callable(AudioProcessor)
        Same for AudioProcessor.
    on_event : optional callable(component: str, event: str, detail: str)
        Receives watchdog events for the UI log stream.
    """

    def __init__(
        self,
        video_factory: Callable,
        audio_factory: Callable,
        on_video_replace: Callable,
        on_audio_replace: Callable,
        on_event: Optional[Callable[[str, str, str], None]] = None,
    ) -> None:
        self._video_factory = video_factory
        self._audio_factory = audio_factory
        self._on_video_replace = on_video_replace
        self._on_audio_replace = on_audio_replace
        self._on_event = on_event or (lambda *_: None)

        self._video_health = ComponentHealth("video")
        self._audio_health = ComponentHealth("audio")

        self._running = False
        self._thread: Optional[threading.Thread] = None

        # References to the live processors (set externally via update())
        self._video_proc = None
        self._audio_proc = None
        self._lock = threading.Lock()

    # ── Public API ────────────────────────────────────────────────────────────

    def update_procs(self, video_proc, audio_proc) -> None:
        """Called by main.py whenever processors are (re)created."""
        with self._lock:
            self._video_proc = video_proc
            self._audio_proc = audio_proc
            self._video_health.record_healthy()
            self._audio_health.record_healthy()

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="PipelineWatchdog"
        )
        self._thread.start()
        logger.info("[Watchdog] Started")

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=4.0)
        logger.info("[Watchdog] Stopped")

    # ── Internal ──────────────────────────────────────────────────────────────

    def _loop(self) -> None:
        while self._running:
            time.sleep(_POLL_INTERVAL_S)
            if not self._running:
                break

            with self._lock:
                vp = self._video_proc
                ap = self._audio_proc

            # Only supervise when processors exist and are supposed to be running
            if vp is not None and vp._running:
                self._check_video(vp)

            if ap is not None and ap._running:
                self._check_audio(ap)

    def _check_video(self, vp) -> None:
        status = vp.get_status()
        if status["fps"] > 0.5:
            # Getting frames → healthy
            self._video_health.record_healthy()
            return

        stale_s = self._video_health.seconds_since_healthy()
        if stale_s < _VIDEO_STALL_THRESHOLD_S:
            return  # grace period

        logger.warning(
            f"[Watchdog] Video stall detected — {stale_s:.1f}s without frames. "
            f"Restart #{self._video_health.restart_count + 1}"
        )
        self._on_event("video", "stall", f"{stale_s:.1f}s without frames")

        backoff = self._video_health.next_backoff()
        logger.info(f"[Watchdog] Video restart in {backoff:.1f}s…")
        time.sleep(backoff)

        try:
            vp.stop()
        except Exception as exc:
            logger.debug(f"[Watchdog] Video stop error (expected): {exc}")

        try:
            new_vp = self._video_factory()
            new_vp.start()
            self._on_video_replace(new_vp)
            with self._lock:
                self._video_proc = new_vp
            self._video_health.record_healthy()
            self._on_event("video", "restarted", f"attempt {self._video_health.restart_count}")
            logger.info("[Watchdog] Video processor restarted successfully")
        except Exception as exc:
            logger.error(f"[Watchdog] Video restart failed: {exc}")
            self._on_event("video", "restart_failed", str(exc))

    def _check_audio(self, ap) -> None:
        status = ap.get_status()
        # If latency > 0 it means the inference worker processed at least one chunk
        if status["latency_ms"] > 0 and self._audio_health.seconds_since_healthy() < _AUDIO_STALL_THRESHOLD_S:
            self._audio_health.record_healthy()
            return

        stale_s = self._audio_health.seconds_since_healthy()
        if stale_s < _AUDIO_STALL_THRESHOLD_S:
            return

        logger.warning(
            f"[Watchdog] Audio stall detected — {stale_s:.1f}s without processing. "
            f"Restart #{self._audio_health.restart_count + 1}"
        )
        self._on_event("audio", "stall", f"{stale_s:.1f}s without audio chunks")

        backoff = self._audio_health.next_backoff()
        logger.info(f"[Watchdog] Audio restart in {backoff:.1f}s…")
        time.sleep(backoff)

        try:
            ap.stop()
        except Exception as exc:
            logger.debug(f"[Watchdog] Audio stop error (expected): {exc}")

        try:
            new_ap = self._audio_factory()
            new_ap.start()
            self._on_audio_replace(new_ap)
            with self._lock:
                self._audio_proc = new_ap
            self._audio_health.record_healthy()
            self._on_event("audio", "restarted", f"attempt {self._audio_health.restart_count}")
            logger.info("[Watchdog] Audio processor restarted successfully")
        except Exception as exc:
            logger.error(f"[Watchdog] Audio restart failed: {exc}")
            self._on_event("audio", "restart_failed", str(exc))
