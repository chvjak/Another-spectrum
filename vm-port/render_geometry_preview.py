#!/usr/bin/env python3
"""Render a viewable polygon-only intro preview from the semantic VM trace.

The benchmark deliberately uses neutral bitmap/attribute assets, so its physical
Spectrum output is black even though the renderer work is real. This preview
replays the same DOS bytecode shape operations with a fixed 16-colour palette.
Bitmap resources and exact palette changes are not represented in the semantic
trace and therefore remain black; the video is a visual geometry inspection aid,
not a pixel-identical game capture.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

PALETTE = [
    (0, 0, 0), (32, 48, 192), (192, 64, 16), (192, 64, 192),
    (64, 176, 16), (80, 192, 176), (224, 192, 16), (192, 192, 192),
    (24, 24, 24), (48, 64, 255), (255, 64, 48), (255, 112, 240),
    (80, 224, 16), (80, 224, 255), (255, 232, 80), (255, 255, 255),
]

CLEAR_RE = re.compile(r"SEM clear buffer=(\d+) color=(-?\d+)")
COPY_RE = re.compile(r"SEM copy dst=(\d+) src=(\d+)")
POLY_RE = re.compile(r"SEM quadstrip buffer=(\d+) color=(-?\d+) vertices=(\d+)")
VERTEX_RE = re.compile(r"SEM vertex index=(\d+) x=(-?\d+) y=(-?\d+)")
POINT_RE = re.compile(r"SEM point buffer=(\d+) color=(-?\d+) x=(-?\d+) y=(-?\d+)")
GLYPH_RE = re.compile(r"SEM glyph buffer=(\d+) color=(-?\d+) char=(\d+) x=(-?\d+) y=(-?\d+)")
PRESENT_RE = re.compile(r"SEM present buffer=(\d+)")
TICK_RE = re.compile(r"TRACE_TICK (\d+)")


def rgb_page() -> Image.Image:
    return Image.new("RGB", (320, 200), PALETTE[0])


def colour(index: int) -> tuple[int, int, int]:
    # 16 and 17 are renderer control colours in some ports. The semantic copy
    # operations are already explicit; use a visible neutral fallback here.
    if 0 <= index < len(PALETTE):
        return PALETTE[index]
    return PALETTE[index & 15]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("trace", type=Path)
    parser.add_argument("out", type=Path)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    pages = [rgb_page() for _ in range(4)]
    lines = args.trace.read_text().splitlines()
    tick = -1
    saved = 0
    presents = 0
    font = ImageFont.load_default()

    i = 0
    while i < len(lines):
        line = lines[i]
        if match := TICK_RE.fullmatch(line):
            tick = int(match.group(1))
        elif match := CLEAR_RE.fullmatch(line):
            page, value = map(int, match.groups())
            if 0 <= page < len(pages):
                pages[page].paste(colour(value), (0, 0, 320, 200))
        elif match := COPY_RE.fullmatch(line):
            dst, src = map(int, match.groups())
            if 0 <= dst < len(pages) and 0 <= src < len(pages):
                pages[dst] = pages[src].copy()
        elif match := POLY_RE.fullmatch(line):
            page, value, count = map(int, match.groups())
            vertices: list[tuple[int, int]] = []
            for _ in range(count):
                i += 1
                vertex = VERTEX_RE.fullmatch(lines[i])
                if vertex is None:
                    raise RuntimeError(f"missing vertex after {line!r}: {lines[i]!r}")
                _, x, y = map(int, vertex.groups())
                vertices.append((max(-512, min(831, x)), max(-512, min(711, y))))
            if 0 <= page < len(pages) and vertices:
                draw = ImageDraw.Draw(pages[page])
                if len(vertices) == 1:
                    draw.point(vertices[0], fill=colour(value))
                elif len(vertices) == 2:
                    draw.line(vertices, fill=colour(value))
                else:
                    draw.polygon(vertices, fill=colour(value))
        elif match := POINT_RE.fullmatch(line):
            page, value, x, y = map(int, match.groups())
            if 0 <= page < len(pages):
                ImageDraw.Draw(pages[page]).point((x, y), fill=colour(value))
        elif match := GLYPH_RE.fullmatch(line):
            page, value, char, x, y = map(int, match.groups())
            if 0 <= page < len(pages):
                glyph = chr(char) if 32 <= char < 127 else "?"
                ImageDraw.Draw(pages[page]).text((x, y), glyph, fill=colour(value), font=font)
        elif match := PRESENT_RE.fullmatch(line):
            page = int(match.group(1))
            presents += 1
            # Match the Spectrum VM's sampled presentation schedule: tick 8,
            # then every tenth VM tick through tick 2978.
            if tick >= 8 and (tick - 8) % 10 == 0 and 0 <= page < len(pages):
                frame = pages[page].copy()
                frame.save(args.out / f"frame-{saved:03d}.png", optimize=True)
                saved += 1
        i += 1

    summary = {"trace_lines": len(lines), "present_events": presents, "saved_frames": saved, "last_tick": tick}
    print(summary)
    if saved != 298:
        raise RuntimeError(f"expected 298 sampled frames, got {saved}")


if __name__ == "__main__":
    main()
