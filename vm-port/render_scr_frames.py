#!/usr/bin/env python3
"""Render Spectrum .scr captures as PNGs or a labelled contact sheet."""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


PALETTE = (
    (0, 0, 0), (32, 48, 192), (192, 64, 16), (192, 64, 192),
    (64, 176, 16), (80, 192, 176), (224, 192, 16), (192, 192, 192),
    (0, 0, 0), (48, 64, 255), (255, 64, 48), (255, 112, 240),
    (80, 224, 16), (80, 224, 255), (255, 232, 80), (255, 255, 255),
)


def spectrum_offset(y: int, byte_x: int) -> int:
    return ((y & 0xC0) << 5) | ((y & 7) << 8) | ((y & 0x38) << 2) | byte_x


def render(payload: bytes) -> Image.Image:
    if len(payload) != 6912:
        raise RuntimeError(f"expected 6912-byte screen, got {len(payload)}")
    image = Image.new("RGB", (256, 192))
    pixels = image.load()
    for y in range(192):
        for byte_x in range(32):
            bits = payload[spectrum_offset(y, byte_x)]
            attribute = payload[6144 + (y // 8) * 32 + byte_x]
            bright = (attribute >> 6) & 1
            ink = PALETTE[(attribute & 7) + 8 * bright]
            paper = PALETTE[((attribute >> 3) & 7) + 8 * bright]
            for bit in range(8):
                pixels[byte_x * 8 + bit, y] = ink if bits & (0x80 >> bit) else paper
    return image


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("screens", nargs="+", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--columns", type=int, default=4)
    args = parser.parse_args()

    images = [(path.stem, render(path.read_bytes())) for path in args.screens]
    if len(images) == 1 and args.out.suffix.lower() == ".png":
        args.out.parent.mkdir(parents=True, exist_ok=True)
        images[0][1].save(args.out)
        return

    label_height = 18
    columns = min(args.columns, len(images))
    rows = (len(images) + columns - 1) // columns
    sheet = Image.new("RGB", (columns * 256, rows * (192 + label_height)), "black")
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default()
    for index, (label, image) in enumerate(images):
        x = index % columns * 256
        y = index // columns * (192 + label_height)
        sheet.paste(image, (x, y + label_height))
        draw.text((x + 4, y + 3), label, fill="white", font=font)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(args.out)


if __name__ == "__main__":
    main()
