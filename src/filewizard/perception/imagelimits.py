"""Bounded image loading for the perception chain (WP-D1, F-12).

Perception must never decode unbounded attacker-controlled files:
huge archives, decompression bombs and malformed formats are explicit
errors, not hangs or OOM kills. Limits come from the perception config
(extractor settings), applied *before* decoding where possible.
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Magic bytes of formats we accept when Pillow is unavailable. With
# Pillow installed, format validation is delegated to its decoder.
_KNOWN_MAGICS: tuple[tuple[bytes, str], ...] = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"BM", "image/bmp"),
    (b"RIFF", "image/webp"),  # RIFF....WEBP
)


class ImageLimitError(ValueError):
    """The file exceeds a configured perception resource limit."""


def check_file_bytes(path: Path, max_bytes: int) -> None:
    """Raise ImageLimitError when the file is larger than max_bytes."""
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise ImageLimitError(f"cannot stat {path}: {exc}") from exc
    if size > max_bytes:
        raise ImageLimitError(
            f"file too large for perception: {size} bytes "
            f"(limit {max_bytes}): {path}"
        )


def check_dimensions(width: int, height: int, max_pixels: int) -> None:
    """Raise ImageLimitError before decoding when pixels exceed the cap."""
    pixels = int(width) * int(height)
    if pixels > max_pixels:
        raise ImageLimitError(
            f"image too large to decode: {width}x{height} "
            f"({pixels} pixels, limit {max_pixels})"
        )


def open_image_bounded(path: Path, *, max_bytes: int, max_pixels: int):
    """Open an image with PIL, enforcing byte and pixel caps first.

    Returns the open PIL image (header read; caller must decode/convert
    within the caps — size is already checked). Raises ImageLimitError
    on any configured limit. ImportError propagates when Pillow is not
    installed (callers handle the no-Pillow policy themselves).
    """
    from PIL import Image

    check_file_bytes(path, max_bytes)
    img = Image.open(path)
    try:
        check_dimensions(img.size[0], img.size[1], max_pixels)
    except ImageLimitError:
        img.close()
        raise
    return img


def read_image_bytes_bounded(
    path: Path, *, max_bytes: int
) -> tuple[bytes, str]:
    """No-Pillow policy: byte cap + format whitelist by magic bytes.

    Without Pillow we cannot decode or resize, so only formats we can
    pass through verbatim are accepted, and only within the byte cap.
    """
    check_file_bytes(path, max_bytes)
    try:
        with path.open("rb") as fh:
            head = fh.read(16)
    except OSError as exc:
        raise ImageLimitError(f"cannot read {path}: {exc}") from exc
    mime = None
    for magic, candidate in _KNOWN_MAGICS:
        if head.startswith(magic):
            if candidate == "image/webp" and head[8:12] != b"WEBP":
                continue
            mime = candidate
            break
    if mime is None:
        raise ImageLimitError(
            f"unsupported image format without Pillow "
            f"(accepted: PNG, JPEG, GIF, BMP, WEBP): {path}"
        )
    data = path.read_bytes()
    if len(data) > max_bytes:
        raise ImageLimitError(
            f"file too large for perception: {len(data)} bytes "
            f"(limit {max_bytes}): {path}"
        )
    return data, mime
