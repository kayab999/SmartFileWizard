from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..facts import IMAGE_EXTENSIONS
from .config import PerceptionConfig
from .extractors import LlamaHttpOcrExtractor, LlamaHttpVisionExtractor
from .http_openai import parse_vision_json

logger = logging.getLogger(__name__)

# Canonical labels (stage 1 / UI). Mapped to vision.* keys for rules.
DEFAULT_LABELS = [
    "factura",
    "recibo",
    "documento_escaneado",
    "formulario",
    "captura_pantalla",
    "foto_persona",
    "foto_paisaje",
    "foto_producto",
    "meme",
    "grafico",
    "diapositiva",
    "interfaz_web",
    "codigo",
]

LABEL_TO_VISION_KEY = {
    "factura": "invoice",
    "recibo": "invoice",
    "documento_escaneado": "document",
    "formulario": "document",
    "captura_pantalla": "screenshot",
    "foto_persona": "photo",
    "foto_paisaje": "photo",
    "foto_producto": "photo",
    "meme": "photo",
    "grafico": "document",
    "diapositiva": "document",
    "interfaz_web": "screenshot",
    "codigo": "screenshot",
    "unknown": "unknown",
}

# C2 (0.9.8): canonical vision-key → category. A dict-comprehension reverse
# keeps the LAST key per value (invoice→recibo, photo→meme), which
# systematically mislabeled stage-3 winners.
VISION_KEY_TO_LABEL = {
    "invoice": "factura",
    "document": "documento_escaneado",
    "screenshot": "captura_pantalla",
    "photo": "foto_persona",
    "unknown": "unknown",
}

# NOTE: "total" deliberately excluded (Fase 3): it appears in tickets,
# spreadsheets and memes. Require factura|invoice|subtotal (+date for
# confirmed) instead.
INVOICE_KEYWORDS = [
    "factura",
    "invoice",
    "iva",
    "vat",
    "nif",
    "cif",
    "subtotal",
    "recibo",
    "receipt",
]

DATE_RE = re.compile(r"\d{1,2}[/-]\d{1,2}[/-]\d{2,4}")


@dataclass
class CascadeThresholds:
    """Gating semantics: >= high → confirmed, stop; >= medium → OCR at
    most (no VLM); < medium → full pipeline incl. VLM."""

    high_confidence: float = 0.75
    medium_confidence: float = 0.50
    vlm_min_confidence: float = 0.70
    stage2_keyword_min_hits: int = 2


@dataclass
class CascadeResult:
    stage_used: int
    category: str
    confidence: float
    status: str  # confirmed | probable | rejected | unknown | error
    stages: dict[str, Any] = field(default_factory=dict)
    ocr_text: str = ""
    vision_scores: dict[str, float] = field(default_factory=dict)
    filename_slug: str = ""
    tags: list[str] = field(default_factory=list)
    reasoning: str = ""

    def to_features(self) -> dict[str, Any]:
        """Map cascade outcome into engine-consumable features."""
        vision: dict[str, Any] = dict(self.vision_scores)
        # Ensure mapped key from category has at least confidence
        vkey = LABEL_TO_VISION_KEY.get(self.category, self.category)
        if vkey and vkey != "unknown":
            vision[vkey] = max(float(vision.get(vkey, 0.0)), self.confidence)
        vision["provider"] = "cascade"
        vision["stage_used"] = self.stage_used
        vision["category"] = self.category
        vision["status"] = self.status

        out: dict[str, Any] = {
            "cascade": {
                "stage_used": self.stage_used,
                "category": self.category,
                "confidence": self.confidence,
                "status": self.status,
                "stages": self.stages,
                "filename_slug": self.filename_slug,
                "tags": self.tags,
                "reasoning": self.reasoning,
            },
            "vision": vision,
        }
        if self.ocr_text:
            out["ocr"] = {
                "text": self.ocr_text,
                "provider": "cascade",
                "source": f"stage_{self.stage_used}",
            }
        return out


