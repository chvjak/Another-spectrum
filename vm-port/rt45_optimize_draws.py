#!/usr/bin/env python3
"""Classify intro draw calls by final sampled-pixel ownership.

This is deliberately an offline tool. It replays the traced four logical
pages with an owner id beside every indexed pixel. At each retained 5 fps
presentation, owners which survive the painter's algorithm are marked live.
The resulting report separates clipping, sub-pixel collapse, overwrite, static
background work, and dynamic survivors without duplicating shape geometry.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

TRACE: Path
OUT: Path
KEEP_TICKS: set[int]
W, H = 320, 200


def main() -> None:
    pages = [np.zeros((H, W), dtype=np.int32) for _ in range(4)]
    colors = [np.zeros((H, W), dtype=np.uint8) for _ in range(4)]
    tick = -1
    current_event = 0
    event_tick: dict[int, int] = {}
    event_kind: dict[int, str] = {}
    event_page: dict[int, int] = {}
    event_pixels: Counter[int] = Counter()
    live: set[int] = set()
    sampled = 0
    pending_quad: tuple[int, int, int] | None = None
    vertices: list[tuple[int, int]] = []

    def new_event(kind: str) -> None:
        nonlocal current_event
        current_event += 1
        event_tick[current_event] = tick
        event_kind[current_event] = kind

    def paint(page: int, pixels: np.ndarray, color: int) -> None:
        if color == 17:
            colors[page][pixels] = colors[0][pixels]
        elif color == 16:
            colors[page][pixels] |= 8
        else:
            colors[page][pixels] = color
        changed = pixels
        count = int(changed.sum())
        event_pixels[current_event] += count
        if count:
            pages[page][changed] = current_event
            event_page[current_event] = page

    def raster_polygon(page: int, color: int, points: list[tuple[int, int]]) -> None:
        if current_event == 0 or not points:
            return
        mask = Image.new("1", (W, H))
        ImageDraw.Draw(mask).polygon(points, fill=1)
        pixels = np.asarray(mask, dtype=bool)
        paint(page, pixels, color)

    def flush_quad() -> None:
        nonlocal pending_quad, vertices
        if pending_quad is not None:
            page, color, expected = pending_quad
            if len(vertices) != expected:
                raise RuntimeError((tick, current_event, len(vertices), expected))
            raster_polygon(page, color, vertices)
        pending_quad = None
        vertices = []

    tick_re = re.compile(r"TRACE_TICK (\d+)")
    quad_re = re.compile(r"SEM quadstrip buffer=(\d+) color=(\d+) vertices=(\d+)")
    vertex_re = re.compile(r"SEM vertex index=\d+ x=(-?\d+) y=(-?\d+)")
    point_re = re.compile(r"SEM point buffer=(\d+) color=(\d+) x=(-?\d+) y=(-?\d+)")
    glyph_re = re.compile(r"SEM glyph buffer=(\d+) color=(\d+) char=\d+ x=(-?\d+) y=(-?\d+)")
    clear_re = re.compile(r"SEM clear buffer=(\d+) color=(\d+)")
    copy_re = re.compile(r"SEM copy dst=(\d+) src=(\d+)")
    present_re = re.compile(r"SEM present buffer=(\d+)")

    for line in TRACE.read_text(errors="replace").splitlines():
        match = vertex_re.search(line)
        if match:
            vertices.append((int(match.group(1)), int(match.group(2))))
            continue
        flush_quad()
        match = tick_re.search(line)
        if match:
            tick = int(match.group(1))
            continue
        if "vid_opcd_" in line:
            new_event("shape")
            continue
        if "Script::op_drawString(" in line:
            new_event("text")
            continue
        match = quad_re.search(line)
        if match:
            pending_quad = tuple(map(int, match.groups()))
            continue
        match = point_re.search(line)
        if match:
            page, color, x, y = map(int, match.groups())
            if 0 <= x < W and 0 <= y < H:
                pixels = np.zeros((H, W), dtype=bool)
                pixels[y, x] = True
                paint(page, pixels, color)
            continue
        match = glyph_re.search(line)
        if match:
            page, color, x, y = map(int, match.groups())
            x0, y0, x1, y1 = max(0, x), max(0, y), min(W, x + 8), min(H, y + 8)
            if x0 < x1 and y0 < y1:
                pixels = np.zeros((H, W), dtype=bool)
                pixels[y0:y1, x0:x1] = True
                paint(page, pixels, color)
            continue
        match = clear_re.search(line)
        if match:
            page, color = map(int, match.groups())
            pages[page].fill(0)
            colors[page].fill(color)
            continue
        match = copy_re.search(line)
        if match:
            dst, src = map(int, match.groups())
            pages[dst][:] = pages[src]
            colors[dst][:] = colors[src]
            continue
        match = present_re.search(line)
        if match:
            is_sample = tick in KEEP_TICKS
            if is_sample:
                sampled += 1
                live.update(map(int, np.unique(pages[int(match.group(1))])))
    flush_quad()
    live.discard(0)

    categories = Counter()
    for event in range(1, current_event + 1):
        pixels = event_pixels[event]
        page = event_page.get(event)
        if pixels == 0:
            categories["clipped_or_zero_area"] += 1
        elif pixels < 2:
            categories["subpixel_point"] += 1
        elif event in live:
            categories["static_survivor" if page == 0 else "dynamic_survivor"] += 1
        else:
            categories["overwritten_before_sample"] += 1

    checkpoint_ticks = {190, 302, 403, 1053, 2211}
    baked = {
        event for event in range(1, current_event + 1)
        if event_page.get(event) == 0 and event_tick[event] in checkpoint_ticks
    }
    categories["checkpoint_baked"] = len(baked)

    keep = bytearray((current_event + 7) // 8)
    for event in live:
        keep[(event - 1) >> 3] |= 1 << ((event - 1) & 7)
    report = {
        "events": current_event,
        "sampled_presentations": sampled,
        "live_events": len(live),
        "removed_events": current_event - len(live),
        "categories": dict(categories),
        "event_mask_bytes_uncompressed": len(keep),
        "note": (
            "Owner analysis is exact for opaque painter-order survival. Text uses "
            "a conservative 8x8 box. COL_ALPHA/COL_PAGE events remain candidates "
            "for byte-level ablation before runtime removal."
        ),
    }
    OUT.write_text(json.dumps(report, indent=2) + "\n")
    (OUT.parent / "draw-event-keep-mask.bin").write_bytes(keep)
    print(json.dumps(report, indent=2))


def encode_runs(packed: bytes, count: int = 9648) -> bytes:
    bits = [(packed[i >> 3] >> (i & 7)) & 1 for i in range(count)]
    out = bytearray([bits[0]])
    current = bits[0]
    run = 0
    for bit in bits:
        if bit == current and run < 255:
            run += 1
            continue
        out.append(run)
        if bit == current:
            out.append(0)
        current = bit
        run = 1
    out.append(run)
    return bytes(out)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace", type=Path, required=True)
    ap.add_argument("--plan", type=Path, required=True)
    ap.add_argument("--out-dir", type=Path, required=True)
    args = ap.parse_args()
    plan = json.loads(args.plan.read_text())
    TRACE = args.trace
    KEEP_TICKS = {int(x) for x in plan["keep_ticks"]}
    args.out_dir.mkdir(parents=True, exist_ok=True)
    OUT = args.out_dir / "draw-optimization.json"
    main()
    packed = (args.out_dir / "draw-event-keep-mask.bin").read_bytes()
    runs = encode_runs(packed)
    (args.out_dir / "event-runs.bin").write_bytes(runs)
    report = json.loads(OUT.read_text())
    report.update({
        "plan": plan["name"],
        "kept_sample_slots": len(plan["keep_slots"]),
        "dropped_sample_slots": len(plan["drop_slots"]),
        "event_runs_bytes": len(runs),
    })
    OUT.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
