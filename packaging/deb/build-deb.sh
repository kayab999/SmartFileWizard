#!/usr/bin/env bash
# Build FileWizard .deb from the PyInstaller one-dir (dist/FileWizard).
# Needs: dist/FileWizard already built (via packaging/appimage/build.sh --no-appimage)
#        or will build it if missing.
# Produces: dist/filewizard_*_amd64.deb
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
VERSION="$(python3 -c 'import sys; sys.path.insert(0, "src"); import filewizard; print(filewizard.__version__)')"
DIST="$ROOT/dist"
ARCH="${ARCH:-amd64}"

echo "[deb] FileWizard $VERSION arch=$ARCH"
echo "[deb] ROOT=$ROOT"

# Ensure PyInstaller payload exists; build if missing
if [ ! -d "$DIST/FileWizard" ]; then
  echo "[deb] dist/FileWizard not found — building via appimage --no-appimage ..."
  bash packaging/appimage/build.sh --no-appimage
fi

# Validate payload
if [ ! -x "$DIST/FileWizard/FileWizard" ]; then
  echo "ERROR: $DIST/FileWizard/FileWizard not executable" >&2
  ls -lh "$DIST/FileWizard/" | head -n 20 >&2
  exit 1
fi

# Render nfpm.yaml with current version (templated if needed)
NFPM_CFG="/tmp/nfpm.filewizard.yaml"
# Use the committed packaging/nfpm.yaml as template, patch version line
sed -E "s/^(version:).*/\1 $VERSION/" packaging/nfpm.yaml > "$NFPM_CFG"
echo "[deb] nfpm config $NFPM_CFG:"
cat "$NFPM_CFG"

# Ensure nfpm is available
if ! command -v nfpm >/dev/null 2>&1; then
  echo "[deb] nfpm not found, installing ..."
  TMP_DEB="/tmp/nfpm_${ARCH}.deb"
  # goreleaser/nfpm: try the canonical latest URL, fallback to API-discovered asset
  if ! curl -sSfL -o "$TMP_DEB" "https://github.com/goreleaser/nfpm/releases/latest/download/nfpm_amd64.deb" 2>/dev/null; then
    echo "[deb] primary nfpm URL 404, resolving via GitHub API ..."
    NFPM_URL="$(curl -s https://api.github.com/repos/goreleaser/nfpm/releases/latest | python3 -c 'import sys, json; data=json.load(sys.stdin); print(next((a["browser_download_url"] for a in data.get("assets",[]) if a["name"].endswith("amd64.deb")), ""))')"
    if [ -z "$NFPM_URL" ] || [ "$NFPM_URL" = "" ]; then
      echo "ERROR: could not resolve nfpm .deb URL from GitHub API" >&2
      exit 1
    fi
    echo "[deb] downloading $NFPM_URL ..."
    curl -sSfL -o "$TMP_DEB" "$NFPM_URL"
  fi
  sudo dpkg -i "$TMP_DEB" || sudo apt-get install -f -y
fi
nfpm --version

# Build
echo "[deb] building .deb ..."
# nfpm 2.x: nfpm pkg --packager deb --target dist/ --config /tmp/...
nfpm pkg --packager deb --target "$DIST/" --config "$NFPM_CFG"

echo "[deb] done:"
ls -lh "$DIST"/*.deb 2>/dev/null || ls -lh "$DIST"/filewizard*.deb 2>/dev/null
DEB="$(ls -1 "$DIST"/*.deb 2>/dev/null | head -n1)"
if [ -n "${DEB:-}" ]; then
  echo "[deb] SHA256: $(sha256sum "$DEB" | cut -d' ' -f1)"
  # quick lint if available
  if command -v lintian >/dev/null 2>&1; then
    echo "[deb] lintian (non-fatal):"
    lintian "$DEB" || true
  fi
  echo ""
  echo "Install test (dry): sudo dpkg -i \"$DEB\" && filewizard --help && filewizard-ui --help"
fi
