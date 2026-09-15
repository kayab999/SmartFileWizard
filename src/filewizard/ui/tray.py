"""Linux system tray: idle / active / alert. Optional — never traps the user."""

from __future__ import annotations

import logging
from typing import Any

from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon, QWidget

from .theme import asset_path

logger = logging.getLogger(__name__)


class TrayIconManager:
    """QSystemTrayIcon wrapper. If the tray cannot load, callers must quit on close."""

    def __init__(self, window: QWidget):
        self.window = window
        self.tray: QSystemTrayIcon | None = None
        self._icons: dict[str, QIcon] = {}
        self._state = "idle"

    @property
    def available(self) -> bool:
        return self.tray is not None

    def attach(self) -> bool:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            logger.info("No system tray; window close will quit.")
            return False
        icons: dict[str, QIcon] = {}
        for key, filename in (
            ("idle", "tray_idle.png"),
            ("active", "tray_active.png"),
            ("alert", "tray_alert.png"),
        ):
            icon = QIcon(str(asset_path(filename)))
            if icon.isNull():
                logger.warning("Tray icon missing: %s", filename)
                return False
            icons[key] = icon
        self._icons = icons
        tray = QSystemTrayIcon(icons["idle"], self.window)
        tray.setToolTip("FileWizard")
        menu = QMenu(self.window)
        show = QAction("Mostrar ventana", menu)
        show.triggered.connect(self.show_window)
        watch = QAction("Vigilancia rápida", menu)
        watch.triggered.connect(self._open_watch)
        support = QAction("Apoyar…", menu)
        support.triggered.connect(self._open_support)
        quit_act = QAction("Salir", menu)
        quit_act.triggered.connect(self.quit_app)
        menu.addAction(show)
        menu.addAction(watch)
        menu.addAction(support)
        menu.addSeparator()
        menu.addAction(quit_act)
        tray.setContextMenu(menu)
        tray.activated.connect(self._on_activated)
        tray.show()
        self.tray = tray
        return True

    def set_state_idle(self) -> None:
        self._apply("idle")

    def set_state_active(self) -> None:
        self._apply("active")

    def set_state_alert(self) -> None:
        self._apply("alert")

    def _apply(self, state: str) -> None:
        self._state = state
        if self.tray is None:
            return
        icon = self._icons.get(state)
        if icon is not None:
            self.tray.setIcon(icon)

    def show_window(self) -> None:
        self.window.show()
        self.window.raise_()
        self.window.activateWindow()

    def quit_app(self) -> None:
        setattr(self.window, "_force_quit", True)
        QApplication.instance().quit()

    def _open_watch(self) -> None:
        self.show_window()
        opener = getattr(self.window, "open_watch", None)
        if callable(opener):
            opener()

    def _open_support(self) -> None:
        self.show_window()
        from .support import open_support_links

        open_support_links(self.window)

    def _on_activated(self, reason: Any) -> None:
        if reason in {
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        }:
            self.show_window()
