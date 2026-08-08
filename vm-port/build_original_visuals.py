#!/usr/bin/env python3
"""Build the live full-VM SNA from an exact original indexed capture.

The capture is produced by ``capture_original_colour_preview.mjs --indexed``.
Each sampled presentation contains the visible logical-colour page, logical
page 0, and the active 16-colour RGB palette.  Stable Spectrum PAPER/INK roles
are selected from the *visible* sequence for each page-0 generation; the old
build accidentally selected them from page 0 alone, which badly represented
dynamic scenes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image

import lzss


SNA_BYTES = 131_103
SNA_HEADER_BYTES = 27
BANK_BYTES = 0x4000
FRAMES = 298
SOURCE_WIDTH = 320
SOURCE_HEIGHT = 200
PIXELS = SOURCE_WIDTH * SOURCE_HEIGHT
CAPTURE_RECORD_BYTES = PIXELS * 2 + 16 * 3
PAGE3_CAPTURE_RECORD_BYTES = PIXELS + 16 * 3

RENDERER_OFFSET_BANK5 = 0x1D20
RENDERER_LIMIT_BANK5 = 0x2C80
# The unsafe 4.5 fps event-run stream formerly occupied this area.  The exact
# renderer no longer consumes it, so leave enough headroom for the signed edge
# code and place the compact page-3 snapshots immediately after it.
PAGE3_SNAPSHOT_OFFSET_BANK5 = 0x2C80
PAGE3_SNAPSHOT_LIMIT_BANK5 = 0x3400
ATTR_CHANGE_MASK_OFFSET_BANK5 = 0x1C75
LIVE_TICK_MASK_OFFSET_BANK5 = 0x1B00
BITMAP19_OFFSET_BANK5 = 0x3400
ATTR_CHUNK0_OFFSET_BANK1 = 0x2E00
ATTR_CHUNK0_BYTES = 0x1200
PAGED_DATA_OFFSET_BANK7 = 0x1B00
PALETTE_SLOTS_OFFSET_BANK2 = 0x3B00
PALETTE_MAPS_OFFSET_BANK2 = 0x3B40
PALETTE_SLOT_COUNT = 44

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


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def live_visual_tick_mask(trace_path: Path) -> bytes:
    """Derive retained dynamic draw ticks from resolved semantic page history."""

    histories: list[list[int]] = [[], [], [], []]
    event_ticks: dict[int, int] = {}
    event_pages: dict[int, int] = {}
    live_events: set[int] = set()
    tick = -1
    pending_event: int | None = None
    lines = trace_path.read_text(encoding="utf-8", errors="replace").splitlines()
    for line in lines:
        if line.startswith("TRACE_TICK "):
            tick = int(line.split()[1])
            continue
        if line.startswith("vid_opcd_event "):
            pending_event = int(line.split()[1])
            event_ticks[pending_event] = tick
            match = re.search(r"buffer=(\d+)", line)
            if match:
                page = int(match.group(1))
                event_pages[pending_event] = page
                histories[page].append(pending_event)
            continue
        if line.startswith("Script::op_drawString("):
            # Text event numbers immediately follow the last numbered shape
            # event in the semantic generator. Assign a stable synthetic id.
            pending_event = max(event_ticks, default=0) + 1
            while pending_event in event_ticks:
                pending_event += 1
            event_ticks[pending_event] = tick
            match = re.search(r"buffer=(\d+)", line)
            if match:
                page = int(match.group(1))
                event_pages[pending_event] = page
                histories[page].append(pending_event)
            continue
        match = re.match(r"SEM (?:quadstrip|point|glyph) buffer=(\d+)", line)
        if match and pending_event is not None:
            page = int(match.group(1))
            event_pages.setdefault(pending_event, page)
            if pending_event not in histories[page]:
                histories[page].append(pending_event)
            continue
        match = re.match(r"SEM clear buffer=(\d+)", line)
        if match:
            histories[int(match.group(1))] = []
            pending_event = None
            continue
        match = re.match(r"SEM copy dst=(\d+) src=(\d+)", line)
        if match:
            destination, source = map(int, match.groups())
            histories[destination] = list(histories[source])
            pending_event = None
            continue
        match = re.match(r"SEM present buffer=(\d+)", line)
        if match:
            page = int(match.group(1))
            if tick >= 8 and (tick - 8) % 10 == 0:
                live_events.update(histories[page])
            pending_event = None

    mask = bytearray((2980 + 7) // 8)
    for event in live_events:
        if event_pages.get(event) not in (1, 2):
            continue
        event_tick = event_ticks[event]
        if 0 <= event_tick < 2980:
            mask[event_tick >> 3] |= 1 << (event_tick & 7)
    return bytes(mask)


def bank_offset(bank: int) -> int:
    if bank == 5:
        return SNA_HEADER_BYTES
    if bank == 2:
        return SNA_HEADER_BYTES + BANK_BYTES
    if bank == 0:
        return SNA_HEADER_BYTES + 2 * BANK_BYTES
    return 49_183 + (1, 3, 4, 6, 7).index(bank) * BANK_BYTES


def bank_view(snapshot: bytearray, bank: int) -> memoryview:
    start = bank_offset(bank)
    return memoryview(snapshot)[start : start + BANK_BYTES]


def spectrum_offset(y: int, byte_x: int) -> int:
    return ((y & 0xC0) << 5) | ((y & 7) << 8) | ((y & 0x38) << 2) | byte_x


def load_capture(path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    raw = np.fromfile(path, dtype=np.uint8)
    expected = FRAMES * CAPTURE_RECORD_BYTES
    if raw.size != expected:
        raise RuntimeError(f"indexed capture has {raw.size} bytes, expected {expected}")
    records = raw.reshape(FRAMES, CAPTURE_RECORD_BYTES)
    visible = records[:, :PIXELS].reshape(FRAMES, SOURCE_HEIGHT, SOURCE_WIDTH)
    page0 = records[:, PIXELS : PIXELS * 2].reshape(
        FRAMES, SOURCE_HEIGHT, SOURCE_WIDTH
    )
    palette = records[:, PIXELS * 2 :].reshape(FRAMES, 16, 3).astype(np.int32)
    return visible, page0, palette


def load_page3_capture(path: Path) -> tuple[np.ndarray, np.ndarray]:
    raw = np.fromfile(path, dtype=np.uint8)
    expected = 2 * PAGE3_CAPTURE_RECORD_BYTES
    if raw.size != expected:
        raise RuntimeError(f"page-3 capture has {raw.size} bytes, expected {expected}")
    records = raw.reshape(2, PAGE3_CAPTURE_RECORD_BYTES)
    indexes = records[:, :PIXELS].reshape(2, SOURCE_HEIGHT, SOURCE_WIDTH)
    palettes = records[:, PIXELS:].reshape(2, 16, 3).astype(np.int32)
    return indexes, palettes


def load_palette_ids(path: Path) -> np.ndarray:
    raw = np.fromfile(path, dtype=np.uint8)
    if raw.size != FRAMES:
        raise RuntimeError(f"palette-id capture has {raw.size} bytes, expected {FRAMES}")
    return raw


def resize_indexes(frames: np.ndarray) -> np.ndarray:
    return np.stack(
        [
            np.asarray(
                Image.fromarray(frame).resize((256, 192), Image.Resampling.NEAREST),
                dtype=np.uint8,
            )
            for frame in frames
        ]
    )


def pair_generation(frame_number: int) -> int:
    return max(frame for frame in PAIR_GENERATION_FRAMES if frame <= frame_number)


def visible_pair_maps(visible: np.ndarray) -> dict[int, np.ndarray]:
    """Choose stable logical colour roles from all visible pixels in a scene."""

    frame_numbers = np.arange(1, FRAMES + 1) * 10
    result: dict[int, np.ndarray] = {}
    for generation_index, generation in enumerate(PAIR_GENERATION_FRAMES):
        end = (
            PAIR_GENERATION_FRAMES[generation_index + 1]
            if generation_index + 1 < len(PAIR_GENERATION_FRAMES)
            else 2990
        )
        selected = visible[
            (frame_numbers >= generation) & (frame_numbers < end)
        ]
        cells = (
            selected.reshape(len(selected), 24, 8, 32, 8)
            .transpose(0, 1, 3, 2, 4)
            .reshape(-1, 768, 64)
        )
        counts = np.stack(
            [np.count_nonzero(cells == colour, axis=(0, 2)) for colour in range(16)],
            axis=1,
        )
        paper = np.argmax(counts, axis=1)
        counts[np.arange(768), paper] = -1
        ink = np.argmax(counts, axis=1)
        result[generation] = np.stack((paper, ink), axis=1).astype(np.uint8)
    return result


def best_attribute_tables(palettes: np.ndarray) -> np.ndarray:
    """Return [frame, logical paper, logical ink] -> Spectrum attribute."""

    endpoints = np.stack(
        [
            np.stack(
                (
                    SPECTRUM_PALETTE[((attribute >> 3) & 7) + ((attribute >> 6) & 1) * 8],
                    SPECTRUM_PALETTE[(attribute & 7) + ((attribute >> 6) & 1) * 8],
                )
            )
            for attribute in range(128)
        ]
    )
    paper_error = np.sum(
        (palettes[:, :, None, :] - endpoints[None, None, :, 0, :]) ** 2,
        axis=3,
    )
    ink_error = np.sum(
        (palettes[:, :, None, :] - endpoints[None, None, :, 1, :]) ** 2,
        axis=3,
    )
    return np.argmin(
        paper_error[:, :, None, :] + ink_error[:, None, :, :], axis=3
    ).astype(np.uint8)


def direct_decision_data(
    palettes: np.ndarray, palette_ids: np.ndarray
) -> tuple[bytes, bytes, bytes]:
    """Build exact logical-colour -> PAPER/INK rows for every used palette.

    The previous snapshot first quantised a logical colour to one Spectrum
    colour and only then chose the nearer endpoint of the active attribute.
    That stale two-step table disagreed with the newly generated attributes
    and turned dense scenes into multicolour overdraw.  Packed rows are
    deduplicated; the fixed PALETTE_MAPS area stores their byte indices.
    """

    endpoints = np.stack(
        [
            np.stack(
                (
                    SPECTRUM_PALETTE[
                        ((attribute >> 3) & 7) + ((attribute >> 6) & 1) * 8
                    ],
                    SPECTRUM_PALETTE[
                        (attribute & 7) + ((attribute >> 6) & 1) * 8
                    ],
                )
            )
            for attribute in range(128)
        ]
    )
    palette_by_id: dict[int, np.ndarray] = {}
    for frame_index, palette_id_value in enumerate(palette_ids):
        palette_id = int(palette_id_value)
        if palette_id in palette_by_id:
            if not np.array_equal(palette_by_id[palette_id], palettes[frame_index]):
                raise RuntimeError(f"palette {palette_id} changed RGB values")
        else:
            palette_by_id[palette_id] = palettes[frame_index]

    used_palette_ids = sorted(palette_by_id)
    if len(used_palette_ids) > PALETTE_SLOT_COUNT:
        raise RuntimeError(
            f"{len(used_palette_ids)} used palettes exceed {PALETTE_SLOT_COUNT} slots"
        )
    slots = bytearray([0xFF] * 64)
    for slot, palette_id in enumerate(used_palette_ids):
        if palette_id >= len(slots):
            raise RuntimeError(f"palette id {palette_id} is outside PALETTE_SLOTS")
        slots[palette_id] = slot

    rows: list[bytes] = []
    row_index: dict[bytes, int] = {}
    maps = bytearray(PALETTE_SLOT_COUNT * 16)
    for palette_id, palette in sorted(palette_by_id.items()):
        slot = slots[palette_id]
        for colour, source_rgb in enumerate(palette):
            paper_error = np.sum((endpoints[:, 0] - source_rgb) ** 2, axis=1)
            ink_error = np.sum((endpoints[:, 1] - source_rgb) ** 2, axis=1)
            packed = np.packbits(ink_error < paper_error, bitorder="little").tobytes()
            if packed not in row_index:
                if len(rows) >= 256:
                    raise RuntimeError("direct decision rows exceed byte index")
                row_index[packed] = len(rows)
                rows.append(packed)
            maps[slot * 16 + colour] = row_index[packed]
    return bytes(slots), bytes(maps), b"".join(rows)


def runtime_attributes(
    palettes: np.ndarray, pair_maps: dict[int, np.ndarray]
) -> list[bytes]:
    tables = best_attribute_tables(palettes)
    output: list[bytes] = []
    for frame_index in range(FRAMES):
        pairs = pair_maps[pair_generation((frame_index + 1) * 10)]
        attributes = tables[frame_index, pairs[:, 0], pairs[:, 1]]
        output.append(attributes.tobytes())
    return output


def choose_runs(frames: list[bytes]) -> tuple[list[bytes], list[int]]:
    maps: list[bytes] = []
    indices: list[int] = []
    previous: bytes | None = None
    for frame in frames:
        if frame != previous:
            maps.append(frame)
            previous = frame
        indices.append(len(maps) - 1)
    return maps, indices


def encode_screen(indexes: np.ndarray, palette: np.ndarray, attributes: bytes) -> bytes:
    attr = np.frombuffer(attributes, dtype=np.uint8).reshape(24, 32)
    bright = (attr >> 6) & 1
    ink = (attr & 7) + bright * 8
    paper = ((attr >> 3) & 7) + bright * 8
    ink_rgb = np.repeat(np.repeat(SPECTRUM_PALETTE[ink], 8, axis=0), 8, axis=1)
    paper_rgb = np.repeat(
        np.repeat(SPECTRUM_PALETTE[paper], 8, axis=0), 8, axis=1
    )
    source_rgb = palette[indexes]
    bits = np.sum((source_rgb - ink_rgb) ** 2, axis=2) < np.sum(
        (source_rgb - paper_rgb) ** 2, axis=2
    )
    output = bytearray(6912)
    output[6144:] = attributes
    for y in range(192):
        for byte_x in range(32):
            value = 0
            for bit in bits[y, byte_x * 8 : byte_x * 8 + 8]:
                value = (value << 1) | int(bit)
            output[spectrum_offset(y, byte_x)] = value
    return bytes(output)


def build_visual_data(
    visible: np.ndarray,
    page0: np.ndarray,
    palettes: np.ndarray,
    page3_snapshots: np.ndarray,
    page3_palettes: np.ndarray,
    palette_ids: np.ndarray,
) -> dict[str, object]:
    pairs = visible_pair_maps(visible)
    attributes = runtime_attributes(palettes, pairs)
    exact_groups = (attributes[:5], attributes[5:294], attributes[294:])
    map_groups: list[list[bytes]] = []
    group_indices: list[list[int]] = []
    for group in exact_groups:
        maps, indices = choose_runs(group)
        map_groups.append(maps)
        group_indices.append(indices)
    packed_attributes = [lzss.compress(b"".join(group)) for group in map_groups]

    change_mask = bytearray((FRAMES + 7) // 8)
    global_index = 0
    for indices in group_indices:
        for local_index, map_index in enumerate(indices):
            if local_index and map_index != indices[local_index - 1]:
                change_mask[global_index >> 3] |= 1 << (global_index & 7)
            global_index += 1

    bitmap_frames = (10, 60, 2950)
    bitmaps = [
        encode_screen(
            page0[frame // 10 - 1],
            palettes[frame // 10 - 1],
            attributes[frame // 10 - 1],
        )
        for frame in bitmap_frames
    ]
    packed_bitmaps = [lzss.compress(bitmap) for bitmap in bitmaps]

    checkpoint_frames = (200, 310, 410, 1060, 2220)
    checkpoints = [
        lzss.compress(
            encode_screen(
                page0[frame // 10 - 1],
                palettes[frame // 10 - 1],
                attributes[frame // 10 - 1],
            )[:6144]
        )
        for frame in checkpoint_frames
    ]

    # Page 3 receives true page-0 snapshots at VM ticks 1597 and 1712.  The
    # compact VM used to retain only a "base is page 0" marker, so later page-0
    # changes corrupted every copy back from page 3.  Attributes last advanced
    # at sampled presentations 159 and 171 respectively.
    page3_attribute_indices = (158, 170)
    packed_page3_snapshots = [
        lzss.compress(
            encode_screen(
                page3_snapshots[index],
                page3_palettes[index],
                attributes[attribute_index],
            )[:6144]
        )
        for index, attribute_index in enumerate(page3_attribute_indices)
    ]

    references = [
        encode_screen(visible[index], palettes[index], attributes[index])
        for index in range(FRAMES)
    ]
    palette_slots, palette_maps, decision_rows = direct_decision_data(
        palettes, palette_ids
    )
    return {
        "pair_maps": pairs,
        "attributes": attributes,
        "attribute_groups": map_groups,
        "attribute_group_indices": group_indices,
        "packed_attributes": packed_attributes,
        "attribute_change_mask": bytes(change_mask),
        "bitmap_frames": bitmap_frames,
        "packed_bitmaps": packed_bitmaps,
        "checkpoint_frames": checkpoint_frames,
        "checkpoints": checkpoints,
        "packed_page3_snapshots": packed_page3_snapshots,
        "palette_slots": palette_slots,
        "palette_maps": palette_maps,
        "direct_decision_rows": decision_rows,
        "references": references,
    }


def pack_bank7(data: dict[str, object]) -> tuple[bytes, dict[str, int]]:
    packed_attributes: list[bytes] = data["packed_attributes"]  # type: ignore[assignment]
    packed_bitmaps: list[bytes] = data["packed_bitmaps"]  # type: ignore[assignment]
    checkpoints: list[bytes] = data["checkpoints"]  # type: ignore[assignment]
    direct_decision_rows: bytes = data["direct_decision_rows"]  # type: ignore[assignment]
    middle_tail = packed_attributes[1][ATTR_CHUNK0_BYTES:]
    payloads = (
        ("ATTR_MIDDLE_CHUNK1", middle_tail),
        ("ATTR_FIRST", packed_attributes[0]),
        ("ATTR_LAST", packed_attributes[2]),
        ("BITMAP18", packed_bitmaps[0]),
        ("BITMAP71", packed_bitmaps[1]),
        *((f"CHECKPOINT{index}", item) for index, item in enumerate(checkpoints)),
        ("DIRECT_DECISION_ROWS", direct_decision_rows),
    )
    cursor = PAGED_DATA_OFFSET_BANK7
    addresses: dict[str, int] = {}
    output = bytearray()
    for name, payload in payloads:
        addresses[name] = 0xC000 + cursor
        output += payload
        cursor += len(payload)
    if cursor > BANK_BYTES:
        raise RuntimeError(f"bank 7 visual payload exceeds bank by {cursor - BANK_BYTES} bytes")
    return bytes(output), addresses


def pack_page3_snapshots(data: dict[str, object]) -> tuple[bytes, dict[str, int]]:
    snapshots: list[bytes] = data["packed_page3_snapshots"]  # type: ignore[assignment]
    payload = bytearray()
    addresses: dict[str, int] = {}
    cursor = PAGE3_SNAPSHOT_OFFSET_BANK5
    for index, snapshot in enumerate(snapshots):
        addresses[f"PAGE3_SNAPSHOT{index}"] = 0x4000 + cursor
        payload += snapshot
        cursor += len(snapshot)
    if cursor > PAGE3_SNAPSHOT_LIMIT_BANK5:
        raise RuntimeError(
            f"page-3 snapshots exceed fixed-bank slot by "
            f"{cursor - PAGE3_SNAPSHOT_LIMIT_BANK5} bytes"
        )
    return bytes(payload), addresses


def write_layout(path: Path, addresses: dict[str, int]) -> None:
    lines = [
        "; Generated by build_original_visuals.py; do not hand-edit.",
        *(f"{name:<24} EQU 0x{address:04X}" for name, address in addresses.items()),
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def assemble_renderer(
    renderer_source: Path,
    addresses: dict[str, int],
    sjasmplus: Path,
    work: Path,
) -> bytes:
    source = work / "renderer-original-visuals.asm"
    shutil.copy2(renderer_source, source)
    write_layout(work / "generated_full_layout.inc", addresses)
    binary = work / "renderer-original-visuals.bin"
    subprocess.run(
        [str(sjasmplus), f"--raw={binary.resolve()}", source.name],
        cwd=work,
        check=True,
    )
    renderer = binary.read_bytes()
    if RENDERER_OFFSET_BANK5 + len(renderer) > RENDERER_LIMIT_BANK5:
        raise RuntimeError(
            f"renderer overlaps event data by "
            f"{RENDERER_OFFSET_BANK5 + len(renderer) - RENDERER_LIMIT_BANK5} bytes"
        )
    return renderer


def assemble_vm(vm_source: Path, sjasmplus: Path, work: Path) -> bytes:
    source = work / "vm-original-visuals.asm"
    text = vm_source.read_text(encoding="utf-8")
    # sjasmplus requires local labels at column zero; archived sources may
    # contain harmless indentation from earlier generated patches.
    import re

    text = re.sub(r"(?m)^\s+(\.[A-Za-z_][A-Za-z0-9_]*:)\s*$", r"\1", text)
    source.write_text(text, encoding="utf-8")
    binary = work / "vm-original-visuals.bin"
    subprocess.run(
        [str(sjasmplus), f"--raw={binary.resolve()}", source.name],
        cwd=work,
        check=True,
    )
    vm = binary.read_bytes()
    if len(vm) > 0x1000:
        raise RuntimeError(f"VM code overlaps state by {len(vm) - 0x1000} bytes")
    return vm


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--indexed-capture", type=Path, required=True)
    parser.add_argument("--page3-capture", type=Path, required=True)
    parser.add_argument("--palette-ids", type=Path, required=True)
    parser.add_argument("--trace", type=Path)
    parser.add_argument("--base-sna", type=Path, required=True)
    parser.add_argument(
        "--renderer",
        type=Path,
        default=Path(__file__).with_name("renderer_full.asm"),
    )
    parser.add_argument("--sjasmplus", type=Path, required=True)
    parser.add_argument(
        "--vm", type=Path, default=Path(__file__).with_name("vm_full.asm")
    )
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    output = args.out.resolve()
    work = output / "work"
    shutil.rmtree(output, ignore_errors=True)
    work.mkdir(parents=True)

    base = args.base_sna.resolve().read_bytes()
    if len(base) != SNA_BYTES:
        raise RuntimeError(f"unexpected base SNA size: {len(base)}")
    visible_source, page0_source, palettes = load_capture(
        args.indexed_capture.resolve()
    )
    page3_source, page3_palettes = load_page3_capture(args.page3_capture.resolve())
    palette_ids = load_palette_ids(args.palette_ids.resolve())
    visible = resize_indexes(visible_source)
    page0 = resize_indexes(page0_source)
    page3_snapshots = resize_indexes(page3_source)
    data = build_visual_data(
        visible,
        page0,
        palettes,
        page3_snapshots,
        page3_palettes,
        palette_ids,
    )
    bank7_payload, addresses = pack_bank7(data)
    page3_payload, page3_addresses = pack_page3_snapshots(data)
    addresses.update(page3_addresses)
    renderer = assemble_renderer(
        args.renderer.resolve(), addresses, args.sjasmplus.resolve(), work
    )
    vm = assemble_vm(args.vm.resolve(), args.sjasmplus.resolve(), work)

    packed_attributes: list[bytes] = data["packed_attributes"]  # type: ignore[assignment]
    packed_bitmaps: list[bytes] = data["packed_bitmaps"]  # type: ignore[assignment]
    snapshot = bytearray(base)
    bank2 = bank_view(snapshot, 2)
    bank2[:0x1000] = bytes(0x1000)
    bank2[: len(vm)] = vm
    palette_slots: bytes = data["palette_slots"]  # type: ignore[assignment]
    bank2[
        PALETTE_SLOTS_OFFSET_BANK2 : PALETTE_SLOTS_OFFSET_BANK2 + len(palette_slots)
    ] = palette_slots
    palette_maps: bytes = data["palette_maps"]  # type: ignore[assignment]
    bank2[
        PALETTE_MAPS_OFFSET_BANK2 : PALETTE_MAPS_OFFSET_BANK2 + len(palette_maps)
    ] = palette_maps
    bank1 = bank_view(snapshot, 1)
    bank1[ATTR_CHUNK0_OFFSET_BANK1:] = bytes(BANK_BYTES - ATTR_CHUNK0_OFFSET_BANK1)
    bank1[ATTR_CHUNK0_OFFSET_BANK1:] = packed_attributes[1][:ATTR_CHUNK0_BYTES]
    bank7 = bank_view(snapshot, 7)
    bank7[PAGED_DATA_OFFSET_BANK7:] = bytes(BANK_BYTES - PAGED_DATA_OFFSET_BANK7)
    bank7[PAGED_DATA_OFFSET_BANK7 : PAGED_DATA_OFFSET_BANK7 + len(bank7_payload)] = (
        bank7_payload
    )
    bank5 = bank_view(snapshot, 5)
    if args.trace is not None:
        live_mask = live_visual_tick_mask(args.trace.resolve())
        bank5[
            LIVE_TICK_MASK_OFFSET_BANK5 : LIVE_TICK_MASK_OFFSET_BANK5 + len(live_mask)
        ] = live_mask
    bank5[PAGE3_SNAPSHOT_OFFSET_BANK5:PAGE3_SNAPSHOT_LIMIT_BANK5] = bytes(
        PAGE3_SNAPSHOT_LIMIT_BANK5 - PAGE3_SNAPSHOT_OFFSET_BANK5
    )
    bank5[
        PAGE3_SNAPSHOT_OFFSET_BANK5 : PAGE3_SNAPSHOT_OFFSET_BANK5
        + len(page3_payload)
    ] = page3_payload
    bank5[BITMAP19_OFFSET_BANK5:] = bytes(BANK_BYTES - BITMAP19_OFFSET_BANK5)
    bank5[
        BITMAP19_OFFSET_BANK5 : BITMAP19_OFFSET_BANK5 + len(packed_bitmaps[2])
    ] = packed_bitmaps[2]
    change_mask: bytes = data["attribute_change_mask"]  # type: ignore[assignment]
    bank5[
        ATTR_CHANGE_MASK_OFFSET_BANK5 : ATTR_CHANGE_MASK_OFFSET_BANK5
        + len(change_mask)
    ] = change_mask
    bank5[RENDERER_OFFSET_BANK5:RENDERER_LIMIT_BANK5] = bytes(
        RENDERER_LIMIT_BANK5 - RENDERER_OFFSET_BANK5
    )
    bank5[RENDERER_OFFSET_BANK5 : RENDERER_OFFSET_BANK5 + len(renderer)] = renderer

    snapshot_path = output / "another-world-original-render-fixed.sna"
    snapshot_path.write_bytes(snapshot)
    reference_dir = output / "reference-screens"
    reference_dir.mkdir()
    references: list[bytes] = data["references"]  # type: ignore[assignment]
    for index, screen in enumerate(references, 1):
        (reference_dir / f"frame-{index:03d}.scr").write_bytes(screen)

    manifest = {
        "kind": "live full VM renderer with visible-sequence colour roles",
        "base_sna": args.base_sna.name,
        "base_sha256": sha256(base),
        "indexed_capture_sha256": sha256(args.indexed_capture.read_bytes()),
        "page3_capture_sha256": sha256(args.page3_capture.read_bytes()),
        "palette_ids_sha256": sha256(args.palette_ids.read_bytes()),
        "snapshot_bytes": len(snapshot),
        "snapshot_sha256": sha256(snapshot),
        "renderer_bytes": len(renderer),
        "vm_bytes": len(vm),
        "attribute_distinct_maps": [
            len(group) for group in data["attribute_groups"]  # type: ignore[union-attr]
        ],
        "attribute_stream_bytes": [len(item) for item in packed_attributes],
        "bitmap_stream_bytes": [len(item) for item in packed_bitmaps],
        "checkpoint_stream_bytes": [
            len(item) for item in data["checkpoints"]  # type: ignore[union-attr]
        ],
        "page3_snapshot_stream_bytes": [
            len(item)
            for item in data["packed_page3_snapshots"]  # type: ignore[union-attr]
        ],
        "page3_snapshot_fixed_bank_bytes": len(page3_payload),
        "direct_decision_rows": len(data["direct_decision_rows"]) // 16,  # type: ignore[arg-type]
        "direct_decision_bytes": len(data["direct_decision_rows"]),  # type: ignore[arg-type]
        "bank7_payload_bytes": len(bank7_payload),
        "bank7_free_bytes": BANK_BYTES - PAGED_DATA_OFFSET_BANK7 - len(bank7_payload),
        "layout": addresses,
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
