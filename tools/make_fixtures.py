#!/usr/bin/env python3
"""Génère les images et pages synthétiques du site de démonstration.

Aucune photo réelle : ce sont des formes géométriques plates, volontairement
simples. Un modèle vision les décrira comme telles, et c'est exactement le
comportement attendu : l'outil ``inspect_image`` ne prétend pas inventer une
scène, il décrit ce qu'il voit.

    python tools/make_fixtures.py
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "fixtures" / "site"
GAMME = ROOT / "fixtures" / "gamme"


def write_png(path: Path, width: int, height: int, painter) -> None:
    """PNG RGB minimal (filtre 0, compression zlib), sans dépendance."""
    raw = bytearray()
    for y in range(height):
        raw.append(0)
        for x in range(width):
            raw.extend(painter(x, y, width, height))

    def chunk(kind: bytes, payload: bytes) -> bytes:
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    data = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(bytes(raw), 6)) + chunk(b"IEND", b"")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def scooter(x: int, y: int, w: int, h: int) -> tuple[int, int, int]:
    if (x // 10 + y // 10) % 2 == 0:
        background = (238, 240, 243)
    else:
        background = (232, 235, 239)
    cx, cy = w * 0.5, h * 0.62
    if abs((x - cx) ** 2 + (y - cy) ** 2 - (h * 0.16) ** 2) < h * 16:
        return (34, 34, 38)
    if abs(x - cx) < w * 0.16 and h * 0.45 < y < cy:
        return (198, 40, 40)
    if abs(y - (h * 0.42)) < h * 0.02 and w * 0.34 < x < w * 0.66:
        return (120, 120, 126)
    return background


def bicycle(x: int, y: int, w: int, h: int) -> tuple[int, int, int]:
    background = (245, 247, 250)
    if abs((x - w * 0.3) ** 2 + (y - h * 0.65) ** 2 - (h * 0.12) ** 2) < h * 12:
        return (30, 30, 34)
    if abs((x - w * 0.7) ** 2 + (y - h * 0.65) ** 2 - (h * 0.12) ** 2) < h * 12:
        return (30, 30, 34)
    if h * 0.35 < y < h * 0.65 and w * 0.3 < x < w * 0.7 and abs((x - w * 0.5) - (y - h * 0.5) * 0.8) < w * 0.02:
        return (38, 92, 168)
    return background


def shopfront(x: int, y: int, w: int, h: int) -> tuple[int, int, int]:
    if y < h * 0.28:
        return (176, 178, 182)
    if y > h * 0.8:
        return (120, 116, 110)
    if abs(x - w * 0.5) < w * 0.12 and h * 0.45 < y < h * 0.8:
        return (92, 64, 40)
    if (x < w * 0.12 or x > w * 0.88) or y < h * 0.33:
        return (150, 152, 156)
    return (214, 226, 236)


def lineup(x: int, y: int, w: int, h: int) -> tuple[int, int, int]:
    background = (250, 250, 252)
    band = y / h
    if 0.25 < band < 0.32:
        return (28, 28, 32)
    left = x / w
    if 0.4 < band < 0.78:
        for start, color in ((0.14, (198, 40, 40)), (0.42, (38, 92, 168)), (0.70, (46, 125, 70))):
            if start < left < start + 0.16:
                return color
    return background


def logo(x: int, y: int, w: int, h: int) -> tuple[int, int, int]:
    """Pictogramme simple : un disque rose et une barre, sans texte."""
    cx, cy, radius = w * 0.42, h * 0.5, w * 0.26
    if (x - cx) ** 2 + (y - cy) ** 2 < radius ** 2:
        return (176, 48, 96)
    if w * 0.66 < x < w * 0.84 and h * 0.38 < y < h * 0.62:
        return (107, 91, 210)
    return (255, 255, 255)


def main() -> int:
    write_png(SITE / "hero.png", 320, 200, scooter)
    write_png(SITE / "velo.png", 320, 200, bicycle)
    write_png(SITE / "boutique.png", 320, 200, shopfront)
    write_png(SITE / "logo.png", 160, 160, logo)
    write_png(GAMME / "gamme.png", 320, 200, lineup)
    for path in sorted(list(SITE.glob("*.png")) + list(GAMME.glob("*.png"))):
        print(f"{path.relative_to(ROOT)}  {path.stat().st_size} o")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
