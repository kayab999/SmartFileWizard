"""C2: accessibility smoke tests (offscreen).

Checks that every interactive control on the home screen exposes an
accessible name (screen-reader basic contract) and that the window uses
a sane focus policy (keyboard-only navigation).
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QPushButton


@pytest.fixture()
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _make_window():
    from filewizard.ui.main_window import MainWindow

    return MainWindow(Path("~/.local/share/filewizard").expanduser())


def test_home_buttons_have_accessible_names(qapp) -> None:
    win = _make_window()
    missing = []
    for btn in win.findChildren(QPushButton):
        # A button with visible text always has *some* label; accessibleName
        # must be set for badge/toolbar buttons whose text is not enough.
        if not btn.accessibleName() and not btn.text():
            missing.append(btn.objectName() or "unnamed")
    assert missing == []
    win.close()


def test_toolbar_buttons_expose_roles(qapp) -> None:
    win = _make_window()
    named = {
        btn.accessibleName()
        for btn in win.findChildren(QPushButton)
        if btn.accessibleName()
    }
    for expected in ("Cola de revisión", "Vigilancia", "Ajustes", "Salir"):
        assert any(expected in n for n in named), expected
    win.close()


def test_intent_cards_are_focusable(qapp) -> None:
    from filewizard.ui.widgets import IntentCard

    card = IntentCard("Organizar archivos", "desc")
    assert card.accessibleName() == "Organizar archivos"
    # QPushButton is focusable by default (keyboard-only navigation).
    assert card.focusPolicy() != card.focusPolicy().NoFocus


def test_preset_combo_has_accessible_name(qapp) -> None:
    win = _make_window()
    combo = win.preset_combo
    assert combo.accessibleName() or combo.toolTip()
    win.close()
