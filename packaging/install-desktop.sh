#!/usr/bin/env bash
# Install a user-local .desktop + hicolor icon.
# Works for pip installs (Exec=filewizard-ui). For the AppImage, the
# artifact itself carries the desktop file; this script is for source installs.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ICON_SRC="$ROOT/src/filewizard/ui/assets/app_icon_256.png"
DESKTOP_SRC="$ROOT/packaging/filewizard.desktop"
ICON_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/256x256/apps"
APP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"

mkdir -p "$ICON_DIR" "$APP_DIR"
install -m 644 "$ICON_SRC" "$ICON_DIR/filewizard.png"
# If an AppImage is present in ~/Applications, prefer its desktop entry's Exec;
# otherwise use the pip-installed filewizard-ui from this repo.
install -m 644 "$DESKTOP_SRC" "$APP_DIR/filewizard.desktop"
echo "Installed $APP_DIR/filewizard.desktop"
echo "Icon: $ICON_DIR/filewizard.png"
# Validate when possible
if command -v desktop-file-validate >/dev/null 2>&1; then
  desktop-file-validate "$APP_DIR/filewizard.desktop" || true
fi
if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "$APP_DIR" || true
fi
echo "Tip: AppImage users don't need this script — the AppImage is self-contained."
