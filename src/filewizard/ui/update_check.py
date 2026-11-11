"""Non-blocking update check for the GUI (B5).

Runs in a QThread so startup never waits on the network; the result is
delivered as a Qt signal and shown in the status bar / tray. Best-effort:
offline or GitHub failure is silently ignored.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, QThread, Signal


class UpdateCheckWorker(QThread):
    notice_ready = Signal(str)

    def __init__(self, current_version: str, parent: QObject | None = None):
        super().__init__(parent)
        self.current_version = current_version

    def run(self) -> None:
        try:
            from ..update import update_notice

            notice = update_notice(self.current_version)
        except Exception:
            return
        if notice:
            self.notice_ready.emit(notice)
