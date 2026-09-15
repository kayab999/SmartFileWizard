from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field

from ..persist import atomic_write_text


class OcrSettings(BaseModel):
    provider: Literal["none", "tesseract", "llama_http"] = "none"
    base_url: str = "http://127.0.0.1:8080/v1"
    model: str = "GLM-OCR-Q8_0"
    timeout_s: float = 120.0
    max_image_edge: int = 1600
    temperature: float = 0.0
    langs: str | None = None  # tesseract


class VisionSettings(BaseModel):
    provider: Literal["none", "llama_http"] = "none"
    base_url: str = "http://127.0.0.1:8081/v1"
    model: str = "Qwen3-VL-2B-Instruct"
    timeout_s: float = 120.0
    max_image_edge: int = 1280
    temperature: float = 0.0
    labels: list[str] = Field(
        default_factory=lambda: [
            "screenshot",
            "document",
            "photo",
            "scan",
            "invoice",
            "social",
        ]
    )


class CascadeSettings(BaseModel):
    """Cheap-first cascade thresholds (see docs/PLAN_CASCADE.md)."""

    enabled: bool = False
    high_confidence: float = 0.75
    medium_confidence: float = 0.50
    vlm_min_confidence: float = 0.70
    stage2_keyword_min_hits: int = 2
    enable_stage1: bool = True  # zero-shot CLIP/SigLIP if deps installed
    enable_stage2: bool = True
    enable_stage3: bool = True
    zeroshot_model: str = "openai/clip-vit-base-patch32"
    # HuggingFace download of CLIP/SigLIP weights (can be hundreds of MB).
    allow_model_download: bool = False


class CacheSettings(BaseModel):
    """Disk cache of perception features keyed by file content hash."""

    enabled: bool = True
    max_entries: int = 5000
    max_bytes: int = 64 * 1024 * 1024


class PerceptionConfig(BaseModel):
    version: int = 1
    heuristics: bool = True
    ocr: OcrSettings = Field(default_factory=OcrSettings)
    vision: VisionSettings = Field(default_factory=VisionSettings)
    cascade: CascadeSettings = Field(default_factory=CascadeSettings)
    cache: CacheSettings = Field(default_factory=CacheSettings)
    profile: str | None = None


# Built-in hardware / usage profiles (defaults product).
PROFILES: dict[str, dict[str, Any]] = {
    "lite": {
        "heuristics": True,
        "ocr": {"provider": "tesseract"},
        "vision": {"provider": "none"},
    },
    "recommended": {
        "heuristics": True,
        "ocr": {
            "provider": "llama_http",
            "base_url": "http://127.0.0.1:8080/v1",
            "model": "GLM-OCR-Q8_0",
        },
        "vision": {
            "provider": "llama_http",
            "base_url": "http://127.0.0.1:8081/v1",
            "model": "Qwen3-VL-2B-Instruct",
        },
        # Cascade: barato primero; OCR/VLM solo si hace falta
        "cascade": {
            "enabled": True,
            "high_confidence": 0.75,
            "medium_confidence": 0.50,
            "vlm_min_confidence": 0.70,
            "enable_stage1": True,
            "enable_stage2": True,
            "enable_stage3": True,
        },
    },
    "cascade": {
        "heuristics": True,
        "ocr": {
            "provider": "llama_http",
            "base_url": "http://127.0.0.1:8080/v1",
            "model": "GLM-OCR-Q8_0",
        },
        "vision": {
            "provider": "llama_http",
            "base_url": "http://127.0.0.1:8081/v1",
            "model": "Qwen3-VL-2B-Instruct",
        },
        "cascade": {
            "enabled": True,
            "enable_stage1": True,
            "enable_stage2": True,
            "enable_stage3": True,
        },
    },
    "ocr_only": {
        "heuristics": True,
        "ocr": {
            "provider": "llama_http",
            "base_url": "http://127.0.0.1:8080/v1",
            "model": "GLM-OCR-Q8_0",
        },
        "vision": {"provider": "none"},
    },
    "vision_only": {
        "heuristics": True,
        "ocr": {"provider": "none"},
        "vision": {
            "provider": "llama_http",
            "base_url": "http://127.0.0.1:8081/v1",
            "model": "Qwen3-VL-2B-Instruct",
        },
    },
}


def default_config_path(state_dir: Path | None = None) -> Path:
    root = (state_dir or Path("~/.local/share/filewizard")).expanduser()
    return root / "perception.yaml"


def config_from_profile(name: str) -> PerceptionConfig:
    if name not in PROFILES:
        raise ValueError(
            f"Unknown perception profile {name!r}. "
            f"Known: {', '.join(sorted(PROFILES))}"
        )
    data = {"profile": name, **PROFILES[name]}
    return PerceptionConfig.model_validate(data)


def load_perception_config(
    path: Path | None = None,
    *,
    profile: str | None = None,
    state_dir: Path | None = None,
) -> PerceptionConfig:
    """
    Load perception config.

    Priority:
      1. explicit profile name (built-in)
      2. YAML file (path or default state_dir/perception.yaml)
      3. lite defaults (heuristics only; OCR off until requested)
    """
    if profile:
        return config_from_profile(profile)

    cfg_path = path or default_config_path(state_dir)
    if cfg_path.is_file():
        raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
        if isinstance(raw, dict) and raw.get("profile") in PROFILES:
            # Merge profile defaults then overlay file fields.
            base = dict(PROFILES[str(raw["profile"])])
            base.update({k: v for k, v in raw.items() if k != "profile"})
            base["profile"] = raw["profile"]
            return PerceptionConfig.model_validate(base)
        return PerceptionConfig.model_validate(raw)

    # Safe default: no remote models until user opts in.
    return PerceptionConfig()


def save_perception_config(
    config: PerceptionConfig,
    path: Path | None = None,
    state_dir: Path | None = None,
) -> Path:
    out = path or default_config_path(state_dir)
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = config.model_dump(mode="python")
    atomic_write_text(
        out,
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
    )
    return out
