"""WP-0.11.4: desktop entry and packaged icon."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_desktop_entry_and_icon_exist() -> None:
    desktop = (ROOT / "packaging" / "filewizard.desktop").read_text(
        encoding="utf-8"
    )
    assert "Exec=filewizard-ui" in desktop
    assert "Icon=filewizard" in desktop
    assert "Name=FileWizard" in desktop
    icon = ROOT / "src" / "filewizard" / "ui" / "assets" / "app_icon_256.png"
    assert icon.is_file()
    script = ROOT / "packaging" / "install-desktop.sh"
    assert script.is_file()
    assert "filewizard.png" in script.read_text(encoding="utf-8")
