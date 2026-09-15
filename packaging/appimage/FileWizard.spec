# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for FileWizard.
Produces a one-dir distribution under dist/FileWizard/
which is assembled into an AppImage by packaging/appimage/build.sh.

GUI is the default entry; CLI is preserved via a second executable
that shares the same collected dependencies (one-dir mode).
"""

import os
import sys
from pathlib import Path

# Resolve project root (spec is at packaging/appimage/FileWizard.spec)
# PyInstaller >=6 exposes SPECPATH; fallback to __file__ for manual runs.
try:
    SPEC_DIR = Path(SPECPATH).resolve()  # type: ignore[name-defined]
except NameError:
    SPEC_DIR = Path(__file__).parent.resolve()
ROOT = SPEC_DIR.parent.parent.resolve()
SRC = ROOT / "src"

block_cipher = None

# Data files: QSS + assets + example yamls (for presets/docs reference)
datas = [
    (str(SRC / "filewizard" / "ui" / "style.qss"), "filewizard/ui"),
    (str(SRC / "filewizard" / "ui" / "assets"), "filewizard/ui/assets"),
]

# Include example rules if present (optional, not required at runtime)
for name in ["rules.example.yaml", "rules_sharp.yaml", "rules_cascade_ml.example.yaml",
             "rules_downloads.example.yaml", "perception.example.yaml"]:
    p = ROOT / name
    if p.exists():
        datas.append((str(p), "."))

# PySide6 needs its Qt plugins; PyInstaller's hook-PySide6 does most of it.
# Hidden imports for dynamic import sites (lazy imports, plugins, etc.).
hiddenimports = [
    "filewizard.cli",
    "filewizard.ui.app",
    "filewizard.ui.__main__",
    "filewizard.ui.main_window",
    "filewizard.ui.wizard",
    "filewizard.ui.settings_dialog",
    "filewizard.ui.review_dialog",
    "filewizard.ui.preview_dialog",
    "filewizard.ui.theme",
    "filewizard.ui.tray",
    "filewizard.mcp",
    "filewizard.mcp.server",
    "filewizard.mcp.tools",
    "filewizard.perception.factory",
    "filewizard.perception.config",
    "filewizard.perception.cascade",
    "filewizard.perception.extractors",
    "filewizard.perception.http_openai",
    "filewizard.perception.zeroshot",
    "filewizard.plugins.heuristics",
    "PIL",
    "PIL.Image",
    "yaml",
    "pydantic",
    "click",
]

# Exclude heavy optional deps that are NOT bundled (zeroshot/torch).
# They remain import-guarded in code; bundling would blow up size to >2GB.
excludes = [
    "torch",
    "transformers",
    "torchvision",
    "accelerate",
    "sentencepiece",
    "tkinter",
    "IPython",
    "notebook",
    "matplotlib",
]

a = Analysis(
    [str(SPEC_DIR / "entry_main.py")],
    pathex=[str(SRC)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="FileWizard",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    icon=str(SRC / "filewizard" / "ui" / "assets" / "app_icon_256.png"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="FileWizard",
)
