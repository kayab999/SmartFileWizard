#!/usr/bin/env python3
"""Slice brand JPEGs into runtime RGBA PNGs (run from repo root)."""

from __future__ import annotations

from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
BRAND = ROOT / "docs" / "brand"
OUT = ROOT / "src" / "filewizard" / "ui" / "assets"


def _chroma(im: Image.Image, key: tuple[int, int, int], thresh: int) -> Image.Image:
    rgba = im.convert("RGBA")
    px = rgba.load()
    w, h = rgba.size
    kr, kg, kb = key
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            if abs(r - kr) + abs(g - kg) + abs(b - kb) <= thresh:
                px[x, y] = (r, g, b, 0)
    return rgba


def _bbox_opaque(im: Image.Image, min_alpha: int = 16) -> tuple[int, int, int, int]:
    extrema = im.split()[-1]
    return extrema.point(lambda a: 255 if a >= min_alpha else 0).getbbox() or (
        0,
        0,
        im.width,
        im.height,
    )


def prepare_icon(src: Path) -> None:
    # Keep the squircle-on-canvas; flood-fill eats the folder fill (same gray).
    im = Image.open(src).convert("RGBA")
    im.save(OUT / "app_icon.png", "PNG")
    im.resize((256, 256), Image.Resampling.LANCZOS).save(
        OUT / "app_icon_256.png", "PNG"
    )


def prepare_splash(src: Path) -> None:
    Image.open(src).convert("RGB").save(OUT / "splash.png", "PNG")


def prepare_tray_file(src: Path, name: str) -> None:
    im = Image.open(src).convert("RGBA")
    im.resize((128, 128), Image.Resampling.LANCZOS).save(OUT / name, "PNG")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    prepare_icon(BRAND / "icon.png")
    prepare_splash(BRAND / "splash screen.png")
    for name in ("tray_idle.png", "tray_active.png", "tray_alert.png"):
        prepare_tray_file(BRAND / name, name)
    print(f"Wrote assets to {OUT}")


if __name__ == "__main__":
    main()
