#!/usr/bin/env python3
"""Build a live optimized renderer with the real visual asset pack.

The builder relocates the historical benchmark payloads so they can coexist
with the real bitmap, attribute and checkpoint streams.  Individual unsafe
optimizations can be disabled for the pixel-verified production build.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import struct
import subprocess
from pathlib import Path


SNA_HEADER = 27
BANK_SIZE = 0x4000
RENDERER_OFFSET_BANK5 = 0x1D20
EVENT_RUNS_OFFSET_BANK5 = 0x2BD8
EVENT_RUNS_ADDRESS = 0x4000 + EVENT_RUNS_OFFSET_BANK5
DROP_LIST_OFFSET_BANK5 = 0x1C9B
DROP_LIST_CAPACITY = 0x1CFF - DROP_LIST_OFFSET_BANK5
OLD_BITMAP19_OFFSET = 0x3400
NEW_BITMAP19_OFFSET = 0x33F8
DEEP_OFFSET_BANK5 = 0x3AC3
OLD_DEEP_ADDRESS = 0xE000
NEW_DEEP_ADDRESS = 0xC000 + DEEP_OFFSET_BANK5
DEEP_STREAM_BYTES = 440
DEEP_TABLE_BYTES = 660
X_COORDINATE_TABLE_OFFSET_BANK5 = 0x2F00
X_COORDINATE_TABLE_ADDRESS = 0x4000 + X_COORDINATE_TABLE_OFFSET_BANK5


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


def patch_event_stream_address(text: str) -> str:
    old_head = "        ld hl,0x6C01\n"
    new_head = f"        ld hl,0x{EVENT_RUNS_ADDRESS + 1:04X}\n"
    old_first = "        ld a,(0x6C00)\n"
    new_first = f"        ld a,(0x{EVENT_RUNS_ADDRESS:04X})\n"
    if text.count(old_head) != 1 or text.count(old_first) != 1:
        raise RuntimeError("event-stream initializer changed")
    return text.replace(old_head, new_head, 1).replace(old_first, new_first, 1)


def disable_event_filter(text: str) -> str:
    text_call = "        call visual_event_live\n        jp z,dispatch\n"
    shape_call = "        call visual_event_live\n        ret z\n"
    if text.count(text_call) != 1 or text.count(shape_call) != 1:
        raise RuntimeError("visual-event filter call sites changed")
    return text.replace(text_call, "", 1).replace(shape_call, "", 1)


def disable_deep_culling(text: str) -> str:
    old = "        ld a,(DEEP_DESC_VALUE)\n        ld (SHAPE_DESCRIPTOR),a\n"
    new = "        xor a\n        ld (SHAPE_DESCRIPTOR),a\n"
    if text.count(old) != 1:
        raise RuntimeError("deep-culling descriptor site changed")
    return text.replace(old, new, 1)


def disable_fast_degenerate(text: str) -> str:
    start_marker = "        ; Polygons which collapse after coordinate scaling need no edge tables.\n"
    end_marker = ".st_normal_primitive:\n        ld hl,(BBOX_WIDTH)"
    if text.count(start_marker) != 1 or text.count(end_marker) != 1:
        raise RuntimeError("collapsed-polygon fast path changed")
    start = text.index(start_marker)
    end = text.index(end_marker, start)
    return text[:start] + "        ld hl,(BBOX_WIDTH)" + text[end + len(end_marker) :]


def disable_fast_fill(text: str) -> str:
    start_marker = "fill_span:\n"
    end_marker = "; Expand the current primitive's 16-byte packed decision row"
    reference = Path(__file__).with_name("renderer_full.asm").read_text(encoding="utf-8")
    if text.count(start_marker) != 1 or text.count(end_marker) != 1:
        raise RuntimeError("optimized fill-span markers changed")
    if reference.count(start_marker) != 1 or reference.count(end_marker) != 1:
        raise RuntimeError("reference fill-span markers changed")
    start = text.index(start_marker)
    end = text.index(end_marker, start)
    reference_start = reference.index(start_marker)
    reference_end = reference.index(end_marker, reference_start)
    return text[:start] + reference[reference_start:reference_end] + text[end:]


def patch_renderer(text: str, *, clip_screen_y: bool = True) -> str:
    old = "BITMAP19                EQU 0x7400"
    new = "BITMAP19                EQU 0x73F8"
    if text.count(old) != 1:
        raise RuntimeError("BITMAP19 declaration changed")
    text = text.replace(old, new)

    old_x = """scale_x_clamped:
        bit 7,h
        jr z,.non_negative
        ld a,0
        ret
