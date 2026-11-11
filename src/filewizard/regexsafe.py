"""Bounded regex evaluation for rule patterns.

The stdlib ``re`` engine has no backtracking limit. We prefer the optional
``regex`` package (per-call timeout) and fall back to ``re`` with a
best-effort ``signal.SIGALRM`` guard on Unix main thread. On any timeout or
error the pattern is treated as non-matching (fail-closed).
"""

from __future__ import annotations

import re
import signal
import threading
from typing import Any

try:
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


class _Timeout:
    def __init__(self, seconds: float) -> None:
        self.seconds = seconds
        self._old_handler = None
        self._supported = (
            _ENGINE == "re"
            and hasattr(signal, "SIGALRM")
            and threading.current_thread() is threading.main_thread()
        )

    def __enter__(self):
        if self._supported:
            self._old_handler = signal.getsignal(signal.SIGALRM)
            signal.signal(signal.SIGALRM, _alarm_handler)
            signal.setitimer(signal.ITIMER_REAL, self.seconds)
        return self

    def __exit__(self, *exc):
        if self._supported:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, self._old_handler)


def _alarm_handler(signum, frame):
    raise TimeoutError("regex evaluation exceeded timeout")


def safe_search(pattern: Any, text: str, *, timeout: float = 0.25) -> bool:
    """Return whether *pattern* matches *text*, bounded when possible."""
    if _ENGINE == "regex" and _regex is not None:
        try:
            return bool(pattern.search(text, timeout=timeout))
        except Exception:
            return False
    try:
        with _Timeout(timeout):
            return bool(pattern.search(text))
    except Exception:
        return False


def engine_name() -> str:
    return _ENGINE
