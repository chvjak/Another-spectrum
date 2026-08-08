#!/usr/bin/env python3
"""Build Spectrum background and actor assets from the DOS shareware VM.

The generated contact sheets use the same 4/5 X and 24/25 Y transform as the
live Spectrum renderer.  Every 8x8 cell is reduced to a legal ULA PAPER/INK
pair; no unrestricted RGB preview is presented as Spectrum output.
"""
from __future__ import annotations

import argparse
import base64
import json
import math
import subprocess
import zlib
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
HERE = Path(__file__).resolve().parent
PIXELS = 320 * 200
INDEXED_RECORD_BYTES = PIXELS * 2 + 16 * 3
LESTER_ROOTS = (0x06A4, 0x0734, 0x07B8, 0x0854, 0x08F0, 0x0970, 0x09E8, 0x0A14)
BUDDY_ROOTS = (0x1D78, 0x1D9A, 0x1DBC, 0x1DDE, 0x1E00, 0x1E22, 0x1E44, 0x1E66)
SHIFT_PIXELS = (0, 2, 4, 6)

SPECTRUM_PALETTE = np.array(
    [
        (0, 0, 0),
        (32, 48, 192),
        (192, 64, 16),
        (192, 64, 192),
        (64, 176, 16),
        (80, 192, 176),
        (224, 192, 16),
        (192, 192, 192),
        (0, 0, 0),
        (48, 64, 255),
        (255, 64, 48),
        (255, 112, 240),
        (80, 224, 16),
        (80, 224, 255),
        (255, 232, 80),
        (255, 255, 255),
    ],
    dtype=np.int32,
)


@dataclass(frozen=True)
class Background:
    slug: str
    label: str
    source: Image.Image
    source_kind: str


def run(command: list[str], *, stdout: int | None = None) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        command,
        cwd=ROOT,
        check=True,
        stdout=stdout,
        stderr=subprocess.PIPE,
    )


def capture_sources(data_path: Path, engine_path: Path, build: Path) -> tuple[Path, Path, bytes]:
    gameplay = build / "source-gameplay"
    common = build / "source-common-shapes"
    run(
        [
            "node",
            str(HERE / "capture_gameplay.mjs"),
            str(data_path),
            str(engine_path),
            str(gameplay),
            "1800",
        ]
    )
    run(
        [
            "node",
            str(HERE / "enumerate_common_shapes.mjs"),
            str(data_path),
            str(engine_path),
            str(common),
        ]
    )
    intro = run(
        [
            "node",
            str(ROOT / "vm-port" / "capture_original_colour_preview.mjs"),
            str(data_path),
            str(engine_path),
            "--indexed",
        ],
        stdout=subprocess.PIPE,
    ).stdout
    expected = 298 * INDEXED_RECORD_BYTES
    if len(intro) != expected:
        raise RuntimeError(f"indexed intro capture is {len(intro)} bytes, expected {expected}")
    return gameplay, common, intro


def intro_page0_rgb(capture: bytes, frame: int) -> Image.Image:
    start = frame * INDEXED_RECORD_BYTES
    record = np.frombuffer(capture, dtype=np.uint8, count=INDEXED_RECORD_BYTES, offset=start)
    indexes = record[PIXELS : PIXELS * 2].reshape(200, 320)
    palette = record[-48:].reshape(16, 3)
    return Image.fromarray(palette[indexes].astype(np.uint8), "RGB")


def gameplay_frame(gameplay: Path, tick: int) -> Image.Image:
    metadata = json.loads((gameplay / "capture.json").read_text(encoding="utf-8"))
    matches = [item for item in metadata["screens"] if item["tick"] == tick]
    if not matches:
        raise RuntimeError(f"no gameplay capture at tick {tick}")
    return Image.open(gameplay / "screens" / matches[-1]["file"]).convert("RGB")


