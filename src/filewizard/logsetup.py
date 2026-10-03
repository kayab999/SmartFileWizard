"""Rotating file log shared by the GUI and the CLI.

Callers must not log OCR bodies or image payloads.
"""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path


def setup_file_logging(state_dir: Path) -> Path:
    """Attach a 1MB × 3 rotating log under ``state_dir``. Idempotent."""
    state_dir = Path(state_dir).expanduser()
    state_dir.mkdir(parents=True, exist_ok=True)
    log_path = state_dir / "filewizard.log"
    logger = logging.getLogger("filewizard")
    logger.setLevel(logging.INFO)
    for handler in logger.handlers:
        if isinstance(handler, RotatingFileHandler) and getattr(
            handler, "_fw_path", None
        ) == str(log_path):
            return log_path
    file_handler = RotatingFileHandler(
        log_path, maxBytes=1_000_000, backupCount=3, encoding="utf-8"
    )
    file_handler._fw_path = str(log_path)  # type: ignore[attr-defined]
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
