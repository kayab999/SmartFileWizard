#!/bin/sh
set -e
if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database /usr/share/applications || true
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
  gtk-update-icon-cache -f -t /usr/share/icons/hicolor 2>/dev/null || true
fi
# Do NOT delete user state in ~/.local/share/filewizard on purge — user asked to keep/wipe via 'filewizard reset'
echo "FileWizard removed. User data remains in ~/.local/share/filewizard (use 'filewizard reset --all --yes' to wipe)."
