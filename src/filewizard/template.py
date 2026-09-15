from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from pathlib import Path

from .facts import FileFacts


class TemplateError(Exception):
    pass


CASCADE_CATEGORY_FALLBACK = "uncategorized"


def cascade_category_slug(facts: FileFacts) -> str:
    """Filesystem-safe cascade category for {cascade_category} templates.

    Falls back to "uncategorized" when there is no cascade evidence or the
    status is unknown — the router then degrades to a static bucket instead
    of failing the whole operation.
    """
    cascade = facts.features.get("cascade")
    raw = ""
    if isinstance(cascade, dict):
        raw = str(cascade.get("category") or "")
    if not raw or raw.strip().casefold() == "unknown":
        return CASCADE_CATEGORY_FALLBACK
    slug = unicodedata.normalize("NFC", raw.strip().casefold())
    slug = re.sub(r"[^a-z0-9_-]+", "_", slug).strip("_")
    return slug or CASCADE_CATEGORY_FALLBACK


def _effective_datetime(facts: FileFacts) -> datetime:
    """Prefer true capture date from heuristics when available."""
    dt = facts.mtime
    raw_taken = facts.features.get("date_taken")
    if raw_taken:
        try:
            parsed = datetime.fromisoformat(str(raw_taken))
            if parsed.tzinfo is not None and dt.tzinfo is None:
                parsed = parsed.replace(tzinfo=None)
            elif parsed.tzinfo is None and dt.tzinfo is not None:
                # Align naive taken date with mtime tz if any
                pass
            return parsed if parsed.tzinfo is None else parsed.replace(tzinfo=None)
        except ValueError:
            return dt.replace(tzinfo=None) if dt.tzinfo else dt
    return dt.replace(tzinfo=None) if getattr(dt, "tzinfo", None) else dt


def render_template(template: str, facts: FileFacts) -> str:
    """
    Render a template using file facts.

    Available variables:

      {original_name}
      {stem}
      {ext}
      {year}
      {month}
      {day}
      {hour}
      {minute}
      {second}
      {date}
      {datetime}
      {size}
      {mime}
      {cascade_category}
    """

    dt = _effective_datetime(facts)

    context = {
        "cascade_category": cascade_category_slug(facts),
        "original_name": facts.filename,
        "stem": facts.stem,
        "ext": facts.extension,
        "year": f"{dt.year:04d}",
        "month": f"{dt.month:02d}",
        "day": f"{dt.day:02d}",
        "hour": f"{dt.hour:02d}",
        "minute": f"{dt.minute:02d}",
        "second": f"{dt.second:02d}",
        "date": dt.strftime("%Y-%m-%d"),
        "datetime": dt.strftime("%Y%m%d_%H%M%S"),
        "size": str(facts.size),
        "mime": facts.mime,
    }

    try:
        return template.format_map(context)
    except KeyError as exc:
        raise TemplateError(f"Unknown template variable: {exc}") from exc
    except Exception as exc:
        raise TemplateError(f"Invalid template: {exc}") from exc


def render_path_template(template: str, facts: FileFacts) -> Path:
    """
    Render a path template.

    Example:
      ~/Documents/Invoices/{year}/{month}
    """

    rendered = render_template(template, facts)
    return Path(rendered).expanduser()


def render_filename_template(template: str, facts: FileFacts) -> str:
    """
    Render a filename template.

    Example:
      {date}_{original_name}
    """

    rendered = render_template(template, facts)

    if not rendered:
        raise TemplateError("Rendered filename is empty")

    if rendered in {".", ".."}:
        raise TemplateError(f"Invalid filename: {rendered!r}")

    if "/" in rendered or "\x00" in rendered:
        raise TemplateError(f"Invalid filename: {rendered!r}")

    return rendered
