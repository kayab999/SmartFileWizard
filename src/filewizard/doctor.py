"""Environment diagnostics for FileWizard."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any


def doctor_report(state_dir: Path) -> dict[str, Any]:
    """Return a structured health report for the local installation."""
    from . import __version__
    from .journal import Journal
    from .persist import ensure_private_dir
    from .review_queue import ReviewQueue

    state_dir = Path(state_dir).expanduser().resolve()
    report: dict[str, Any] = {
        "version": __version__,
        "python": sys.version.split()[0],
        "platform": sys.platform,
        "state_dir": str(state_dir),
        "checks": [],
    }

    def check(name: str, ok: bool, detail: str) -> None:
        report["checks"].append({"name": name, "ok": ok, "detail": detail})

    # State directory
    try:
        state_dir.mkdir(parents=True, exist_ok=True)
        ensure_private_dir(state_dir)
        mode = state_dir.stat().st_mode & 0o777
        check("state_dir", True, f"{state_dir} (mode {mode:o})")
    except OSError as exc:
        check("state_dir", False, str(exc))

    # Journal
    try:
        journal = Journal(state_dir / "journal.db")
        try:
            total = len(journal.recent_operations(1000))
            check("journal", True, f"{total} operations")
        finally:
            journal.close()
    except Exception as exc:
        check("journal", False, str(exc))

    # Review queue
    try:
        queue = ReviewQueue(state_dir=state_dir)
        pending = len(queue.pending())
        check("review_queue", True, f"{pending} pending")
    except Exception as exc:
        check("review_queue", False, str(exc))

    # Optional deps
    for name in ("PIL", "pytesseract", "torch", "transformers", "PySide6", "mcp"):
        try:
            __import__(name)
            check(f"dep:{name}", True, "available")
        except ImportError:
            check(f"dep:{name}", False, "not installed")

    return report
