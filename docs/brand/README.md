# Brand sources

JPEG masters (misnamed `.png`) used to generate runtime assets:

- `icon.png` — app / window icon (folder + purple→cyan swirl)
- `splash screen.png` — startup splash
- `TRAY ICON SET.png` — idle / active / alert tray glyphs

Regenerate packaged files:

```bash
python3 scripts/prepare_ui_assets.py
```

Output: `src/filewizard/ui/assets/`.
