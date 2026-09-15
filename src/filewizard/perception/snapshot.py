from __future__ import annotations

from typing import Any

# Enough for ocr_contains_* on cache hits; full invoice bodies stay out of disk.
MAX_CACHE_OCR_CHARS = 4000


def compact_cache_features(features: dict[str, Any]) -> dict[str, Any]:
    """Persistable copy of extractor output (no raw/stage OCR bodies).

    Keeps ``ocr.text`` truncated so ``ocr_contains_*`` still matches on
    cache hits. Journal snapshots remain even smaller (see
    ``perception_snapshot``).
    """
    out = dict(features)
    cascade = out.get("cascade")
    if isinstance(cascade, dict):
        cascade = dict(cascade)
        stages = cascade.get("stages")
        if isinstance(stages, dict):
            compact_stages: dict[str, Any] = {}
            for key, val in stages.items():
                if not isinstance(val, dict):
                    compact_stages[str(key)] = val
                    continue
                compact_stages[str(key)] = {
                    k: v for k, v in val.items() if k not in {"text", "raw"}
                }
            cascade["stages"] = compact_stages
        out["cascade"] = cascade
    ocr = out.get("ocr")
    if isinstance(ocr, dict):
        ocr = dict(ocr)
        text = str(ocr.get("text") or "")
        if len(text) > MAX_CACHE_OCR_CHARS:
            ocr["text"] = text[:MAX_CACHE_OCR_CHARS]
            ocr["text_truncated"] = True
        out["ocr"] = ocr
    vision = out.get("vision")
    if isinstance(vision, dict):
        out["vision"] = {k: v for k, v in vision.items() if k != "raw"}
    return out


def perception_snapshot(features: dict[str, Any] | None) -> dict[str, Any] | None:
    """
    Compact, journal-safe perception evidence.

    Omits full OCR bodies and huge stage dumps; keeps enough to audit
    “why was this classified this way?” after a batch.
    """
    if not features:
        return None

    out: dict[str, Any] = {}

    cascade = features.get("cascade")
    if isinstance(cascade, dict):
        stages_in = cascade.get("stages") or {}
        stages_out: dict[str, Any] = {}
        if isinstance(stages_in, dict):
            for stage_key, stage_val in stages_in.items():
                if not isinstance(stage_val, dict):
                    stages_out[str(stage_key)] = stage_val
                    continue
                compact = {
                    k: v
                    for k, v in stage_val.items()
                    if k not in {"text", "raw", "scores"}
                }
                if "scores" in stage_val and isinstance(stage_val["scores"], dict):
                    # keep top-3 labels only
                    scored = sorted(
                        stage_val["scores"].items(),
                        key=lambda kv: float(kv[1]) if isinstance(kv[1], (int, float)) else 0.0,
                        reverse=True,
                    )[:3]
                    compact["top_scores"] = {k: float(v) for k, v in scored}
                stages_out[str(stage_key)] = compact

        out["cascade"] = {
            "stage_used": cascade.get("stage_used"),
            "category": cascade.get("category"),
            "confidence": cascade.get("confidence"),
            "status": cascade.get("status"),
            "reasoning": (cascade.get("reasoning") or "")[:300] or None,
            "filename_slug": cascade.get("filename_slug") or None,
            "tags": cascade.get("tags") or [],
            "stages": stages_out,
            "cache_hit": cascade.get("cache_hit"),
        }
        # drop Nones
        out["cascade"] = {
            k: v for k, v in out["cascade"].items() if v is not None and v != []
        }

    ocr = features.get("ocr")
    if isinstance(ocr, dict):
        text = str(ocr.get("text") or "")
        out["ocr"] = {
            "provider": ocr.get("provider"),
            "model": ocr.get("model"),
            "text_len": len(text),
            "text_preview": text[:200] if text else "",
            "error": ocr.get("error"),
        }
        out["ocr"] = {k: v for k, v in out["ocr"].items() if v not in (None, "")}

    vision = features.get("vision")
    if isinstance(vision, dict):
        scores: dict[str, float] = {}
        meta: dict[str, Any] = {}
        skip = {"raw"}  # never persist bulky model dumps
        meta_keys = {
            "provider",
            "model",
            "error",
            "stage_used",
            "category",
            "status",
        }
        for key, value in vision.items():
            if key in skip:
                continue
            if key in meta_keys:
                if value is not None and value != "":
                    meta[key] = value
            elif isinstance(value, (int, float)):
                scores[key] = float(value)
        block: dict[str, Any] = {**meta}
        if scores:
            block["scores"] = scores
        if block:
            out["vision"] = block

    patterns = features.get("filename_patterns")
    if patterns:
        out["filename_patterns"] = list(patterns)

    if not out:
        return None
    return out


def format_perception_evidence(
    perception: dict[str, Any] | None,
) -> str:
    """One-line human summary for journal / preview tooltips (WP-0.8.4)."""
    if not perception:
        return ""
    cascade = perception.get("cascade")
    if not isinstance(cascade, dict):
        ocr = perception.get("ocr") or {}
        if ocr.get("text_preview"):
            return f"OCR: {str(ocr.get('text_preview'))[:80]}"
        return ""
    parts: list[str] = []
    cat = cascade.get("category")
    if cat:
        parts.append(str(cat))
    status = cascade.get("status")
    if status:
        parts.append(str(status))
    if cascade.get("stage_used") is not None:
        parts.append(f"etapa {cascade.get('stage_used')}")
    conf = cascade.get("confidence")
    if isinstance(conf, (int, float)):
        parts.append(f"{float(conf):.2f}")
    return " · ".join(parts)
