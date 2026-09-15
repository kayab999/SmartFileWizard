#!/usr/bin/env bash
# Build FileWizard .deb from the PyInstaller one-dir (dist/FileWizard).
# Needs: dist/FileWizard already built (via packaging/appimage/build.sh --no-appimage)
#        or will build it if missing.
# Produces: dist/filewizard_*_amd64.deb
# Uses dpkg-deb staging (no nfpm required) for reliable recursive copies.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
VERSION="$(python3 -c 'import sys; sys.path.insert(0, "src"); import filewizard; print(filewizard.__version__)')"
DIST="$ROOT/dist"
ARCH="${ARCH:-amd64}"
DEB_ARCH="amd64"
STAGING="$ROOT/build/deb-root"

echo "[deb] FileWizard $VERSION arch=$ARCH"
echo "[deb] ROOT=$ROOT"

# Ensure PyInstaller payload exists; build if missing
if [ ! -d "$DIST/FileWizard" ]; then
  echo "[deb] dist/FileWizard not found — building via appimage --no-appimage ..."
  bash packaging/appimage/build.sh --no-appimage
fi

if [ ! -x "$DIST/FileWizard/FileWizard" ]; then
  echo "ERROR: $DIST/FileWizard/FileWizard not executable" >&2
  ls -lh "$DIST/FileWizard/" | head -n 20 >&2
  exit 1
fi

# Clean staging
rm -rf "$STAGING"
mkdir -p "$STAGING/DEBIAN" "$STAGING/opt/filewizard" "$STAGING/usr/bin" "$STAGING/usr/share/applications" "$STAGING/usr/share/icons/hicolor/256x256/apps"

# Copy payload (preserves _internal + libs)
echo "[deb] staging payload ..."
cp -a "$DIST/FileWizard/." "$STAGING/opt/filewizard/"
chmod +x "$STAGING/opt/filewizard/FileWizard"

# Desktop + icon
install -m 644 packaging/filewizard.desktop "$STAGING/usr/share/applications/filewizard.desktop"
install -m 644 src/filewizard/ui/assets/app_icon_256.png "$STAGING/usr/share/icons/hicolor/256x256/apps/filewizard.png"

# Symlink shims (small shell wrappers calling the unified binary)
install -m 755 packaging/deb/bin-filewizard "$STAGING/usr/bin/filewizard"
install -m 755 packaging/deb/bin-filewizard-ui "$STAGING/usr/bin/filewizard-ui"
install -m 755 packaging/deb/bin-filewizard-mcp "$STAGING/usr/bin/filewizard-mcp"

# Control file
cat > "$STAGING/DEBIAN/control" <<EOF
Package: filewizard
Version: $VERSION
Section: utils
Priority: optional
Architecture: $DEB_ARCH
Maintainer: Kayab Software <kayab999@users.noreply.github.com>
Homepage: https://github.com/kayab999/SmartFileWizard
Description: Local-first file classification and organization engine for Linux
 Rule-based moves with dry-run, journal undo, cascade perception.
 .
 The .deb bundles the same PyInstaller payload as the AppImage
 (/opt/filewizard) plus desktop entry and icons. User data stays
 in ~/.local/share/filewizard and is preserved on removal.
Depends: libgl1, libxcb-xinerama0 | libxcb1, libxkbcommon0, libdbus-1-3
Recommends: tesseract-ocr
Suggests: llama-server
EOF

cat "$STAGING/DEBIAN/control"

# Maintainer scripts
install -m 755 packaging/deb/postinstall.sh "$STAGING/DEBIAN/postinst"
install -m 755 packaging/deb/postremove.sh "$STAGING/DEBIAN/postrm"

# Build deb
DEB_NAME="filewizard_${VERSION}_${DEB_ARCH}.deb"
DEB_PATH="$DIST/$DEB_NAME"
echo "[deb] building $DEB_PATH ..."
rm -f "$DEB_PATH"
dpkg-deb --build "$STAGING" "$DEB_PATH"

echo "[deb] done:"
ls -lh "$DEB_PATH"
echo "[deb] contents (first 40):"
dpkg-deb -c "$DEB_PATH" | head -n 50
echo "[deb] SHA256: $(sha256sum "$DEB_PATH" | cut -d' ' -f1)"
if command -v lintian >/dev/null 2>&1; then
  echo "[deb] lintian (non-fatal):"
  lintian "$DEB_PATH" || true
fi
echo ""
echo "Test: sudo dpkg -i \"$DEB_PATH\" && filewizard --help && filewizard --version && dpkg -L filewizard | head"
