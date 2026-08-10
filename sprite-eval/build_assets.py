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
LESTER_RUN_RIGHT = (
    0x06A4,
    0x0734,
    0x07B8,
    0x0854,
    0x08F0,
    0x0970,
    0x0998,
    0x09C0,
    0x09E8,
    0x0A14,
)
LESTER_RUN_LEFT = (
    0x1884,
    0x1928,
    0x19D4,
    0x1A84,
    0x1B48,
    0x1BDC,
    0x1C04,
    0x1C2C,
    0x1C54,
    0x1C80,
)
LESTER_STOP_RIGHT = (0x16D0, 0x1668)
LESTER_TURN_LEFT = (0x0CA0, 0x0640, 0x061C)
LESTER_STOP_LEFT = (0x0640, 0x061C)
LESTER_TURN_RIGHT = (0x0E78, 0x1668)
LESTER_POSE_ROOTS = tuple(
    dict.fromkeys(
        LESTER_RUN_RIGHT
        + LESTER_STOP_RIGHT
        + LESTER_TURN_LEFT
        + LESTER_RUN_LEFT
        + LESTER_STOP_LEFT
        + LESTER_TURN_RIGHT
    )
)

BUDDY_RUN_RIGHT_TICKS = tuple(range(429, 439))
BUDDY_RUN_LEFT_TICKS = tuple(range(515, 525))
BUDDY_STATE_TICKS = (425, 424, 428)
BUDDY_POSE_TICKS = BUDDY_RUN_RIGHT_TICKS + BUDDY_RUN_LEFT_TICKS + BUDDY_STATE_TICKS

BACKGROUND_SPECS = (
    ("flooded-ascent", "Flooded ascent", 45),
    ("alien-basin", "Alien basin", 69),
    ("stone-colonnade", "Stone colonnade", 201),
    ("root-overhang", "Root overhang", 369),
    ("giant-trunk", "Giant trunk", 717),
    ("predator-cave", "Predator cave", 729),
    ("basin-chase", "Basin chase", 825),
    ("dark-ravine", "Dark ravine", 921),
    ("spike-pit", "Spike pit", 1005),
    ("capture-clearing", "Capture clearing", 1233),
)
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


def capture_sources(
    data_path: Path,
    engine_path: Path,
    demo_joy_path: Path,
    jail_data_path: Path,
    build: Path,
) -> tuple[Path, Path]:
    gameplay = build / "source-water-gameplay"
    jail = build / "source-jail-gameplay"
    run(
        [
            "node",
            str(HERE / "capture_gameplay.mjs"),
            str(data_path),
            str(engine_path),
            str(gameplay),
            "1400",
            str(demo_joy_path),
            "16002",
        ]
    )
    run(
        [
            "node",
            str(HERE / "capture_gameplay.mjs"),
            str(jail_data_path),
            str(engine_path),
            str(jail),
            "650",
            "-",
            "16003",
        ]
    )
    return gameplay, jail


def gameplay_frame(gameplay: Path, tick: int, *, prefer_pre_actor: bool = False) -> tuple[Image.Image, str]:
    metadata = json.loads((gameplay / "capture.json").read_text(encoding="utf-8"))
    if prefer_pre_actor:
        matches = [item for item in metadata.get("preActorScreens", []) if item["tick"] == tick]
        if matches:
            return (
                Image.open(gameplay / "pre-actor-screens" / matches[-1]["file"]).convert("RGB"),
                f"DOS DEMO3.JOY gameplay · tick {tick} · before actor draw",
            )
    matches = [item for item in metadata["screens"] if item["tick"] == tick]
    if not matches:
        raise RuntimeError(f"no gameplay capture at tick {tick}")
    return (
        Image.open(gameplay / "screens" / matches[-1]["file"]).convert("RGB"),
        f"DOS DEMO3.JOY gameplay · tick {tick}",
    )


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


