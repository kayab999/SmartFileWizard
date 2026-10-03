# Brand sources

Masters used to regenerate the runtime assets:

- `icon.png` — app / window icon (folder + violet→cyan path)
- `splash screen.png` — startup splash (hat mark + wordmark)
- `tray_idle.png`, `tray_active.png`, `tray_alert.png` — tray glyphs (hat mark)

Regenerate packaged files:

```bash
python3 scripts/prepare_ui_assets.py
```

Output: `src/filewizard/ui/assets/`.
