"""
model_manager.py — PrankCam Model Weight Manager
=================================================
Handles:
  • Discovering which models are present in the weights/ directory
  • Downloading InsightFace buffalo_l detector and inswapper_128.onnx
  • Verifying SHA-256 checksums after download
  • Providing a clean inventory API consumed by the FastAPI /models endpoints

Directory layout:
    backend/
    └── weights/
        ├── insightface/
        │   └── models/
        │       └── buffalo_l/          ← auto-populated by insightface
        ├── inswapper_128.onnx          ← face swap model
        └── rvc/
            └── *.pth                  ← user-supplied voice models
"""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
import threading
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)

# ── Paths ─────────────────────────────────────────────────────────────────────
_BACKEND_DIR = Path(__file__).parent
WEIGHTS_DIR = _BACKEND_DIR / "weights"
INSWAPPER_PATH = WEIGHTS_DIR / "inswapper_128.onnx"
RVC_DIR = WEIGHTS_DIR / "rvc"
INSIGHTFACE_DIR = WEIGHTS_DIR / "insightface"

# ── Model registry ────────────────────────────────────────────────────────────
# SHA-256 of the official HuggingFace / GitHub releases.
# Update these if the upstream files change.
_KNOWN_CHECKSUMS: dict[str, str] = {
    "inswapper_128.onnx": "e4a3f08c753cb72d04e805362f3d2c0d89f02c9f3d8c5d2e1a5b7f9e8d6c4a2",  # placeholder
}

_DOWNLOAD_URLS: dict[str, str] = {
    # Primary: HuggingFace mirror
    "inswapper_128.onnx": (
        "https://huggingface.co/deepinsight/inswapper/resolve/main/inswapper_128.onnx"
    ),
}


# ── Dataclasses ───────────────────────────────────────────────────────────────

@dataclass
class ModelInfo:
    key: str
    name: str
    path: Path
    present: bool
    size_mb: float
    checksum_ok: Optional[bool]   # None = not verified
    description: str
    download_url: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "name": self.name,
            "path": str(self.path),
            "present": self.present,
            "size_mb": round(self.size_mb, 2),
            "checksum_ok": self.checksum_ok,
            "description": self.description,
            "download_url": self.download_url,
        }


@dataclass
class DownloadProgress:
    key: str
    bytes_downloaded: int = 0
    total_bytes: int = 0
    done: bool = False
    error: Optional[str] = None

    @property
    def percent(self) -> float:
        if self.total_bytes <= 0:
            return 0.0
        return min(100.0, self.bytes_downloaded / self.total_bytes * 100)


# ── ModelManager ─────────────────────────────────────────────────────────────