def frame_masks(
    rgba_frames: list[Image.Image],
    relative: list[tuple[int, int, int, int]],
) -> tuple[list[np.ndarray], dict[str, int], list[int]]:
    min_top = min(item[1] for item in relative)
    max_bottom = max(item[3] for item in relative)
    source_width = max(item[2] - item[0] for item in relative)
    source_height = max_bottom - min_top
    width = math.ceil(source_width * 4 / 5)
    height = math.ceil(source_height * 24 / 25)
    masks: list[np.ndarray] = []
    x_offsets = []
    for frame, bounds in zip(rgba_frames, relative):
        frame_source_width = bounds[2] - bounds[0]
        canvas = Image.new("L", (frame_source_width, source_height), 0)
        canvas.paste(frame.getchannel("A"), (0, bounds[1] - min_top))
        frame_width = math.ceil(frame_source_width * 4 / 5)
        scaled = canvas.resize((frame_width, height), Image.Resampling.NEAREST)
        normalized = Image.new("L", (width, height), 0)
        normalized.paste(scaled, (0, 0))
        masks.append(np.asarray(normalized, dtype=np.uint8) >= 128)
        x_offsets.append(math.floor(bounds[0] * 4 / 5))
    layout = {
        "source_width": source_width,
        "source_height": source_height,
        "width": width,
        "height": height,
        "anchor_x": 0,
        "anchor_y": round(-min_top * 24 / 25),
        "bytes_per_row": max(5, math.ceil((width + max(SHIFT_PIXELS)) / 8)),
    }
    return masks, layout, x_offsets


def actor_masks(
    root: Path,
    records: list[dict[str, object]],
    *,
    anchor_x_key: str,
    anchor_y_key: str,
) -> tuple[list[Image.Image], list[np.ndarray], dict[str, int], list[int]]:
    rgba_frames = [load_rgba(root, record) for record in records]
    relative = []
    for record in records:
        left = int(record["minX"]) - int(record[anchor_x_key])
        top = int(record["minY"]) - int(record[anchor_y_key])
        relative.append((left, top, left + int(record["width"]), top + int(record["height"])))
    masks, layout, x_offsets = frame_masks(rgba_frames, relative)
    return rgba_frames, masks, layout, x_offsets


def composite_actor_frames(
    root: Path,
    metadata: dict[str, object],
    specs: list[tuple[int, str, int]],
) -> tuple[list[Image.Image], list[tuple[int, int, int, int]], list[list[dict[str, object]]]]:
    unique_shapes: list[dict[str, object]] = metadata["shapes"]  # type: ignore[assignment]
    occurrences: list[dict[str, object]] = metadata["shapeOccurrences"]  # type: ignore[assignment]
    by_hash = {str(item["hash"]): item for item in unique_shapes}
    frames: list[Image.Image] = []
    relative: list[tuple[int, int, int, int]] = []
    selected_components: list[list[dict[str, object]]] = []

    for tick, anchor_resource, anchor_root in specs:
        tick_items = [item for item in occurrences if int(item["tick"]) == tick]
        anchors = [
            item
            for item in tick_items
            if str(item["resource"]) == anchor_resource and int(item["root"]) == anchor_root
        ]
        if len(anchors) != 1:
            raise RuntimeError(
                f"expected one {anchor_resource}:{anchor_root:#x} anchor at tick {tick}, got {len(anchors)}"
            )
        anchor_x = int(anchors[0]["x"])
        anchor_y = int(anchors[0]["y"])
        components = [
            item
            for item in tick_items
            if abs(int(item["x"]) - anchor_x) <= 1
            and abs(int(item["y"]) - anchor_y) <= 1
            and 5 <= int(item["width"]) <= 80
            and 10 <= int(item["height"]) <= 100
            and int(item["minY"]) - int(item["y"]) <= -50
            and str(item["resource"]) in {"p1", "p2"}
        ]
        if len(components) < 2:
            raise RuntimeError(f"incomplete composite at tick {tick}: {len(components)} component(s)")
        left = min(int(item["minX"]) - int(item["x"]) for item in components)
        top = min(int(item["minY"]) - int(item["y"]) for item in components)
        right = max(
            int(item["minX"]) - int(item["x"]) + int(item["width"]) for item in components
        )
        bottom = max(
            int(item["minY"]) - int(item["y"]) + int(item["height"]) for item in components
        )
        canvas = Image.new("RGBA", (right - left, bottom - top), (0, 0, 0, 0))
        for item in components:
            record = by_hash.get(str(item["hash"]))
            if record is None:
                raise RuntimeError(f"missing unique shape for hash {item['hash']}")
            rgba = load_rgba(root / "shapes", record)
            x = int(item["minX"]) - int(item["x"]) - left
            y = int(item["minY"]) - int(item["y"]) - top
            canvas.alpha_composite(rgba, (x, y))
        frames.append(canvas)
        relative.append((left, top, right, bottom))
        selected_components.append(components)
    return frames, relative, selected_components


