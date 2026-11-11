"""Bounded regex evaluation for untrusted rule patterns.

The standard-library ``re`` engine has no backtracking limit and no
timeout. FileWizard rules are user-authored, but a pasted catastrophic
pattern must not be able to hang the engine. This module prefers the
optional ``regex`` package (which supports a per-call timeout) and falls
back to ``re`` with the same API surface used by the engine.
"""

from __future__ import annotations

import re
from typing import Any

try:  # Optional, declared in pyproject [redos]; not a core dependency.
    import regex as _regex  # type: ignore[import-not-found]

    _ENGINE = "regex"
except ImportError:  # pragma: no cover - depends on environment
    _regex = None
    _ENGINE = "re"


def compile_pattern(pattern: str, flags: int = 0) -> Any:
    """Compile with the best available engine."""
    if _ENGINE == "regex" and _regex is not None:
        return _regex.compile(pattern, flags=flags)
    return re.compile(pattern, flags=flags)


def safe_search(pattern: Any, text: str, *, timeout: float = 0.25) -> bool:
    """Return whether *pattern* matches *text*, bounded when possible."""
    if _ENGINE == "regex" and _regex is not None:
        try:
            return bool(pattern.search(text, timeout=timeout))
        except Exception:
            return False
    # stdlib fallback: no timeout primitive; callers must also apply the
    # heuristic in models._looks_catastrophic before reaching here.
    try:
        return bool(pattern.search(text))
    except Exception:
        return False


def engine_name() -> str:
    return _ENGINE
