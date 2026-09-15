from __future__ import annotations

import threading


class CancelToken:
    """
    Cooperative cancellation (R13).

    Check between files / before inference; never mid-shutil.move.
    """

    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    def is_cancelled(self) -> bool:
        return self._event.is_set()

    def reset(self) -> None:
        self._event.clear()


class CancelledError(Exception):
    """Raised when a cooperative cancel is observed."""
