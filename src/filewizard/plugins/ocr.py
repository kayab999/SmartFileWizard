"""Backward-compatible OCR plugin entry (delegates to perception). """

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..perception.config import OcrSettings
from ..perception.extractors import TesseractOcrExtractor


class TesseractOCR:
    """
    Optional OCR extractor based on Tesseract.

    Requires:
      pip install filewizard[ocr]
      apt install tesseract-ocr
    """

    name = "ocr"

    def __init__(self, langs: str | None = None):
        self._impl = TesseractOcrExtractor(OcrSettings(provider="tesseract", langs=langs))

    def extract(self, path: Path) -> dict[str, Any]:
        return self._impl.extract(path)