.non_negative:
        push hl
        ld de,320
        or a
        sbc hl,de
        pop hl
        jr c,.lookup
        ld a,255
        ret
.lookup:
        ld de,0xb800
        add hl,de
        ld a,(hl)
        ret
"""
    new_x = f"""scale_x_clamped:
        bit 7,h
        jr z,.non_negative
        xor a
        ret
.non_negative:
        push hl
        ld de,320
        or a
        sbc hl,de
        pop hl
        jr c,.lookup
        ld a,255
        ret
.lookup:
        push hl
        ld a,h
        or a
        jr nz,.high
        ld de,0x{X_COORDINATE_TABLE_ADDRESS:04X}
        add hl,de
        ld a,(hl)
        jr .lookup_done
.high:
        inc l
        ld h,0
        ld de,0x{X_COORDINATE_TABLE_ADDRESS:04X}
        add hl,de
        ld a,(hl)
        add a,204
.lookup_done:
        ; Match the arithmetic routine's documented register/flag result so
        ; callers that reuse DE/HL cannot observe that a table was used.
        ld c,a
        pop hl
        ld a,l
        sub c
        ld c,a
        ld b,0
        ld de,5
        or a
        sbc hl,bc
        ld a,l
        ret
"""
    if text.count(old_x) != 1:
        raise RuntimeError("X coordinate lookup shape changed")
    text = text.replace(old_x, new_x, 1)

    old_y = "        ld de,0xb940\n        add hl,de\n        ld a,(hl)\n        ret\n"
    new_y = """        push hl
        ld de,25
        ld bc,0
.divide:
        or a
        sbc hl,de
        jr c,.done
        inc bc
        jr .divide
.done:
        pop hl
        or a
        sbc hl,bc
        ld a,l
        ret
"""
    if text.count(old_y) != 1:
        raise RuntimeError("Y coordinate lookup shape changed")
    text = text.replace(old_y, new_y, 1)
    text = text.replace(
        "scale_y_clamped:\n        bit 7,h\n        jr z,.non_negative\n        ld a,0\n",
        "scale_y_clamped:\n        bit 7,h\n        jr z,.non_negative\n        xor a\n",
        1,
    )

    if clip_screen_y:
        point_marker = """        call scale_y_clamped
        ld (SPAN_Y),a
        push af
"""
        point_replacement = """        call scale_y_clamped
        cp 192
        ret nc
        ld (SPAN_Y),a
        push af
"""
        if text.count(point_marker) != 1:
            raise RuntimeError("point clipping marker changed")
        text = text.replace(point_marker, point_replacement, 1)

        polygon_marker = """        call prepare_color_decisions
        call mark_polygon_dirty

"""
        polygon_replacement = """        call prepare_color_decisions

        ; y=199 maps to byte value 192 in the original transform.  It is
        ; outside the 192-line Spectrum bitmap, so reject or clip it before
        ; computing a dirty-cell address.
        ld a,(MIN_Y)
        cp 192
        ret nc
        ld a,(MAX_Y)
        cp 192
        jr c,.st_y_clipped
        ld a,191
        ld (MAX_Y),a
.st_y_clipped:
        call mark_polygon_dirty

