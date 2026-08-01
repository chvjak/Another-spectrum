#!/usr/bin/env python3
"""Compare captured SNA presentations with the exact original VM capture."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from build_original_visuals import (
    CAPTURE_RECORD_BYTES,
    FRAMES,
    SPECTRUM_PALETTE,
    load_capture,
    resize_indexes,
    spectrum_offset,
)


def colour_indexes(screen: bytes) -> np.ndarray:
    if len(screen) != 6912:
        raise RuntimeError(f"unexpected screen size: {len(screen)}")
    source = np.frombuffer(screen, dtype=np.uint8)
    output = np.empty((192, 256), dtype=np.uint8)
    for y in range(192):
        for byte_x in range(32):
            bits = int(source[spectrum_offset(y, byte_x)])
            attribute = int(source[6144 + (y >> 3) * 32 + byte_x])
            bright = (attribute >> 6) & 1
            ink = (attribute & 7) + bright * 8
            paper = ((attribute >> 3) & 7) + bright * 8
            for bit in range(8):
                output[y, byte_x * 8 + bit] = (
                    ink if bits & (0x80 >> bit) else paper
                )
    return output


def rgb(screen: bytes) -> np.ndarray:
    return SPECTRUM_PALETTE[colour_indexes(screen)].astype(np.uint8)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("indexed_capture", type=Path)
    parser.add_argument("screens", type=Path)
    parser.add_argument("--reference-screens", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    captured_paths = sorted(args.screens.glob("frame-*.scr"))
    reference_paths = sorted(args.reference_screens.glob("frame-*.scr"))
    if len(captured_paths) != FRAMES or len(reference_paths) != FRAMES:
        raise RuntimeError(
            f"expected {FRAMES} captured/reference screens, got "
            f"{len(captured_paths)}/{len(reference_paths)}"
        )
    visible_source, _, palettes = load_capture(args.indexed_capture)
    visible = resize_indexes(visible_source)

    rows: list[dict[str, float | int]] = []
    rendered: list[tuple[np.ndarray, np.ndarray, np.ndarray]] = []
    for index, (candidate_path, reference_path) in enumerate(
        zip(captured_paths, reference_paths)
    ):
        candidate = candidate_path.read_bytes()
        reference = reference_path.read_bytes()
        candidate_rgb = rgb(candidate).astype(np.int32)
        reference_rgb = rgb(reference).astype(np.int32)
        original_rgb = palettes[index][visible[index]]
        bitmap_mismatch = sum(a != b for a, b in zip(candidate[:6144], reference[:6144]))
        attribute_mismatch = sum(a != b for a, b in zip(candidate[6144:], reference[6144:]))
        rows.append(
            {
                "presentation": index + 1,
                "bitmap_mismatch_bytes": bitmap_mismatch,
                "attribute_mismatch_bytes": attribute_mismatch,
                "total_mismatch_bytes": bitmap_mismatch + attribute_mismatch,
                "candidate_original_rgb_mse": float(
                    np.mean((candidate_rgb - original_rgb) ** 2)
                ),
                "reference_original_rgb_mse": float(
                    np.mean((reference_rgb - original_rgb) ** 2)
                ),
            }
        )
        rendered.append(
            (
                candidate_rgb.astype(np.uint8),
                original_rgb.astype(np.uint8),
                reference_rgb.astype(np.uint8),
            )
        )

    candidate_mse = np.array(
        [row["candidate_original_rgb_mse"] for row in rows], dtype=float
    )
    reference_mse = np.array(
        [row["reference_original_rgb_mse"] for row in rows], dtype=float
    )
    mismatch = np.array([row["total_mismatch_bytes"] for row in rows], dtype=int)
    ranked = np.argsort(mismatch)[::-1]
    summary = {
        "passed": True,
        "presentations": FRAMES,
        "exact_reference_presentations": int(np.count_nonzero(mismatch == 0)),
        "average_reference_mismatch_bytes": float(np.mean(mismatch)),
        "worst_reference_mismatch_bytes": int(np.max(mismatch)),
        "candidate_original_rgb_mse": float(np.mean(candidate_mse)),
        "ideal_reference_original_rgb_mse": float(np.mean(reference_mse)),
        "excess_rgb_error_fraction": float(
            np.mean(candidate_mse) / np.mean(reference_mse) - 1
        ),
        "worst": [rows[int(index)] for index in ranked[:16]],
        "per_presentation": rows,
    }
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "original-reference-comparison.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )

    selected = sorted(
        set(
            [0, FRAMES - 1]
            + [round(index * (FRAMES - 1) / 11) for index in range(12)]
            + [int(index) for index in ranked[:8]]
        )
    )
    label_height = 20
    sheet = Image.new(
        "RGB", (256 * 3, (192 + label_height) * len(selected)), "black"
    )
    draw = ImageDraw.Draw(sheet)
    for row_index, presentation_index in enumerate(selected):
        top = row_index * (192 + label_height)
        candidate_rgb, original_rgb, reference_rgb = rendered[presentation_index]
        sheet.paste(Image.fromarray(candidate_rgb), (0, top + label_height))
        sheet.paste(Image.fromarray(original_rgb), (256, top + label_height))
        sheet.paste(Image.fromarray(reference_rgb), (512, top + label_height))
        draw.text((3, top + 3), f"P{presentation_index + 1} SNA", fill="white")
        draw.text((259, top + 3), "original VM", fill="white")
        draw.text((515, top + 3), "ideal Spectrum", fill="white")
    sheet.save(args.out / "original-reference-contact-sheet.png", optimize=True)
    print(json.dumps({key: value for key, value in summary.items() if key != "per_presentation"}, indent=2))


if __name__ == "__main__":
    main()
