#!/usr/bin/env python3
"""Assemble the double-buffered actor test and package a 128K SNA."""
from __future__ import annotations

import argparse
import hashlib
import json
import runpy
import struct
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HERE = Path(__file__).resolve().parent
BANK_BYTES = 0x4000
SCREEN_BYTES = 6912
SNA_BYTES = 131_103
STATUS = {
    "magic": 0x9F00,
    "frames": 0x9F04,
    "scene": 0x9F06,
    "missed": 0x9F07,
    "render_irq_max": 0x9F08,
    "screen_bit": 0x9F09,
    "irq": 0x9F0A,
    "position": 0x9F0B,
    "animation": 0x9F0D,
    "transitions": 0x9F0E,
}


def spectrum_address(base: int, y: int) -> int:
    return base + ((y & 0xC0) << 5) + ((y & 7) << 8) + ((y & 0x38) << 2)


BACKGROUND_PLACEMENTS = ((3, 0), (3, SCREEN_BYTES), (4, 0))
LESTER_REGIONS = ((0, 0, BANK_BYTES), (6, 0, BANK_BYTES))
BUDDY_REGIONS = (
    (1, 0, BANK_BYTES),
    (4, SCREEN_BYTES, BANK_BYTES),
    (3, SCREEN_BYTES * 2, BANK_BYTES),
)


def pack_actor_frames(
    pages: list[bytearray],
    frames: list[bytes],
    frame_bytes: int,
    regions: tuple[tuple[int, int, int], ...],
    label: str,
) -> tuple[list[tuple[int, int]], dict[int, int]]:
    placements: list[tuple[int, int]] = []
    used: dict[int, int] = {}
    region_index = 0
    bank, cursor, end = regions[region_index]
    for pose, blob in enumerate(frames):
        if len(blob) != frame_bytes * 4:
            raise RuntimeError(
                f"{label} pose {pose} has {len(blob)} bytes, expected {frame_bytes * 4}"
            )
        for shift in range(4):
            if cursor + frame_bytes > end:
                region_index += 1
                if region_index >= len(regions):
                    raise RuntimeError(f"{label} frames exceed allocated 128K pages")
                bank, cursor, end = regions[region_index]
            payload = blob[shift * frame_bytes : (shift + 1) * frame_bytes]
            put(pages[bank], cursor, payload, f"{label} pose {pose} shift {shift}")
            placements.append((bank, 0xC000 + cursor))
            cursor += frame_bytes
            used[bank] = max(used.get(bank, 0), cursor)
    return placements, used


def pack_assets(
    assets: dict[str, object],
) -> tuple[list[bytearray], dict[str, list[tuple[int, int]]], dict[str, object]]:
    pages = [bytearray(BANK_BYTES) for _ in range(8)]
    runtime_indexes: list[int] = assets["RUNTIME_BACKGROUND_INDICES"]
    screens: list[bytes] = assets["BACKGROUND_SCREENS"]
    runtime_screens = [screens[index] for index in runtime_indexes]
    if len(runtime_screens) != 3:
        raise RuntimeError(f"expected three runtime backgrounds, got {len(runtime_screens)}")
    for index, (screen, (bank, offset)) in enumerate(zip(runtime_screens, BACKGROUND_PLACEMENTS)):
        if len(screen) != SCREEN_BYTES:
            raise RuntimeError(f"background {index} has {len(screen)} bytes")
        put(pages[bank], offset, screen, f"background {index} bank {bank}")
    put(pages[5], 0, runtime_screens[0], "initial screen 5")
    put(pages[7], 0, runtime_screens[0], "initial screen 7")

    lester_layout = assets["LESTER_LAYOUT"]
    buddy_layout = assets["BUDDY_LAYOUT"]
    lester_frame_bytes = int(lester_layout["height"]) * int(lester_layout["bytes_per_row"])
    buddy_frame_bytes = int(buddy_layout["height"]) * int(buddy_layout["bytes_per_row"])
    lester_pointers, lester_used = pack_actor_frames(
        pages,
        assets["LESTER_FRAME_BLOBS"],
        lester_frame_bytes,
        LESTER_REGIONS,
        "Lester",
    )
    buddy_pointers, buddy_used = pack_actor_frames(
        pages,
        assets["BUDDY_FRAME_BLOBS"],
        buddy_frame_bytes,
        BUDDY_REGIONS,
        "Buddy",
    )
    layout = {
        "backgrounds": [
            {"bank": bank, "offset": offset, "bytes": SCREEN_BYTES}
            for bank, offset in BACKGROUND_PLACEMENTS
        ],
        "lester_actor_bytes": sum(len(frame) for frame in assets["LESTER_FRAME_BLOBS"]),
        "buddy_actor_bytes": sum(len(frame) for frame in assets["BUDDY_FRAME_BLOBS"]),
        "lester_bank_high_water": lester_used,
        "buddy_bank_high_water": buddy_used,
        "screen_banks": [5, 7],
    }
    return pages, {"lester": lester_pointers, "buddy": buddy_pointers}, layout


