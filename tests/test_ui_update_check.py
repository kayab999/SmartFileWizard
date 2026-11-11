"""B5: non-blocking update notice in the GUI (offscreen)."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication


@pytest.fixture()
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def test_update_worker_emits_notice(qapp, monkeypatch) -> None:
    from filewizard.ui.update_check import UpdateCheckWorker

    monkeypatch.setattr(
        "filewizard.update.update_notice", lambda current: "v99 available"
    )
    worker = UpdateCheckWorker("0.11.1")
    received: list[str] = []
    worker.notice_ready.connect(received.append)
    worker.start()

    def _finish():
        qapp.quit()

    QTimer.singleShot(3000, _finish)
    qapp.exec()
    assert received == ["v99 available"]


def test_update_worker_silent_when_up_to_date(qapp, monkeypatch) -> None:
    from filewizard.ui.update_check import UpdateCheckWorker

    monkeypatch.setattr(
        "filewizard.update.update_notice", lambda current: None
    )
    worker = UpdateCheckWorker("0.11.1")
    received: list[str] = []
    worker.notice_ready.connect(received.append)
    worker.start()
    QTimer.singleShot(3000, qapp.quit)
    qapp.exec()
    assert received == []


def test_update_worker_offline_is_silent(qapp, monkeypatch) -> None:
    from filewizard.ui.update_check import UpdateCheckWorker

    def boom(current):
        raise OSError("offline")

    monkeypatch.setattr("filewizard.update.update_notice", boom)
    worker = UpdateCheckWorker("0.11.1")
    received: list[str] = []
    worker.notice_ready.connect(received.append)
    worker.start()
    QTimer.singleShot(3000, qapp.quit)
    qapp.exec()
    assert received == []


def test_main_window_shows_notice_in_statusbar(qapp, monkeypatch) -> None:
    from filewizard.ui.main_window import MainWindow

    monkeypatch.setattr(
        "filewizard.update.update_notice", lambda current: "New version 9.9"
    )
    win = MainWindow(Path("~/.local/share/filewizard").expanduser())
    win._show_update_notice("New version 9.9")
    assert "New version 9.9" in win.statusBar().currentMessage()
    win.close()
