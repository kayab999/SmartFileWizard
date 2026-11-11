"""Headless smoke tests for the PySide6 shell (pytest-qt)."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

try:
    import PySide6  # noqa: F401
except ImportError:  # pragma: no cover
    pytest.skip("PySide6 not installed", allow_module_level=True)

try:
    from pytestqt.qtbot import QtBot  # noqa: F401
except ImportError:  # pragma: no cover
    pytest.skip("pytest-qt not installed", allow_module_level=True)

from PySide6.QtWidgets import QApplication


def test_qapplication_can_be_created(qtbot) -> None:
    app = QApplication.instance() or QApplication([])
    assert app is not None


def test_main_window_imports_without_display() -> None:
    from filewizard.ui.main_window import MainWindow  # noqa: F401
    assert MainWindow is not None
