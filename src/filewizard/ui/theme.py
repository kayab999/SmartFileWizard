"""Dark QSS theme and packaged UI asset paths."""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

BG = "#1A1A1D"
SURFACE = "#242428"
SURFACE_HOVER = "#2E2E33"
ACCENT_START = "#8B5CF6"
ACCENT_END = "#06B6D4"
ALERT = "#F59E0B"
SUCCESS = "#10B981"
TEXT = "#F3F4F6"
MUTED = "#9CA3AF"

_ASSETS = Path(__file__).resolve().parent / "assets"
_QSS = Path(__file__).resolve().parent / "style.qss"


def assets_dir() -> Path:
    return _ASSETS


def asset_path(name: str) -> Path:
    return _ASSETS / name


def load_qss() -> str:
    """Load the dark stylesheet; fall back to unstyled Qt on any failure.

    I1: a missing/corrupt style.qss must never abort GUI startup.
    """
    try:
        return _QSS.read_text(encoding="utf-8")
    except Exception as exc:
        logger.warning("Could not load stylesheet %s: %s", _QSS, exc)
        return ""
