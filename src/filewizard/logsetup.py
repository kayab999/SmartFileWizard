"""Rotating file log shared by the GUI and the CLI.

Callers must not log OCR bodies or image payloads.
"""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path


class _PrivateRotatingFileHandler(RotatingFileHandler):
    """RotatingFileHandler that keeps the log owner-only (F-05b, R5).

    Plain rollover reopens the live file with the process umask, so the
    first rotation regresses a 0600 log to 0644/0664. Every rollover
    re-tightens the live file and its backups (user paths live here).
    """

    def doRollover(self) -> None:  # noqa: D102 - stdlib override
        super().doRollover()
        from .persist import ensure_private_file

        ensure_private_file(Path(self.baseFilename))
        base = Path(self.baseFilename)
        for i in range(1, getattr(self, "backupCount", 0) + 1):
            rotated = base.with_name(f"{base.name}.{i}")
            if rotated.exists():
                ensure_private_file(rotated)


def setup_file_logging(state_dir: Path) -> Path:
    """Attach a 1MB × 3 rotating log under ``state_dir``. Idempotent."""
    state_dir = Path(state_dir).expanduser()
    state_dir.mkdir(parents=True, exist_ok=True)
    log_path = state_dir / "filewizard.log"
    logger = logging.getLogger("filewizard")
    logger.setLevel(logging.INFO)
    from .persist import ensure_private_file

    for handler in logger.handlers:
        if isinstance(handler, RotatingFileHandler) and getattr(
            handler, "_fw_path", None
        ) == str(log_path):
            # R5 perms round: a preexisting log with an excessive mode
            # (e.g. 0666 written by hand) is tightened on every setup,
            # not only when the handler is first created.
            ensure_private_file(log_path)
            return log_path
    file_handler = _PrivateRotatingFileHandler(
        log_path, maxBytes=1_000_000, backupCount=3, encoding="utf-8"
    )
    file_handler._fw_path = str(log_path)  # type: ignore[attr-defined]
    # E2 (F-05b): the log records user paths — owner-only, best-effort.
    # Rollover keeps this via _PrivateRotatingFileHandler.
    ensure_private_file(log_path)
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )
    logger.addHandler(file_handler)
    try:
        if sys.stderr.isatty() and not any(
            isinstance(handler, logging.StreamHandler)
            and not isinstance(handler, RotatingFileHandler)
            for handler in logger.handlers
        ):
            console = logging.StreamHandler()
            console.setFormatter(
                logging.Formatter("%(levelname)s %(name)s %(message)s")
            )
            logger.addHandler(console)
    except Exception:
        logger.debug("console log handler was not attached", exc_info=True)
    return log_path