def build_choreography(assets: dict[str, object]) -> list[tuple[int, int, int, int]]:
    lester: dict[str, tuple[int, ...]] = assets["LESTER_SEQUENCES"]
    buddy: dict[str, tuple[int, ...]] = assets["BUDDY_SEQUENCES"]
    lester_offsets: list[int] = assets["LESTER_X_OFFSETS"]
    buddy_offsets: list[int] = assets["BUDDY_X_OFFSETS"]
    rows: list[tuple[int, int, int, int]] = []

    def append(base_x: int, lester_pose: int, buddy_pose: int) -> None:
        lester_x = base_x + lester_offsets[lester_pose]
        buddy_x = base_x - 32 + buddy_offsets[buddy_pose]
        if not (0 <= lester_x <= 216 and 0 <= buddy_x <= 216):
            raise RuntimeError(
                f"choreography position out of range: {lester_x}, {buddy_x} at base {base_x}"
            )
        rows.append((lester_x, buddy_x, lester_pose, buddy_pose))

    for index, x in enumerate(range(64, 201, 2)):
        append(x, lester["run_right"][index % 10], buddy["run_right"][index % 10])
    for pose in lester["stop_right"]:
        append(200, pose, buddy["idle_right"][0])
        append(200, pose, buddy["idle_right"][0])
    buddy_turn_left = (buddy["idle_right"][0], buddy["turn"][0], buddy["idle_left"][0])
    for lester_pose, buddy_pose in zip(lester["turn_left"], buddy_turn_left):
        append(200, lester_pose, buddy_pose)
        append(200, lester_pose, buddy_pose)
    for index, x in enumerate(range(200, 63, -2)):
        append(x, lester["run_left"][index % 10], buddy["run_left"][index % 10])
    for pose in lester["stop_left"]:
        append(64, pose, buddy["idle_left"][0])
        append(64, pose, buddy["idle_left"][0])
    buddy_turn_right = (buddy["turn"][0], buddy["idle_right"][0])
    for lester_pose, buddy_pose in zip(lester["turn_right"], buddy_turn_right):
        append(64, lester_pose, buddy_pose)
        append(64, lester_pose, buddy_pose)
    if len(rows) >= 256:
        raise RuntimeError(f"choreography has {len(rows)} rows; byte index would overflow")
    max_dirty_bytes = max(
        max(lester_x // 8 + 5, buddy_x // 8 + 5)
        - min(lester_x // 8, buddy_x // 8)
        for lester_x, buddy_x, _, _ in rows
    )
    if max_dirty_bytes > 10:
        raise RuntimeError(
            f"choreography needs a {max_dirty_bytes}-byte dirty span; compositor has 10"
        )
    return rows


def write_generated_includes(
    assets: dict[str, object],
    pointers: dict[str, list[tuple[int, int]]],
    choreography: list[tuple[int, int, int, int]],
) -> dict[str, int]:
    lester = assets["LESTER_LAYOUT"]
    buddy = assets["BUDDY_LAYOUT"]
    shifts = assets["SHIFT_PIXELS"]
    if shifts != (0, 2, 4, 6):
        raise RuntimeError(f"unsupported shift set {shifts!r}")
    baseline = 176
    lester_y = baseline - int(lester["anchor_y"])
    buddy_y = baseline - int(buddy["anchor_y"])
    dirty_top = min(lester_y, buddy_y)
    dirty_bottom = max(lester_y + int(lester["height"]), buddy_y + int(buddy["height"]))
    dirty_height = dirty_bottom - dirty_top
    lester_frame_bytes = int(lester["height"]) * int(lester["bytes_per_row"])
    buddy_frame_bytes = int(buddy["height"]) * int(buddy["bytes_per_row"])
    if len(pointers["lester"]) != len(assets["LESTER_FRAME_BLOBS"]) * 4:
        raise RuntimeError("Lester pointer layout mismatch")
    if len(pointers["buddy"]) != len(assets["BUDDY_FRAME_BLOBS"]) * 4:
        raise RuntimeError("Buddy pointer layout mismatch")

    constants = {
        "LESTER_HEIGHT": int(lester["height"]),
        "LESTER_STRIDE": int(lester["bytes_per_row"]),
        "LESTER_FRAME_BYTES": lester_frame_bytes,
        "LESTER_Y": lester_y,
        "BUDDY_HEIGHT": int(buddy["height"]),
        "BUDDY_STRIDE": int(buddy["bytes_per_row"]),
        "BUDDY_FRAME_BYTES": buddy_frame_bytes,
        "BUDDY_Y": buddy_y,
        "DIRTY_TOP": dirty_top,
        "DIRTY_HEIGHT": dirty_height,
        "CHOREOGRAPHY_LENGTH": len(choreography),
    }
    lines = [
        "; Generated by build_sna.py; do not hand-edit.",
        *(f"{name:<24} EQU {value}" for name, value in constants.items()),
        "",
        "scene_sources:",
    ]
    for bank, offset in BACKGROUND_PLACEMENTS:
        lines.append(f"        db {bank}")
        lines.append(f"        dw 0x{0xC000 + offset:04X}")
    lines += ["", "lester_pointers:"]
    for bank, address in pointers["lester"]:
        lines.append(f"        db {bank}")
        lines.append(f"        dw 0x{address:04X}")
    lines += ["", "buddy_pointers:"]
    for bank, address in pointers["buddy"]:
        lines.append(f"        db {bank}")
        lines.append(f"        dw 0x{address:04X}")
    lines += ["", "choreography:"]
    for lester_x, buddy_x, lester_pose, buddy_pose in choreography:
        lines.append(f"        db {lester_x},{buddy_x},{lester_pose},{buddy_pose}")
    lines.append("")
    (HERE / "generated_layout.inc").write_text("\n".join(lines), encoding="utf-8")

    row_lines = ["; Generated by build_sna.py; do not hand-edit.", "ROW_TABLE5:"]
    for y in range(192):
        row_lines.append(f"        dw 0x{spectrum_address(0x4000, y):04X}")
    row_lines.append("ROW_TABLE7:")
    for y in range(192):
        row_lines.append(f"        dw 0x{spectrum_address(0xC000, y):04X}")
    row_lines.append("")
    (HERE / "generated_rows.inc").write_text("\n".join(row_lines), encoding="utf-8")
    return constants


def put(page: bytearray, offset: int, payload: bytes, label: str) -> None:
    if offset < 0 or offset + len(payload) > len(page):
        raise RuntimeError(f"{label} does not fit bank: {offset:#x}+{len(payload):#x}")
    page[offset : offset + len(payload)] = payload


def make_snapshot(code: bytes, pages: list[bytearray]) -> bytes:
    put(pages[2], 0, code, "fixed code")

    header = bytearray(27)
    header[19] = 4
    header[23:25] = struct.pack("<H", 0xBFF0)
    header[25] = 1
    header[26] = 0
    blob = bytearray(header) + pages[5] + pages[2] + pages[0]
    blob += struct.pack("<HBB", 0x8000, 0x00, 0x00)
    for bank in (1, 3, 4, 6, 7):
        blob += pages[bank]
    if len(blob) != SNA_BYTES:
        raise AssertionError(len(blob))
    return bytes(blob)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--sjasmplus", type=Path, default=ROOT / "vendor" / "sjasmplus" / "sjasmplus"
    )
    parser.add_argument("--out", type=Path, default=ROOT / "build" / "sprite-eval-runtime")
    args = parser.parse_args()
    if not (HERE / "generated_assets.py").is_file():
        raise RuntimeError("generated_assets.py is missing; run build_assets.py first")
    if not args.sjasmplus.is_file():
        raise RuntimeError(f"sjasmplus not found: {args.sjasmplus}")
    assets = runpy.run_path(str(HERE / "generated_assets.py"))
    pages, pointers, layout = pack_assets(assets)
    choreography = build_choreography(assets)
    constants = write_generated_includes(assets, pointers, choreography)
    args.out.mkdir(parents=True, exist_ok=True)
    binary = args.out / "sprite-eval-code.bin"
    symbols = args.out / "sprite-eval.sym"
    result = subprocess.run(
        [
            str(args.sjasmplus.resolve()),
            f"--raw={binary.resolve()}",
            f"--sym={symbols.resolve()}",
            "sprite_eval.asm",
        ],
        cwd=HERE,
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"sjasmplus failed\n{result.stdout}\n{result.stderr}")
    code = binary.read_bytes()
    if len(code) > BANK_BYTES:
        raise RuntimeError(f"fixed code image is {len(code)} bytes")
    snapshot = make_snapshot(code, pages)
    layout["bank2_code_bytes"] = len(code)
    sna = args.out / "another-world-gameplay-gaits-25fps.sna"
    sna.write_bytes(snapshot)
    names: list[str] = assets["BACKGROUND_NAMES"]
    runtime_indexes: list[int] = assets["RUNTIME_BACKGROUND_INDICES"]
    manifest = {
        "implementation": "saved-under double buffer + pre-shifted XOR sprites",
        "target": "ZX Spectrum 128K stock 3.5469 MHz",
        "presentation_fps": 25,
        "spectrum_refresh_hz": 50,
        "backgrounds_in_contact_sheet": len(names),
        "runtime_backgrounds": [names[index] for index in runtime_indexes],
        "actor_frames": {
            "lester": len(assets["LESTER_FRAME_BLOBS"]),
            "buddy": len(assets["BUDDY_FRAME_BLOBS"]),
        },
        "motion_sequences": {
            "lester": assets["LESTER_SEQUENCES"],
            "buddy": assets["BUDDY_SEQUENCES"],
        },
        "choreography_frames": len(choreography),
        "actor_x_shifts": list(assets["SHIFT_PIXELS"]),
        "status_addresses": STATUS,
        "constants": constants,
        "layout": layout,
        "snapshot_bytes": len(snapshot),
        "snapshot_sha256": hashlib.sha256(snapshot).hexdigest(),
    }
    (args.out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    (HERE / "artifacts" / "runtime-manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "sna": str(sna),
                "sha256": manifest["snapshot_sha256"],
                "code_bytes": len(code),
                "choreography_frames": len(choreography),
                "lester_actor_bytes": layout["lester_actor_bytes"],
                "buddy_actor_bytes": layout["buddy_actor_bytes"],
            }
        )
    )


if __name__ == "__main__":
    main()