"""
        if text.count(polygon_marker) != 1:
            raise RuntimeError("polygon clipping marker changed")
        text = text.replace(polygon_marker, polygon_replacement, 1)
    return text


def safe_x_coordinate_table() -> bytes:
    return bytes((value - value // 5) & 0xFF for value in range(256))


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
    parser.add_argument("--vm-source", type=Path)
    parser.add_argument("--renderer-source", type=Path)
    parser.add_argument("--neutral-sna", type=Path)
    parser.add_argument("--full-build", type=Path, required=True)
    parser.add_argument("--deep-blob", type=Path, required=True)
    parser.add_argument("--event-runs", type=Path)
    parser.add_argument("--rt45-plan", type=Path)
    parser.add_argument("--legacy-y-overflow", action="store_true")
    parser.add_argument("--disable-event-filter", action="store_true")
    parser.add_argument("--disable-deep-culling", action="store_true")
    parser.add_argument("--disable-fast-degenerate", action="store_true")
    parser.add_argument("--disable-fast-fill", action="store_true")
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
    vm_input = args.vm_source or args.optimized_work / "vm-u-w1-fill.asm"
    renderer_input = args.renderer_source or args.optimized_work / "renderer-r-row-vertical-exx-table.asm"
    vm_text = patch_vm(vm_input.read_text())
    if args.disable_event_filter:
        vm_text = disable_event_filter(vm_text)
    if args.disable_deep_culling:
        vm_text = disable_deep_culling(vm_text)
    plan = None
    if args.rt45_plan:
        from rt45_patch import patch_vm as patch_rt45

        plan = json.loads(args.rt45_plan.read_text())
        vm_text = patch_rt45(vm_text)
    if not args.disable_event_filter:
        vm_text = patch_event_stream_address(vm_text)
    vm_source.write_text(vm_text)
    renderer_text = renderer_input.read_text()
    if args.disable_fast_fill:
        renderer_text = disable_fast_fill(renderer_text)
    if args.disable_fast_degenerate:
        renderer_text = disable_fast_degenerate(renderer_text)
    renderer_source.write_text(
        patch_renderer(
            renderer_text,
            clip_screen_y=not args.legacy_y_overflow,
        )
    )
    shutil.copy2(full.parent / "generated_full_layout.inc", work / "generated_full_layout.inc")
    (work / "deep_layout.inc").write_text(
        "; relocated by build_proper_ega.py\n"
        f"DEEP_DESCRIPTOR_STREAM    EQU 0x{NEW_DEEP_ADDRESS:04X}\n"
        f"DEEP_DESCRIPTOR_TABLE     EQU 0x{NEW_DEEP_ADDRESS + DEEP_STREAM_BYTES:04X}\n"
    )

    vm = assemble(args.sjasmplus.resolve(), vm_source, out / "vm-proper-ega.bin")
    renderer = assemble(args.sjasmplus.resolve(), renderer_source, out / "renderer-proper-ega.bin")
    renderer_limit = X_COORDINATE_TABLE_OFFSET_BANK5 if args.disable_event_filter else EVENT_RUNS_OFFSET_BANK5
    if RENDERER_OFFSET_BANK5 + len(renderer) > renderer_limit:
        raise RuntimeError("renderer overlaps the next bank-5 payload")

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
    event_runs = b""
    if not args.disable_event_filter:
        if args.event_runs is None:
            raise RuntimeError("--event-runs is required while the event filter is enabled")
        event_runs = args.event_runs.read_bytes()
        if EVENT_RUNS_OFFSET_BANK5 + len(event_runs) > X_COORDINATE_TABLE_OFFSET_BANK5:
            raise RuntimeError("event stream overlaps safe X coordinate table")
        inject(snapshot, 5, EVENT_RUNS_OFFSET_BANK5, event_runs)
    if plan:
        drop_ticks = plan.get("drop_ticks") or [8 + (int(slot) - 1) * 10 for slot in plan["drop_slots"]]
        inject(snapshot, 5, DROP_LIST_OFFSET_BANK5, drop_payload(drop_ticks))
    x_coordinates = safe_x_coordinate_table()
    inject(snapshot, 5, X_COORDINATE_TABLE_OFFSET_BANK5, x_coordinates)
    inject(snapshot, 5, DEEP_OFFSET_BANK5, relocate_deep_blob(args.deep_blob.read_bytes()))

    sna = out / "another-world-proper-ega-rowfill.sna"
    sna.write_bytes(snapshot)
    manifest = {
        "kind": "live VM/vector renderer; not a diff-stream replay",
        "base_visual_snapshot": base_path.name,
        "base_visual_sha256": hashlib.sha256(base_path.read_bytes()).hexdigest(),
        "vm_source": vm_input.name,
        "renderer_source": renderer_input.name,
        "vm_bytes": len(vm),
        "renderer_bytes": len(renderer),
        "bitmap19": {"old_offset": OLD_BITMAP19_OFFSET, "new_offset": NEW_BITMAP19_OFFSET, "bytes": len(bitmap19)},
        "deep_child": {"bank": 5, "offset": DEEP_OFFSET_BANK5, "address": NEW_DEEP_ADDRESS, "bytes": len(args.deep_blob.read_bytes())},
        "coordinate_tables": {
            "layout": "safe X table in fixed bank 5; arithmetic Y scaling",
            "x": {"bank": 5, "offset": X_COORDINATE_TABLE_OFFSET_BANK5, "address": X_COORDINATE_TABLE_ADDRESS, "bytes": len(x_coordinates)},
        },
        "disabled_optimizations": {
            "event_filter": args.disable_event_filter,
            "deep_culling": args.disable_deep_culling,
            "fast_degenerate": args.disable_fast_degenerate,
            "fast_fill": args.disable_fast_fill,
        },
        "snapshot_bytes": len(snapshot),
        "snapshot_sha256": hashlib.sha256(snapshot).hexdigest(),
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
