"""C3/C4: drag & drop a directory onto the home; JSON CLI output."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QMimeData, QUrl
from PySide6.QtWidgets import QApplication

from click.testing import CliRunner


@pytest.fixture()
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def test_drop_directory_opens_wizard_with_source(qapp, tmp_path) -> None:
    from filewizard.ui.main_window import MainWindow
    from filewizard.ui.wizard import WizardDialog

    win = MainWindow(Path("~/.local/share/filewizard").expanduser())
    opened: list[WizardDialog] = []

    def fake_open_intent(intent):
        opened.append(WizardDialog(intent=intent, state_dir=win.state_dir))

    win.open_intent = fake_open_intent

    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(tmp_path))])

    class FakeEvent:
        def mimeData(self):
            return mime

        def acceptProposedAction(self):
            pass

        def ignore(self):
            pass

    win.dropEvent(FakeEvent())
    assert len(opened) == 1
    dlg = opened[0]
    # SourcePage prefilled with the dropped directory.
    assert dlg.page_source.source_edit.text() == str(tmp_path)
    dlg.close()
    win.close()


def test_drop_ignores_non_directory(qapp, tmp_path) -> None:
    from filewizard.ui.main_window import MainWindow

    win = MainWindow(Path("~/.local/share/filewizard").expanduser())
    called = []
    win.open_intent = lambda intent: called.append(intent)

    f = tmp_path / "file.txt"
    f.write_text("x")
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(f))])

    class FakeEvent:
        def mimeData(self):
            return mime

        def acceptProposedAction(self):
            pass

        def ignore(self):
            pass

    win.dropEvent(FakeEvent())
    assert called == []
    win.close()


def test_drag_enter_accepts_directory(qapp, tmp_path) -> None:
    from filewizard.ui.main_window import MainWindow

    win = MainWindow(Path("~/.local/share/filewizard").expanduser())
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(tmp_path))])
    accepted = []

    class FakeEvent:
        def mimeData(self):
            return mime

        def acceptProposedAction(self):
            accepted.append(True)

        def ignore(self):
            accepted.append(False)

    ev = FakeEvent()
    win.dragEnterEvent(ev)
    assert accepted == [True]
    win.close()


# --- C4: JSON CLI output ----------------------------------------------


def test_presets_list_json(tmp_path: Path) -> None:
    from filewizard.cli import presets_list

    state_dir = tmp_path / "state"
    state_dir.mkdir()
    runner = CliRunner()
    result = runner.invoke(
        presets_list, ["--state-dir", str(state_dir), "--json"]
    )
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert isinstance(data, list) and data
    assert {"name", "rule_count", "description"} <= set(data[0])


def test_perception_status_json(tmp_path: Path) -> None:
    from filewizard.cli import perception_status_cmd

    state_dir = tmp_path / "state"
    state_dir.mkdir()
    runner = CliRunner()
    result = runner.invoke(
        perception_status_cmd, ["--state-dir", str(state_dir), "--json"]
    )
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert "profile" in data and "ocr" in data and "vision" in data


def test_doctor_json(tmp_path: Path) -> None:
    from filewizard.cli import doctor_cmd

    state_dir = tmp_path / "state"
    state_dir.mkdir()
    runner = CliRunner()
    result = runner.invoke(
        doctor_cmd, ["--state-dir", str(state_dir), "--json"]
    )
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["checks"] and {"name", "ok", "detail"} <= set(
        data["checks"][0]
    )


def test_watch_list_json(tmp_path: Path) -> None:
    from filewizard.cli import watch_list

    state_dir = tmp_path / "state"
    state_dir.mkdir()
    runner = CliRunner()
    # First empty, then with one watch added.
    result = runner.invoke(watch_list, ["--state-dir", str(state_dir), "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == []

    src = tmp_path / "src"
    src.mkdir()
    rules = tmp_path / "r.yaml"
    rules.write_text("rules: []\n")
    from filewizard.cli import watch_add

    runner.invoke(
        watch_add,
        [
            "--state-dir",
            str(state_dir),
            "--name",
            "w1",
            "--source",
            str(src),
            "--rules",
            str(rules),
        ],
    )
    result = runner.invoke(watch_list, ["--state-dir", str(state_dir), "--json"])
    data = json.loads(result.output)
    assert len(data) == 1
    assert data[0]["name"] == "w1"
    assert data[0]["dry_run"] is True
