from __future__ import annotations

import logging
import mimetypes
from pathlib import Path
from typing import Any

from ..facts import IMAGE_EXTENSIONS
from .config import OcrSettings, VisionSettings
from .http_openai import chat_completion_with_image, parse_vision_json
from .prompts import ocr_user_prompt, vision_labels_prompt

logger = logging.getLogger(__name__)


def _is_image(path: Path) -> bool:
    mime, _ = mimetypes.guess_type(path.name)
    return (mime is not None and mime.startswith("image/")) or (
        path.suffix.lower() in IMAGE_EXTENSIONS
    )


class TesseractOcrExtractor:
    name = "ocr"

    def __init__(self, settings: OcrSettings):
        self.settings = settings

    def extract(self, path: Path) -> dict[str, Any]:
        if not _is_image(path):
            return {}
        try:
            from PIL import Image
            import pytesseract
        except ImportError:
            return {
                "ocr": {
                    "error": "OCR dependencies not installed. Install filewizard[ocr].",
                    "provider": "tesseract",
                }
            }
        try:
            with Image.open(path) as img:
                if self.settings.langs:
                    text = pytesseract.image_to_string(
                        img, lang=self.settings.langs
                    )
                else:
                    text = pytesseract.image_to_string(img)
            return {
                "ocr": {
                    "text": text.strip(),
                    "provider": "tesseract",
                    "model": "tesseract",
                }
            }
        except Exception as exc:
            return {
                "ocr": {
                    "error": str(exc),
                    "provider": "tesseract",
                }
            }


class LlamaHttpOcrExtractor:
    name = "ocr"

    def __init__(self, settings: OcrSettings):
        self.settings = settings

    def extract(self, path: Path) -> dict[str, Any]:
        if not _is_image(path):
            return {}
        try:
            content = chat_completion_with_image(
                base_url=self.settings.base_url,
                model=self.settings.model,
                prompt=ocr_user_prompt(),
                image_path=path,
                timeout_s=self.settings.timeout_s,
                max_image_edge=self.settings.max_image_edge,
                temperature=self.settings.temperature,
            )
            return {
                "ocr": {
                    "text": content.strip(),
                    "provider": "llama_http",
                    "model": self.settings.model,
                }
            }
        except Exception as exc:
            logger.warning("llama_http OCR failed for %s: %s", path, exc)
            return {
                "ocr": {
                    "error": str(exc),
                    "provider": "llama_http",
                    "model": self.settings.model,
                }
            }


class LlamaHttpVisionExtractor:
    name = "vision"

    def __init__(self, settings: VisionSettings):
        self.settings = settings

    def extract(self, path: Path) -> dict[str, Any]:
        if not _is_image(path):
            return {}
        try:
            content = chat_completion_with_image(
                base_url=self.settings.base_url,
                model=self.settings.model,
                prompt=vision_labels_prompt(self.settings.labels),
                image_path=path,
                timeout_s=self.settings.timeout_s,
                max_image_edge=self.settings.max_image_edge,
                temperature=self.settings.temperature,
            )
            parsed = parse_vision_json(content, self.settings.labels)
            vision: dict[str, Any] = dict(parsed.get("labels") or {})
            vision["provider"] = "llama_http"
            vision["model"] = self.settings.model
            if parsed.get("error"):
                vision["error"] = parsed["error"]
            if parsed.get("raw"):
                vision["raw"] = parsed["raw"]

            out: dict[str, Any] = {"vision": vision}
            # Optional OCR text from the same call (does not override if empty).
            text = (parsed.get("text") or "").strip()
            if text:
                out["ocr"] = {
                    "text": text,
                    "provider": "llama_http",
                    "model": self.settings.model,
                    "source": "vision_joint",
                }
            return out
        except Exception as exc:
            logger.warning("llama_http vision failed for %s: %s", path, exc)
            return {
                "vision": {
                    "error": str(exc),
                    "provider": "llama_http",
                    "model": self.settings.model,
                }
            }
