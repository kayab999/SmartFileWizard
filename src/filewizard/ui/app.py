from __future__ import annotations

import sys
from pathlib import Path


def setup_gui_logging(state_dir: Path) -> Path:
    """File logging for GUI runs. Same rotating log as the CLI."""
    from ..logsetup import setup_file_logging

    return setup_file_logging(state_dir)


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
    from .single_instance import accept_show_requests, claim_primary

    primary = claim_primary()
    if primary is None:
        print(
            "FileWizard ya está abierto. Se mostró la ventana existente.",
            file=sys.stderr,
        )
        return
    primary.setParent(app)
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
    accept_show_requests(primary, window)
    tray = TrayIconManager(window)
    window.tray_manager = tray if tray.attach() else None

    window.show()
    if splash is not None:
        splash.finish(window)

    sys.exit(app.exec())
