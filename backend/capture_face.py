"""
capture_face.py — PrankCam Live Face Capture
=============================================
Captures a single frame from the webcam (or uses the latest preview JPEG
already produced by VideoProcessor) and saves it as a face image the user
can immediately use as a persona target.

Flow:
  1. GET /capture/face  →  grabs current webcam frame
  2. Detects faces in frame (using FaceAnalyzer)
  3. Crops the face region with some padding
  4. Saves to ~/.prankcam/captures/<timestamp>.jpg
  5. Returns the saved path + a base64 thumbnail for the UI to display
"""

from __future__ import annotations

import base64
import logging
import time
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

logger = logging.getLogger(__name__)

# ── Storage ───────────────────────────────────────────────────────────────────
_BACKEND_DIR  = Path(__file__).parent
CAPTURES_DIR  = _BACKEND_DIR.parent / "data" / "captures"
CAPTURES_DIR.mkdir(parents=True, exist_ok=True)


# ── Capture ───────────────────────────────────────────────────────────────────

def capture_face_from_frame(
    frame_bgr: np.ndarray,
    face_analyzer,          # FaceAnalyzer instance from ml_pipeline
    padding_fraction: float = 0.25,
) -> dict:
    """
    Given a BGR frame, detect the largest face, crop it with padding,
    save as JPEG, and return metadata.

    Returns:
        {
          "success": bool,
          "path": str | None,           absolute path to saved JPEG
          "thumbnail_b64": str | None,  base64-encoded 128×128 JPEG
          "face_found": bool,
          "message": str
        }
    """
    h, w = frame_bgr.shape[:2]

    faces = face_analyzer.get_faces(frame_bgr)
    if not faces:
        # No face detected — save the full frame anyway so user can still use it
        logger.info("[Capture] No face detected — saving full frame")
        saved_path = _save_frame(frame_bgr)
        thumb_b64  = _make_thumbnail_b64(frame_bgr)
        return {
            "success": True,
            "path": str(saved_path),
            "thumbnail_b64": thumb_b64,
            "face_found": False,
            "message": "No face detected — full frame saved. You can still use it as a target.",
        }

    # Pick the largest face by bbox area
    largest = max(
        faces,
        key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]),
    )
    x1, y1, x2, y2 = largest.bbox.astype(int)

    # Add padding
    bw = x2 - x1
    bh = y2 - y1
    pad_x = int(bw * padding_fraction)
    pad_y = int(bh * padding_fraction)
    x1 = max(0, x1 - pad_x)
    y1 = max(0, y1 - pad_y)
    x2 = min(w, x2 + pad_x)
    y2 = min(h, y2 + pad_y)

    cropped     = frame_bgr[y1:y2, x1:x2].copy()
    saved_path  = _save_frame(cropped)
    thumb_b64   = _make_thumbnail_b64(cropped)

    logger.info("[Capture] Face captured → %s  (crop %dx%d)", saved_path.name, bw, bh)

    return {
        "success": True,
        "path": str(saved_path),
        "thumbnail_b64": thumb_b64,
        "face_found": True,
        "message": f"Face captured and saved as {saved_path.name}",
    }


def capture_from_camera(
    camera_index: int,
    face_analyzer,
    width: int = 640,
    height: int = 480,
) -> dict:
    """
    Open the webcam directly (when no pipeline is running), grab one frame,
    close the camera, and call capture_face_from_frame().
    """
    cap = cv2.VideoCapture(camera_index, cv2.CAP_ANY)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH,  width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

    if not cap.isOpened():
        return {
            "success": False,
            "path": None,
            "thumbnail_b64": None,
            "face_found": False,
            "message": f"Cannot open camera {camera_index}",
        }

    # Discard first few frames (exposure adjustment on some cams)
    for _ in range(3):
        cap.read()

    ret, frame = cap.read()
    cap.release()

    if not ret or frame is None:
        return {
            "success": False,
            "path": None,
            "thumbnail_b64": None,
            "face_found": False,
            "message": "Failed to read frame from camera",
        }

    return capture_face_from_frame(frame, face_analyzer)


def list_captures() -> list[dict]:
    """Return metadata for all saved captures, newest first."""
    result = []
    for p in sorted(CAPTURES_DIR.glob("*.jpg"), key=lambda f: f.stat().st_mtime, reverse=True):
        result.append({
            "name":     p.stem,
            "path":     str(p),
            "size_kb":  round(p.stat().st_size / 1024, 1),
            "created":  p.stat().st_mtime,
        })
    return result


def delete_capture(filename: str) -> bool:
    """Delete a capture by filename (stem or full name)."""
    # Accept both "1234567890" and "1234567890.jpg"
    if not filename.endswith(".jpg"):
        filename += ".jpg"
    target = CAPTURES_DIR / filename
    if target.exists() and target.parent == CAPTURES_DIR:
        target.unlink()
        return True
    return False


# ── Helpers ───────────────────────────────────────────────────────────────────

def _save_frame(frame: np.ndarray) -> Path:
    ts   = int(time.time() * 1000)
    path = CAPTURES_DIR / f"capture_{ts}.jpg"
    cv2.imwrite(str(path), frame, [cv2.IMWRITE_JPEG_QUALITY, 92])
    return path


def _make_thumbnail_b64(frame: np.ndarray, size: int = 128) -> str:
    """Resize frame to size×size, return base64-encoded JPEG."""
    h, w = frame.shape[:2]
    s    = min(h, w)
    y0   = (h - s) // 2
    x0   = (w - s) // 2
    crop = frame[y0: y0 + s, x0: x0 + s]
    thumb = cv2.resize(crop, (size, size), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", thumb, [cv2.IMWRITE_JPEG_QUALITY, 80])
    if not ok:
        return ""
    return base64.b64encode(buf.tobytes()).decode()
