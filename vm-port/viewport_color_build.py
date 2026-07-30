#!/usr/bin/env python3
from __future__ import annotations
import argparse, importlib.util, json, os, shutil, sys
from pathlib import Path

ATTR_HELPER_VECTOR = 0x90D2
ACTIVE_MASK_ADDR = 0xBA20
ACTIVE_MASK_BANK2_OFFSET = ACTIVE_MASK_ADDR - 0x8000


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def snapshot_bank_offset(bank: int) -> int:
    if bank == 5:
        return 27
    if bank == 2:
        return 27 + 0x4000
    if bank == 0:
        return 27 + 0x8000
    return 49183 + [1, 3, 4, 6, 7].index(bank) * 0x4000


def inject(snapshot: bytes, bank: int, offset: int, payload: bytes, label: str) -> bytes:
    if not 0 <= offset <= 0x4000 - len(payload):
        raise RuntimeError(f"{label} overflow")
    out = bytearray(snapshot)
    start = snapshot_bank_offset(bank) + offset
    out[start:start + len(payload)] = payload
    return bytes(out)


def normalize(path: Path) -> None:
    import re
    text = path.read_text()
    text = re.sub(r"(?m)^\s+(\.[A-Za-z_][A-Za-z0-9_]*:)\s*$", r"\1", text)
    path.write_text(text)


def active_mask(width: int, height: int) -> bytes:
    assert width % 8 == 0 and height % 8 == 0
    x0 = (256 - width) // 16
    y0 = (192 - height) // 16
    wc = width // 8
    hc = height // 8
    bits = [0] * 768
    for y in range(y0, y0 + hc):
        for x in range(x0, x0 + wc):
            bits[y * 32 + x] = 1
    out = bytearray(96)
    for index, bit in enumerate(bits):
        out[index >> 3] |= bit << (index & 7)
    return bytes(out)


def patch_active_renderer(source: str, width: int, height: int) -> str:
    x0 = (256 - width) // 16
    y0 = (192 - height) // 16
    wc = width // 8
    hc = height // 8

    old = '''renderer_present:
        ld hl,ATTR_STAGE
        ld de,0x5800
        ld bc,0x0300
        ldir
        ld a,(DISPLAY_BIT)
        or 7
        call page_a
        ld hl,ATTR_STAGE
        ld de,0xD800
        ld bc,0x0300
        ldir
        ld hl,(FRAME_COUNT)
'''
    new = f'''renderer_present:
        call {ATTR_HELPER_VECTOR:#06x}
        ld hl,(FRAME_COUNT)
'''
    if source.count(old) != 1:
        raise ValueError("renderer_present marker changed")
    source = source.replace(old, new, 1)
    if (width, height) == (256, 192):
        return source

    start = source.index("mark_both_full:\n")
    end = source.index("; Mark SPAN_CELL", start)
    marks = f'''mark_both_full:
        ld hl,{ACTIVE_MASK_ADDR:#06x}
        ld de,DIRTY5
        ld bc,96
        ldir
        ld hl,{ACTIVE_MASK_ADDR:#06x}
        ld de,DIRTY7
        ld bc,96
        ldir
        ret

mark_target_full:
        ld a,(TARGET_SCREEN)
        or a
        ld de,DIRTY5
        jr z,.selected
        ld de,DIRTY7
.selected:
        ld hl,{ACTIVE_MASK_ADDR:#06x}
        ld bc,96
        ldir
        ret

'''
    source = source[:start] + marks + source[end:]

    start = source.index("fill_destination_full:\n")
    end = source.index("fill_destination_cell:\n", start)
    start_cell = y0 * 32 + x0
    skip = 32 - wc
    fill = f'''fill_destination_full:
        call prepare_color_decisions
        call map_destination
        ld hl,{start_cell}
        ld (RESTORE_CELL),hl
        ld a,{hc}
        ld (DIRTY_RECT_Y),a
.row_loop:
        ld a,{wc}
        ld (DIRTY_RECT_X0),a
.cell_loop:
        ld hl,ATTR_STAGE
        ld de,(RESTORE_CELL)
        add hl,de
        ld a,(hl)
        call decision_ink
        ld (CELL_FILL_VALUE),a
        ld hl,(RESTORE_CELL)
        call fill_destination_cell
        ld hl,(RESTORE_CELL)
        inc hl
        ld (RESTORE_CELL),hl
        ld a,(DIRTY_RECT_X0)
        dec a
        ld (DIRTY_RECT_X0),a
        jr nz,.cell_loop
        ld hl,(RESTORE_CELL)
        ld de,{skip}
        add hl,de
        ld (RESTORE_CELL),hl
        ld a,(DIRTY_RECT_Y)
        dec a
        ld (DIRTY_RECT_Y),a
        jr nz,.row_loop
        ret

'''
    return source[:start] + fill + source[end:]


def patch_attr_vm(source: str, width: int, height: int) -> str:
    x0 = (256 - width) // 16
    y0 = (192 - height) // 16
    wc = width // 8
    hc = height // 8

    marker = "        jp profile_latch\n"
    if source.count(marker) != 1:
        raise ValueError("EGA vector marker changed")
    source = source.replace(marker, marker + "        jp active_attr_copy\n", 1)

    helper = f'''
active_attr_copy:
        ld a,(TARGET_SCREEN)
        or a
        jr z,.bank5
        ld a,(DISPLAY_BIT)
        or 7
        call page_a
        ld de,{0xD800 + y0 * 32 + x0:#06x}
        jr .dest_ready
.bank5:
        ld de,{0x5800 + y0 * 32 + x0:#06x}
.dest_ready:
        ld hl,{0x9C00 + y0 * 32 + x0:#06x}
        ld a,{hc}
.row:
        push af
        ld bc,{wc}
        ldir
        ld bc,{32 - wc}
        add hl,bc
        ex de,hl
        add hl,bc
        ex de,hl
        pop af
        dec a
        jr nz,.row
        ret
'''
    marker = "        ASSERT $ <= 0x9300\n\n        END\n"
    if source.count(marker) != 1:
        raise ValueError("VM helper end marker changed")
    return source.replace(marker, helper + "        ASSERT $ <= 0x9300\n\n        END\n", 1)


