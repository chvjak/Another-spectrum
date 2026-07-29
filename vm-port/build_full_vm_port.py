#!/usr/bin/env python3
"""Build the size-first full-intro ZX Spectrum VM/vector prototype."""

from __future__ import annotations

import argparse
import json
import os
import re
import struct
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image

import analyze_visual_assets as visual
import build_vm_port as base
import lzss


ROOT = Path(__file__).resolve().parent
WORKSPACE = ROOT.parent
BUILD = ROOT / "build-full"

RESOURCE_BYTECODE = 0x18
RESOURCE_SHAPES = 0x19
RESOURCE_PALETTE = 0x17

TEXT_DATA_OFFSET_BANK1 = 0x2680
ATTR_CHUNK0_OFFSET_BANK1 = 0x2E00
ATTR_CHUNK0_SIZE = 0x1200
PAGED_DATA_OFFSET_BANK7 = 0x1B00
RENDERER_OFFSET_BANK5 = 0x1D20  # address 0x5D20, immediately after IM2 code
ASSET19_OFFSET_BANK5 = 0x3400   # address 0x7400
EVENT_RUNS_OFFSET_BANK5 = 0x2C00  # address 0x6C00

REFERENCE_FRAMES = sorted((WORKSPACE / "full-speccy").glob("frame-*.scr"))
SOURCE_PAGE0 = WORKSPACE / "captured-pages-aligned"
SOURCE_INDEXED_PAGE0 = BUILD / "indexed-pages"

# Frame numbers whose page-0 generation begins with a resource load or clear.
# A new logical PAPER/INK pairing is safe only at these points; copy-based and
# incremental background changes retain the previous bit interpretation.
PAIR_GENERATION_FRAMES = (
    10,
    60,
    110,
    190,
    200,
    310,
    410,
    780,
    1060,
    1090,
    1180,
    2170,
    2220,
    2910,
    2950,
)


def extract_used_palettes() -> list[int]:
    used: set[int] = set()
    pattern = re.compile(r"Script::op_changePalette\((\d+)\)")
    with base.TRACE.open(encoding="utf-8", errors="replace") as source:
        for line in source:
            match = pattern.search(line)
            if match:
                number = int(match.group(1)) >> 8
                if number not in (10, 16):  # rawgl DOS-intro redraw fixup
                    used.add(number)
    return sorted(used)


def spectrum_palette_mapping(palette: bytes, used: list[int]) -> bytes:
    spectrum = visual.PALETTE.astype(int)
    slots = bytearray([0xFF] * 64)
    mappings = bytearray()
    for slot, palette_number in enumerate(used):
        slots[palette_number] = slot
        start = palette_number * 32
        for color in range(16):
            value = int.from_bytes(
                palette[start + color * 2 : start + color * 2 + 2], "big"
            )
            rgb = (
                ((value >> 8) & 15) * 17,
                ((value >> 4) & 15) * 17,
                (value & 15) * 17,
            )
            distances = [
                sum((rgb[channel] - int(candidate[channel])) ** 2 for channel in range(3))
                for candidate in spectrum
            ]
            mappings.append(min(range(16), key=distances.__getitem__))
    return bytes(slots + mappings)


def spectrum_decision_masks() -> bytes:
    spectrum = visual.PALETTE.astype(int)
    output = bytearray()
    for desired in range(16):
        for group in range(16):
            bits = 0
            for low in range(8):
                attribute = group * 8 + low
                bright = (attribute >> 6) & 1
                ink = (attribute & 7) + bright * 8
                paper = ((attribute >> 3) & 7) + bright * 8
                ink_error = sum(
                    (int(spectrum[desired][channel]) - int(spectrum[ink][channel])) ** 2
                    for channel in range(3)
                )
                paper_error = sum(
                    (int(spectrum[desired][channel]) - int(spectrum[paper][channel])) ** 2
                    for channel in range(3)
                )
                if ink_error < paper_error:
                    bits |= 1 << low
            output.append(bits)
    # Row 16 is Another World's COL_ALPHA operation. On the indexed original
    # it sets colour bit 3; for a two-colour Spectrum cell, choosing the
    # brighter of INK/PAPER is the compact and deterministic equivalent.
    for group in range(16):
        bits = 0
        for low in range(8):
            attribute = group * 8 + low
            bright = (attribute >> 6) & 1
            ink = (attribute & 7) + bright * 8
            paper = ((attribute >> 3) & 7) + bright * 8
            if sum(spectrum[ink]) > sum(spectrum[paper]):
                bits |= 1 << low
        output.append(bits)
    if len(output) != 272:
        raise AssertionError(len(output))
    return bytes(output)


