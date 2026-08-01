#!/usr/bin/env python3
"""Rebuild an AWD2 stream with RawGL text converted to native 6x6 glyphs.

The picture remains the original alternating-bank 25 fps diff stream.  Only
known text masks are changed: the captured 8x8 RawGL glyph pixels are cleared,
then area-resized 6x6 glyphs are written into the affected Spectrum cells.

Another World assets are deliberately not stored in this repository.  Supply a
local AWD2 stream and RawGL's ``staticres.cpp`` when running the builder.
"""

from __future__ import annotations

import argparse
import ast
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import struct
from typing import Iterable

try:
    from PIL import Image
except ImportError as exc:  # pragma: no cover - command-line dependency guard
    raise SystemExit("Pillow is required: python3 -m pip install Pillow") from exc


MAGIC = b"AWD2"
SCREEN_WIDTH = 256
SCREEN_HEIGHT = 192
SCREEN_SIZE = 6912
RAWGL_WIDTH = 320
RAWGL_HEIGHT = 200
GLYPH_SOURCE_SIZE = 8
GLYPH_TARGET_SIZE = 6
AREA_THRESHOLD = 64


@dataclass(frozen=True)
class Overlay:
    name: str
    text: str
    x: int
    y: int
    colour: int
    ranges: tuple[tuple[int, int], ...]

    def active(self, frame: int) -> bool:
        return any(first <= frame <= last for first, last in self.ranges)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def spectrum_offset(y: int, x_byte: int) -> int:
    return (
        ((y & 0xC0) << 5)
        | ((y & 0x07) << 8)
        | ((y & 0x38) << 2)
        | x_byte
    )


def parse_rawgl(path: Path) -> tuple[bytes, dict[str, dict[int, str]]]:
    source = path.read_text(encoding="utf-8")
    font_match = re.search(
        r"const uint8_t Graphics::_font\[\] = \{(.*?)\n\};",
        source,
        re.DOTALL,
    )
    if not font_match:
        raise ValueError("RawGL font table was not found in staticres.cpp")
    font = bytes(
        int(value, 16)
        for value in re.findall(r"0x([0-9A-Fa-f]+)", font_match.group(1))
    )
    if len(font) != 96 * GLYPH_SOURCE_SIZE:
        raise ValueError(f"unexpected RawGL font size: {len(font)} bytes")

    tables: dict[str, dict[int, str]] = {}
    for schedule_name, source_name in (("eng", "Eng"), ("demo", "Demo")):
        table_match = re.search(
            rf"const StrEntry Video::_stringsTable{source_name}\[\] = \{{"
            rf"(.*?)\n\}};",
            source,
            re.DOTALL,
        )
        if not table_match:
            raise ValueError(f"RawGL {schedule_name} string table was not found")
        entries: dict[int, str] = {}
        for number, literal in re.findall(
            r'\{\s*0x([0-9A-Fa-f]+),\s*"((?:\\.|[^"\\])*)"\s*\}',
            table_match.group(1),
        ):
            entries[int(number, 16)] = ast.literal_eval(f'"{literal}"')
        tables[schedule_name] = entries
    return font, tables


def load_schedule(
    path: Path,
    tables: dict[str, dict[int, str]],
) -> tuple[list[Overlay], dict]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("version") != 1:
        raise ValueError("unsupported hybrid text schedule version")

    overlays: list[Overlay] = []
    for item in document.get("overlays", []):
        if "text" in item:
            text = str(item["text"])
        else:
            table = str(item["table"])
            string_id = int(str(item["id"]), 0)
            try:
                text = tables[table][string_id]
            except KeyError as exc:
                raise ValueError(
                    f"string {table}:{string_id:#05x} was not found in RawGL"
                ) from exc
        ranges = tuple((int(first), int(last)) for first, last in item["ranges"])
        if not ranges or any(first < 0 or last < first for first, last in ranges):
            raise ValueError(f"invalid frame range for overlay {item['name']}")
        colour = int(item["colour"])
        if not 0 <= colour <= 15:
            raise ValueError(f"invalid Spectrum colour for overlay {item['name']}")
        overlays.append(
            Overlay(
                name=str(item["name"]),
                text=text,
                x=int(item["x"]),
                y=int(item["y"]),
                colour=colour,
                ranges=ranges,
            )
        )
    if not overlays:
        raise ValueError("hybrid text schedule contains no overlays")
    return overlays, document


