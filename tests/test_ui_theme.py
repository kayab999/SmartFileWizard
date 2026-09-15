"""Theme assets and QSS — no Qt / no display."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "src" / "filewizard" / "ui" / "assets"
QSS = ROOT / "src" / "filewizard" / "ui" / "style.qss"
TRAY_SRC = ROOT / "src" / "filewizard" / "ui" / "tray.py"


def test_packaged_assets_exist() -> None:
    for name in (
        "app_icon.png",
        "splash.png",
        "tray_idle.png",
        "tray_active.png",
        "tray_alert.png",
    ):
        path = ASSETS / name
        assert path.is_file(), path
        assert path.stat().st_size > 100


def test_tray_pngs_have_alpha() -> None:
    """PNG color type 6 = RGBA (no Pillow — CI is [dev] only)."""
    for name in ("tray_idle.png", "tray_active.png", "tray_alert.png"):
        data = (ASSETS / name).read_bytes()
        assert data[:8] == b"\x89PNG\r\n\x1a\n"
        assert data[25] == 6  # IHDR color type RGBA


def test_qss_contains_palette() -> None:
    text = QSS.read_text(encoding="utf-8")
    for token in (
        "#1A1A1D",
        "#242428",
        "#8B5CF6",
        "#06B6D4",
        "#F59E0B",
        "#10B981",
        "#F3F4F6",
        "btnPrimary",
        "intentCard",
    ):
        assert token in text, token


def test_tray_manager_state_methods() -> None:
    src = TRAY_SRC.read_text(encoding="utf-8")
    for name in ("set_state_idle", "set_state_active", "set_state_alert"):
        assert f"def {name}(" in src
    assert "Mostrar ventana" in src
    assert "Vigilancia rápida" in src
    assert "Apoyar" in src
    assert "Salir" in src
    assert "isSystemTrayAvailable" in src


def test_support_urls() -> None:
    from filewizard.ui.support import REPO_URL, SUPPORT_URL

    assert SUPPORT_URL == "https://buymeacoffee.com/kayabsoftware"
    assert REPO_URL == "https://github.com/kayab999/SmartFileWizard"


def test_theme_loader_without_qt() -> None:
    from filewizard.ui.theme import asset_path, load_qss

    assert asset_path("app_icon.png").is_file()
    qss = load_qss()
    assert "#8B5CF6" in qss