def map_heuristic_category(features: dict[str, Any]) -> CascadeResult | None:
    """
    Stage 0 hard rules from existing heuristics (no ML).

    High confidence shortcuts used before SigLIP/VLM.
    """
    patterns = set(features.get("filename_patterns") or [])
    if "screenshot" in patterns:
        # C1 parity (0.10.1): filename alone must not confirm — a rename to
        # *screenshot* would otherwise auto-confirm without pixels.
        return CascadeResult(
            stage_used=0,
            category="captura_pantalla",
            confidence=0.95,
            status="probable",
            stages={
                "0": {
                    "source": "filename_patterns",
                    "patterns": sorted(patterns),
                }
            },
            vision_scores={"screenshot": 0.95},
        )
    if "invoice" in patterns:
        # C1 (0.9.8): filename alone must not confirm an invoice — any
        # rename to *factura* would otherwise auto-confirm without OCR.
        # Probable continues to stage-2 OCR validation.
        return CascadeResult(
            stage_used=0,
            category="factura",
            confidence=0.90,
            status="probable",
            stages={
                "0": {
                    "source": "filename_patterns",
                    "patterns": sorted(patterns),
                }
            },
            vision_scores={"invoice": 0.90, "document": 0.80},
        )
    if "scan" in patterns:
        return CascadeResult(
            stage_used=0,
            category="documento_escaneado",
            confidence=0.85,
            status="probable",
            stages={
                "0": {
                    "source": "filename_patterns",
                    "patterns": sorted(patterns),
                }
            },
            vision_scores={"document": 0.85, "scan": 0.85},
        )
    # Low-color large images often scans/docs (palette heuristic)
    uc = features.get("unique_colors")
    if isinstance(uc, int) and uc <= 64:
        return CascadeResult(
            stage_used=0,
            category="documento_escaneado",
            confidence=0.70,
            status="probable",
            stages={"0": {"source": "unique_colors", "unique_colors": uc}},
            vision_scores={"document": 0.70, "scan": 0.65},
        )
    return None


def _category_from_invoice_hint(hint: str, ocr_text: str) -> str:
    """Map OCR-validated document to a cascade category.

    Do not treat a non-empty status string as 'factura' (F2 / WP-0.8.2).
    """
    lower = (ocr_text or "").lower()
    if hint == "recibo" or (
        "recibo" in lower and "factura" not in lower and hint != "factura"
    ):
        return "recibo"
    if hint in {"factura"} or "factura" in lower:
        return "factura"
    if hint in {"documento_escaneado", "formulario"}:
        return hint
    return "factura" if hint == "unknown" else hint


def _invoice_evidence(ocr_text: str) -> tuple[int, bool]:
    """(keyword hits, has_date) for invoice validation."""
    lower = (ocr_text or "").lower()
    hits = sum(1 for kw in INVOICE_KEYWORDS if kw in lower)
    return hits, bool(DATE_RE.search(ocr_text or ""))


def validate_invoice_ocr(
    ocr_text: str,
    *,
    min_hits: int = 2,
) -> str:
    """Return confirmed | probable | rejected from OCR text.

    I4: a single generic hit (e.g. "total" alone) is rejected, not probable.
    """
    hits, has_date = _invoice_evidence(ocr_text)
    if hits >= min_hits and has_date:
        return "confirmed"
    if hits >= min_hits or (hits >= 1 and has_date):
        return "probable"
    return "rejected"


def invoice_confidence(status: str, hits: int) -> float:
    """Confidence scaled by evidence instead of hardcoded constants (I4).

    Probable stays below high_confidence so stage-3 VLM still runs.
    """
    if status == "confirmed":
        return min(0.95, 0.85 + 0.02 * max(hits, 0))
    return min(0.70, 0.55 + 0.05 * max(hits, 0))