def shifted_frames(masks: list[np.ndarray], layout: dict[str, int]) -> list[bytes]:
    height = layout["height"]
    stride = layout["bytes_per_row"]
    payloads = []
    for mask in masks:
        if mask.shape != (height, layout["width"]):
            raise AssertionError(mask.shape)
        payload = bytearray()
        for shift in SHIFT_PIXELS:
            frame = bytearray(height * stride)
            ys, xs = np.nonzero(mask)
            for y, x in zip(ys.tolist(), xs.tolist()):
                target = x + shift
                frame[y * stride + target // 8] |= 0x80 >> (target & 7)
            payload += frame
        payloads.append(bytes(payload))
    return payloads


def checker(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], size: int = 8) -> None:
    left, top, right, bottom = box
    for y in range(top, bottom, size):
        for x in range(left, right, size):
            color = (47, 51, 57) if ((x // size + y // size) & 1) else (29, 32, 36)
            draw.rectangle((x, y, min(right - 1, x + size - 1), min(bottom - 1, y + size - 1)), fill=color)


def sequence_sprite_sheet(
    path: Path,
    title: str,
    rgba_frames: list[Image.Image],
    masks: list[np.ndarray],
    frame_labels: list[str],
    groups: list[tuple[str, list[int]]],
) -> None:
    font = ImageFont.load_default()
    columns = max(len(indexes) for _, indexes in groups)
    cell_width = 120
    row_height = 252
    sheet = Image.new("RGB", (cell_width * columns, 34 + row_height * len(groups)), (17, 19, 22))
    draw = ImageDraw.Draw(sheet)
    draw.text((12, 10), title, fill=(241, 243, 232), font=font)
    for row, (group_label, indexes) in enumerate(groups):
        y0 = 34 + row * row_height
        draw.text((6, y0 + 5), group_label, fill=(246, 196, 83), font=font)
        for column, index in enumerate(indexes):
            frame = rgba_frames[index]
            mask = masks[index]
            x0 = column * cell_width
            draw.text((x0 + 6, y0 + 20), frame_labels[index], fill=(220, 224, 211), font=font)
            checker(draw, (x0, y0 + 35, x0 + cell_width, y0 + 132))
            scale = min(4, 89 / frame.height, 108 / frame.width)
            size = (max(1, round(frame.width * scale)), max(1, round(frame.height * scale)))
            enlarged = frame.resize(size, Image.Resampling.NEAREST)
            sheet.paste(
                enlarged,
                (x0 + (cell_width - size[0]) // 2, y0 + 39 + (89 - size[1]) // 2),
                enlarged,
            )

            mask_image = Image.fromarray(np.where(mask, 255, 0).astype(np.uint8), "L")
            color = Image.new("RGB", mask_image.size, (93, 232, 255))
            color.putalpha(mask_image)
            scale = min(4, 89 / color.height, 108 / color.width)
            size = (max(1, round(color.width * scale)), max(1, round(color.height * scale)))
            enlarged = color.resize(size, Image.Resampling.NEAREST)
            checker(draw, (x0, y0 + 147, x0 + cell_width, y0 + 244))
            sheet.paste(
                enlarged,
                (x0 + (cell_width - size[0]) // 2, y0 + 151 + (89 - size[1]) // 2),
                enlarged,
            )
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
    runtime_backgrounds: list[str],
    lester_frames: list[bytes],
    buddy_frames: list[bytes],
    lester_layout: dict[str, int],
    buddy_layout: dict[str, int],
    lester_sequences: dict[str, tuple[int, ...]],
    buddy_sequences: dict[str, tuple[int, ...]],
    lester_labels: list[str],
    buddy_labels: list[str],
    lester_x_offsets: list[int],
    buddy_x_offsets: list[int],
) -> None:
    names = [item.slug for item in backgrounds]
    runtime = [names.index(name) for name in runtime_backgrounds]
    screen_strings = ",\n".join(f'    _decode("{encoded(screen)}")' for screen in screens)
    lester_strings = ",\n".join(f'    _decode("{encoded(frame)}")' for frame in lester_frames)
    buddy_strings = ",\n".join(f'    _decode("{encoded(frame)}")' for frame in buddy_frames)
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
LESTER_FRAME_LABELS = {lester_labels!r}
BUDDY_FRAME_LABELS = {buddy_labels!r}
LESTER_X_OFFSETS = {lester_x_offsets!r}
BUDDY_X_OFFSETS = {buddy_x_offsets!r}
LESTER_SEQUENCES = {lester_sequences!r}
BUDDY_SEQUENCES = {buddy_sequences!r}
LESTER_FRAME_BLOBS = [
{lester_strings}
]
BUDDY_FRAME_BLOBS = [
{buddy_strings}
]
'''
    path.write_text(source, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, default=ROOT / "vendor" / "another-js" / "ootwdemo.js")
    parser.add_argument("--engine", type=Path, default=ROOT / "vendor" / "another-js" / "another.min.js")
    parser.add_argument("--demo-joy", type=Path, default=ROOT / "vendor" / "ootwdemo" / "DEMO3.JOY")
    parser.add_argument(
        "--jail-data",
        type=Path,
        default=ROOT / "build" / "anniversary-demo-jail.js",
        help="raw Jail resource JS made by extract_anniversary_jail.py",
    )
    parser.add_argument("--build", type=Path, default=ROOT / "build" / "sprite-eval")
    args = parser.parse_args()
    if not args.data.is_file() or not args.engine.is_file() or not args.demo_joy.is_file():
        raise RuntimeError(
            "DOS shareware data, engine, or DEMO3.JOY is missing; see sprite-eval/README.md"
        )
    if not args.jail_data.is_file():
        raise RuntimeError(
            "Anniversary-demo Jail data is missing; run extract_anniversary_jail.py on Pak01.pak"
        )
    args.build.mkdir(parents=True, exist_ok=True)
    artifacts = HERE / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)

    gameplay, jail = capture_sources(
        args.data.resolve(),
        args.engine.resolve(),
        args.demo_joy.resolve(),
        args.jail_data.resolve(),
        args.build,
    )
    backgrounds = []
    for slug, label, tick in BACKGROUND_SPECS:
        source, source_kind = gameplay_frame(gameplay, tick, prefer_pre_actor=True)
        backgrounds.append(Background(slug, label, source, source_kind))
    runtime_backgrounds = ["alien-basin", "root-overhang", "predator-cave"]

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
    jail_meta = json.loads((jail / "capture.json").read_text(encoding="utf-8"))
    lester_records = select_records(gameplay_meta, LESTER_POSE_ROOTS, "root")
    lester_rgba, lester_masks, lester_layout, lester_x_offsets = actor_masks(
        gameplay / "shapes", lester_records, anchor_x_key="x", anchor_y_key="y"
    )
    buddy_specs = (
        [(tick, "p1", 0x1604) for tick in BUDDY_RUN_RIGHT_TICKS]
        + [(tick, "p1", 0x2A78) for tick in BUDDY_RUN_LEFT_TICKS]
        + [(425, "p1", 0x3E7E), (424, "p1", 0x3E7E), (428, "p1", 0x1604)]
    )
    buddy_rgba, buddy_relative, buddy_components = composite_actor_frames(
        jail, jail_meta, buddy_specs
    )
    buddy_masks, buddy_layout, buddy_x_offsets = frame_masks(buddy_rgba, buddy_relative)
    if lester_layout["bytes_per_row"] != 5 or buddy_layout["bytes_per_row"] != 5:
        raise RuntimeError(
            f"runtime compositor expects five-byte rows, got {lester_layout['bytes_per_row']} and "
            f"{buddy_layout['bytes_per_row']}"
        )
    lester_frames = shifted_frames(lester_masks, lester_layout)
    buddy_frames = shifted_frames(buddy_masks, buddy_layout)

    lester_pose_index = {root: index for index, root in enumerate(LESTER_POSE_ROOTS)}
    lester_sequences = {
        "run_right": tuple(lester_pose_index[root] for root in LESTER_RUN_RIGHT),
        "stop_right": tuple(lester_pose_index[root] for root in LESTER_STOP_RIGHT),
        "turn_left": tuple(lester_pose_index[root] for root in LESTER_TURN_LEFT),
        "run_left": tuple(lester_pose_index[root] for root in LESTER_RUN_LEFT),
        "stop_left": tuple(lester_pose_index[root] for root in LESTER_STOP_LEFT),
        "turn_right": tuple(lester_pose_index[root] for root in LESTER_TURN_RIGHT),
    }
    buddy_sequences = {
        "run_right": tuple(range(0, 10)),
        "run_left": tuple(range(10, 20)),
        "idle_left": (20,),
        "turn": (21,),
        "idle_right": (22,),
    }
    lester_labels = [f"{root:04X}" for root in LESTER_POSE_ROOTS]
    buddy_labels = [f"tick {tick}" for tick in BUDDY_POSE_TICKS]

    background_sheet(
        artifacts / "another-world-speccy-backgrounds-contact-sheet.png", backgrounds, previews
    )
    sequence_sprite_sheet(
        artifacts / "lester-sprite-contact-sheet.png",
        "Lester · recorded Water gameplay gait / Spectrum XOR masks",
        lester_rgba,
        lester_masks,
        lester_labels,
        [
            ("Run right · 10 frames", list(lester_sequences["run_right"])),
            (
                "Stop right · turn left",
                list(lester_sequences["stop_right"] + lester_sequences["turn_left"]),
            ),
            ("Run left · 10 frames", list(lester_sequences["run_left"])),
            (
                "Stop left · turn right",
                list(lester_sequences["stop_left"] + lester_sequences["turn_right"]),
            ),
        ],
    )
    sequence_sprite_sheet(
        artifacts / "buddy-sprite-contact-sheet.png",
        "Buddy · actual Jail composites (head + body + arms) / Spectrum XOR masks",
        buddy_rgba,
        buddy_masks,
        buddy_labels,
        [
            ("Run right · 10 composite frames", list(buddy_sequences["run_right"])),
            ("Run left · 10 composite frames", list(buddy_sequences["run_left"])),
            ("Idle · gesture · launch", [20, 21, 22]),
        ],
    )
    write_generated_assets(
        HERE / "generated_assets.py",
        backgrounds,
        screens,
        runtime_backgrounds,
        lester_frames,
        buddy_frames,
        lester_layout,
        buddy_layout,
        lester_sequences,
        buddy_sequences,
        lester_labels,
        buddy_labels,
        lester_x_offsets,
        buddy_x_offsets,
    )
    manifest = {
        "backgrounds": metrics,
        "runtime_backgrounds": runtime_backgrounds,
        "lester": {
            "pose_roots": list(LESTER_POSE_ROOTS),
            "sequences": lester_sequences,
            "layout": lester_layout,
            "x_offsets": lester_x_offsets,
            "pre_shifted_bytes": sum(len(frame) for frame in lester_frames),
        },
        "buddy": {
            "pose_ticks": list(BUDDY_POSE_TICKS),
            "sequences": buddy_sequences,
            "layout": buddy_layout,
            "x_offsets": buddy_x_offsets,
            "pre_shifted_bytes": sum(len(frame) for frame in buddy_frames),
            "components": [
                [
                    {"resource": str(item["resource"]), "root": int(item["root"])}
                    for item in frame
                ]
                for frame in buddy_components
            ],
        },
        "sprite_shifts": list(SHIFT_PIXELS),
        "provenance": {
            "water": "DOS shareware DEMO3.JOY exact input playback · part 16002",
            "buddy": "official Anniversary demo Jail gameplay · part 16003",
        },
    }
    (artifacts / "asset-manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "backgrounds": len(backgrounds),
                "lester_frames": len(lester_frames),
                "lester_bytes": sum(len(frame) for frame in lester_frames),
                "buddy_frames": len(buddy_frames),
                "buddy_bytes": sum(len(frame) for frame in buddy_frames),
                "artifacts": str(artifacts),
            }
        )
    )


if __name__ == "__main__":
    main()
