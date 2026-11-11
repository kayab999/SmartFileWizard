"""B5: non-blocking update notice in the GUI (offscreen).

Uses pytest-qt's session-scoped ``qapp`` (via ``qtbot``) so Qt teardown
is managed properly; every QThread started here is reaped with
``wait()`` before the test ends (a QThread alive at interpreter
shutdown aborts the process, exit 134/139, even when all tests passed).
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot


def _app():
    return QApplication.instance()


def _run_worker(worker, *, expect_notice: bool) -> list[str]:
    app = _app()
    received: list[str] = []
    worker.notice_ready.connect(received.append)
    worker.start()
    QTimer.singleShot(3000, app.quit)
    app.exec()
    # Reap the thread: never leave a QThread running at test teardown.
    assert worker.wait(5000), "update-check thread did not finish"
    if expect_notice:
        assert received == ["v99 available"], received
    else:
        assert received == []
    return received


def test_update_worker_emits_notice(qtbot: QtBot, monkeypatch) -> None:
    from filewizard.ui.update_check import UpdateCheckWorker

    monkeypatch.setattr(
        "filewizard.update.update_notice", lambda current: "v99 available"
    )
    _run_worker(UpdateCheckWorker("0.11.1"), expect_notice=True)


def test_update_worker_silent_when_up_to_date(qtbot: QtBot, monkeypatch) -> None:
    from filewizard.ui.update_check import UpdateCheckWorker

    monkeypatch.setattr("filewizard.update.update_notice", lambda current: None)
    _run_worker(UpdateCheckWorker("0.11.1"), expect_notice=False)


def test_update_worker_offline_is_silent(qtbot: QtBot, monkeypatch) -> None:
    from filewizard.ui.update_check import UpdateCheckWorker

    def boom(current):
        raise OSError("offline")

    monkeypatch.setattr("filewizard.update.update_notice", boom)
    _run_worker(UpdateCheckWorker("0.11.1"), expect_notice=False)


def test_main_window_shows_notice_in_statusbar(qtbot: QtBot, monkeypatch) -> None:
    from filewizard.ui.main_window import MainWindow

    monkeypatch.setattr(
        "filewizard.update.update_notice", lambda current: "New version 9.9"
    )
    win = MainWindow(Path("~/.local/share/filewizard").expanduser())
    try:
        win._show_update_notice("New version 9.9")
        assert "New version 9.9" in win.statusBar().currentMessage()
    finally:
        win._force_quit = True
        win.close()
        win.deleteLater()
        _app().processEvents()