def export_all_text() -> tuple[dict[int, bytes], bytes]:
    BUILD.mkdir(parents=True, exist_ok=True)
    tool = BUILD / "export-text-data"
    raw = BUILD / "all-text.bin"
    sources = [
        ROOT / "export_text_data.cpp",
        *[
            WORKSPACE / "rawgl" / name
            for name in (
                "aifcplayer.cpp",
                "bitmap.cpp",
                "file.cpp",
                "engine.cpp",
                "graphics_soft.cpp",
                "script.cpp",
                "mixer_headless.cpp",
                "pak.cpp",
                "resource.cpp",
                "resource_nth.cpp",
                "resource_win31.cpp",
                "resource_3do.cpp",
                "scaler.cpp",
                "screenshot.cpp",
                "sfxplayer.cpp",
                "staticres.cpp",
                "unpack.cpp",
                "util.cpp",
                "video.cpp",
            )
        ],
    ]
    subprocess.run(
        [
            "g++",
            "-std=c++17",
            "-O2",
            "-DBYPASS_PROTECTION",
            f"-I{WORKSPACE / 'rawgl'}",
            *map(str, sources),
            "-lz",
            "-o",
            str(tool),
        ],
        check=True,
    )
    subprocess.run([str(tool), str(raw)], check=True)
    blob = raw.read_bytes()
    count = struct.unpack_from("<H", blob)[0]
    position = 2
    strings: dict[int, bytes] = {}
    for _ in range(count):
        string_id, length = struct.unpack_from("<HH", blob, position)
        position += 4
        strings[string_id] = blob[position : position + length]
        position += length
    font = blob[position : position + 96 * 8]
    if len(font) != 96 * 8:
        raise RuntimeError("short exported font")
    return strings, font


def used_string_ids() -> list[int]:
    tick = -1
    work_page = 0xFE
    result: set[int] = set()
    tick_pattern = re.compile(r"TRACE_TICK (\d+)")
    page_pattern = re.compile(r"Script::op_selectPage\((\d+)\)")
    text_pattern = re.compile(r"Script::op_drawString\(0x([0-9A-F]+),")
    with base.TRACE.open(encoding="utf-8", errors="replace") as source:
        for line in source:
            match = tick_pattern.search(line)
            if match:
                tick = int(match.group(1))
                continue
            match = page_pattern.search(line)
            if match:
                work_page = int(match.group(1))
                continue
            match = text_pattern.search(line)
            if not match:
                continue
            sampled = tick == 0 or (tick >= 8 and (tick - 8) % 10 == 0)
            if work_page == 0 or sampled:
                result.add(int(match.group(1), 16))
    return sorted(result)


