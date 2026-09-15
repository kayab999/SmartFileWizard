from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path


def setup_gui_logging(state_dir: Path) -> Path:
    """File logging for GUI runs (H9): rotating filewizard.log in state_dir.

    Never logs OCR bodies / base64 — callers only log paths, sizes, errors.
    Idempotent: safe to call once at startup.
    """
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
    # Console too when launched from a terminal; .desktop runs have no TTY.
    try:
        if sys.stderr.isatty() and not any(
            isinstance(h, logging.StreamHandler)
            and not isinstance(h, RotatingFileHandler)
            for h in logger.handlers
        ):
            console = logging.StreamHandler()
            console.setFormatter(
                logging.Formatter("%(levelname)s %(name)s %(message)s")
            )
            logger.addHandler(console)
    except Exception:
        pass
    return log_path


def main() -> None:
    try:
        from PySide6.QtGui import QFont, QIcon, QPixmap
        from PySide6.QtWidgets import QApplication, QSplashScreen
    except ImportError as exc:
        raise SystemExit(
            "Missing UI dependencies. Install with:\n\n"
            '    pip install -e ".[ui]"\n'
        ) from exc

    from .main_window import MainWindow
    from .theme import asset_path, load_qss
    from .tray import TrayIconManager

    state_dir = Path("~/.local/share/filewizard").expanduser()
    state_dir.mkdir(parents=True, exist_ok=True)
    setup_gui_logging(state_dir)

    app = QApplication(sys.argv)
    app.setApplicationName("FileWizard")
    app.setOrganizationName("FileWizard")
    app.setWindowIcon(QIcon(str(asset_path("app_icon.png"))))
    font = QFont(app.font())
    font.setStyleHint(QFont.StyleHint.SansSerif)
    app.setFont(font)
    app.setStyleSheet(load_qss())

    splash: QSplashScreen | None = None
    splash_path = asset_path("splash.png")
    if splash_path.is_file():
        pix = QPixmap(str(splash_path))
        if not pix.isNull():
            splash = QSplashScreen(pix)
            splash.show()
            app.processEvents()

    window = MainWindow(state_dir=state_dir)
    tray = TrayIconManager(window)
    window.tray_manager = tray if tray.attach() else None

    window.show()
    if splash is not None:
        splash.finish(window)

    sys.exit(app.exec())