def main() -> None:
    parser = argparse.ArgumentParser()
    for arg in ("source-dir", "helper", "resource-js", "event-runs", "deep-data", "sjasmplus", "out"):
        parser.add_argument("--" + arg, type=Path, required=True)
    args = parser.parse_args()
    source = args.source_dir.resolve()
    out = args.out.resolve()
    work = out / "viewport-work"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    out.mkdir(exist_ok=True)

    helper = load_module(args.helper.resolve(), "vc_helper")
    load_module(source / "st_renderer_patch.py", "st_renderer_patch_base")
    viewport = load_module(source / "viewport_renderer_patch.py", "vc_viewport")
    deep = load_module(source / "deep_source_patch.py", "vc_deep")
    ega = load_module(source / "ega_renderer_patch.py", "vc_ega")
    lzss = load_module(source / "lzss.py", "vc_lz")

    bytecode, shapes, palette = helper.extract_js_resources(args.resource_js.resolve())
    attr = bytes([0x47]) * 768
    bitmap = bytes(6912)
    packed_attrs = [lzss.compress(attr)] * 3
    packed_bitmaps = [lzss.compress(bitmap)] * 3
    checkpoints = [lzss.compress(bytes(6144)) for _ in range(5)]
    helper.write_layout(work, packed_attrs, packed_bitmaps, checkpoints)
    for name in ("vm_full.asm", "renderer_full.asm"):
        shutil.copy2(source / name, work / name)
        normalize(work / name)

    event_runs = args.event_runs.read_bytes()
    palette_tables = bytes(64) + bytes(range(16))
    decisions = helper.spectrum_decisions()
    child_blob = (args.deep_data / "deep-child.bin").read_bytes()
    (work / "deep_layout.inc").write_text((args.deep_data / "deep-child.inc").read_text())

    variants = {
        "full-current": (256, 192, False),
        "full-colorcopy": (256, 192, True),
        "240x176": (240, 176, True),
        "224x176": (224, 176, True),
        "224x160": (224, 160, True),
    }
    manifest: dict[str, object] = {
        "mode": "EGA winner plus single-screen colour copy and active viewport",
        "variants": {},
        "resource_sizes": {"bytecode": len(bytecode), "shapes": len(shapes), "palette": len(palette)},
        "snapshot_bytes": None,
    }
    base_vm = (work / "vm_full.asm").read_text()
    base_renderer = (work / "renderer_full.asm").read_text()

    for label, (width, height, optimize) in variants.items():
        viewport.VIEWPORTS[f"{width}x{height}"] = (width, height)
        os.environ["AW_VIEWPORT"] = f"{width}x{height}"
        os.environ["AW_FAST_DEGENERATE"] = "1"
        coordinates = viewport.viewport_tables()
        renderer_text = viewport.patch_renderer(base_renderer)
        renderer_text = deep.patch_renderer(renderer_text)
        vm_text = deep.patch_vm(base_vm)
        renderer_text = ega.patch_renderer(renderer_text, "both")
        vm_text = ega.patch_vm(vm_text, "both")
        if optimize:
            renderer_text = patch_active_renderer(renderer_text, width, height)
            vm_text = patch_attr_vm(vm_text, width, height)

        renderer_source = work / f"renderer-{label}.asm"
        vm_source = work / f"vm-{label}.asm"
        renderer_source.write_text(renderer_text)
        vm_source.write_text(vm_text)
        normalize(renderer_source)
        normalize(vm_source)
        renderer = helper.assemble(args.sjasmplus, renderer_source, out / f"renderer-{label}.bin")
        vm = helper.assemble(args.sjasmplus, vm_source, out / f"vm-{label}.bin")
        snapshot = helper.make_snapshot(
            vm, renderer, bytecode, shapes, packed_attrs, packed_bitmaps, checkpoints,
            palette_tables, decisions, event_runs,
        )
        snapshot = inject(snapshot, 2, viewport.TABLE_BANK2_OFFSET, coordinates, "coordinates")
        snapshot = inject(snapshot, 7, 0x2000, child_blob, "child data")
        if optimize and (width, height) != (256, 192):
            snapshot = inject(snapshot, 2, ACTIVE_MASK_BANK2_OFFSET, active_mask(width, height), "active mask")
        (out / f"{label}.sna").write_bytes(snapshot)
        manifest["snapshot_bytes"] = len(snapshot)
        manifest["variants"][label] = {
            "viewport": [width, height],
            "active_pixels": width * height,
            "active_percent": 100 * width * height / (256 * 192),
            "vm_bytes": len(vm),
            "renderer_bytes": len(renderer),
            "renderer_gap_remaining": helper.EVENT_RUNS_OFFSET_BANK5 - (helper.RENDERER_OFFSET_BANK5 + len(renderer)),
            "coordinate_table_bytes": len(coordinates),
            "active_mask_bytes": 96 if optimize and (width, height) != (256, 192) else 0,
        }

    (out / "viewport-color-build-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
