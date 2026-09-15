"""Pluggable OCR / vision perception (evidence only)."""

from .config import PerceptionConfig, load_perception_config
from .factory import build_extractors, perception_status

__all__ = [
    "PerceptionConfig",
    "load_perception_config",
    "build_extractors",
    "perception_status",
]
