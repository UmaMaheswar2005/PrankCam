"""
logging_config.py — PrankCam Structured Logging
=================================================
Call configure_logging() once at startup (done in main.py).

Outputs:
  • Console  — coloured, human-readable
  • File     — ~/.prankcam/logs/prankcam.log with daily rotation, 7-day retention
"""

from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path

# ── Colours for the console handler ──────────────────────────────────────────
_RESET = "\033[0m"
_LEVEL_COLOURS = {
    logging.DEBUG:    "\033[36m",   # cyan
    logging.INFO:     "\033[32m",   # green
    logging.WARNING:  "\033[33m",   # yellow
    logging.ERROR:    "\033[31m",   # red
    logging.CRITICAL: "\033[35m",   # magenta
}


class _ColouredFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        colour = _LEVEL_COLOURS.get(record.levelno, "")
        record.levelname = f"{colour}{record.levelname:<8}{_RESET}"
        return super().format(record)


# ── Plain formatter for file output ──────────────────────────────────────────
_FILE_FMT = "%(asctime)s  %(levelname)-8s  %(name)s  %(message)s"
_CONSOLE_FMT = "%(asctime)s  %(levelname)s  %(name)s  %(message)s"
_DATE_FMT = "%Y-%m-%d %H:%M:%S"


def configure_logging(
    log_dir: Path,
    level: int = logging.INFO,
    console: bool = True,
) -> None:
    """
    Set up root logger. Safe to call multiple times (idempotent after first call).

    Parameters
    ----------
    log_dir : directory where prankcam.log will be written
    level   : root log level (default INFO)
    console : whether to also log to stdout
    """
    root = logging.getLogger()
    if root.handlers:
        return  # already configured

    root.setLevel(level)

    # ── Console handler ───────────────────────────────────────────────────────
    if console:
        ch = logging.StreamHandler(sys.stdout)
        ch.setLevel(level)
        # Only colour when the terminal supports it
        if sys.stdout.isatty():
            ch.setFormatter(_ColouredFormatter(_CONSOLE_FMT, datefmt=_DATE_FMT))
        else:
            ch.setFormatter(logging.Formatter(_CONSOLE_FMT, datefmt=_DATE_FMT))
        root.addHandler(ch)

    # ── Rotating file handler ─────────────────────────────────────────────────
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / "prankcam.log"
        fh = logging.handlers.TimedRotatingFileHandler(
            filename=str(log_path),
            when="midnight",
            backupCount=7,
            encoding="utf-8",
        )
        fh.setLevel(logging.DEBUG)  # capture everything to file
        fh.setFormatter(logging.Formatter(_FILE_FMT, datefmt=_DATE_FMT))
        root.addHandler(fh)
        logging.getLogger(__name__).info(f"Log file: {log_path}")
    except Exception as exc:
        logging.getLogger(__name__).warning(f"Could not open log file: {exc}")

    # ── Silence noisy third-party loggers ─────────────────────────────────────
    for noisy in ("uvicorn.access", "httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
