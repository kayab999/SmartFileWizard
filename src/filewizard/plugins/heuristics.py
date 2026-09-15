from __future__ import annotations

import logging
import mimetypes
import re
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    from PIL import Image
except ImportError:
    Image = None

from ..facts import IMAGE_EXTENSIONS

logger = logging.getLogger(__name__)

FILENAME_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("screenshot", re.compile(r"(?i)(screenshot|captura|screen[-_ ]?shot)")),
    ("camera", re.compile(r"(?i)^(IMG|DSC|DSCN|PXL|GOPRO|DJI)[-_ ]?\d")),
    ("whatsapp", re.compile(r"(?i)whatsapp|wa[-_ ]?image")),
    ("telegram", re.compile(r"(?i)telegram|^tg[-_ ]\d")),
    ("scan", re.compile(r"(?i)(scan|escane)")),
    ("invoice", re.compile(r"(?i)(factura|invoice|recibo|receipt)")),
]

FILENAME_DATE_PATTERNS = [
    re.compile(
        r"(?P<y>20\d{2})[-_. ](?P<m>0[1-9]|1[0-2])[-_. ](?P<d>0[1-9]|[12]\d|3[01])"
    ),
    re.compile(
        r"(?P<y>20\d{2})(?P<m>0[1-9]|1[0-2])(?P<d>0[1-9]|[12]\d|3[01])"
    ),
]


def _parse_exif_date(value: str) -> datetime | None:
    for fmt in ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y:%m:%d"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def _read_exif(img) -> dict[str, Any]:
    data: dict[str, Any] = {}
    try:
        exif = img.getexif()
    except Exception as exc:
        logger.debug("EXIF read failed: %s", exc)
        return data

    make = exif.get(271)
    model = exif.get(272)
    software = exif.get(305)
    dt_value = exif.get(306)

    try:
        sub_ifd = exif.get_ifd(0x8769)
        dto_value = sub_ifd.get(36867)
    except Exception:
        dto_value = None

    if make:
        data["make"] = str(make).strip()
    if model:
        data["model"] = str(model).strip()
    if software:
        data["software"] = str(software).strip()

    dto = _parse_exif_date(str(dto_value)) if dto_value else None
    if dto:
        data["datetime_original"] = dto.isoformat()
    else:
        dt = _parse_exif_date(str(dt_value)) if dt_value else None
        if dt:
            data["datetime"] = dt.isoformat()

    return data


def _image_stats(img) -> dict[str, Any]:
    """
    Approximate palette on a 48x48 thumbnail.

    unique_colors is capped at 2304; getcolors returning None means
    "many colors" (typical of photography).
    """
    try:
        thumb = img.convert("RGB")
        thumb.thumbnail((48, 48))
        max_colors = 48 * 48
        colors = thumb.getcolors(max_colors)
        return {
            "unique_colors": len(colors) if colors is not None else max_colors
        }
    except Exception as exc:
        logger.debug("image stats failed: %s", exc)
        return {}


class ImageHeuristics:
    """
    Fully deterministic extractor: EXIF, filename patterns, palette stats.
    """

    name = "heuristics"

    def extract(self, path: Path) -> dict[str, Any]:
        features: dict[str, Any] = {}

        patterns = [
            label for label, rx in FILENAME_PATTERNS if rx.search(path.name)
        ]
        if patterns:
            features["filename_patterns"] = patterns

        date_taken: datetime | None = None
        date_source = "mtime"

        for rx in FILENAME_DATE_PATTERNS:
            m = rx.search(path.name)
            if m:
                try:
                    date_taken = datetime(
                        int(m["y"]), int(m["m"]), int(m["d"])
                    )
                    date_source = "filename"
                except ValueError:
                    date_taken = None
                break

        mime, _ = mimetypes.guess_type(path.name)
        is_image = (mime or "").startswith("image/") or (
            path.suffix.lower() in IMAGE_EXTENSIONS
        )

        if is_image and Image is not None:
            try:
                with Image.open(path) as img:
                    exif = _read_exif(img)
                    if exif:
                        features["exif"] = exif
                        if date_taken is None and exif.get("datetime_original"):
                            date_taken = datetime.fromisoformat(
                                exif["datetime_original"]
                            )
                            date_source = "exif"
                        elif date_taken is None and exif.get("datetime"):
                            date_taken = datetime.fromisoformat(exif["datetime"])
                            date_source = "exif"
                    features.update(_image_stats(img))
            except Exception as exc:
                # R1/R2: per-file failure recorded, does not kill the batch.
                logger.debug("heuristics image open failed for %s: %s", path, exc)
                features.setdefault("errors", []).append(
                    {"provider": self.name, "error": str(exc)}
                )

        if date_taken is None:
            date_taken = datetime.fromtimestamp(path.stat().st_mtime)
            date_source = "mtime"

        features["date_taken"] = date_taken.isoformat()
        features["date_source"] = date_source
        return features
