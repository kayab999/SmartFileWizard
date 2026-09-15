from __future__ import annotations

from pathlib import Path
from typing import Any

from ..facts import FeatureExtractor
from .cascade import CascadeExtractor, CascadeThresholds
from .config import PerceptionConfig, load_perception_config
from .extractors import (
    LlamaHttpOcrExtractor,
    LlamaHttpVisionExtractor,
    TesseractOcrExtractor,
)
from .http_openai import probe_server


def _maybe_wrap_cache(
    extractors: list[FeatureExtractor],
    cfg: PerceptionConfig,
    *,
    state_dir: Path | None,
) -> list[FeatureExtractor]:
    if not cfg.cache.enabled or not extractors:
        return extractors
    from .cache import CachingExtractor, PerceptionCache, config_fingerprint

    cache = PerceptionCache(
        state_dir=state_dir,
        max_entries=cfg.cache.max_entries,
        max_bytes=cfg.cache.max_bytes,
    )
    fp = config_fingerprint(cfg)
    return [
        CachingExtractor(inner, cache, config_fp=fp) for inner in extractors
    ]


def build_extractors(
    config: PerceptionConfig | None = None,
    *,
    force_ocr: bool = False,
    force_vision: bool = False,
    state_dir: Path | None = None,
) -> list[FeatureExtractor]:
    """
    Build the perception stack.

    If cascade.enabled: single CascadeExtractor (stage 0→2→3 as needed).
    Else: parallel legacy stack (heuristics + ocr + vision).
    """
    cfg = config or load_perception_config(state_dir=state_dir)
    extractors: list[FeatureExtractor] = []

    # Cascade mode (recommended): one orchestrator, not dual full-scan.
    if cfg.cascade.enabled:
        # Cascade includes heuristics internally (stage 0).
        th = CascadeThresholds(
            high_confidence=cfg.cascade.high_confidence,
            medium_confidence=cfg.cascade.medium_confidence,
            vlm_min_confidence=cfg.cascade.vlm_min_confidence,
            stage2_keyword_min_hits=cfg.cascade.stage2_keyword_min_hits,
        )
        # force_ocr with cascade off stage2 providers still need config;
        # if force_ocr and ocr is none, temporarily use tesseract for stage2.
        cascade_cfg = cfg
        if force_ocr and cfg.ocr.provider == "none":
            cascade_cfg = cfg.model_copy(
                update={"ocr": cfg.ocr.model_copy(update={"provider": "tesseract"})}
            )
        zeroshot_fn = None
        if cfg.cascade.enable_stage1:
            from .zeroshot import make_zeroshot_fn

            zeroshot_fn = make_zeroshot_fn(
                cfg.cascade.zeroshot_model,
                allow_download=cfg.cascade.allow_model_download,
            )

        extractors.append(
            CascadeExtractor(
                cascade_cfg,
                thresholds=th,
                enable_stage2=cfg.cascade.enable_stage2
                and (force_ocr or cfg.ocr.provider != "none"),
                enable_stage3=cfg.cascade.enable_stage3
                and (force_vision or cfg.vision.provider != "none"),
                zeroshot_fn=zeroshot_fn,
            )
        )
        return _maybe_wrap_cache(extractors, cfg, state_dir=state_dir)

    # --- Legacy parallel extractors ---
    if cfg.heuristics:
        from ..plugins.heuristics import ImageHeuristics

        extractors.append(ImageHeuristics())

    ocr_provider = cfg.ocr.provider
    if force_ocr and ocr_provider == "none":
        ocr_provider = "tesseract"

    if ocr_provider == "tesseract":
        extractors.append(TesseractOcrExtractor(cfg.ocr))
    elif ocr_provider == "llama_http":
        extractors.append(LlamaHttpOcrExtractor(cfg.ocr))

    use_vision = cfg.vision.provider == "llama_http" and (
        force_vision
        or cfg.profile in {"recommended", "vision_only"}
        or cfg.profile is None
    )
    if cfg.vision.provider == "llama_http" and cfg.profile is None:
        use_vision = True

    if use_vision and cfg.vision.provider == "llama_http":
        extractors.append(LlamaHttpVisionExtractor(cfg.vision))

    return _maybe_wrap_cache(extractors, cfg, state_dir=state_dir)


def perception_status(
    config: PerceptionConfig | None = None,
    *,
    state_dir: Path | None = None,
) -> dict[str, Any]:
    """Report configured providers and endpoint reachability."""
    cfg = config or load_perception_config(state_dir=state_dir)
    status: dict[str, Any] = {
        "profile": cfg.profile,
        "heuristics": cfg.heuristics,
        "cascade": {
            "enabled": cfg.cascade.enabled,
            "high_confidence": cfg.cascade.high_confidence,
            "medium_confidence": cfg.cascade.medium_confidence,
            "vlm_min_confidence": cfg.cascade.vlm_min_confidence,
            "enable_stage1": cfg.cascade.enable_stage1,
            "enable_stage2": cfg.cascade.enable_stage2,
            "enable_stage3": cfg.cascade.enable_stage3,
            "zeroshot_model": cfg.cascade.zeroshot_model,
        },
        "cache": {
            "enabled": cfg.cache.enabled,
            "max_entries": cfg.cache.max_entries,
        },
        "ocr": {
            "provider": cfg.ocr.provider,
            "model": (
                cfg.ocr.model if cfg.ocr.provider == "llama_http" else cfg.ocr.provider
            ),
            "base_url": (
                cfg.ocr.base_url if cfg.ocr.provider == "llama_http" else None
            ),
        },
        "vision": {
            "provider": cfg.vision.provider,
            "model": (
                cfg.vision.model if cfg.vision.provider == "llama_http" else None
            ),
            "base_url": (
                cfg.vision.base_url if cfg.vision.provider == "llama_http" else None
            ),
            "labels": cfg.vision.labels,
        },
        "endpoints": {},
    }

    if cfg.ocr.provider == "llama_http":
        status["endpoints"]["ocr"] = probe_server(cfg.ocr.base_url)
    if cfg.vision.provider == "llama_http":
        status["endpoints"]["vision"] = probe_server(cfg.vision.base_url)

    if cfg.cascade.enabled and cfg.cascade.enable_stage1:
        from .zeroshot import zeroshot_available

        status["zeroshot"] = {
            "available": zeroshot_available(),
            "model": cfg.cascade.zeroshot_model,
        }

    return status