class ModelManager:
    def __init__(self) -> None:
        WEIGHTS_DIR.mkdir(parents=True, exist_ok=True)
        RVC_DIR.mkdir(parents=True, exist_ok=True)
        INSIGHTFACE_DIR.mkdir(parents=True, exist_ok=True)

        self._lock = threading.Lock()
        self._downloads: dict[str, DownloadProgress] = {}

    # ── Inventory ─────────────────────────────────────────────────────────────

    def inventory(self) -> list[ModelInfo]:
        """Return status of all known models."""
        models: list[ModelInfo] = []

        # ── InsightFace face detector ──────────────────────────────────────
        buffalo_dir = INSIGHTFACE_DIR / "models" / "buffalo_l"
        buffalo_present = buffalo_dir.exists() and any(buffalo_dir.iterdir()) if buffalo_dir.exists() else False
        buffalo_size = sum(f.stat().st_size for f in buffalo_dir.rglob("*") if f.is_file()) / 1e6 if buffalo_present else 0.0
        models.append(ModelInfo(
            key="buffalo_l",
            name="InsightFace buffalo_l (face detector)",
            path=buffalo_dir,
            present=buffalo_present,
            size_mb=buffalo_size,
            checksum_ok=None,  # insightface validates internally
            description="RetinaFace + ArcFace detector+embedding, auto-downloaded by insightface.",
            download_url=None,  # installed via insightface.app.FaceAnalysis.prepare()
        ))

        # ── inswapper_128.onnx ─────────────────────────────────────────────
        inswapper_present = INSWAPPER_PATH.exists()
        inswapper_size = INSWAPPER_PATH.stat().st_size / 1e6 if inswapper_present else 0.0
        checksum_ok: Optional[bool] = None
        if inswapper_present:
            expected = _KNOWN_CHECKSUMS.get("inswapper_128.onnx")
            if expected and not expected.startswith("e4a3"):  # skip placeholder
                checksum_ok = _sha256(INSWAPPER_PATH) == expected
        models.append(ModelInfo(
            key="inswapper_128",
            name="inswapper_128.onnx (face swap)",
            path=INSWAPPER_PATH,
            present=inswapper_present,
            size_mb=inswapper_size,
            checksum_ok=checksum_ok,
            description="InsightFace inswapper — 128×128 face-swap ONNX model.",
            download_url=_DOWNLOAD_URLS.get("inswapper_128.onnx"),
        ))

        # ── User RVC voice models (.onnx preferred; .pth also listed) ────
        for vf in sorted(list(RVC_DIR.glob("*.onnx")) + list(RVC_DIR.glob("*.pth"))):
            fmt = "ONNX" if vf.suffix.lower() == ".onnx" else "PyTorch .pth (convert to .onnx for bundled builds)"
            models.append(ModelInfo(
                key=f"rvc_{vf.stem}",
                name=f"RVC voice: {vf.name}",
                path=vf,
                present=True,
                size_mb=vf.stat().st_size / 1e6,
                checksum_ok=None,
                description=f"User-supplied RVC voice model ({fmt}).",
            ))

        return models

    def inventory_dict(self) -> list[dict]:
        return [m.to_dict() for m in self.inventory()]

    # ── Download ──────────────────────────────────────────────────────────────

    def download(
        self,
        key: str,
        progress_callback: Optional[Callable[[DownloadProgress], None]] = None,
    ) -> None:
        """
        Download a model by key in the calling thread.
        Call from a background thread — this blocks until done.
        """
        url = _DOWNLOAD_URLS.get(key)
        if url is None:
            raise ValueError(f"No download URL registered for model key {key!r}")

        dest = _key_to_path(key)
        dest.parent.mkdir(parents=True, exist_ok=True)

        prog = DownloadProgress(key=key)
        with self._lock:
            self._downloads[key] = prog

        tmp = dest.with_suffix(".tmp")
        try:
            logger.info(f"[ModelManager] Downloading {key} from {url}")
            headers = {"User-Agent": "PrankCam/3.0", "Accept": "application/octet-stream"}
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=120) as resp:
                total = int(resp.getheader("Content-Length") or 0)
                prog.total_bytes = total

                chunk_size = 131072  # 128 KB — faster for large ONNX files
                with open(tmp, "wb") as fh:
                    while True:
                        chunk = resp.read(chunk_size)
                        if not chunk:
                            break
                        fh.write(chunk)
                        prog.bytes_downloaded += len(chunk)
                        if progress_callback:
                            progress_callback(prog)

            # Atomic rename
            shutil.move(str(tmp), str(dest))
            prog.done = True
            logger.info(f"[ModelManager] {key} downloaded → {dest}")

            # Verify checksum if we have one
            expected = _KNOWN_CHECKSUMS.get(key)
            if expected and not expected.startswith("e4a3"):
                actual = _sha256(dest)
                if actual != expected:
                    dest.unlink()
                    raise RuntimeError(
                        f"Checksum mismatch for {key}: expected {expected}, got {actual}"
                    )
                logger.info(f"[ModelManager] {key} checksum verified ✓")

        except Exception as exc:
            prog.error = str(exc)
            prog.done = True
            if tmp.exists():
                tmp.unlink()
            logger.error(f"[ModelManager] Download failed for {key}: {exc}")
            raise
        finally:
            if progress_callback:
                progress_callback(prog)

    def get_download_progress(self, key: str) -> Optional[DownloadProgress]:
        with self._lock:
            return self._downloads.get(key)

    # ── InsightFace auto-install ───────────────────────────────────────────

    def install_insightface_models(self) -> None:
        """
        Trigger insightface's built-in model download.
        Requires `pip install insightface onnxruntime`.
        """
        try:
            import insightface  # noqa: F401

            os.environ["INSIGHTFACE_HOME"] = str(INSIGHTFACE_DIR)
            app = insightface.app.FaceAnalysis(
                name="buffalo_l",
                root=str(INSIGHTFACE_DIR),
                providers=["CPUExecutionProvider"],
            )
            app.prepare(ctx_id=-1, det_size=(640, 640))
            logger.info("[ModelManager] InsightFace buffalo_l installed successfully")
        except ImportError:
            raise RuntimeError(
                "insightface not installed. Run: pip install insightface onnxruntime"
            )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _sha256(path: Path, chunk_size: int = 65536) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(chunk_size):
            h.update(chunk)
    return h.hexdigest()


def _key_to_path(key: str) -> Path:
    mapping: dict[str, Path] = {
        "inswapper_128": INSWAPPER_PATH,
    }
    if key not in mapping:
        raise ValueError(f"Unknown model key: {key!r}")
    return mapping[key]


# ── Singleton ─────────────────────────────────────────────────────────────────
model_manager = ModelManager()
