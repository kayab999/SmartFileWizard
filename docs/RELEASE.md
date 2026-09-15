# FileWizard 0.11.0 — release notes

**Date:** 2026-09-15  
**Tag:** `v0.11.0`  
**Python:** ≥ 3.11 · **Tests:** 224 passed

Full history: [CHANGELOG.md](../CHANGELOG.md) · User guide: [USER_MANUAL.md](./USER_MANUAL.md)

---

## What this release is

Coverage for mixed Downloads, a closed review loop, and a user-local desktop
icon plus a portable AppImage. The rule engine is unchanged (AND + priority).
Perception still does not move files.

1. Builtin preset **downloads-docs** (PDF, office, archives, video, audio).
2. Resolving the review queue writes `review_labels.json`; the next plan injects
   those categories after the cascade.
3. New conditions: `older_than_days`, `min_aspect`, `max_aspect`.
4. `packaging/install-desktop.sh` installs `.desktop` + hicolor 256px icon.
5. **AppImage** `FileWizard-0.11.0-x86_64.AppImage` (PyInstaller + appimagetool, `packaging/appimage/`).

---

## Install

### End users (AppImage, no Python needed)

```bash
# From https://github.com/kayab999/SmartFileWizard/releases/latest
chmod +x FileWizard-0.11.0-x86_64.AppImage
./FileWizard-0.11.0-x86_64.AppImage              # GUI or double-click
./FileWizard-0.11.0-x86_64.AppImage --help      # CLI
# FUSE fallback (Ubuntu 24.04 without libfuse2):
# ./FileWizard-0.11.0-x86_64.AppImage --appimage-extract-and-run --help
```

### Developers

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,ui]"
pytest -q
filewizard --version    # FileWizard, version 0.11.0
filewizard-ui
bash packaging/install-desktop.sh   # optional app menu (source install only)

# Build the AppImage locally:
bash packaging/appimage/build.sh
ls -lh dist/FileWizard-*.AppImage
```

---

## Verify before you tag

- [x] `__version__` == `0.11.0` (setuptools dynamic attr)
- [x] `pytest -q` green (224)
- [x] `filewizard --version` works
- [x] `bash packaging/appimage/build.sh` produces `dist/FileWizard-0.11.0-x86_64.AppImage`
- [x] `dist/FileWizard-*.AppImage --help` and `--appimage-extract-and-run --help` show CLI
- [x] `desktop-file-validate packaging/filewizard.desktop` passes
- [ ] Human: GUI intent descargas + cola → segunda preview
- [ ] Human: double-click AppImage shows splash + home (X11/Wayland)

```bash
git tag -a v0.11.0 -m "FileWizard 0.11.0"
git push origin main --tags   # triggers .github/workflows/release.yml → Releases
```

---

## Build outputs

| Artifact | Path | Notes |
|----------|------|-------|
| AppImage | `dist/FileWizard-0.11.0-x86_64.AppImage` | Portable, double-click; GUI default, CLI via args |
| AppDir | `dist/FileWizard.AppDir/` | Intermediate (for inspection / .deb via nfpm) |
| PyInstaller one-dir | `dist/FileWizard/` | Tunable via `packaging/appimage/FileWizard.spec` |

---

## Not in 0.11.0

Flatpak, inotify daemon, NPU/4B backends. See ROADMAP 0.12+.