def live_visual_tick_mask() -> bytes:
    """Conservative dead-draw elimination for the 5 fps Spectrum timeline.

    Page histories are followed through fills, copies and the 0xFF front/back
    swap.  A shape/text tick is retained when any operation from that tick is
    still present in a sampled display.  This costs one bit per VM tick and
    avoids carrying a much larger precompiled command stream.
    """

    histories: dict[int, list[int]] = {0: [], 1: [], 2: [], 3: []}
    front, back = 2, 1
    work_page = 0xFE
    tick = -1
    event_ticks: dict[int, int] = {}
    event_work_pages: dict[int, int] = {}
    live_events: set[int] = set()
    next_event = 0

    def resolve(page: int) -> int:
        if page == 0xFF:
            return back
        if page == 0xFE:
            return front
        return page

    tick_pattern = re.compile(r"TRACE_TICK (\d+)")
    select_pattern = re.compile(r"Script::op_selectPage\((\d+)\)")
    fill_pattern = re.compile(r"Script::op_fillPage\((\d+), (\d+)\)")
    copy_pattern = re.compile(r"Script::op_copyPage\((\d+), (\d+)\)")
    present_pattern = re.compile(r"Script::op_updateDisplay\((\d+)\)")

    with base.TRACE.open(encoding="utf-8", errors="replace") as source:
        for line in source:
            match = tick_pattern.search(line)
            if match:
                tick = int(match.group(1))
                continue
            match = select_pattern.search(line)
            if match:
                work_page = int(match.group(1))
                continue
            match = fill_pattern.search(line)
            if match:
                page = resolve(int(match.group(1)))
                next_event += 1
                event_ticks[next_event] = tick
                histories[page] = [next_event]
                continue
            match = copy_pattern.search(line)
            if match:
                source_page = resolve(int(match.group(1)))
                destination_page = resolve(int(match.group(2)))
                histories[destination_page] = list(histories[source_page])
                continue
            if "vid_opcd_" in line or "Script::op_drawString(" in line:
                next_event += 1
                event_ticks[next_event] = tick
                event_work_pages[next_event] = work_page
                histories[resolve(work_page)].append(next_event)
                continue
            match = present_pattern.search(line)
            if not match:
                continue
            page = int(match.group(1))
            sampled = tick == 0 or (tick >= 8 and (tick - 8) % 10 == 0)
            if sampled:
                live_events.update(histories[resolve(page)])
            if page == 0xFF:
                front, back = back, front

    mask = bytearray((2980 + 7) // 8)
    for event in live_events:
        # Page 0 and page 3 are persistent and are always rendered.  This bit
        # field is solely the dead-draw filter for the two swapping pages.
        if event_work_pages.get(event) not in (0xFE, 0xFF):
            continue
        event_tick = event_ticks[event]
        if 0 <= event_tick < 2980:
            mask[event_tick >> 3] |= 1 << (event_tick & 7)
    return bytes(mask)


def draw_event_runs() -> bytes:
    """Run-code the offline final-pixel ownership mask.

    Byte zero is the initial keep bit.  Remaining bytes are alternating run
    lengths. Runs longer than 255 are split by inserting a zero-length run of
    the opposite value, preserving the implicit toggle.
    """
    mask_path = BUILD / "draw-event-keep-mask.bin"
    if not mask_path.exists():
        subprocess.run(
            ["python3", str(ROOT / "optimize_draws.py")],
            check=True,
            cwd=WORKSPACE,
        )
    packed = mask_path.read_bytes()
    count = 9648
    bits = (
        [1] * count
        if os.environ.get("AW_KEEP_ALL_DRAWS") == "1"
        else [(packed[index >> 3] >> (index & 7)) & 1 for index in range(count)]
    )
    output = bytearray([bits[0]])
    current = bits[0]
    run = 0
    for bit in bits:
        if bit == current and run < 255:
            run += 1
            continue
        output.append(run)
        if bit == current:
            output.append(0)
        current = bit
        run = 1
    output.append(run)
    return bytes(output)


def compact_text_data() -> bytes:
    strings, font = export_all_text()
    ids = used_string_ids()
    missing = [string_id for string_id in ids if string_id not in strings]
    if missing:
        raise RuntimeError(f"missing strings {missing}")

    characters = sorted(
        set(b"".join(strings[string_id] for string_id in ids)) - {10, 13}
    )
    glyph_map = bytearray([0xFF] * 96)
    glyphs = bytearray()
    for slot, character in enumerate(characters):
        if not 0x20 <= character <= 0x7F:
            raise RuntimeError(f"unsupported text byte {character}")
        glyph_map[character - 0x20] = slot
        glyphs += font[(character - 0x20) * 8 : (character - 0x20 + 1) * 8]

    header_size = 7 + len(ids) * 4
    text_blob = bytearray()
    entries = bytearray()
    for string_id in ids:
        entries += struct.pack("<HH", string_id, header_size + len(text_blob))
        text_blob += strings[string_id] + b"\0"
    glyph_map_offset = header_size + len(text_blob)
    glyph_data_offset = glyph_map_offset + len(glyph_map)
    output = bytearray(
        struct.pack("<BHHH", len(ids), header_size, glyph_map_offset, glyph_data_offset)
    )
    output += entries + text_blob + glyph_map + glyphs
    return bytes(output)


def converted_page0(frame_number: int, attributes: bytes) -> bytes:
    source = SOURCE_PAGE0 / f"page0-{frame_number:04}.ppm"
    return visual.encode_with_attributes(Image.open(source), attributes)


def indexed_page0(frame_number: int) -> np.ndarray:
    source = SOURCE_INDEXED_PAGE0 / f"page0-{frame_number:04}.idx"
    raw = source.read_bytes()
    if len(raw) != 320 * 200:
        raise RuntimeError(f"bad indexed page {source}: {len(raw)} bytes")
    image = Image.frombytes("L", (320, 200), raw)
    return np.asarray(
        image.resize((256, 192), Image.Resampling.NEAREST),
        dtype=np.uint8,
    )


def indexed_palette(frame_number: int) -> np.ndarray:
    source = SOURCE_INDEXED_PAGE0 / f"page0-{frame_number:04}.pal"
    raw = source.read_bytes()
    if len(raw) != 16 * 3:
        raise RuntimeError(f"bad indexed palette {source}: {len(raw)} bytes")
    return np.frombuffer(raw, dtype=np.uint8).reshape(16, 3).astype(np.int16)


def generation_for_frame(frame_number: int) -> int:
    generation = PAIR_GENERATION_FRAMES[0]
    for candidate in PAIR_GENERATION_FRAMES:
        if candidate > frame_number:
            break
        generation = candidate
    return generation


def logical_pair_maps() -> dict[int, bytes]:
    """Choose stable logical PAPER/INK colours for each page-0 generation.

    Counts cover the generation's complete lifetime, not just its first
    picture, so incremental text and geometry are represented without changing
    what existing bitmap bits mean.
    """

    runtime_frames = list(range(10, 2990, 10))
    indexed = {frame: indexed_page0(frame) for frame in runtime_frames}
    result: dict[int, bytes] = {}
    for generation_index, generation in enumerate(PAIR_GENERATION_FRAMES):
        end = (
            PAIR_GENERATION_FRAMES[generation_index + 1]
            if generation_index + 1 < len(PAIR_GENERATION_FRAMES)
            else 2990
        )
        counts = np.zeros((768, 16), dtype=np.int32)
        for frame in runtime_frames:
            if frame < generation or frame >= end:
                continue
            cells = (
                indexed[frame]
                .reshape(24, 8, 32, 8)
                .transpose(0, 2, 1, 3)
                .reshape(768, 64)
            )
            for color in range(16):
                counts[:, color] += np.count_nonzero(cells == color, axis=1)

        paper = np.argmax(counts, axis=1)
        counts[np.arange(768), paper] = -1
        ink = np.argmax(counts, axis=1)
        packed = bytes(
            (int(paper[cell]) & 15) | ((int(ink[cell]) & 15) << 4)
            for cell in range(768)
        )
        result[generation] = packed
    return result


def stable_attributes(
    pair_maps: dict[int, bytes],
) -> list[bytes]:
    """Generate palette-dependent attributes without swapping bitmap roles."""

    spectrum = visual.PALETTE.astype(np.int32)
    cache: dict[tuple[bytes, int, int], int] = {}
    output: list[bytes] = []
    for frame in range(10, 2990, 10):
        palette = indexed_palette(frame).astype(np.int32)
        palette_key = palette.astype(np.uint8).tobytes()
        pairs = pair_maps[generation_for_frame(frame)]
        attributes = bytearray(768)
        for cell, pair in enumerate(pairs):
            paper_logical = pair & 15
            ink_logical = pair >> 4
            key = (palette_key, paper_logical, ink_logical)
            attribute = cache.get(key)
            if attribute is None:
                paper_rgb = palette[paper_logical]
                ink_rgb = palette[ink_logical]
                best_error: int | None = None
                best_attribute = 0
                for bright in range(2):
                    for paper_color in range(8):
                        for ink_color in range(8):
                            paper_spectrum = spectrum[paper_color + bright * 8]
                            ink_spectrum = spectrum[ink_color + bright * 8]
                            error = int(
                                np.sum((paper_rgb - paper_spectrum) ** 2)
                                + np.sum((ink_rgb - ink_spectrum) ** 2)
                            )
                            if best_error is None or error < best_error:
                                best_error = error
                                best_attribute = (
                                    ink_color | (paper_color << 3) | (bright << 6)
                                )
                attribute = best_attribute
                cache[key] = attribute
            attributes[cell] = attribute
        output.append(bytes(attributes))
    return output


def converted_indexed_page0(
    frame_number: int,
    attributes: bytes,
    pairs: bytes,
) -> bytes:
    """Encode page 0 while preserving the generation's logical bit roles."""

    pixels = indexed_page0(frame_number)
    palette = indexed_palette(frame_number).astype(np.int32)
    spectrum = visual.PALETTE.astype(np.int32)
    output = bytearray(6912)
    output[6144:] = attributes
    for cy in range(24):
        for cx in range(32):
            cell = cy * 32 + cx
            pair = pairs[cell]
            paper_logical = pair & 15
            ink_logical = pair >> 4
            attribute = attributes[cell]
            bright = (attribute >> 6) & 1
            ink_rgb = spectrum[(attribute & 7) + bright * 8]
            paper_rgb = spectrum[((attribute >> 3) & 7) + bright * 8]
            block = pixels[cy * 8 : cy * 8 + 8, cx * 8 : cx * 8 + 8]
            value_rows = np.zeros((8, 8), dtype=np.uint8)
            value_rows[block == ink_logical] = 1
            unresolved = (block != ink_logical) & (block != paper_logical)
            if np.any(unresolved):
                rgb = palette[block]
                ink_error = np.sum((rgb - ink_rgb) ** 2, axis=2)
                paper_error = np.sum((rgb - paper_rgb) ** 2, axis=2)
                value_rows[unresolved] = (ink_error < paper_error)[unresolved]
            for yy in range(8):
                value = 0
                for bit in value_rows[yy]:
                    value = (value << 1) | int(bit)
                output[visual.spectrum_offset(cy * 8 + yy, cx)] = value
    return bytes(output)


def make_data() -> dict[str, object]:
    reference = [path.read_bytes() for path in REFERENCE_FRAMES]
    if len(reference) != 299:
        raise RuntimeError(f"expected 299 full reference frames, got {len(reference)}")
    pair_maps = logical_pair_maps()
    runtime_attributes = stable_attributes(pair_maps)
    if len(runtime_attributes) != 298:
        raise AssertionError(len(runtime_attributes))

    exact_groups = (
        runtime_attributes[:5],     # frames 10..50, bitmap resource 18
        runtime_attributes[5:294],  # frames 60..2940, bitmap resource 71
        runtime_attributes[294:],   # frames 2950..2980, bitmap resource 19
    )
    map_groups: list[list[bytes]] = []
    group_indices: list[list[int]] = []
    encoded_runtime_attributes: list[bytes] = []
    for group in exact_groups:
        maps, indices = visual.choose_runs(list(group), 0)
        map_groups.append(maps)
        group_indices.append(indices)
        encoded_runtime_attributes.extend(maps[index] for index in indices)
    runtime_attributes = encoded_runtime_attributes

    packed_attrs = [lzss.compress(b"".join(group)) for group in map_groups]
    for group, packed in zip(map_groups, packed_attrs):
        raw = b"".join(group)
        if lzss.decompress(packed, len(raw)) != raw:
            raise RuntimeError("attribute LZSS validation failed")

    bitmap_frames = (10, 60, 2950)
    bitmap_indices = (0, 5, 294)
    bitmaps = [
        converted_indexed_page0(
            number,
            runtime_attributes[index],
            pair_maps[generation_for_frame(number)],
        )
        for number, index in zip(bitmap_frames, bitmap_indices)
    ]
    packed_bitmaps = [lzss.compress(bitmap) for bitmap in bitmaps]
    for bitmap, packed in zip(bitmaps, packed_bitmaps):
        if lzss.decompress(packed, len(bitmap)) != bitmap:
            raise RuntimeError("bitmap LZSS validation failed")

    # Global sampled-frame change mask. Bit N says frame N+1 needs a newly
    # decoded attribute map; resource boundaries decode their first map.
    attr_change_mask = bytearray((298 + 7) // 8)
    global_index = 0
    for indices in group_indices:
        for local_index, map_index in enumerate(indices):
            if local_index != 0 and map_index != indices[local_index - 1]:
                attr_change_mask[global_index >> 3] |= 1 << (global_index & 7)
            global_index += 1

    checkpoint_frames = (200, 310, 410, 1060, 2220)
    checkpoints = []
    for number in checkpoint_frames:
        attribute_index = number // 10 - 1
        screen = converted_indexed_page0(
            number,
            runtime_attributes[attribute_index],
            pair_maps[generation_for_frame(number)],
        )
        checkpoints.append(lzss.compress(screen[:6144]))
        if lzss.decompress(checkpoints[-1], 6144) != screen[:6144]:
            raise RuntimeError(f"checkpoint {number} LZSS validation failed")

    return {
        "attribute_groups": map_groups,
        "attribute_group_indices": group_indices,
        "runtime_attributes": runtime_attributes,
        "logical_pair_maps": pair_maps,
        "attribute_change_mask": bytes(attr_change_mask),
        "packed_attributes": packed_attrs,
        "bitmap_frames": bitmap_frames,
        "bitmaps": bitmaps,
        "packed_bitmaps": packed_bitmaps,
        "checkpoint_frames": checkpoint_frames,
        "checkpoints": checkpoints,
    }


def put(page: bytearray, offset: int, data: bytes, label: str) -> None:
    if offset < 0 or offset + len(data) > len(page):
        raise RuntimeError(
            f"{label} does not fit: offset={offset:#x}, bytes={len(data)}, "
            f"capacity={len(page) - offset}"
        )
    page[offset : offset + len(data)] = data


def write_generated_layout(data: dict[str, object]) -> None:
    packed_attrs: list[bytes] = data["packed_attributes"]  # type: ignore[assignment]
    packed_bitmaps: list[bytes] = data["packed_bitmaps"]  # type: ignore[assignment]
    checkpoints: list[bytes] = data["checkpoints"]  # type: ignore[assignment]
    cursor = PAGED_DATA_OFFSET_BANK7
    addresses: dict[str, int] = {}

    def allocate(name: str, size: int) -> None:
        nonlocal cursor
        addresses[name] = 0xC000 + cursor
        cursor += size

    allocate(
        "ATTR_MIDDLE_CHUNK1",
        max(0, len(packed_attrs[1]) - ATTR_CHUNK0_SIZE),
    )
    allocate("ATTR_FIRST", len(packed_attrs[0]))
    allocate("ATTR_LAST", len(packed_attrs[2]))
    allocate("BITMAP18", len(packed_bitmaps[0]))
    allocate("BITMAP71", len(packed_bitmaps[1]))
    for index, payload in enumerate(checkpoints):
        allocate(f"CHECKPOINT{index}", len(payload))

    lines = [
        "; Generated by build_full_vm_port.py; do not hand-edit.",
        *(f"{name:<24} EQU 0x{address:04X}" for name, address in addresses.items()),
        "",
    ]
    (ROOT / "generated_full_layout.inc").write_text("\n".join(lines))


def make_snapshot(
    vm: bytes,
    renderer: bytes,
    bytecode: bytes,
    shapes: bytes,
    text: bytes,
    palette_tables: bytes,
    decisions: bytes,
    live_ticks: bytes,
    event_runs: bytes,
    data: dict[str, object],
) -> tuple[bytes, dict[str, object]]:
    pages = [bytearray(0x4000) for _ in range(8)]
    put(pages[2], 0, vm, "VM")
    put(pages[1], 0, bytecode, "bytecode")
    put(pages[1], TEXT_DATA_OFFSET_BANK1, text, "text data")
    shape_layout = base.pack_shapes(pages, shapes)

    packed_attrs: list[bytes] = data["packed_attributes"]  # type: ignore[assignment]
    packed_bitmaps: list[bytes] = data["packed_bitmaps"]  # type: ignore[assignment]
    middle = packed_attrs[1]
    chunk0 = middle[:ATTR_CHUNK0_SIZE]
    chunk1 = middle[ATTR_CHUNK0_SIZE:]
    put(pages[1], ATTR_CHUNK0_OFFSET_BANK1, chunk0, "middle attributes chunk 0")

    bank7_cursor = PAGED_DATA_OFFSET_BANK7
    layout: dict[str, object] = {}

    def put7(name: str, payload: bytes) -> int:
        nonlocal bank7_cursor
        offset = bank7_cursor
        put(pages[7], offset, payload, name)
        bank7_cursor += len(payload)
        layout[name] = {
            "bank": 7,
            "offset": offset,
            "address": 0xC000 + offset,
            "bytes": len(payload),
        }
        return offset

    middle_chunk1_offset = put7("attr_middle_chunk1", chunk1)
    attr_first_offset = put7("attr_first", packed_attrs[0])
    attr_last_offset = put7("attr_last", packed_attrs[2])
    bitmap18_offset = put7("bitmap18", packed_bitmaps[0])
    bitmap71_offset = put7("bitmap71", packed_bitmaps[1])
    checkpoints: list[bytes] = data["checkpoints"]  # type: ignore[assignment]
    checkpoint_frames: tuple[int, ...] = data["checkpoint_frames"]  # type: ignore[assignment]
    checkpoint_offsets = [
        put7(f"checkpoint_{frame}", payload)
        for frame, payload in zip(checkpoint_frames, checkpoints)
    ]

    put(pages[5], RENDERER_OFFSET_BANK5, renderer, "renderer")
    put(pages[5], EVENT_RUNS_OFFSET_BANK5, event_runs, "draw event runs")
    put(pages[5], ASSET19_OFFSET_BANK5, packed_bitmaps[2], "bitmap19")
    put(pages[5], 0x1B00, live_ticks, "live visual tick mask")
    attribute_change_mask: bytes = data["attribute_change_mask"]  # type: ignore[assignment]
    put(pages[5], 0x1C75, attribute_change_mask, "attribute change mask")

    # Palette conversion tables occupy the fixed-bank tail after the 6912-byte
    # page-0 background. The original 2 KiB palette resource is not resident.
    fixed_tables = palette_tables + decisions
    put(pages[2], 0x3B00, fixed_tables, "palette conversion tables")

    # IM2 vector 0x5CFF/0x5D00 -> 0x5D10.
    pages[5][0x1CFF] = 0x10
    pages[5][0x1D00] = 0x5D
    pages[5][0x1D10 : 0x1D1C] = bytes(
        (
            0xF5,
            0xE5,
            0x21,
            0x25,
            0x93,
            0x34,
            0xE1,
            0xF1,
            0xFB,
            0xED,
            0x4D,
            0x00,
        )
    )

    layout.update(
        {
            "attr_middle_chunk0": {
                "bank": 1,
                "offset": ATTR_CHUNK0_OFFSET_BANK1,
                "address": 0xC000 + ATTR_CHUNK0_OFFSET_BANK1,
                "bytes": len(chunk0),
            },
            "attr_middle_chunk1_address": 0xC000 + middle_chunk1_offset,
            "attr_first_address": 0xC000 + attr_first_offset,
            "attr_last_address": 0xC000 + attr_last_offset,
            "bitmap18_address": 0xC000 + bitmap18_offset,
            "bitmap71_address": 0xC000 + bitmap71_offset,
            "checkpoint_addresses": [
                0xC000 + offset for offset in checkpoint_offsets
            ],
            "bitmap19": {
                "bank": 5,
                "offset": ASSET19_OFFSET_BANK5,
                "address": 0x4000 + ASSET19_OFFSET_BANK5,
                "bytes": len(packed_bitmaps[2]),
            },
            "renderer_address": 0x4000 + RENDERER_OFFSET_BANK5,
            "draw_event_runs_address": 0x4000 + EVENT_RUNS_OFFSET_BANK5,
            "live_tick_mask_address": 0x5B00,
            "attribute_change_mask_address": 0x5C75,
            "bank7_end_offset": bank7_cursor,
            "palette_tables_address": 0xBB00,
            "decisions_address": 0xBB00 + len(palette_tables),
            "text_address": 0xC000 + TEXT_DATA_OFFSET_BANK1,
        }
    )

    header = bytearray(27)
    header[19] = 4
    header[23:25] = struct.pack("<H", 0xBFF0)
    header[25] = 2
    header[26] = 0
    blob = bytearray(header) + pages[5] + pages[2] + pages[0]
    blob += struct.pack("<HBB", 0x8000, 0x00, 0x00)
    for bank in (1, 3, 4, 6, 7):
        blob += pages[bank]
    if len(blob) != 131103:
        raise AssertionError(len(blob))
    layout["shape_layout"] = shape_layout
    return bytes(blob), layout


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--zxasm",
        type=Path,
        default=Path("/tmp/aw-z80-assembler/node_modules/.bin/zxasm"),
    )
    args = parser.parse_args()
    BUILD.mkdir(parents=True, exist_ok=True)

    entries = base.read_entries()
    bytecode = base.extract_resource(entries, RESOURCE_BYTECODE)
    shapes = base.extract_resource(entries, RESOURCE_SHAPES)
    palette = base.extract_resource(entries, RESOURCE_PALETTE)
    used_palettes = extract_used_palettes()
    palette_tables = spectrum_palette_mapping(palette, used_palettes)
    decisions = spectrum_decision_masks()
    text = compact_text_data()
    live_ticks = live_visual_tick_mask()
    event_runs = draw_event_runs()
    data = make_data()
    write_generated_layout(data)
    vm = base.assemble(args.zxasm, "vm_full.asm")
    renderer = base.assemble(args.zxasm, "renderer_full.asm")
    snapshot, layout = make_snapshot(
        vm,
        renderer,
        bytecode,
        shapes,
        text,
        palette_tables,
        decisions,
        live_ticks,
        event_runs,
        data,
    )

    packed_attrs: list[bytes] = data["packed_attributes"]  # type: ignore[assignment]
    packed_bitmaps: list[bytes] = data["packed_bitmaps"]  # type: ignore[assignment]
    (BUILD / "another-world-vm-full.sna").write_bytes(snapshot)
    (BUILD / "vm-code.bin").write_bytes(vm)
    (BUILD / "renderer-code.bin").write_bytes(renderer)
    (BUILD / "text-data.bin").write_bytes(text)
    (BUILD / "palette-map.bin").write_bytes(palette_tables)
    (BUILD / "spectrum-decisions.bin").write_bytes(decisions)
    (BUILD / "live-visual-ticks.bin").write_bytes(live_ticks)
    (BUILD / "draw-event-runs.bin").write_bytes(event_runs)
    (BUILD / "attribute-change-mask.bin").write_bytes(data["attribute_change_mask"])  # type: ignore[arg-type]
    (BUILD / "runtime-attributes.bin").write_bytes(
        b"".join(data["runtime_attributes"])  # type: ignore[arg-type]
    )
    for index, payload in enumerate(packed_attrs):
        (BUILD / f"attributes-{index}.lzss").write_bytes(payload)
    for resource, payload in zip((18, 71, 19), packed_bitmaps):
        (BUILD / f"bitmap-{resource}.lzss").write_bytes(payload)
    for frame, payload in zip(data["checkpoint_frames"], data["checkpoints"]):  # type: ignore[arg-type]
        (BUILD / f"checkpoint-{frame}.lzss").write_bytes(payload)
        (BUILD / f"checkpoint-{frame}.bitmap").write_bytes(
            lzss.decompress(payload, 6144)
        )

    reference = base.reference_trace()
    resident_payload = (
        len(vm)
        + len(renderer)
        + len(bytecode)
        + len(shapes)
        + len(text)
        + len(palette_tables)
        + len(decisions)
        + len(live_ticks)
        + len(event_runs)
        + len(data["attribute_change_mask"])  # type: ignore[arg-type]
        + sum(map(len, packed_attrs))
        + sum(map(len, packed_bitmaps))
        + sum(
            len(item)
            for item in data["checkpoints"]  # type: ignore[union-attr]
        )
        + 2 * 6912                    # bank 5 / bank 7 physical screens
        + 6912                        # page-0 background
        + 0x0800                      # VM variables, tasks and dirty masks
        + 0x0C00                      # LZ ring, attribute stage and page 3
        + 0x02F1                      # renderer vertex/edge scratch
        + 48                          # interrupt vectors and stack headroom
    )
    manifest = {
        "milestone": "full intro, size-first VM/vector renderer",
        "entry_point": 0x8000,
        "state_addresses": {
            "tick": 0x9300,
            "instruction_count": 0x9302,
            "trace_hash": 0x9304,
            "error_opcode": 0x9306,
            "done": 0x9307,
            "frame_count": 0x9308,
        },
        "reference": reference,
        "sizes": {
            "vm": len(vm),
            "renderer": len(renderer),
            "bytecode": len(bytecode),
            "shapes": len(shapes),
            "text": len(text),
            "palette_conversion": len(palette_tables),
            "decision_masks": len(decisions),
            "live_visual_tick_mask": len(live_ticks),
            "draw_event_runs": len(event_runs),
            "attribute_change_mask": len(data["attribute_change_mask"]),  # type: ignore[arg-type]
            "attribute_streams": [len(item) for item in packed_attrs],
            "bitmap_streams": [len(item) for item in packed_bitmaps],
            "checkpoint_streams": [
                len(item) for item in data["checkpoints"]  # type: ignore[union-attr]
            ],
            "snapshot": len(snapshot),
        },
        "resident_estimate": {
            "used_bytes": resident_payload,
            "aggregate_free_bytes": 128 * 1024 - resident_payload,
            "note": "Free space is fragmented across banks.",
        },
        "used_palettes": used_palettes,
        "layout": layout,
    }
    (BUILD / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
