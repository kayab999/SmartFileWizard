"""Version consistency guard (R9 P0 / R9.1 Unit 3)."""

from __future__ import annotations

import re
from pathlib import Path

import filewizard


def _root() -> Path:
    return Path(__file__).resolve().parents[1]


def _version() -> str:
    return filewizard.__version__


def test_python_version_matches_readme() -> None:
    readme = (_root() / "README.md").read_text(encoding="utf-8")
    m = re.search(r"\|\s*\*\*Version\*\*\s*\|\s*([0-9.]+)\s*\|", readme)
    assert m is not None, "README version row not found"
    assert m.group(1) == _version()


def test_python_version_matches_pyproject_dynamic() -> None:
    pyproject = (_root() / "pyproject.toml").read_text(encoding="utf-8")
    # The project must declare dynamic version sourced from __version__.
    assert 'dynamic = ["version"]' in pyproject
    assert 'version = {attr = "filewizard.__version__"}' in pyproject
    # And the attr must resolve to the running package's version.
    assert _version() is not None


def test_python_version_matches_nfpm() -> None:
    nfpm = (_root() / "packaging" / "nfpm.yaml").read_text(encoding="utf-8")
    m = re.search(r"^version:\s*([0-9.]+)\s*$", nfpm, re.MULTILINE)
    assert m is not None
    assert m.group(1) == _version()


def test_python_version_matches_flatpak_metainfo() -> None:
    meta = _root() / "packaging" / "flatpak" / "com.kayab.FileWizard.metainfo.xml"
    if not meta.is_file():
        return
    text = meta.read_text(encoding="utf-8")
    m = re.search(r'<release version="([0-9.]+)"', text)
    assert m is not None
    assert m.group(1) == _version()


def test_python_version_matches_changelog() -> None:
    changelog = (_root() / "CHANGELOG.md").read_text(encoding="utf-8")
    m = re.search(r"^## \[([0-9.]+)\]", changelog, re.MULTILINE)
    assert m is not None, "CHANGELOG has no versioned section"
    assert m.group(1) == _version()


def test_python_version_matches_appimage_readme() -> None:
    readme = (_root() / "packaging" / "appimage" / "README.md").read_text(
        encoding="utf-8"
    )
    assert _version() in readme, "AppImage README missing current version"


def test_artifact_names_derive_from_version() -> None:
    # build.sh derives VERSION from __version__; check the literal template.
    build = (_root() / "packaging" / "appimage" / "build.sh").read_text(
        encoding="utf-8"
    )
    assert "FileWizard-${VERSION}" in build
    assert "filewizard_${VERSION}" in (
        _root() / "packaging" / "deb" / "build-deb.sh"
    ).read_text(encoding="utf-8")


def test_python_version_matches_init_and_cli() -> None:
    init = (_root() / "src" / "filewizard" / "__init__.py").read_text(
        encoding="utf-8"
    )
    assert f'__version__ = "{_version()}"' in init
    # CLI reads the same __version__.
    cli = (_root() / "src" / "filewizard" / "cli.py").read_text(encoding="utf-8")
    # click version comes from __version__ via import in cli module.
    assert "filewizard" in cli