def transform_to_spectrum(source: Image.Image) -> np.ndarray:
    source = np.asarray(source.convert("RGB"), dtype=np.uint8)
    x_indexes = np.minimum(319, (np.arange(256) * 5) // 4)
    y_indexes = np.minimum(199, (np.arange(192) * 25) // 24)
    return source[y_indexes[:, None], x_indexes[None, :], :]


def bitmap_offset(y: int, byte_x: int) -> int:
    return ((y & 0xC0) << 5) | ((y & 7) << 8) | ((y & 0x38) << 2) | byte_x


def quantize_screen(source: Image.Image) -> tuple[bytes, Image.Image, dict[str, float]]:
    rgb = transform_to_spectrum(source).astype(np.int32)
    bitmap = bytearray(6144)
    attributes = bytearray(768)
    preview = np.zeros((192, 256, 3), dtype=np.uint8)
    weights = np.array((30, 59, 11), dtype=np.int64)
    total_error = 0

    for cell_y in range(24):
        for cell_x in range(32):
            cell = rgb[cell_y * 8 : cell_y * 8 + 8, cell_x * 8 : cell_x * 8 + 8]
            flat = cell.reshape(64, 3).astype(np.int64)
            best: tuple[int, int, int, np.ndarray] | None = None
            for bright in (0, 1):
                colors = SPECTRUM_PALETTE[bright * 8 : bright * 8 + 8].astype(np.int64)
                errors = ((flat[:, None, :] - colors[None, :, :]) ** 2 * weights).sum(axis=2)
                for paper in range(8):
                    for ink in range(paper + 1, 8):
                        use_ink = errors[:, ink] < errors[:, paper]
                        cost = int(np.where(use_ink, errors[:, ink], errors[:, paper]).sum())
                        candidate = (cost, bright * 8 + paper, bright * 8 + ink, use_ink)
                        if best is None or cost < best[0]:
                            best = candidate
            assert best is not None
            cost, paper, ink, use_ink = best
            # Prefer a sparse bitmap: swapping PAPER and INK is visually exact.
            if int(use_ink.sum()) > 32:
                paper, ink = ink, paper
                use_ink = ~use_ink
            bright = paper >> 3
            paper_base = paper & 7
            ink_base = ink & 7
            attributes[cell_y * 32 + cell_x] = (bright << 6) | (paper_base << 3) | ink_base
            mask = use_ink.reshape(8, 8)
            for row in range(8):
                value = 0
                for bit in range(8):
                    if mask[row, bit]:
                        value |= 0x80 >> bit
                bitmap[bitmap_offset(cell_y * 8 + row, cell_x)] = value
            rendered = np.where(mask[:, :, None], SPECTRUM_PALETTE[ink], SPECTRUM_PALETTE[paper])
            preview[cell_y * 8 : cell_y * 8 + 8, cell_x * 8 : cell_x * 8 + 8] = rendered
            total_error += cost

    mse = float(((rgb.astype(np.float64) - preview.astype(np.float64)) ** 2).mean())
    return bytes(bitmap + attributes), Image.fromarray(preview, "RGB"), {
        "weighted_error": float(total_error),
        "rgb_mse": mse,
    }


def load_rgba(root: Path, record: dict[str, object]) -> Image.Image:
    stem = str(record["stem"])
    rgb = Image.open(root / f"{stem}.ppm").convert("RGB")
    alpha = Image.open(root / f"{stem}.pgm").convert("L")
    rgb.putalpha(alpha)
    return rgb


def select_records(metadata: dict[str, object], roots: tuple[int, ...], key: str) -> list[dict[str, object]]:
    records: list[dict[str, object]] = metadata["shapes"]  # type: ignore[assignment]
    selected = []
    for root in roots:
        matches = [record for record in records if int(record[key]) == root]
        if not matches:
            raise RuntimeError(f"missing sprite root {root:#x}")
        selected.append(max(matches, key=lambda record: int(record["width"]) * int(record["height"])))
    return selected


def actor_masks(
    root: Path,
    records: list[dict[str, object]],
    *,
    anchor_x_key: str,
    anchor_y_key: str,
) -> tuple[list[Image.Image], list[np.ndarray], dict[str, int]]:
    rgba_frames = [load_rgba(root, record) for record in records]
    relative = []
    for record in records:
        left = int(record["minX"]) - int(record[anchor_x_key])
        top = int(record["minY"]) - int(record[anchor_y_key])
        relative.append((left, top, left + int(record["width"]), top + int(record["height"])))
    min_left = min(item[0] for item in relative)
    min_top = min(item[1] for item in relative)
    max_right = max(item[2] for item in relative)
    max_bottom = max(item[3] for item in relative)
    source_width = max_right - min_left
    source_height = max_bottom - min_top
    width = math.ceil(source_width * 4 / 5)
    height = math.ceil(source_height * 24 / 25)
    masks: list[np.ndarray] = []
    for frame, bounds in zip(rgba_frames, relative):
        canvas = Image.new("L", (source_width, source_height), 0)
        canvas.paste(frame.getchannel("A"), (bounds[0] - min_left, bounds[1] - min_top))
        scaled = canvas.resize((width, height), Image.Resampling.NEAREST)
        masks.append(np.asarray(scaled, dtype=np.uint8) >= 128)
    layout = {
        "source_width": source_width,
        "source_height": source_height,
        "width": width,
        "height": height,
        "anchor_x": round(-min_left * 4 / 5),
        "anchor_y": round(-min_top * 24 / 25),
        "bytes_per_row": math.ceil((width + max(SHIFT_PIXELS)) / 8),
    }
    return rgba_frames, masks, layout


def shifted_bank(masks: list[np.ndarray], layout: dict[str, int]) -> bytes:
    height = layout["height"]
    stride = layout["bytes_per_row"]
    payload = bytearray()
    for mask in masks:
        if mask.shape != (height, layout["width"]):
            raise AssertionError(mask.shape)
        for shift in SHIFT_PIXELS:
            frame = bytearray(height * stride)
            ys, xs = np.nonzero(mask)
            for y, x in zip(ys.tolist(), xs.tolist()):
                target = x + shift
                frame[y * stride + target // 8] |= 0x80 >> (target & 7)
            payload += frame
    return bytes(payload)


def checker(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], size: int = 8) -> None:
    left, top, right, bottom = box
    for y in range(top, bottom, size):
        for x in range(left, right, size):
            color = (47, 51, 57) if ((x // size + y // size) & 1) else (29, 32, 36)
            draw.rectangle((x, y, min(right - 1, x + size - 1), min(bottom - 1, y + size - 1)), fill=color)


def sprite_sheet(
    path: Path,
    title: str,
    roots: tuple[int, ...],
    rgba_frames: list[Image.Image],
    masks: list[np.ndarray],
) -> None:
    font = ImageFont.load_default()
    cell_width = 150
    sheet = Image.new("RGB", (cell_width * 8, 340), (17, 19, 22))
    draw = ImageDraw.Draw(sheet)
    draw.text((12, 10), title, fill=(241, 243, 232), font=font)
    draw.text((12, 174), "ZX XOR mask · 4/5 × 24/25 transform", fill=(137, 230, 244), font=font)
    for index, (root, frame, mask) in enumerate(zip(roots, rgba_frames, masks)):
        x0 = index * cell_width
        draw.text((x0 + 6, 31), f"{index + 1} · {root:04X}", fill=(220, 224, 211), font=font)
        checker(draw, (x0, 48, x0 + cell_width, 166))
        scale = min(4, 108 / frame.height, 132 / frame.width)
        size = (max(1, round(frame.width * scale)), max(1, round(frame.height * scale)))
        enlarged = frame.resize(size, Image.Resampling.NEAREST)
        sheet.paste(enlarged, (x0 + (cell_width - size[0]) // 2, 52 + (108 - size[1]) // 2), enlarged)

        mask_image = Image.fromarray(np.where(mask, 255, 0).astype(np.uint8), "L")
        color = Image.new("RGB", mask_image.size, (93, 232, 255))
        color.putalpha(mask_image)
        scale = min(4, 110 / color.height, 132 / color.width)
        size = (max(1, round(color.width * scale)), max(1, round(color.height * scale)))
        enlarged = color.resize(size, Image.Resampling.NEAREST)
        checker(draw, (x0, 195, x0 + cell_width, 330))
        sheet.paste(enlarged, (x0 + (cell_width - size[0]) // 2, 207 + (110 - size[1]) // 2), enlarged)
    sheet.save(path, optimize=True)


def background_sheet(path: Path, backgrounds: list[Background], previews: list[Image.Image]) -> None:
    font = ImageFont.load_default()
    cell_width = 256
    cell_height = 224
    sheet = Image.new("RGB", (cell_width * 5, cell_height * 2), (12, 14, 16))
    draw = ImageDraw.Draw(sheet)
    for index, (background, preview) in enumerate(zip(backgrounds, previews)):
        x = (index % 5) * cell_width
        y = (index // 5) * cell_height
        sheet.paste(preview, (x, y + 24))
        draw.text((x + 5, y + 6), f"{index + 1:02d}  {background.label}", fill=(235, 239, 222), font=font)
    sheet.save(path, optimize=True)


def encoded(payload: bytes) -> str:
    return base64.b85encode(zlib.compress(payload, 9)).decode("ascii")


def write_generated_assets(
    path: Path,
    backgrounds: list[Background],
    screens: list[bytes],
    lester_bank: bytes,
    buddy_bank: bytes,
    lester_layout: dict[str, int],
    buddy_layout: dict[str, int],
) -> None:
    names = [item.slug for item in backgrounds]
    runtime = [names.index("lab-entrance"), names.index("flooded-cavern"), names.index("alien-surface")]
    screen_strings = ",\n".join(f'    _decode("{encoded(screen)}")' for screen in screens)
    source = f'''# Generated by build_assets.py; do not hand-edit.
import base64
import zlib


def _decode(value: str) -> bytes:
    return zlib.decompress(base64.b85decode(value.encode("ascii")))


BACKGROUND_NAMES = {names!r}
BACKGROUND_SCREENS = [
{screen_strings}
]
RUNTIME_BACKGROUND_INDICES = {runtime!r}
SHIFT_PIXELS = {SHIFT_PIXELS!r}
LESTER_LAYOUT = {lester_layout!r}
BUDDY_LAYOUT = {buddy_layout!r}
LESTER_BANK = _decode("{encoded(lester_bank)}")
BUDDY_BANK = _decode("{encoded(buddy_bank)}")
'''
    path.write_text(source, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, default=ROOT / "vendor" / "another-js" / "ootwdemo.js")
    parser.add_argument("--engine", type=Path, default=ROOT / "vendor" / "another-js" / "another.min.js")
    parser.add_argument("--build", type=Path, default=ROOT / "build" / "sprite-eval")
    args = parser.parse_args()
    if not args.data.is_file() or not args.engine.is_file():
        raise RuntimeError(
            "another_js shareware files are missing; clone its gh-pages branch into vendor/another-js"
        )
    args.build.mkdir(parents=True, exist_ok=True)
    artifacts = HERE / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)

    gameplay, common, intro = capture_sources(args.data.resolve(), args.engine.resolve(), args.build)
    backgrounds = [
        Background("lab-entrance", "Lab entrance", intro_page0_rgb(intro, 20), "intro page 0 · frame 20"),
        Background("access-corridor", "Access corridor", intro_page0_rgb(intro, 40), "intro page 0 · frame 40"),
        Background("empty-chamber", "Empty chamber", intro_page0_rgb(intro, 100), "intro page 0 · frame 100"),
        Background("keypad-wall", "Keypad wall", intro_page0_rgb(intro, 120), "intro page 0 · frame 120"),
        Background("identification", "Identification", intro_page0_rgb(intro, 140), "intro page 0 · frame 140"),
        Background("diagnostics", "Diagnostics", intro_page0_rgb(intro, 180), "intro page 0 · frame 180"),
        Background("countdown", "Experiment countdown", intro_page0_rgb(intro, 200), "intro page 0 · frame 200"),
        Background("accelerator-ring", "Accelerator ring", intro_page0_rgb(intro, 260), "intro page 0 · frame 260"),
        Background("flooded-cavern", "Flooded cavern", gameplay_frame(gameplay, 4), "shareware gameplay · tick 4"),
        Background("alien-surface", "Alien surface", gameplay_frame(gameplay, 69), "shareware gameplay · tick 69"),
    ]

    screens = []
    previews = []
    metrics = []
    for background in backgrounds:
        screen, preview, result = quantize_screen(background.source)
        screens.append(screen)
        previews.append(preview)
        result.update(slug=background.slug, label=background.label, source=background.source_kind)
        metrics.append(result)
        (args.build / f"background-{background.slug}.scr").write_bytes(screen)
        preview.save(args.build / f"background-{background.slug}.png", optimize=True)

    gameplay_meta = json.loads((gameplay / "capture.json").read_text(encoding="utf-8"))
    common_meta = json.loads((common / "common-shapes.json").read_text(encoding="utf-8"))
    lester_records = select_records(gameplay_meta, LESTER_ROOTS, "root")
    buddy_records = select_records(common_meta, BUDDY_ROOTS, "offset")
    lester_rgba, lester_masks, lester_layout = actor_masks(
        gameplay / "shapes", lester_records, anchor_x_key="x", anchor_y_key="y"
    )
    buddy_rgba, buddy_masks, buddy_layout = actor_masks(
        common, buddy_records, anchor_x_key="anchorX", anchor_y_key="anchorY"
    )
    lester_bank = shifted_bank(lester_masks, lester_layout)
    buddy_bank = shifted_bank(buddy_masks, buddy_layout)
    if len(lester_bank) > 0x4000 or len(buddy_bank) > 0x4000:
        raise RuntimeError("pre-shifted actor bank exceeds a 16K Spectrum page")

    background_sheet(
        artifacts / "another-world-speccy-backgrounds-contact-sheet.png", backgrounds, previews
    )
    sprite_sheet(
        artifacts / "lester-sprite-contact-sheet.png",
        "Lester · original vector frames / Spectrum XOR masks",
        LESTER_ROOTS,
        lester_rgba,
        lester_masks,
    )
    sprite_sheet(
        artifacts / "buddy-sprite-contact-sheet.png",
        "Buddy · shared-vector animation / Spectrum XOR masks",
        BUDDY_ROOTS,
        buddy_rgba,
        buddy_masks,
    )
    write_generated_assets(
        HERE / "generated_assets.py",
        backgrounds,
        screens,
        lester_bank,
        buddy_bank,
        lester_layout,
        buddy_layout,
    )
    manifest = {
        "backgrounds": metrics,
        "runtime_backgrounds": ["lab-entrance", "flooded-cavern", "alien-surface"],
        "lester": {"roots": list(LESTER_ROOTS), "layout": lester_layout, "bank_bytes": len(lester_bank)},
        "buddy": {"roots": list(BUDDY_ROOTS), "layout": buddy_layout, "bank_bytes": len(buddy_bank)},
        "sprite_shifts": list(SHIFT_PIXELS),
    }
    (artifacts / "asset-manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "backgrounds": len(backgrounds),
                "lester_bank": len(lester_bank),
                "buddy_bank": len(buddy_bank),
                "artifacts": str(artifacts),
            }
        )
    )


if __name__ == "__main__":
    main()
