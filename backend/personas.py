"""
personas.py — PrankCam Persona Storage
Manages a JSON file (~/.prankcam/personas.json) that stores named
face+voice configurations so users can hot-swap personas without
re-picking files every session.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Storage location
# ---------------------------------------------------------------------------

def _data_dir() -> Path:
    """Platform-aware config directory."""
    base = os.environ.get("PRANKCAM_DATA_DIR")
    if base:
        return Path(base)
    if os.name == "nt":
        base = os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")
    elif os.uname().sysname == "Darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return Path(base) / "prankcam"


DATA_DIR = _data_dir()
PERSONAS_FILE = DATA_DIR / "personas.json"
THUMBNAILS_DIR = DATA_DIR / "thumbnails"


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------

@dataclass
class Persona:
    id: str
    name: str
    face_image_path: str
    voice_model_path: Optional[str] = None
    camera_index: int = 0
    input_audio_device: Optional[int] = None
    output_audio_device: Optional[int] = None
    virtual_cam_device: Optional[str] = None
    fps: int = 30
    width: int = 640
    height: int = 480
    created_at: float = field(default_factory=time.time)
    last_used_at: Optional[float] = None
    # Relative path inside THUMBNAILS_DIR (set by store on save)
    thumbnail_path: Optional[str] = None

    @classmethod
    def from_dict(cls, d: dict) -> "Persona":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# PersonaStore
# ---------------------------------------------------------------------------

class PersonaStore:
    """
    Thread-safe, file-backed persona registry.

    All mutations immediately flush to PERSONAS_FILE so data survives
    crashes. Reads serve from an in-memory dict for speed.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._personas: dict[str, Persona] = {}
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        THUMBNAILS_DIR.mkdir(parents=True, exist_ok=True)
        self._load()

    # ------------------------------------------------------------------
    # Internal I/O
    # ------------------------------------------------------------------

    def _load(self) -> None:
        if not PERSONAS_FILE.exists():
            logger.info("[PersonaStore] No personas file — starting fresh")
            return
        try:
            raw = json.loads(PERSONAS_FILE.read_text(encoding="utf-8"))
            for item in raw:
                p = Persona.from_dict(item)
                self._personas[p.id] = p
            logger.info(f"[PersonaStore] Loaded {len(self._personas)} persona(s)")
        except Exception as exc:
            logger.error(f"[PersonaStore] Load failed: {exc} — starting fresh")

    def _flush(self) -> None:
        """Write personas to disk. Must be called with _lock held."""
        tmp = PERSONAS_FILE.with_suffix(".tmp")
        data = [p.to_dict() for p in self._personas.values()]
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(PERSONAS_FILE)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def list(self) -> list[Persona]:
        with self._lock:
            return sorted(self._personas.values(), key=lambda p: p.created_at, reverse=True)

    def get(self, persona_id: str) -> Optional[Persona]:
        with self._lock:
            return self._personas.get(persona_id)

    def create(
        self,
        name: str,
        face_image_path: str,
        voice_model_path: Optional[str] = None,
        **kwargs,
    ) -> Persona:
        p = Persona(
            id=str(uuid.uuid4()),
            name=name,
            face_image_path=face_image_path,
            voice_model_path=voice_model_path,
            **{k: v for k, v in kwargs.items() if k in Persona.__dataclass_fields__},
        )
        # Generate thumbnail
        p.thumbnail_path = self._generate_thumbnail(p.id, face_image_path)

        with self._lock:
            self._personas[p.id] = p
            self._flush()

        logger.info(f"[PersonaStore] Created persona {p.id!r} name={p.name!r}")
        return p

    def update(self, persona_id: str, **fields) -> Optional[Persona]:
        with self._lock:
            p = self._personas.get(persona_id)
            if p is None:
                return None
            allowed = set(Persona.__dataclass_fields__) - {"id", "created_at"}
            for k, v in fields.items():
                if k in allowed:
                    setattr(p, k, v)
            # Regenerate thumbnail if face changed
            if "face_image_path" in fields:
                p.thumbnail_path = self._generate_thumbnail(p.id, p.face_image_path)
            self._flush()
        logger.info(f"[PersonaStore] Updated persona {persona_id!r}")
        return p

    def touch(self, persona_id: str) -> None:
        """Record last-used timestamp."""
        with self._lock:
            p = self._personas.get(persona_id)
            if p:
                p.last_used_at = time.time()
                self._flush()

    def delete(self, persona_id: str) -> bool:
        with self._lock:
            p = self._personas.pop(persona_id, None)
            if p is None:
                return False
            # Remove thumbnail
            if p.thumbnail_path:
                thumb = THUMBNAILS_DIR / p.thumbnail_path
                if thumb.exists():
                    thumb.unlink(missing_ok=True)
            self._flush()
        logger.info(f"[PersonaStore] Deleted persona {persona_id!r}")
        return True

    def get_thumbnail_path(self, persona_id: str) -> Optional[Path]:
        with self._lock:
            p = self._personas.get(persona_id)
            if p and p.thumbnail_path:
                full = THUMBNAILS_DIR / p.thumbnail_path
                return full if full.exists() else None
        return None

    # ------------------------------------------------------------------
    # Thumbnail generation (64×64 face crop saved as JPEG)
    # ------------------------------------------------------------------

    def _generate_thumbnail(self, persona_id: str, image_path: str) -> Optional[str]:
        try:
            import cv2
            img = cv2.imread(image_path)
            if img is None:
                return None
            # Centre-square crop
            h, w = img.shape[:2]
            s = min(h, w)
            y0, x0 = (h - s) // 2, (w - s) // 2
            crop = img[y0: y0 + s, x0: x0 + s]
            thumb = cv2.resize(crop, (64, 64), interpolation=cv2.INTER_AREA)
            fname = f"{persona_id}.jpg"
            cv2.imwrite(str(THUMBNAILS_DIR / fname), thumb, [cv2.IMWRITE_JPEG_QUALITY, 80])
            return fname
        except Exception as exc:
            logger.warning(f"[PersonaStore] Thumbnail generation failed: {exc}")
            return None
