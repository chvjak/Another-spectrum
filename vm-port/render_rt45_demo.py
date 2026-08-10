#!/usr/bin/env python3
"""Render the 298 original-colour intro samples using the verified 4.5 fps plan.

Input is exactly 298 packed RGB24 frames at 320x200, produced by
capture_original_colour_preview.mjs. The source dimensions are asserted so an
incorrect 320x240 interpretation cannot skew frame boundaries.

The Spectrum mode rescales to 256x192 and chooses one legal bright/normal
paper+ink pair per 8x8 cell. It then adds the real 32/24-pixel Spectrum border,
producing packed RGB24 320x240 frames on stdout.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

SOURCE_W = 320
SOURCE_H = 200
SOURCE_FRAMES = 298
OUTPUT_W = 320
OUTPUT_H = 240
ACTIVE_W = 256
ACTIVE_H = 192
FPS = 25
DURATION = 164.52
OUTPUT_FRAMES = round(FPS * DURATION)

# Same deliberately softened Spectrum RGB palette used by the emulator capture.
SPECTRUM = np.array([
    [0, 0, 0], [32, 48, 192], [192, 64, 16], [192, 64, 192],
    [64, 176, 16], [80, 192, 176], [224, 192, 16], [192, 192, 192],
    [0, 0, 0], [48, 64, 255], [255, 64, 48], [255, 112, 240],
    [80, 224, 16], [80, 224, 255], [255, 232, 80], [255, 255, 255],
], dtype=np.int16)

# One shared BRIGHT bit per cell; paper and ink may each select colours 0..7.
PAIRS = np.array([
    (bright * 8 + paper, bright * 8 + ink)
    for bright in (0, 1)
    for paper in range(8)
    for ink in range(paper, 8)
], dtype=np.int16)


def read_frames(path: Path) -> np.ndarray:
    raw = path.read_bytes()
    expected = SOURCE_FRAMES * SOURCE_W * SOURCE_H * 3
    if len(raw) != expected:
        raise RuntimeError(
            f"source capture is {len(raw)} bytes, expected exactly {expected} "
            f"({SOURCE_FRAMES} x {SOURCE_W}x{SOURCE_H} RGB24)"
        )
    return np.frombuffer(raw, dtype=np.uint8).reshape(
        SOURCE_FRAMES, SOURCE_H, SOURCE_W, 3
    )


def spectrumise(source: np.ndarray) -> np.ndarray:
    resized = np.asarray(
        Image.fromarray(source, "RGB").resize((ACTIVE_W, ACTIVE_H), Image.Resampling.NEAREST),
        dtype=np.uint8,
    )
    cells = (
        resized.reshape(24, 8, 32, 8, 3)
        .transpose(0, 2, 1, 3, 4)
        .reshape(768, 64, 3)
        .astype(np.int16)
    )
    # 768 cells x 64 pixels x 16 Spectrum colours.
    delta = cells[:, :, None, :] - SPECTRUM[None, None, :, :]
    distance = np.sum(delta.astype(np.int32) ** 2, axis=3)
    first = PAIRS[:, 0]
    second = PAIRS[:, 1]
    costs = np.minimum(distance[:, :, first], distance[:, :, second]).sum(axis=1)
    best = np.argmin(costs, axis=1)
    a = first[best]
    b = second[best]
    rows = np.arange(768)[:, None]
    pixels = np.arange(64)[None, :]
    choose_b = distance[rows, pixels, b[:, None]] < distance[rows, pixels, a[:, None]]
    indices = np.where(choose_b, b[:, None], a[:, None])
    quantised = SPECTRUM[indices].astype(np.uint8)
    active = (
        quantised.reshape(24, 32, 8, 8, 3)
        .transpose(0, 2, 1, 3, 4)
        .reshape(ACTIVE_H, ACTIVE_W, 3)
    )
    output = np.zeros((OUTPUT_H, OUTPUT_W, 3), dtype=np.uint8)
    output[24:216, 32:288] = active
    return output


def source_with_border(source: np.ndarray) -> np.ndarray:
    # Correct 320x200 frame boundaries, with neutral letterboxing to 320x240.
    output = np.zeros((OUTPUT_H, OUTPUT_W, 3), dtype=np.uint8)
    output[20:220] = source
    return output


def make_contact_sheet(frames: dict[int, np.ndarray], slots: list[int], path: Path) -> None:
    sample_positions = np.linspace(0, len(slots) - 1, 12, dtype=np.int32)
    samples = [Image.fromarray(frames[slots[i]], "RGB") for i in sample_positions]
    sheet = Image.new("RGB", (OUTPUT_W * 4, OUTPUT_H * 3))
    for index, image in enumerate(samples):
        sheet.paste(image, ((index % 4) * OUTPUT_W, (index // 4) * OUTPUT_H))
    sheet.save(path, optimize=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("plan", type=Path)
    parser.add_argument("--mode", choices=("spectrum", "source"), default="spectrum")
    parser.add_argument("--contact-sheet", type=Path)
    args = parser.parse_args()

    source_frames = read_frames(args.source)
    plan = json.loads(args.plan.read_text())
    keep_slots = [int(value) for value in plan["keep_slots"]]
    if len(keep_slots) != 268 or keep_slots[0] != 1 or keep_slots[-1] != 298:
        raise RuntimeError("expected the verified 268-of-298 cost plan")
    if len(set(keep_slots)) != len(keep_slots):
        raise RuntimeError("duplicate retained slots")

    converted: dict[int, np.ndarray] = {}
    for count, slot in enumerate(keep_slots, 1):
        frame = source_frames[slot - 1]
        converted[slot] = spectrumise(frame) if args.mode == "spectrum" else source_with_border(frame)
        if count % 32 == 0 or count == len(keep_slots):
            print(f"converted {count}/{len(keep_slots)} retained samples", file=sys.stderr)

    if args.contact_sheet is not None:
        args.contact_sheet.parent.mkdir(parents=True, exist_ok=True)
        make_contact_sheet(converted, keep_slots, args.contact_sheet)

    retained = set(keep_slots)
    held_slot = 1
    output = sys.stdout.buffer
    for frame_number in range(OUTPUT_FRAMES):
        baseline_slot = min(SOURCE_FRAMES, (frame_number * SOURCE_FRAMES) // OUTPUT_FRAMES + 1)
        if baseline_slot in retained:
            held_slot = baseline_slot
        output.write(converted[held_slot].tobytes())

    print(
        f"rendered {OUTPUT_FRAMES} RGB frames at {FPS} fps = "
        f"{OUTPUT_FRAMES / FPS:.2f}s; {len(keep_slots)} retained presentations",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
