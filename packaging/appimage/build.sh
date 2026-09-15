#!/usr/bin/env bash
# Build FileWizard AppImage from the local checkout.
# Usage:
#   bash packaging/appimage/build.sh              # build FileWizard-0.11.0-x86_64.AppImage in dist/
#   bash packaging/appimage/build.sh --no-appimage  # only PyInstaller one-dir (for smoke)
#
# Requirements:
#   Python 3.11+, pip, PyInstaller 6.x, Pillow, PySide6, mcp (optional)
#   appimagetool (auto-downloaded if missing) for the final AppImage
#   Recommended build host: ubuntu-22.04 (glibc 2.35) for max compat.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

VERSION="$(python3 -c 'import sys; sys.path.insert(0, "src"); import filewizard; print(filewizard.__version__)')"
ARCH="${ARCH:-x86_64}"
DIST="$ROOT/dist"
APPDIR="$DIST/FileWizard.AppDir"
SPEC="$ROOT/packaging/appimage/FileWizard.spec"
APPIMAGE_NAME="FileWizard-${VERSION}-${ARCH}.AppImage"
OUTPUT="$DIST/$APPIMAGE_NAME"
NO_APPIMAGE=0

for arg in "$@"; do
  case "$arg" in
    --no-appimage) NO_APPIMAGE=1 ;;
    --help|-h) echo "Usage: $0 [--no-appimage]"; exit 0 ;;
  esac
done

echo "[build] FileWizard $VERSION  ARCH=$ARCH"
echo "[build] ROOT=$ROOT"
echo "[build] SPEC=$SPEC"
echo "[build] DIST=$DIST"

# --- checks ---
if [ ! -f "$SPEC" ]; then echo "ERROR: spec not found: $SPEC" >&2; exit 1; fi
if ! command -v python3 >/dev/null 2>&1; then echo "ERROR: python3 not found" >&2; exit 1; fi

# --- clean previous ---
echo "[build] cleaning $DIST/FileWizard* ..."
rm -rf "$APPDIR" "$DIST/FileWizard" "$DIST"/FileWizard-*.AppImage
mkdir -p "$DIST"

# --- ensure PyInstaller + deps ---
echo "[build] ensuring PyInstaller + runtime deps ..."
python3 -m pip install --quiet --upgrade pip
# Pin PyInstaller 6 to avoid 7-alpha breakage; pillow/PySide6 already in requirements
python3 -m pip install --quiet "pyinstaller>=6,<7" "pillow>=10.0" "PySide6>=6.6" "click>=8.1" "pydantic>=2.7" "PyYAML>=6.0" "mcp>=2.0" || {
  echo "[build] optional mcp install failed, continuing without it"
  python3 -m pip install --quiet "pyinstaller>=6,<7" "pillow>=10.0" "PySide6>=6.6" "click>=8.1" "pydantic>=2.7" "PyYAML>=6.0"
}

# --- PyInstaller ---
echo "[build] running PyInstaller ..."
python3 -m PyInstaller --noconfirm --clean --distpath "$DIST" --workpath "$ROOT/build" "$SPEC"

if [ ! -d "$DIST/FileWizard" ]; then
  echo "ERROR: PyInstaller did not produce $DIST/FileWizard" >&2
  ls -R "$DIST" >&2 || true
  exit 1
fi

if [ "$NO_APPIMAGE" = "1" ]; then
  echo "[build] --no-appimage: stopping after PyInstaller"
  ls -lh "$DIST/FileWizard/" | head -n 30
  exit 0
fi

# --- Assemble AppDir (AppImage spec) ---
echo "[build] assembling AppDir $APPDIR ..."
rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/bin" "$APPDIR/usr/share/applications" "$APPDIR/usr/share/icons/hicolor/256x256/apps"

# Copy PyInstaller one-dir payload into usr/bin
cp -a "$DIST/FileWizard/." "$APPDIR/usr/bin/"

# Desktop file + icons
cp "$ROOT/packaging/filewizard.desktop" "$APPDIR/usr/share/applications/filewizard.desktop"
cp "$ROOT/src/filewizard/ui/assets/app_icon_256.png" "$APPDIR/usr/share/icons/hicolor/256x256/apps/filewizard.png"
# toplevel icon + desktop symlink required by appimagetool
cp "$ROOT/src/filewizard/ui/assets/app_icon_256.png" "$APPDIR/filewizard.png"
ln -sf "usr/share/applications/filewizard.desktop" "$APPDIR/filewizard.desktop"
# DirIcon for appimagetool (must be at toplevel)
cp "$ROOT/src/filewizard/ui/assets/app_icon_256.png" "$APPDIR/.DirIcon"

# AppRun (GUI defaults, CLI dispatch)
cp "$ROOT/packaging/appimage/AppRun" "$APPDIR/AppRun"
chmod +x "$APPDIR/AppRun"

# Symlinks so invoking as filewizard* works inside the mount (AppRun not needed for these)
ln -sf "FileWizard" "$APPDIR/usr/bin/filewizard" 2>/dev/null || true
ln -sf "FileWizard" "$APPDIR/usr/bin/filewizard-ui" 2>/dev/null || true
ln -sf "FileWizard" "$APPDIR/usr/bin/filewizard-mcp" 2>/dev/null || true
ln -sf "FileWizard" "$APPDIR/usr/bin/filewizard-cli" 2>/dev/null || true

echo "[build] AppDir tree:"
find "$APPDIR" -maxdepth 4 -type f -o -type l | sort | head -n 40

# Validate desktop file if possible
if command -v desktop-file-validate >/dev/null 2>&1; then
  echo "[build] validating desktop file ..."
  desktop-file-validate "$APPDIR/usr/share/applications/filewizard.desktop" || echo "[build] WARNING: desktop file validation failed"
fi

# --- appimagetool ---
APPIMAGETOOL_BIN=""
if command -v appimagetool >/dev/null 2>&1; then
  APPIMAGETOOL_BIN="$(command -v appimagetool)"
else
  echo "[build] appimagetool not found, downloading ..."
  TMP_TOOL="/tmp/appimagetool-${ARCH}.AppImage"
  if [ ! -x "$TMP_TOOL" ]; then
    curl -L -o "$TMP_TOOL" "https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-${ARCH}.AppImage"
    chmod +x "$TMP_TOOL"
  fi
  APPIMAGETOOL_BIN="$TMP_TOOL"
fi

echo "[build] creating AppImage $OUTPUT with $APPIMAGETOOL_BIN ..."
ARCH="$ARCH" "$APPIMAGETOOL_BIN" "$APPDIR" "$OUTPUT"

echo "[build] done:"
ls -lh "$OUTPUT"
echo "[build] SHA256: $(sha256sum "$OUTPUT" | cut -d' ' -f1)"
echo ""
echo "Run:  chmod +x \"$OUTPUT\" && \"$OUTPUT\" --help"
echo "GUI:  chmod +x \"$OUTPUT\" && \"$OUTPUT\"   # or double-click in Files"
echo "CLI:  \"$OUTPUT\" run --source ~/Downloads --preset downloads-docs --verbose"
