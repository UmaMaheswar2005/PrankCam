"""
content_packs.py — PrankCam Online Content Pack Manager
=========================================================
Handles fetching, caching, and installing face packs and voice packs
from a remote registry JSON file.

Registry JSON format (hosted at REGISTRY_URL):
{
  "version": 1,
  "faces": [
    {
      "id": "celebrity_pack_1",
      "name": "Movie Stars Pack",
      "description": "10 Hollywood face presets",
      "thumbnail_url": "https://…/thumb.jpg",
      "faces": [
        {
          "id": "actor_cage",
          "name": "Nicolas Cage",
          "image_url": "https://…/cage.jpg",
          "thumbnail_url": "https://…/cage_thumb.jpg",
          "license": "CC0"
        }
      ]
    }
  ],
  "voices": [
    {
      "id": "voice_british_male",
      "name": "British Male",
      "description": "Deep British accent",
      "thumbnail_url": "https://…/brit_thumb.jpg",
      "preview_url": "https://…/brit_preview.mp3",
      "model_url": "https://…/british_male.onnx",
      "size_mb": 45.2,
      "license": "CC BY 4.0"
    }
  ]
}

Since we don't have a live server yet, the registry falls back to a
BUILT-IN STARTER PACK of free, openly-licensed assets that work immediately.
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
import threading
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)

# ── Paths ─────────────────────────────────────────────────────────────────────
_BACKEND_DIR  = Path(__file__).parent
PACKS_DIR     = _BACKEND_DIR.parent / "data" / "packs"   # written to user data dir
FACES_DIR     = PACKS_DIR / "faces"
VOICES_DIR    = PACKS_DIR / "voices"
CACHE_FILE    = PACKS_DIR / "registry_cache.json"
CACHE_TTL_S   = 3600  # re-fetch registry at most once per hour

# ── Registry URL — replace with your own hosted JSON ─────────────────────────
# If this URL is unreachable, the built-in starter pack is used instead.
REGISTRY_URL = "https://raw.githubusercontent.com/prankcam/content-packs/main/registry.json"

# ── Built-in starter pack (works with zero server setup) ─────────────────────
# These are 100% free, openly-licensed images from WikiCommons / ThisPersonDoesNotExist.
# Replace or extend this list to curate your own preset collection.
_BUILTIN_REGISTRY: dict = {
    "version": 1,
    "faces": [
        {
            "id": "ai_generated_pack",
            "name": "AI Generated Faces",
            "description": "10 photorealistic AI faces — no real people, fully license-free",
            "faces": [
                {
                    "id": "aigen_01",
                    "name": "AI Face 1 — Young Woman",
                    "image_url": "https://thispersondoesnotexist.com/image",
                    "thumbnail_url": "https://thispersondoesnotexist.com/image",
                    "license": "Public Domain (AI generated)",
                },
                {
                    "id": "aigen_02",
                    "name": "AI Face 2 — Middle-aged Man",
                    "image_url": "https://thispersondoesnotexist.com/image",
                    "thumbnail_url": "https://thispersondoesnotexist.com/image",
                    "license": "Public Domain (AI generated)",
                },
            ],
        },
        {
            "id": "classic_art_pack",
            "name": "Classic Art Faces",
            "description": "Famous painted portraits — Mona Lisa, Girl with a Pearl Earring, etc.",
            "faces": [
                {
                    "id": "mona_lisa",
                    "name": "Mona Lisa (Leonardo da Vinci)",
                    "image_url": (
                        "https://upload.wikimedia.org/wikipedia/commons/thumb/"
                        "e/ec/Mona_Lisa%2C_by_Leonardo_da_Vinci%2C_from_C2RMF_retouched.jpg/"
                        "402px-Mona_Lisa%2C_by_Leonardo_da_Vinci%2C_from_C2RMF_retouched.jpg"
                    ),
                    "thumbnail_url": (
                        "https://upload.wikimedia.org/wikipedia/commons/thumb/"
                        "e/ec/Mona_Lisa%2C_by_Leonardo_da_Vinci%2C_from_C2RMF_retouched.jpg/"
                        "100px-Mona_Lisa%2C_by_Leonardo_da_Vinci%2C_from_C2RMF_retouched.jpg"
                    ),
                    "license": "Public Domain",
                },
                {
                    "id": "girl_pearl_earring",
                    "name": "Girl with a Pearl Earring (Vermeer)",
                    "image_url": (
                        "https://upload.wikimedia.org/wikipedia/commons/thumb/"
                        "0/0f/1665_Girl_with_a_Pearl_Earring.jpg/"
                        "376px-1665_Girl_with_a_Pearl_Earring.jpg"
                    ),
                    "thumbnail_url": (
                        "https://upload.wikimedia.org/wikipedia/commons/thumb/"
                        "0/0f/1665_Girl_with_a_Pearl_Earring.jpg/"
                        "100px-1665_Girl_with_a_Pearl_Earring.jpg"
                    ),
                    "license": "Public Domain",
                },
                {
                    "id": "self_portrait_rembrandt",
                    "name": "Self Portrait (Rembrandt, 1659)",
                    "image_url": (
                        "https://upload.wikimedia.org/wikipedia/commons/thumb/"
                        "b/bd/Rembrandt_van_Rijn_-_Self-Portrait_-_Google_Art_Project.jpg/"
                        "390px-Rembrandt_van_Rijn_-_Self-Portrait_-_Google_Art_Project.jpg"
                    ),
                    "thumbnail_url": (
                        "https://upload.wikimedia.org/wikipedia/commons/thumb/"
                        "b/bd/Rembrandt_van_Rijn_-_Self-Portrait_-_Google_Art_Project.jpg/"
                        "100px-Rembrandt_van_Rijn_-_Self-Portrait_-_Google_Art_Project.jpg"
                    ),
                    "license": "Public Domain",
                },
            ],
        },
    ],
    "voices": [
        {
            "id": "pitch_shift_pack",
            "name": "Pitch Shift Presets",
            "description": "Built-in pitch effects — no download needed",
            "voices": [
                {
                    "id": "pitch_up_4",
                    "name": "Higher Pitch (+4 semitones)",
                    "description": "Chipmunk-style higher voice",
                    "model_url": None,
                    "builtin": True,
                    "builtin_semitones": 4,
                    "size_mb": 0,
                    "license": "Built-in",
                },
                {
                    "id": "pitch_up_2",
                    "name": "Slightly Higher (+2 semitones)",
                    "description": "Subtle voice lift",
                    "model_url": None,
                    "builtin": True,
                    "builtin_semitones": 2,
                    "size_mb": 0,
                    "license": "Built-in",
                },
                {
                    "id": "pitch_down_3",
                    "name": "Deeper Voice (−3 semitones)",
                    "description": "Lower, more authoritative voice",
                    "model_url": None,
                    "builtin": True,
                    "builtin_semitones": -3,
                    "size_mb": 0,
                    "license": "Built-in",
                },
                {
                    "id": "pitch_down_6",
                    "name": "Very Deep Voice (−6 semitones)",
                    "description": "Deep movie-trailer style voice",
                    "model_url": None,
                    "builtin": True,
                    "builtin_semitones": -6,
                    "size_mb": 0,
                    "license": "Built-in",
                },
            ],
        },
    ],
}


# ── Dataclasses ───────────────────────────────────────────────────────────────

@dataclass
class FaceEntry:
    id: str
    name: str
    image_url: str
    thumbnail_url: str
    license: str
    local_path: Optional[str] = None       # set after download
    local_thumb_path: Optional[str] = None

    def is_downloaded(self) -> bool:
        return bool(self.local_path and Path(self.local_path).exists())

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "image_url": self.image_url,
            "thumbnail_url": self.thumbnail_url,
            "license": self.license,
            "local_path": self.local_path,
            "local_thumb_path": self.local_thumb_path,
            "downloaded": self.is_downloaded(),
        }


@dataclass
class FacePack:
    id: str
    name: str
    description: str
    faces: list[FaceEntry]

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "faces": [f.to_dict() for f in self.faces],
        }


@dataclass
class VoiceEntry:
    id: str
    name: str
    description: str
    model_url: Optional[str]
    size_mb: float
    license: str
    builtin: bool = False
    builtin_semitones: int = 0
    local_path: Optional[str] = None

    def is_downloaded(self) -> bool:
        if self.builtin:
            return True
        return bool(self.local_path and Path(self.local_path).exists())

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "model_url": self.model_url,
            "size_mb": self.size_mb,
            "license": self.license,
            "builtin": self.builtin,
            "builtin_semitones": self.builtin_semitones,
            "local_path": self.local_path,
            "downloaded": self.is_downloaded(),
        }


@dataclass
class VoicePack:
    id: str
    name: str
    description: str
    voices: list[VoiceEntry]

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "voices": [v.to_dict() for v in self.voices],
        }


# ── Download progress ─────────────────────────────────────────────────────────

@dataclass
class PackDownloadProgress:
    item_id: str
    bytes_downloaded: int = 0
    total_bytes: int = 0
    done: bool = False
    error: Optional[str] = None

    @property
    def percent(self) -> float:
        if self.total_bytes <= 0:
            return 0.0
        return min(100.0, self.bytes_downloaded / self.total_bytes * 100)

    def to_dict(self) -> dict:
        return {
            "item_id": self.item_id,
            "percent": round(self.percent, 1),
            "bytes_downloaded": self.bytes_downloaded,
            "total_bytes": self.total_bytes,
            "done": self.done,
            "error": self.error,
        }


# ── ContentPackManager ────────────────────────────────────────────────────────

class ContentPackManager:
    def __init__(self) -> None:
        FACES_DIR.mkdir(parents=True, exist_ok=True)
        VOICES_DIR.mkdir(parents=True, exist_ok=True)

        self._lock = threading.Lock()
        self._registry: dict = {}
        self._last_fetch: float = 0.0
        self._downloads: dict[str, PackDownloadProgress] = {}
        self._face_packs: list[FacePack] = []
        self._voice_packs: list[VoicePack] = []

        self._load_registry()

    # ── Registry loading ──────────────────────────────────────────────────────

    def _load_registry(self) -> None:
        """Load registry from cache or built-in, then try remote refresh."""
        # Start with built-in immediately (instant, no network)
        self._parse_registry(_BUILTIN_REGISTRY)

        # Load cached remote registry if fresh
        if CACHE_FILE.exists():
            try:
                cached = json.loads(CACHE_FILE.read_text())
                age = time.time() - cached.get("_cached_at", 0)
                if age < CACHE_TTL_S:
                    self._parse_registry(cached)
                    logger.info("[Packs] Loaded cached registry (age=%.0fs)", age)
                    return
            except Exception as exc:
                logger.debug("[Packs] Cache load failed: %s", exc)

        # Kick off background refresh
        threading.Thread(
            target=self._fetch_remote_registry, daemon=True, name="PackRegistryFetch"
        ).start()

    def _fetch_remote_registry(self) -> None:
        """Background: fetch registry.json from server, cache locally."""
        try:
            req = urllib.request.Request(
                REGISTRY_URL,
                headers={"User-Agent": "PrankCam/3.0", "Accept": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
                data["_cached_at"] = time.time()
                CACHE_FILE.write_text(json.dumps(data, indent=2))
                with self._lock:
                    self._parse_registry(data)
                logger.info("[Packs] Remote registry refreshed")
        except Exception as exc:
            logger.debug("[Packs] Remote registry unavailable: %s — using built-in", exc)

    def _parse_registry(self, data: dict) -> None:
        """Parse registry JSON into FacePack / VoicePack objects."""
        face_packs: list[FacePack] = []
        for pack_data in data.get("faces", []):
            faces = [
                FaceEntry(
                    id=f["id"],
                    name=f["name"],
                    image_url=f["image_url"],
                    thumbnail_url=f.get("thumbnail_url", f["image_url"]),
                    license=f.get("license", "Unknown"),
                    local_path=self._face_local_path(f["id"]),
                    local_thumb_path=self._face_thumb_path(f["id"]),
                )
                for f in pack_data.get("faces", [])
            ]
            face_packs.append(FacePack(
                id=pack_data["id"],
                name=pack_data["name"],
                description=pack_data.get("description", ""),
                faces=faces,
            ))

        voice_packs: list[VoicePack] = []
        for pack_data in data.get("voices", []):
            voices = [
                VoiceEntry(
                    id=v["id"],
                    name=v["name"],
                    description=v.get("description", ""),
                    model_url=v.get("model_url"),
                    size_mb=v.get("size_mb", 0),
                    license=v.get("license", "Unknown"),
                    builtin=v.get("builtin", False),
                    builtin_semitones=v.get("builtin_semitones", 0),
                    local_path=self._voice_local_path(v["id"]) if not v.get("builtin") else None,
                )
                for v in pack_data.get("voices", [])
            ]
            voice_packs.append(VoicePack(
                id=pack_data["id"],
                name=pack_data["name"],
                description=pack_data.get("description", ""),
                voices=voices,
            ))

        with self._lock:
            self._face_packs  = face_packs
            self._voice_packs = voice_packs

    # ── Path helpers ──────────────────────────────────────────────────────────

    @staticmethod
    def _face_local_path(face_id: str) -> Optional[str]:
        p = FACES_DIR / f"{face_id}.jpg"
        return str(p) if p.exists() else None

    @staticmethod
    def _face_thumb_path(face_id: str) -> Optional[str]:
        p = FACES_DIR / f"{face_id}_thumb.jpg"
        return str(p) if p.exists() else None

    @staticmethod
    def _voice_local_path(voice_id: str) -> Optional[str]:
        p = VOICES_DIR / f"{voice_id}.onnx"
        return str(p) if p.exists() else None

    # ── Public API ────────────────────────────────────────────────────────────

    def get_face_packs(self) -> list[FacePack]:
        with self._lock:
            return list(self._face_packs)

    def get_voice_packs(self) -> list[VoicePack]:
        with self._lock:
            return list(self._voice_packs)

    def get_download_progress(self, item_id: str) -> Optional[PackDownloadProgress]:
        with self._lock:
            return self._downloads.get(item_id)

    # ── Face download ─────────────────────────────────────────────────────────

    def download_face(
        self,
        face_id: str,
        image_url: str,
        thumbnail_url: str,
        progress_cb: Optional[Callable[[PackDownloadProgress], None]] = None,
    ) -> str:
        """Download face image, return local path."""
        dest      = FACES_DIR / f"{face_id}.jpg"
        dest_thumb = FACES_DIR / f"{face_id}_thumb.jpg"

        if dest.exists():
            return str(dest)

        prog = PackDownloadProgress(item_id=face_id)
        with self._lock:
            self._downloads[face_id] = prog

        try:
            self._http_download(image_url, dest, prog, progress_cb)
            # Also download thumbnail
            try:
                self._http_download(thumbnail_url, dest_thumb, PackDownloadProgress(item_id=face_id+"_thumb"))
            except Exception:
                pass  # thumb failure is non-fatal

            prog.done = True
            logger.info("[Packs] Face downloaded: %s → %s", face_id, dest)
            # Refresh local paths in face entries
            self._refresh_local_paths()
            return str(dest)
        except Exception as exc:
            prog.error = str(exc)
            prog.done = True
            logger.error("[Packs] Face download failed %s: %s", face_id, exc)
            raise
        finally:
            if progress_cb:
                progress_cb(prog)

    # ── Voice download ────────────────────────────────────────────────────────

    def download_voice(
        self,
        voice_id: str,
        model_url: str,
        progress_cb: Optional[Callable[[PackDownloadProgress], None]] = None,
    ) -> str:
        """Download voice .onnx model, return local path."""
        dest = VOICES_DIR / f"{voice_id}.onnx"

        if dest.exists():
            return str(dest)

        prog = PackDownloadProgress(item_id=voice_id)
        with self._lock:
            self._downloads[voice_id] = prog

        try:
            self._http_download(model_url, dest, prog, progress_cb)
            prog.done = True
            logger.info("[Packs] Voice downloaded: %s → %s", voice_id, dest)
            self._refresh_local_paths()
            return str(dest)
        except Exception as exc:
            prog.error = str(exc)
            prog.done = True
            logger.error("[Packs] Voice download failed %s: %s", voice_id, exc)
            raise
        finally:
            if progress_cb:
                progress_cb(prog)

    # ── HTTP download helper ──────────────────────────────────────────────────

    @staticmethod
    def _http_download(
        url: str,
        dest: Path,
        prog: PackDownloadProgress,
        cb: Optional[Callable] = None,
    ) -> None:
        tmp = dest.with_suffix(".tmp")
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "PrankCam/3.0"}
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                prog.total_bytes = int(resp.getheader("Content-Length") or 0)
                with open(tmp, "wb") as fh:
                    while True:
                        chunk = resp.read(65536)
                        if not chunk:
                            break
                        fh.write(chunk)
                        prog.bytes_downloaded += len(chunk)
                        if cb:
                            cb(prog)
            shutil.move(str(tmp), str(dest))
        finally:
            if tmp.exists():
                tmp.unlink(missing_ok=True)

    def _refresh_local_paths(self) -> None:
        """Update local_path fields after downloads complete."""
        with self._lock:
            for pack in self._face_packs:
                for face in pack.faces:
                    face.local_path      = self._face_local_path(face.id)
                    face.local_thumb_path = self._face_thumb_path(face.id)
            for pack in self._voice_packs:
                for voice in pack.voices:
                    if not voice.builtin:
                        voice.local_path = self._voice_local_path(voice.id)


# ── Singleton ─────────────────────────────────────────────────────────────────
content_packs = ContentPackManager()