class CascadeExtractor:
    """
    FeatureExtractor: cheap-first cascade.

    Stage 0: heuristics (always if parent provided features merge)
    Stage 1: zeroshot CLIP/SigLIP (optional; zeroshot_fn / filewizard[zeroshot])
    Stage 2: OCR (GLM-OCR / tesseract via extractors)
    Stage 3: VLM JSON (Qwen via llama_http)

    Stages 2–3 only run when enabled and earlier stages are not confirmed.
    """

    name = "cascade"

    def __init__(
        self,
        config: PerceptionConfig,
        *,
        thresholds: CascadeThresholds | None = None,
        enable_stage2: bool = True,
        enable_stage3: bool = True,
        zeroshot_fn=None,
    ):
        self.config = config
        self.thresholds = thresholds or CascadeThresholds()
        self.enable_stage2 = enable_stage2
        self.enable_stage3 = enable_stage3
        self.zeroshot_fn = zeroshot_fn  # (path, labels) -> list[{label,score}]

        ocr = config.ocr
        vision = config.vision
        # model_copy(update={...}) may leave nested dicts; normalize.
        if isinstance(ocr, dict):
            from .config import OcrSettings

            ocr = OcrSettings.model_validate(ocr)
        if isinstance(vision, dict):
            from .config import VisionSettings

            vision = VisionSettings.model_validate(vision)

        self._ocr = None
        if ocr.provider == "llama_http":
            self._ocr = LlamaHttpOcrExtractor(ocr)
        elif ocr.provider == "tesseract":
            from .extractors import TesseractOcrExtractor

            self._ocr = TesseractOcrExtractor(ocr)

        self._vlm = None
        if vision.provider == "llama_http":
            self._vlm = LlamaHttpVisionExtractor(vision)

    def extract(self, path: Path) -> dict[str, Any]:
        if path.suffix.lower() not in IMAGE_EXTENSIONS and not str(
            path.suffix
        ).lower().endswith(
            tuple(IMAGE_EXTENSIONS)
        ):
            # Non-images: cascade does nothing
            mime_ok = False
            try:
                import mimetypes

                mime, _ = mimetypes.guess_type(path.name)
                mime_ok = bool(mime and mime.startswith("image/"))
            except Exception:
                mime_ok = False
            if not mime_ok:
                return {}

        # Stage 0 needs heuristic features first — run lightweight patterns only
        from ..plugins.heuristics import ImageHeuristics

        h = ImageHeuristics().extract(path)
        stage0 = map_heuristic_category(h)
        if stage0 is not None and stage0.status == "confirmed":
            feats = stage0.to_features()
            # Keep raw heuristic side-channel
            if h.get("filename_patterns"):
                feats.setdefault("filename_patterns", h["filename_patterns"])
            if h.get("date_taken"):
                feats["date_taken"] = h["date_taken"]
                feats["date_source"] = h.get("date_source")
            return feats

        result = stage0  # may be probable from stage 0
        stages: dict[str, Any] = {}
        if stage0:
            stages["0"] = stage0.stages.get("0", stage0.stages)

        # Stage 1: zero-shot (optional)
        top_label = stage0.category if stage0 else "unknown"
        top_score = stage0.confidence if stage0 else 0.0

        if self.zeroshot_fn is not None:
            try:
                preds = self.zeroshot_fn(path, DEFAULT_LABELS) or []
                if preds:
                    top_label = preds[0]["label"]
                    top_score = float(preds[0]["score"])
                    stages["1"] = {
                        "provider": "zeroshot",
                        "top_label": top_label,
                        "top_score": top_score,
                        "scores": {
                            p["label"]: float(p["score"]) for p in preds[:13]
                        },
                    }
                    if top_score >= self.thresholds.high_confidence:
                        result = CascadeResult(
                            stage_used=1,
                            category=top_label,
                            confidence=top_score,
                            status="confirmed",
                            stages=stages,
                            vision_scores={
                                LABEL_TO_VISION_KEY.get(top_label, top_label): top_score
                            },
                        )
                        return self._merge_h(h, result)
            except Exception as exc:
                stages["1"] = {"error": str(exc)}
                logger.warning("stage1 zeroshot failed: %s", exc)

        need_stage2 = (
            self.enable_stage2
            and self._ocr is not None
            and (
                result is None
                or result.status != "confirmed"
                or top_score < self.thresholds.high_confidence
            )
        )

        ocr_text = ""
        if need_stage2:
            try:
                ocr_out = self._ocr.extract(path)
                ocr_block = ocr_out.get("ocr") or {}
                ocr_text = str(ocr_block.get("text") or "")
                stages["2"] = {
                    "provider": ocr_block.get("provider"),
                    "model": ocr_block.get("model"),
                    "text_len": len(ocr_text),
                    "error": ocr_block.get("error"),
                }
                # Invoice-oriented validation when hint suggests document
                hint = top_label
                if hint in {
                    "factura",
                    "recibo",
                    "documento_escaneado",
                    "formulario",
                    "unknown",
                } or (result and result.category in {"factura", "recibo"}):
                    status = validate_invoice_ocr(
                        ocr_text,
                        min_hits=self.thresholds.stage2_keyword_min_hits,
                    )
                    if status != "rejected":
                        hits, _ = _invoice_evidence(ocr_text)
                        conf = invoice_confidence(status, hits)
                        result = CascadeResult(
                            stage_used=2,
                            category=_category_from_invoice_hint(hint, ocr_text),
                            confidence=conf,
                            status=status,
                            stages=stages,
                            ocr_text=ocr_text,
                            vision_scores={
                                "invoice": conf,
                                "document": 0.8,
                            },
                        )
                        if status == "confirmed":
                            return self._merge_h(h, result)
                elif ocr_text and top_label == "captura_pantalla":
                    result = CascadeResult(
                        stage_used=2,
                        category="captura_pantalla",
                        confidence=max(top_score, 0.7),
                        status="probable",
                        stages=stages,
                        ocr_text=ocr_text,
                        vision_scores={"screenshot": max(top_score, 0.7)},
                    )
            except Exception as exc:
                stages["2"] = {"error": str(exc)}
                logger.warning("stage2 ocr failed: %s", exc)

        # I4: medium_confidence gates VLM. Scores in [medium, high) stop
        # after stage-2 OCR; VLM runs only on hard failures or low scores.
        need_stage3 = (
            self.enable_stage3
            and self._vlm is not None
            and (
                result is None
                or result.status in {"rejected", "unknown", "error"}
                or top_score < self.thresholds.medium_confidence
            )
        )

        if need_stage3:
            try:
                v_out = self._vlm.extract(path)
                vision = v_out.get("vision") or {}
                stages["3"] = {
                    "provider": vision.get("provider"),
                    "model": vision.get("model"),
                    "error": vision.get("error"),
                }
                # Prefer structured labels from vision extractor
                scores = {
                    k: float(v)
                    for k, v in vision.items()
                    if k
                    not in {
                        "provider",
                        "model",
                        "error",
                        "raw",
                        "stage_used",
                        "category",
                        "status",
                    }
                    and isinstance(v, (int, float))
                }
                if scores:
                    best = max(scores.items(), key=lambda kv: kv[1])
                    # Map vision keys back to category when possible
                    cat = VISION_KEY_TO_LABEL.get(best[0], best[0])
                    conf = best[1]
                    status = (
                        "confirmed"
                        if conf >= self.thresholds.vlm_min_confidence
                        else "unknown"
                    )
                    ocr_from_v = (v_out.get("ocr") or {}).get("text") or ocr_text
                    result = CascadeResult(
                        stage_used=3,
                        category=cat if status == "confirmed" else "unknown",
                        confidence=conf,
                        status=status,
                        stages=stages,
                        ocr_text=str(ocr_from_v or ""),
                        vision_scores=scores,
                    )
                elif vision.get("raw") or vision.get("error"):
                    # Try parse raw if present
                    raw = str(vision.get("raw") or "")
                    parsed = parse_vision_json(raw, list(scores.keys()) or ["photo"])
                    result = CascadeResult(
                        stage_used=3,
                        category="unknown",
                        confidence=0.0,
                        status="unknown",
                        stages={**stages, "3_parse": parsed},
                        ocr_text=ocr_text,
                    )
            except Exception as exc:
                stages["3"] = {"error": str(exc)}
                logger.warning("stage3 vlm failed: %s", exc)

        if result is None:
            result = CascadeResult(
                stage_used=0,
                category="unknown",
                confidence=0.0,
                status="unknown",
                stages=stages or {"0": h},
                ocr_text=ocr_text,
            )
        else:
            result.stages = {**stages, **result.stages}

        return self._merge_h(h, result)

    @staticmethod
    def _merge_h(h: dict[str, Any], result: CascadeResult) -> dict[str, Any]:
        feats = result.to_features()
        for key in (
            "filename_patterns",
            "date_taken",
            "date_source",
            "exif",
            "unique_colors",
        ):
            if key in h:
                feats[key] = h[key]
        return feats
