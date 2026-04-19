#!/usr/bin/env python3
"""
backend/rvc_export.py — Convert an RVC .pth checkpoint to .onnx
================================================================
Run this ONCE on a developer machine that has torch installed.
The resulting .onnx file works inside the bundled app (no torch needed).

Usage:
    # Install conversion dependencies (NOT in the bundled app)
    pip install torch==2.3.0 torchaudio==2.3.0 onnx==1.16.2 onnxsim==0.4.36

    # Export
    python backend/rvc_export.py \\
        --input  /path/to/my_voice.pth \\
        --output backend/weights/rvc/my_voice.onnx \\
        --opset  17

The .onnx file can then be selected as the voice model inside PrankCam.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
log = logging.getLogger("rvc_export")


# ── Argument parsing ──────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Export an RVC .pth voice model to .onnx for PrankCam.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--input",  "-i", required=True,  help="Path to input .pth checkpoint")
    p.add_argument("--output", "-o", required=True,  help="Path to write output .onnx file")
    p.add_argument("--opset",        type=int, default=17, help="ONNX opset version (default 17)")
    p.add_argument("--simplify",     action="store_true",  help="Run onnx-simplifier after export")
    p.add_argument("--sample-rate",  type=int, default=44100, help="Audio sample rate (default 44100)")
    p.add_argument("--chunk-frames", type=int, default=1024,  help="Input chunk size in frames (default 1024)")
    return p.parse_args()


# ── RVC model wrapper ─────────────────────────────────────────────────────────

class RVCWrapper:
    """
    Thin wrapper around a loaded RVC checkpoint that exposes a single
    forward(audio_chunk) → audio_chunk interface for ONNX tracing.

    Supports both the v1 and v2 SynthesizerTrnMs architectures.
    """

    def __init__(self, cpt: dict, device: str = "cpu") -> None:
        import torch
        import torch.nn as nn

        self.device = device
        self.sr = cpt.get("config", [44100])[0] if "config" in cpt else 44100

        # Detect model architecture version
        if "version" in cpt and cpt["version"] == "v2":
            from infer_pack.models import SynthesizerTrnMs768NSFsid  # type: ignore
            cfg = cpt["config"]
            self.model = SynthesizerTrnMs768NSFsid(*cfg, is_half=False)
        else:
            from infer_pack.models import SynthesizerTrnMs256NSFsid  # type: ignore
            cfg = cpt["config"]
            self.model = SynthesizerTrnMs256NSFsid(*cfg, is_half=False)

        self.model.load_state_dict(cpt["weight"], strict=False)
        self.model.eval()
        self.model.to(device)
        log.info("Loaded RVC model (arch=%s, sr=%d)", cpt.get("version", "v1"), self.sr)

    def forward(self, audio: "torch.Tensor") -> "torch.Tensor":
        """
        audio : (1, N) float32 on self.device
        returns (1, M) float32
        """
        import torch
        with torch.no_grad():
            # Simplified passthrough for ONNX export — the real forward
            # requires f0 computation which is done outside the model.
            # We export only the vocoder/decoder portion.
            return self.model.infer_pure(audio)


# ── Export ────────────────────────────────────────────────────────────────────

def export(args: argparse.Namespace) -> None:
    try:
        import torch
        import onnx
    except ImportError:
        log.error("torch and onnx are required. Run:  pip install torch onnx onnxsim")
        sys.exit(1)

    src = Path(args.input)
    dst = Path(args.output)

    if not src.exists():
        log.error("Input file not found: %s", src)
        sys.exit(1)

    dst.parent.mkdir(parents=True, exist_ok=True)

    # Load checkpoint
    log.info("Loading checkpoint: %s", src)
    cpt = torch.load(str(src), map_location="cpu")

    wrapper = RVCWrapper(cpt)
    sample_rate  = args.sample_rate
    chunk_frames = args.chunk_frames

    # Dummy input for tracing
    dummy_audio = torch.zeros(1, chunk_frames, dtype=torch.float32)

    log.info("Exporting to ONNX (opset %d)…", args.opset)
    torch.onnx.export(
        wrapper.model,
        dummy_audio,
        str(dst),
        export_params=True,
        opset_version=args.opset,
        do_constant_folding=True,
        input_names=["input"],
        output_names=["output"],
        dynamic_axes={
            "input":  {0: "batch", 1: "frames"},
            "output": {0: "batch", 1: "frames"},
        },
        verbose=False,
    )
    log.info("Exported to %s  (%.1f MB)", dst, dst.stat().st_size / 1e6)

    # Verify the graph is valid
    log.info("Verifying ONNX graph…")
    model_onnx = onnx.load(str(dst))
    onnx.checker.check_model(model_onnx)
    log.info("Graph check passed")

    # Optional: simplify with onnx-simplifier
    if args.simplify:
        try:
            from onnxsim import simplify as onnxsim  # type: ignore
            log.info("Running onnx-simplifier…")
            simplified, ok = onnxsim(model_onnx)
            if ok:
                onnx.save(simplified, str(dst))
                log.info("Simplified → %s  (%.1f MB)", dst, dst.stat().st_size / 1e6)
            else:
                log.warning("onnx-simplifier could not simplify this model — using original")
        except ImportError:
            log.warning("onnxsim not installed — skipping simplification. Run: pip install onnxsim")

    log.info("")
    log.info("Done! Place this file inside the app or select it as a voice model:")
    log.info("  %s", dst.resolve())


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    export(parse_args())
