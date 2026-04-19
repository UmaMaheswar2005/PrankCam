"""
ml_pipeline.py — PrankCam Video Processing Pipeline  (onnxruntime edition)
===========================================================================
BREAKING CHANGE FROM PREVIOUS VERSION:
  • torch / torchvision REMOVED — inference now uses onnxruntime (50× smaller)
  • FaceAnalyzer now wraps insightface.app.FaceAnalysis directly (buffalo_l)
  • FaceSwapModel now calls inswapper_128.onnx via onnxruntime.InferenceSession
  • A deterministic MOCK path is still available when weights are absent,
    so the UI works immediately and degrades gracefully.

Dependencies (all in requirements.txt):
    onnxruntime==1.20.1
    insightface==0.7.3
    opencv-python-headless==4.10.0.84
    numpy==1.26.4
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

try:
    import onnxruntime as ort
    _ORT_AVAILABLE = True
except ImportError:
    _ORT_AVAILABLE = False

try:
    import insightface
    from insightface.app import FaceAnalysis as _InsightFaceAnalysis
    _INSIGHTFACE_AVAILABLE = True
except ImportError:
    _INSIGHTFACE_AVAILABLE = False

try:
    import pyvirtualcam
    _PVCAM_AVAILABLE = True
except ImportError:
    _PVCAM_AVAILABLE = False

logger = logging.getLogger(__name__)

# ── Weight paths (resolved relative to this file, then to user data dir) ──────
_WEIGHTS_DIR = Path(__file__).parent / "weights"
INSWAPPER_PATH = _WEIGHTS_DIR / "inswapper_128.onnx"
INSIGHTFACE_CACHE = _WEIGHTS_DIR / "insightface"


# ── Config ────────────────────────────────────────────────────────────────────

@dataclass
class FaceSwapConfig:
    target_face_path: str
    device: str = field(default_factory=lambda: "cuda" if _cuda_available() else "cpu")
    camera_index: int = 0
    fps: int = 30
    width: int = 640
    height: int = 480
    virtual_cam_device: Optional[str] = None


def _cuda_available() -> bool:
    if not _ORT_AVAILABLE:
        return False
    return "CUDAExecutionProvider" in ort.get_available_providers()


def _ort_providers(device: str) -> list[str]:
    if device == "cuda" and _cuda_available():
        return ["CUDAExecutionProvider", "CPUExecutionProvider"]
    return ["CPUExecutionProvider"]


# ── Face Analyser ─────────────────────────────────────────────────────────────

class FaceAnalyzer:
    """
    Wraps insightface.app.FaceAnalysis (buffalo_l detector + ArcFace embedder).
    Falls back to a deterministic geometric mock when insightface is not installed.
    """

    def __init__(self, device: str = "cpu") -> None:
        self.device = device
        self._app = None

        if _INSIGHTFACE_AVAILABLE:
            try:
                os.environ["INSIGHTFACE_HOME"] = str(INSIGHTFACE_CACHE)
                providers = _ort_providers(device)
                ctx = 0 if device == "cuda" else -1
                app = _InsightFaceAnalysis(
                    name="buffalo_l",
                    root=str(INSIGHTFACE_CACHE),
                    providers=providers,
                )
                app.prepare(ctx_id=ctx, det_size=(640, 640))
                self._app = app
                logger.info("[FaceAnalyzer] insightface buffalo_l loaded (device=%s)", device)
            except Exception as exc:
                logger.warning("[FaceAnalyzer] insightface load failed: %s — using mock", exc)
        else:
            logger.info("[FaceAnalyzer] insightface not installed — using geometric mock")

    @property
    def is_real(self) -> bool:
        return self._app is not None

    def get_faces(self, bgr_frame: np.ndarray) -> list:
        """
        Returns list of face objects each exposing:
            .bbox      float32[4]  (x1, y1, x2, y2)
            .kps       float32[5,2]
            .embedding float32[512]
        """
        if self._app is not None:
            try:
                return self._app.get(bgr_frame)
            except Exception as exc:
                logger.debug("[FaceAnalyzer] get() failed: %s", exc)
                return []
        return self._mock_face(bgr_frame)

    @staticmethod
    def _mock_face(frame: np.ndarray) -> list:
        h, w = frame.shape[:2]
        rng = np.random.default_rng(42)
        face = type("Face", (), {
            "bbox": np.array([w * .20, h * .10, w * .80, h * .90], dtype=np.float32),
            "embedding": (rng.standard_normal(512) / np.sqrt(512)).astype(np.float32),
            "kps": np.array([
                [w*.35, h*.35], [w*.65, h*.35], [w*.50, h*.55],
                [w*.38, h*.75], [w*.62, h*.75],
            ], dtype=np.float32),
        })()
        return [face]


# ── Face Swap Model ───────────────────────────────────────────────────────────

class FaceSwapModel:
    """
    Wraps inswapper_128.onnx via onnxruntime.
    Falls back to a colour-shift mock when the weights file is absent.
    """

    def __init__(self, device: str = "cpu") -> None:
        self.device = device
        self.target_embedding: Optional[np.ndarray] = None
        self._session: Optional["ort.InferenceSession"] = None
        self._input_name:  Optional[str] = None
        self._target_name: Optional[str] = None

        if _ORT_AVAILABLE and INSWAPPER_PATH.exists():
            try:
                sess_opts = ort.SessionOptions()
                sess_opts.inter_op_num_threads = 2
                sess_opts.intra_op_num_threads = 4
                sess_opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
                self._session = ort.InferenceSession(
                    str(INSWAPPER_PATH),
                    sess_options=sess_opts,
                    providers=_ort_providers(device),
                )
                inputs = self._session.get_inputs()
                self._input_name  = inputs[0].name   # face crop  (1,3,128,128)
                self._target_name = inputs[1].name   # embedding  (1,512)
                logger.info("[FaceSwapModel] inswapper_128.onnx loaded (device=%s)", device)
            except Exception as exc:
                logger.warning("[FaceSwapModel] ONNX load failed: %s — using mock", exc)
        else:
            if not INSWAPPER_PATH.exists():
                logger.info("[FaceSwapModel] inswapper_128.onnx not found — using colour-shift mock")
            elif not _ORT_AVAILABLE:
                logger.warning("[FaceSwapModel] onnxruntime not installed — using mock")

    @property
    def is_real(self) -> bool:
        return self._session is not None

    def load_target_from_image(self, target_bgr: np.ndarray, analyzer: FaceAnalyzer) -> None:
        faces = analyzer.get_faces(target_bgr)
        if not faces:
            raise ValueError("No face detected in target image.")
        emb = np.array(faces[0].embedding, dtype=np.float32)
        norm = float(np.linalg.norm(emb))
        self.target_embedding = emb / (norm + 1e-6)
        logger.info("[FaceSwapModel] target embedding loaded (norm≈1)")

    def swap_face(
        self,
        frame_bgr: np.ndarray,
        source_face,
        target_embedding: np.ndarray,
    ) -> np.ndarray:
        x1, y1, x2, y2 = source_face.bbox.astype(int)
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(frame_bgr.shape[1], x2), min(frame_bgr.shape[0], y2)
        if x2 <= x1 or y2 <= y1:
            return frame_bgr

        face_roi  = frame_bgr[y1:y2, x1:x2].copy()
        orig_h, orig_w = face_roi.shape[:2]

        if self._session is not None:
            face_result = self._onnx_forward(face_roi, target_embedding)
        else:
            face_result = self._mock_forward(face_roi, target_embedding)

        face_result = cv2.resize(face_result, (orig_w, orig_h))

        output = frame_bgr.copy()
        mask   = np.full(face_result.shape, 255, dtype=np.uint8)
        center = ((x1 + x2) // 2, (y1 + y2) // 2)
        try:
            output = cv2.seamlessClone(face_result, output, mask, center, cv2.NORMAL_CLONE)
        except cv2.error:
            output[y1:y2, x1:x2] = face_result
        return output

    def _onnx_forward(self, face_roi: np.ndarray, emb: np.ndarray) -> np.ndarray:
        """Run the real inswapper_128 ONNX graph."""
        inp = cv2.resize(face_roi, (128, 128))
        # BGR→RGB, HWC→CHW, normalise to [-1, 1]
        inp = inp[:, :, ::-1].astype(np.float32) / 127.5 - 1.0
        inp = inp.transpose(2, 0, 1)[None]  # (1, 3, 128, 128)
        emb_input = emb.reshape(1, -1).astype(np.float32)  # (1, 512)

        result = self._session.run(
            None,
            {self._input_name: inp, self._target_name: emb_input},
        )[0]  # (1, 3, 128, 128)

        # Undo normalisation, CHW→HWC, RGB→BGR
        out = ((result.squeeze().transpose(1, 2, 0) + 1.0) * 127.5).clip(0, 255).astype(np.uint8)
        return out[:, :, ::-1]  # back to BGR

    @staticmethod
    def _mock_forward(face_roi: np.ndarray, emb: np.ndarray) -> np.ndarray:
        """Deterministic colour-shift mock (no model weights needed)."""
        face_128 = cv2.resize(face_roi, (128, 128)).astype(np.float32)
        shift = float(emb[:3].mean()) * 18.0
        shifted = np.clip(face_128 + shift, 0, 255).astype(np.uint8)
        return shifted


# ── Video Processor ───────────────────────────────────────────────────────────

class VideoProcessor:
    def __init__(self, config: FaceSwapConfig) -> None:
        self.config = config
        self._analyzer = FaceAnalyzer(config.device)
        self._model    = FaceSwapModel(config.device)
        self._running  = False
        self._thread: Optional[threading.Thread] = None
        self._lock     = threading.Lock()
        self._fps_actual: float = 0.0
        self._preview_jpeg: Optional[bytes] = None
        self._preview_lock = threading.Lock()

    # ── Public ────────────────────────────────────────────────────────────────

    def load_persona(self, face_image_path: str) -> None:
        img = cv2.imread(face_image_path)
        if img is None:
            raise FileNotFoundError(f"Cannot load face image: {face_image_path!r}")
        self._model.load_target_from_image(img, self._analyzer)

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread  = threading.Thread(
            target=self._loop, daemon=True, name="VideoLoop",
        )
        self._thread.start()
        logger.info("[VideoProcessor] started")

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=6.0)
        logger.info("[VideoProcessor] stopped")

    def get_preview_jpeg(self) -> Optional[bytes]:
        with self._preview_lock:
            return self._preview_jpeg

    def get_status(self) -> dict:
        with self._lock:
            return {
                "running": self._running,
                "fps":     round(self._fps_actual, 1),
                "using_real_model": self._model.is_real,
                "using_real_detector": self._analyzer.is_real,
            }

    # ── Internal ──────────────────────────────────────────────────────────────

    def _loop(self) -> None:
        cap = cv2.VideoCapture(self.config.camera_index, cv2.CAP_ANY)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH,  self.config.width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.config.height)
        cap.set(cv2.CAP_PROP_FPS,          self.config.fps)
        cap.set(cv2.CAP_PROP_BUFFERSIZE,   1)

        if not cap.isOpened():
            logger.error("[VideoProcessor] cannot open camera %d", self.config.camera_index)
            self._running = False
            return

        w   = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h   = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = float(cap.get(cv2.CAP_PROP_FPS)) or float(self.config.fps)
        logger.info("[VideoProcessor] camera %d → %dx%d @ %.0f fps", self.config.camera_index, w, h, fps)

        # ── Attempt virtual camera ─────────────────────────────────────────────
        vcam = None
        if _PVCAM_AVAILABLE:
            vcam_kwargs: dict = dict(width=w, height=h, fps=fps, fmt=pyvirtualcam.PixelFormat.BGR)
            if self.config.virtual_cam_device:
                vcam_kwargs["device"] = self.config.virtual_cam_device
            try:
                vcam = pyvirtualcam.Camera(**vcam_kwargs).__enter__()
                logger.info("[VideoProcessor] virtual camera → %s", vcam.device)
            except Exception as exc:
                logger.warning("[VideoProcessor] virtual camera unavailable: %s", exc)

        stat_frames = 0
        stat_t0 = time.perf_counter()

        try:
            while self._running:
                ret, frame = cap.read()
                if not ret:
                    time.sleep(0.005)
                    continue

                processed = self._infer(frame)

                if vcam is not None:
                    vcam.send(processed)
                    vcam.sleep_until_next_frame()

                # Preview JPEG (quality=55 → ~15 KB at 640×480)
                ok, buf = cv2.imencode(".jpg", processed, [cv2.IMWRITE_JPEG_QUALITY, 55])
                if ok:
                    with self._preview_lock:
                        self._preview_jpeg = buf.tobytes()

                stat_frames += 1
                elapsed = time.perf_counter() - stat_t0
                if elapsed >= 2.0:
                    with self._lock:
                        self._fps_actual = stat_frames / elapsed
                    stat_frames = 0
                    stat_t0 = time.perf_counter()

        except Exception as exc:
            logger.error("[VideoProcessor] fatal: %s", exc, exc_info=True)
        finally:
            cap.release()
            if vcam is not None:
                try:
                    vcam.__exit__(None, None, None)
                except Exception:
                    pass
            self._running = False
            logger.info("[VideoProcessor] loop exited")

    def _infer(self, frame: np.ndarray) -> np.ndarray:
        if self._model.target_embedding is None:
            return frame
        try:
            faces = self._analyzer.get_faces(frame)
            if not faces:
                return frame
            return self._model.swap_face(frame, faces[0], self._model.target_embedding)
        except Exception as exc:
            logger.debug("[VideoProcessor] infer error: %s", exc)
            return frame
