# FileWizard AppImage packaging

Local build for `FileWizard-0.11.0-x86_64.AppImage`.

## Quick build (Ubuntu 22.04 / Debian 12 / Fedora 40)

```bash
cd "/home/carlos/file wizard"
bash packaging/appimage/build.sh
# artifact: dist/FileWizard-0.11.0-x86_64.AppImage
chmod +x dist/FileWizard-*.AppImage
./dist/FileWizard-*.AppImage --help      # CLI
./dist/FileWizard-*.AppImage              # GUI (or double-click)
./dist/FileWizard-*.AppImage run --source ~/Downloads --preset downloads-docs --verbose
```

## How it works

1. **PyInstaller** (`packaging/appimage/FileWizard.spec`) collects Python + PySide6 + Pillow
   into `dist/FileWizard/` (one-dir). Two entrypoints share the same libs:
   `filewizard` (CLI, console) + `filewizard-ui` (GUI, windowed).
2. `build.sh` assembles `dist/FileWizard.AppDir/` per AppImage spec:
   `AppRun` (dispatches GUI vs CLI), `filewizard.desktop`, hicolor icon, `.DirIcon`.
3. **appimagetool** squashes the AppDir into a portable AppImage.

Optional deps NOT bundled (remain import-guarded):
- `torch` / `transformers` (zero-shot CLIP)
- `tesseract` binary
- `llama-server` (GLM-OCR / Qwen-VL over HTTP)

Point `perception.yaml` at your own endpoints; see `perception.example.yaml`.

## Smoke only (no AppImage)

```bash
bash packaging/appimage/build.sh --no-appimage
./dist/FileWizard/filewizard --help
./dist/FileWizard/filewizard-ui  # needs display
```

## CI

Tagged push `v*` triggers `.github/workflows/release.yml` on `ubuntu-22.04`
(Python 3.11) and uploads the AppImage to GitHub Releases.

## Troubleshooting

| Issue | Fix |
|-------|-----|
| `libfuse.so.2` missing on Ubuntu 24.04 | `sudo apt install libfuse2` or run with `--appimage-extract-and-run` |
| Blank window / missing `libqxcb` | Ensure PyInstaller hook-PySide6 ran; rebuild on clean host |
| Icon missing in menu | Check `desktop-file-validate packaging/filewizard.desktop` |

## Secondaries

- `.deb` via `nfpm` from same AppDir is easy (`dist/FileWizard.AppDir/usr/bin/filewizard` → `/usr/bin/filewizard`).
- Flatpak manifest is backlog 0.12+ (needs `org.kde.Platform`).

## File map

```
packaging/appimage/FileWizard.spec  # PyInstaller
packaging/appimage/AppRun           # AppImage entry (:/)
packaging/appimage/build.sh         # local + CI build
packaging/filewizard.desktop        # shared with install-desktop.sh
```