def decode_awd2(path: Path) -> tuple[int, int, list[bytes], bytes]:
    blob = path.read_bytes()
    if len(blob) < 14 or blob[:4] != MAGIC:
        raise ValueError(f"{path} is not an AWD2 stream")
    fps_num, fps_den, screen_size, frame_count = struct.unpack_from(
        "<HHHI", blob, 4
    )
    if (fps_num, fps_den) != (25, 1):
        raise ValueError(f"hybrid build requires 25 fps, got {fps_num}/{fps_den}")
    if screen_size != SCREEN_SIZE:
        raise ValueError(f"unexpected AWD2 screen size: {screen_size}")

    states = [bytearray(SCREEN_SIZE), bytearray(SCREEN_SIZE)]
    frames: list[bytes] = []
    offset = 14
    for frame in range(frame_count):
        if offset + 2 > len(blob):
            raise ValueError(f"truncated AWD2 length at frame {frame}")
        size = struct.unpack_from("<H", blob, offset)[0]
        offset += 2
        end = offset + size
        if end > len(blob):
            raise ValueError(f"truncated AWD2 payload at frame {frame}")
        screen = states[frame & 1]
        destination = 0
        ended = False
        while offset < end:
            control = blob[offset]
            offset += 1
            if control == 0:
                ended = True
                break
            if control < 0x80:
                destination += control
                if destination > SCREEN_SIZE:
                    raise ValueError(f"AWD2 skip overflow at frame {frame}")
                continue
            count = (control & 0x7F) + 1
            if offset + count > end or destination + count > SCREEN_SIZE:
                raise ValueError(f"AWD2 literal overflow at frame {frame}")
            screen[destination : destination + count] = blob[offset : offset + count]
            destination += count
            offset += count
        if not ended or offset != end:
            raise ValueError(f"AWD2 payload boundary mismatch at frame {frame}")
        frames.append(bytes(screen))
    if offset != len(blob):
        raise ValueError(f"unused AWD2 bytes: {len(blob) - offset}")
    return fps_num, fps_den, frames, blob


def glyph_rows(font: bytes, character: str) -> bytes:
    code = ord(character)
    if not 0x20 <= code <= 0x7F:
        raise ValueError(f"character is outside the RawGL font: {character!r}")
    start = (code - 0x20) * GLYPH_SOURCE_SIZE
    return font[start : start + GLYPH_SOURCE_SIZE]


