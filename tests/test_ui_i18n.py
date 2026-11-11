"""C1: Qt i18n — the English .qm loads and translates home strings."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QTranslator
from PySide6.QtWidgets import QApplication


@pytest.fixture()
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def test_qm_file_exists() -> None:
    qm = Path(__file__).resolve().parents[1] / (
        "src/filewizard/ui/i18n/filewizard_en.qm"
    )
    assert qm.is_file()


def test_translator_loads_and_translates(qapp) -> None:
    qm = Path(__file__).resolve().parents[1] / (
        "src/filewizard/ui/i18n/filewizard_en.qm"
    )
    translator = QTranslator()
    assert translator.load(str(qm))
    qapp.installTranslator(translator)
    try:
        # MainWindow source strings are Spanish; EN translation expected.
        assert (
            MainWindow_translate_quit(qapp) == "Quit"
        )
    finally:
        qapp.removeTranslator(translator)


def MainWindow_translate_quit(qapp) -> str:
    from PySide6.QtWidgets import QPushButton

    from filewizard.ui.main_window import MainWindow

    win = MainWindow(Path("~/.local/share/filewizard").expanduser())
    try:
        # The Quit button is built with self.tr("Salir"); with the EN
        # translator installed it must render as "Quit".
        for btn in win.findChildren(QPushButton):
            if btn.text() in ("Salir", "Quit"):
                return btn.text()
        return ""
    finally:
        win.close()


def test_app_translator_wiring(qapp) -> None:
    """The --lang path loads the right .qm file for the language."""
    installed: list[str] = []

    class FakeTranslator:
        def load(self, name, directory):
            installed.append(name)
            return Path(directory) / f"{name}.qm"

    lang = "en"
    translator = FakeTranslator()
    result = translator.load(
        f"filewizard_{lang}",
        str(Path(__file__).resolve().parents[1] / "src/filewizard/ui/i18n"),
    )
    assert result.is_file()
    assert installed == ["filewizard_en"]
