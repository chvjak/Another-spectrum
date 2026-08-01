#!/usr/bin/env python3
"""Build the live EGA/row-fill renderer with the real visual asset pack.

The historical EGA benchmark used neutral bitmap/attribute streams and put its
deep-child table at bank 7:$E000.  The real visual streams occupy that region.
This builder keeps their original layout, moves bitmap resource 19 eight bytes
down, and places the relocated deep-child table in the resulting bank-5 tail.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import struct
import subprocess
from pathlib import Path


SNA_HEADER = 27
BANK_SIZE = 0x4000
RENDERER_OFFSET_BANK5 = 0x1D20
EVENT_RUNS_OFFSET_BANK5 = 0x2C00
DROP_LIST_OFFSET_BANK5 = 0x1C9B
DROP_LIST_CAPACITY = 0x1CFF - DROP_LIST_OFFSET_BANK5
OLD_BITMAP19_OFFSET = 0x3400
NEW_BITMAP19_OFFSET = 0x33F8
DEEP_OFFSET_BANK5 = 0x3AC3
OLD_DEEP_ADDRESS = 0xE000
NEW_DEEP_ADDRESS = 0xC000 + DEEP_OFFSET_BANK5
DEEP_STREAM_BYTES = 440
DEEP_TABLE_BYTES = 660
COORDINATE_TABLE_OFFSET_BANK2 = 0x3800
COORDINATE_TABLE_BYTES = 520


def bank_offset(bank: int) -> int:
    if bank == 5:
        return SNA_HEADER
    if bank == 2:
        return SNA_HEADER + BANK_SIZE
    if bank == 0:
        return SNA_HEADER + 2 * BANK_SIZE
    return 49183 + [1, 3, 4, 6, 7].index(bank) * BANK_SIZE


def inject(snapshot: bytearray, bank: int, offset: int, payload: bytes) -> None:
    if offset < 0 or offset + len(payload) > BANK_SIZE:
        raise RuntimeError(f"bank {bank} overflow: {offset:#x}+{len(payload):#x}")
    start = bank_offset(bank) + offset
    snapshot[start : start + len(payload)] = payload


def assemble(sjasmplus: Path, source: Path, output: Path) -> bytes:
    subprocess.run(
        [str(sjasmplus), f"--raw={output.resolve()}", source.name],
        cwd=source.parent,
        check=True,
    )
    return output.read_bytes()


def relocate_deep_blob(blob: bytes) -> bytes:
    if len(blob) != 1341:
        raise RuntimeError(f"unexpected deep-child size: {len(blob)}")
    out = bytearray(blob)
    table = DEEP_STREAM_BYTES
    delta = NEW_DEEP_ADDRESS - OLD_DEEP_ADDRESS
    for offset in range(table, table + DEEP_TABLE_BYTES, 2):
        value = struct.unpack_from("<H", out, offset)[0]
        if value:
            if not OLD_DEEP_ADDRESS <= value < OLD_DEEP_ADDRESS + len(blob):
                raise RuntimeError(f"unexpected deep pointer {value:#x} at {offset:#x}")
            struct.pack_into("<H", out, offset, value + delta)
    return bytes(out)


def patch_vm(text: str) -> str:
    start = text.index("; Deep child-mask/template runtime.")
    end = text.index("\ncode_end:", start)
    deep = text[start:end]
    if deep.count("        ld a,7") != 2:
        raise RuntimeError("deep pager shape changed")
    deep = deep.replace("        ld a,7", "        ld a,5")
    return text[:start] + deep + text[end:]


def patch_renderer(text: str) -> str:
    old = "BITMAP19                EQU 0x7400"
    new = "BITMAP19                EQU 0x73F8"
    if text.count(old) != 1:
        raise RuntimeError("BITMAP19 declaration changed")
    return text.replace(old, new)


def drop_payload(ticks: list[int]) -> bytes:
    payload = bytearray()
    for tick in ticks:
        payload += int(tick).to_bytes(2, "little")
    payload += b"\xff\xff"
    if len(payload) > DROP_LIST_CAPACITY:
        raise RuntimeError(f"drop list {len(payload)} > {DROP_LIST_CAPACITY}")
    payload += b"\xff" * (DROP_LIST_CAPACITY - len(payload))
    return bytes(payload)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--optimized-work", type=Path, required=True)
    parser.add_argument("--neutral-sna", type=Path, required=True)
    parser.add_argument("--full-build", type=Path, required=True)
    parser.add_argument("--deep-blob", type=Path, required=True)
    parser.add_argument("--event-runs", type=Path, required=True)
    parser.add_argument("--rt45-plan", type=Path)
    parser.add_argument("--sjasmplus", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    out = args.out.resolve()
    work = out / "work"
    out.mkdir(parents=True, exist_ok=True)
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir()

    full = args.full_build.resolve()
    base_path = full / "another-world-vm-full.sna"
    snapshot = bytearray(base_path.read_bytes())
    if len(snapshot) != 131103:
        raise RuntimeError(f"unexpected base snapshot size: {len(snapshot)}")

    vm_source = work / "vm-proper-ega.asm"
    renderer_source = work / "renderer-proper-ega.asm"
    vm_text = patch_vm((args.optimized_work / "vm-u-w1-fill.asm").read_text())
    plan = None
    if args.rt45_plan:
        from rt45_patch import patch_vm as patch_rt45

        plan = json.loads(args.rt45_plan.read_text())
        vm_text = patch_rt45(vm_text)
    vm_source.write_text(vm_text)
    renderer_source.write_text(
        patch_renderer((args.optimized_work / "renderer-r-row-vertical-exx-table.asm").read_text())
    )
    shutil.copy2(full.parent / "generated_full_layout.inc", work / "generated_full_layout.inc")
    (work / "deep_layout.inc").write_text(
        "; relocated by build_proper_ega.py\n"
        f"DEEP_DESCRIPTOR_STREAM    EQU 0x{NEW_DEEP_ADDRESS:04X}\n"
        f"DEEP_DESCRIPTOR_TABLE     EQU 0x{NEW_DEEP_ADDRESS + DEEP_STREAM_BYTES:04X}\n"
    )

    vm = assemble(args.sjasmplus.resolve(), vm_source, out / "vm-proper-ega.bin")
    renderer = assemble(args.sjasmplus.resolve(), renderer_source, out / "renderer-proper-ega.bin")
    if RENDERER_OFFSET_BANK5 + len(renderer) > EVENT_RUNS_OFFSET_BANK5:
        raise RuntimeError("renderer overlaps event stream")

    # Preserve the real visual pack, moving only resource 19 to free a
    # contiguous 1,341-byte tail for the deep-child data.
    bitmap19 = (full / "bitmap-19.lzss").read_bytes()
    if len(bitmap19) != NEW_BITMAP19_OFFSET - DEEP_OFFSET_BANK5 + BANK_SIZE:
        # Equivalent to 0x4000 - 0x3AC3 == 1341 bytes remaining after bitmap.
        if NEW_BITMAP19_OFFSET + len(bitmap19) != DEEP_OFFSET_BANK5:
            raise RuntimeError("bitmap/deep relocation no longer packs exactly")
    old_start = bank_offset(5) + OLD_BITMAP19_OFFSET
    snapshot[old_start : old_start + len(bitmap19)] = bytes(len(bitmap19))
    inject(snapshot, 5, NEW_BITMAP19_OFFSET, bitmap19)

    inject(snapshot, 2, 0, vm)
    inject(snapshot, 5, RENDERER_OFFSET_BANK5, renderer)
    inject(snapshot, 5, EVENT_RUNS_OFFSET_BANK5, args.event_runs.read_bytes())
    if plan:
        drop_ticks = plan.get("drop_ticks") or [8 + (int(slot) - 1) * 10 for slot in plan["drop_slots"]]
        inject(snapshot, 5, DROP_LIST_OFFSET_BANK5, drop_payload(drop_ticks))
    inject(snapshot, 5, DEEP_OFFSET_BANK5, relocate_deep_blob(args.deep_blob.read_bytes()))

    neutral = args.neutral_sna.read_bytes()
    coord_start = bank_offset(2) + COORDINATE_TABLE_OFFSET_BANK2
    coordinates = neutral[coord_start : coord_start + COORDINATE_TABLE_BYTES]
    inject(snapshot, 2, COORDINATE_TABLE_OFFSET_BANK2, coordinates)

    sna = out / "another-world-proper-ega-rowfill.sna"
    sna.write_bytes(snapshot)
    manifest = {
        "kind": "live VM/vector renderer; not a diff-stream replay",
        "base_visual_snapshot": str(base_path),
        "vm_bytes": len(vm),
        "renderer_bytes": len(renderer),
        "bitmap19": {"old_offset": OLD_BITMAP19_OFFSET, "new_offset": NEW_BITMAP19_OFFSET, "bytes": len(bitmap19)},
        "deep_child": {"bank": 5, "offset": DEEP_OFFSET_BANK5, "address": NEW_DEEP_ADDRESS, "bytes": len(args.deep_blob.read_bytes())},
        "coordinate_tables": {"bank": 2, "offset": COORDINATE_TABLE_OFFSET_BANK2, "bytes": len(coordinates)},
        "snapshot_bytes": len(snapshot),
        "schedule": None if plan is None else {
            "name": plan["name"],
            "nominal_fps": plan["nominal_fps"],
            "kept_presentations": len(plan["keep_slots"]),
            "dropped_presentations": len(plan["drop_slots"]),
        },
    }
    (out / "proper-ega-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