def legacy_mask(
    font: bytes,
    text: str,
    x: int,
    y: int,
) -> tuple[tuple[int, int], ...]:
    pixels = bytearray(RAWGL_WIDTH * RAWGL_HEIGHT)
    line_x = x
    for character in text:
        if character in "\n\r":
            y += GLYPH_SOURCE_SIZE
            x = line_x
            continue
        rows = glyph_rows(font, character)
        left = x * GLYPH_SOURCE_SIZE
        if left <= RAWGL_WIDTH - GLYPH_SOURCE_SIZE and y <= RAWGL_HEIGHT - 8:
            for row, bits in enumerate(rows):
                for column in range(GLYPH_SOURCE_SIZE):
                    if bits & (0x80 >> column):
                        pixels[(y + row) * RAWGL_WIDTH + left + column] = 255
        x += 1
    image = Image.frombytes("L", (RAWGL_WIDTH, RAWGL_HEIGHT), bytes(pixels))
    resized = image.resize(
        (SCREEN_WIDTH, SCREEN_HEIGHT),
        resample=Image.Resampling.NEAREST,
    )
    return tuple(
        (index % SCREEN_WIDTH, index // SCREEN_WIDTH)
        for index, value in enumerate(resized.tobytes())
        if value
    )


def make_font6(font: bytes) -> dict[str, tuple[tuple[int, int], ...]]:
    resized: dict[str, tuple[tuple[int, int], ...]] = {}
    for code in range(0x20, 0x80):
        rows = glyph_rows(font, chr(code))
        source = bytes(
            255 if rows[y] & (0x80 >> x) else 0
            for y in range(8)
            for x in range(8)
        )
        image = Image.frombytes("L", (8, 8), source).resize(
            (GLYPH_TARGET_SIZE, GLYPH_TARGET_SIZE),
            resample=Image.Resampling.BOX,
        )
        resized[chr(code)] = tuple(
            (index % GLYPH_TARGET_SIZE, index // GLYPH_TARGET_SIZE)
            for index, value in enumerate(image.tobytes())
            if value >= AREA_THRESHOLD
        )
    return resized


def resized_text_points(
    font6: dict[str, tuple[tuple[int, int], ...]],
    text: str,
    x: int,
    y: int,
) -> tuple[tuple[int, int], ...]:
    points: set[tuple[int, int]] = set()
    line_x = x
    line = 0
    column = 0
    for character in text:
        if character in "\n\r":
            line += 1
            column = 0
            continue
        char_x = ((line_x + column) * SCREEN_WIDTH) // 40
        char_y = ((y + line * 8) * SCREEN_HEIGHT) // RAWGL_HEIGHT
        for dx, dy in font6[character]:
            px, py = char_x + dx, char_y + dy
            if 0 <= px < SCREEN_WIDTH and 0 <= py < SCREEN_HEIGHT:
                points.add((px, py))
        column += 1
    return tuple(sorted(points, key=lambda point: (point[1], point[0])))


def set_pixel(screen: bytearray, x: int, y: int, enabled: bool) -> None:
    offset = spectrum_offset(y, x // 8)
    bit = 0x80 >> (x & 7)
    if enabled:
        screen[offset] |= bit
    else:
        screen[offset] &= ~bit


def set_cell_ink(screen: bytearray, x: int, y: int, colour: int) -> None:
    offset = 6144 + (y // 8) * 32 + x // 8
    attribute = screen[offset]
    paper = (attribute >> 3) & 7
    ink = colour & 7
    if paper == ink:
        paper = 0 if ink else 7
    screen[offset] = (
        (attribute & 0x80)
        | (0x40 if colour >= 8 else 0)
        | (paper << 3)
        | ink
    )


def apply_overlay(
    screen: bytearray,
    old_points: Iterable[tuple[int, int]],
    new_points: Iterable[tuple[int, int]],
    colour: int,
) -> None:
    for x, y in old_points:
        set_pixel(screen, x, y, False)
    new_points = tuple(new_points)
    for x, y in new_points:
        set_cell_ink(screen, x, y, colour)
    for x, y in new_points:
        set_pixel(screen, x, y, True)


def encode_delta(previous: bytes, current: bytes, merge_gap: int) -> bytes:
    changed = [
        index
        for index, (old, new) in enumerate(zip(previous, current))
        if old != new
    ]
    output = bytearray()
    position = 0
    cursor = 0
    while cursor < len(changed):
        start = end = changed[cursor]
        cursor += 1
        while cursor < len(changed) and changed[cursor] - end - 1 <= merge_gap:
            end = changed[cursor]
            cursor += 1

        skip = start - position
        while skip:
            count = min(skip, 127)
            output.append(count)
            skip -= count
        data = current[start : end + 1]
        for offset in range(0, len(data), 128):
            chunk = data[offset : offset + 128]
            output.append(0x80 | (len(chunk) - 1))
            output.extend(chunk)
        position = end + 1
    output.append(0)
    return bytes(output)


def encode_awd2(
    frames: list[bytes],
    fps_num: int,
    fps_den: int,
    merge_gap: int,
) -> tuple[bytes, int]:
    output = bytearray(MAGIC)
    output += struct.pack("<HHHI", fps_num, fps_den, SCREEN_SIZE, len(frames))
    states = [bytes(SCREEN_SIZE), bytes(SCREEN_SIZE)]
    payload_bytes = 0
    for frame, screen in enumerate(frames):
        payload = encode_delta(states[frame & 1], screen, merge_gap)
        if len(payload) > 0xFFFF:
            raise ValueError(f"frame {frame} payload exceeds the AWD2 u16 limit")
        output += struct.pack("<H", len(payload))
        output += payload
        payload_bytes += 2 + len(payload)
        states[frame & 1] = screen
    return bytes(output), payload_bytes


def build(
    source_path: Path,
    output_path: Path,
    staticres_path: Path,
    schedule_path: Path,
    rawgl_revision: str,
    merge_gap: int,
) -> dict:
    font, tables = parse_rawgl(staticres_path)
    overlays, schedule = load_schedule(schedule_path, tables)
    fps_num, fps_den, source_frames, source_blob = decode_awd2(source_path)
    if max(last for overlay in overlays for _, last in overlay.ranges) >= len(
        source_frames
    ):
        raise ValueError("hybrid text schedule extends past the source stream")

    font6 = make_font6(font)
    masks = {
        overlay.name: legacy_mask(font, overlay.text, overlay.x, overlay.y)
        for overlay in overlays
    }
    replacements = {
        overlay.name: resized_text_points(
            font6, overlay.text, overlay.x, overlay.y
        )
        for overlay in overlays
    }

    output_frames: list[bytes] = []
    modified_frames = 0
    modified_screen_bytes = 0
    applied_overlays = 0
    active_names: set[str] = set()
    for frame, source in enumerate(source_frames):
        screen = bytearray(source)
        for overlay in overlays:
            if not overlay.active(frame):
                continue
            apply_overlay(
                screen,
                masks[overlay.name],
                replacements[overlay.name],
                overlay.colour,
            )
            applied_overlays += 1
            active_names.add(overlay.name)
        result = bytes(screen)
        differences = sum(old != new for old, new in zip(source, result))
        if differences:
            modified_frames += 1
            modified_screen_bytes += differences
        output_frames.append(result)

    output_blob, payload_bytes = encode_awd2(
        output_frames, fps_num, fps_den, merge_gap
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(output_blob)
    return {
        "format": "AWD2 hybrid text build v1",
        "source_file": source_path.name,
        "source_sha256": sha256(source_blob),
        "output_file": output_path.name,
        "output_sha256": sha256(output_blob),
        "output_bytes": len(output_blob),
        "frames": len(output_frames),
        "fps_numerator": fps_num,
        "fps_denominator": fps_den,
        "duration_seconds": len(output_frames) * fps_den / fps_num,
        "screen_bytes": SCREEN_SIZE,
        "picture_path": "original AWD2 frames; text cells only are modified",
        "text_path": "RawGL 8x8 glyphs resized to 6x6 with Pillow BOX",
        "glyph_source_size": [8, 8],
        "glyph_target_size": [6, 6],
        "area_threshold": AREA_THRESHOLD,
        "rawgl_revision": rawgl_revision,
        "rawgl_staticres_sha256": sha256(staticres_path.read_bytes()),
        "font_sha256": sha256(font),
        "schedule_file": schedule_path.name,
        "schedule_sha256": sha256(schedule_path.read_bytes()),
        "schedule_version": schedule["version"],
        "scheduled_overlays": len(overlays),
        "active_overlays": len(active_names),
        "overlay_applications": applied_overlays,
        "modified_frames": modified_frames,
        "modified_screen_bytes": modified_screen_bytes,
        "payload_bytes": payload_bytes,
        "merge_gap": merge_gap,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--rawgl-staticres", required=True, type=Path)
    parser.add_argument(
        "--schedule",
        type=Path,
        default=Path(__file__).with_name("hybrid_aw_font_schedule.json"),
    )
    parser.add_argument("--rawgl-revision", default="unknown")
    # Gap 1 keeps the external player on its exact 8,226-refresh completion
    # deadline with this schedule while still fitting the stream in 26 blocks.
    parser.add_argument("--merge-gap", type=int, default=1)
    parser.add_argument("--stats", type=Path)
    args = parser.parse_args()

    result = build(
        args.input,
        args.output,
        args.rawgl_staticres,
        args.schedule,
        args.rawgl_revision,
        args.merge_gap,
    )
    if args.stats:
        args.stats.parent.mkdir(parents=True, exist_ok=True)
        args.stats.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
