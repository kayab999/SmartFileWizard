from __future__ import annotations

import mimetypes
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Protocol, runtime_checkable

try:
    from PIL import Image

    # Guard against absurdly large images.
    Image.MAX_IMAGE_PIXELS = 150_000_000
except ImportError:
    Image = None


@runtime_checkable
class FeatureExtractor(Protocol):
    """
    Interface for optional feature extractors.

    Examples:
      - OCR
      - vision
      - EXIF
      - hashes
      - document classifier
    """

    name: str

    def extract(self, path: Path) -> dict[str, Any]:
        ...


IMAGE_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".webp",
    ".bmp",
    ".tif",
    ".tiff",
}


@dataclass(frozen=True)
class FileFacts:
    """
    Known facts about a file.

    The rule engine always decides from explicit, auditable facts.
    """

    path: Path
    size: int
    mime: str
    extension: str
    filename: str
    stem: str
    mtime: datetime
    is_image: bool

    width: int | None = None
    height: int | None = None

    # Optional features:
    # {
    #   "ocr": {"text": "..."},
    #   "vision": {"document": 0.91, "screenshot": 0.03},
    # }
    features: dict[str, Any] = field(default_factory=dict)


def _image_size(path: Path) -> tuple[int | None, int | None]:
    if Image is None:
        return None, None

    try:
        with Image.open(path) as img:
            return img.width, img.height
    except Exception:
        return None, None


def collect_facts(
    path: Path,
    extractors: Iterable[FeatureExtractor] = (),
) -> FileFacts:
    """Collect basic metadata and optional features for a file."""

    path = path.resolve()
    st = path.stat()

    mime, _ = mimetypes.guess_type(path.name)
    mime = mime or "application/octet-stream"

    extension = path.suffix.lower().lstrip(".")
    filename = path.name
    stem = path.stem

    is_image = mime.startswith("image/") or path.suffix.lower() in IMAGE_EXTENSIONS

    width: int | None = None
    height: int | None = None

    if is_image:
        width, height = _image_size(path)

    features: dict[str, Any] = {}

    for extractor in extractors:
        try:
            data = extractor.extract(path)
            if isinstance(data, dict):
                features.update(data)
        except Exception as exc:
            features.setdefault("errors", []).append(
                {
                    "provider": getattr(extractor, "name", "unknown"),
                    "error": str(exc),
                }
            )

    mtime = datetime.fromtimestamp(st.st_mtime, tz=timezone.utc)

    return FileFacts(
        path=path,
        size=st.st_size,
        mime=mime,
        extension=extension,
        filename=filename,
        stem=stem,
        mtime=mtime,
        is_image=is_image,
        width=width,
        height=height,
        features=features,
    )
