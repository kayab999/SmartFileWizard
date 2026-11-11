"""Shared test fixtures.

Qt teardown guard: PySide6 has been observed to segfault during
interpreter shutdown on CI runners ("shared QObject was deleted
directly" → exit 139) when windows/objects are finalized in an
uncontrolled order. Closing top-level widgets, flushing deferred
deletes and collecting garbage while the QApplication is still alive
makes shutdown deterministic.
"""

from __future__ import annotations

import gc

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session", autouse=True)
def _qt_deterministic_teardown():
    yield
    app = QApplication.instance()
    if app is None:
        return
    # Close every remaining top-level widget (windows created by tests
    # that did not go through qtbot fixtures).
    for widget in app.topLevelWidgets():
        widget.close()
    # Schedule deferred deletion of every QObject still parented to the
    # app — including non-widget QtNetwork objects (e.g. QLocalServer)
    # whose destruction during interpreter shutdown segfaults on some
    # runner/PySide6 combinations.
    from PySide6.QtCore import QObject

    for obj in list(app.findChildren(QObject)):
        obj.deleteLater()
    # Run pending deleteLater() calls while the event system is alive.
    app.processEvents()
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    # Drop Python-side cycles BEFORE interpreter shutdown starts.
    gc.collect()
    app.processEvents()
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
