"""Best-effort update check against GitHub Releases."""

from __future__ import annotations

import json
import urllib.request
from typing import Any


def latest_release(repo: str = "kayab999/SmartFileWizard") -> dict[str, Any] | None:
    url = f"https://api.github.com/repos/{repo}/releases/latest"
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            data = json.load(resp)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def update_notice(current: str) -> str | None:
    release = latest_release()
    if not release:
        return None
    tag = str(release.get("tag_name", "")).lstrip("v")
    if tag and tag != current:
        return f"New version available: {tag} (current {current}). See releases page."
    return None
