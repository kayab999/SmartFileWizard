#!/bin/sh
set -e
# Update desktop database if present
if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database /usr/share/applications || true
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
  gtk-update-icon-cache -f -t /usr/share/icons/hicolor 2>/dev/null || true
fi
# No user data migration — XDG state stays in ~/.local/share/filewizard
echo "FileWizard installed. Run 'filewizard --help' or 'filewizard-ui' (also 'FileWizard' from /opt/filewizard)."
