#!/usr/bin/env python3
"""Generate a measurement-only VM/renderer pair with exact write counters.

The production sources remain byte-for-byte unchanged.  Counter helpers live
in unused fixed-bank VM space and are sampled once per emulator refresh, so
16-bit wraparound is unambiguous without consuming production RAM.
"""
from __future__ import annotations

import argparse
from pathlib import Path


PROFILE_SPAN = 0x8A00
PROFILE_PRIMITIVE = 0x8A03
PROFILE_FULL = 0x8A06
PROFILE_TEXT = 0x8A09

PROFILE_EQUATES = r"""
PROFILE_SPAN_TOTAL      EQU 0x9360
PROFILE_TEXT_TOTAL      EQU 0x9362
PROFILE_FULL_TOTAL      EQU 0x9364
PROFILE_POLYGON_TOTAL   EQU 0x9366
PROFILE_POINT_TOTAL     EQU 0x9368
PROFILE_BG_PRIM_TOTAL   EQU 0x936A
PROFILE_FG_PRIM_TOTAL   EQU 0x936C
PROFILE_BG_SPAN_TOTAL   EQU 0x936E
PROFILE_FG_SPAN_TOTAL   EQU 0x9370
PROFILE_TEMP            EQU 0x9372
PROFILE_PHASE           EQU 0x9374

PROFILE_DEST_MODE       EQU 0x7281
PROFILE_POLY_COLOR      EQU 0x72A4
PROFILE_BBOX_WIDTH      EQU 0x72A5
PROFILE_BBOX_HEIGHT     EQU 0x72A7
PROFILE_SPAN_FIRST      EQU 0x72BF
PROFILE_SPAN_LAST       EQU 0x72C0
"""

PROFILE_HELPERS = rf"""
        ASSERT $ <= 0x{PROFILE_SPAN:04X}
        defs 0x{PROFILE_SPAN:04X}-$,0
        ORG 0x{PROFILE_SPAN:04X}
        jp profile_span_bytes
        jp profile_primitive
        jp profile_full_bitmap
        jp profile_text_byte

profile_span_bytes:
        push af
        push bc
        push de
        push hl
        ld a,(PROFILE_POLY_COLOR)
        cp 16                           ; COL_ALPHA performs no bitmap store
        jr z,.done
        cp 17                           ; COL_PAGE on page 0 is a no-op
        jr nz,.count
        ld a,(PROFILE_DEST_MODE)
        or a
        jr nz,.done
.count:
        ld a,(PROFILE_SPAN_LAST)
        ld b,a
        ld a,(PROFILE_SPAN_FIRST)
        ld c,a
        ld a,b
        sub c
        inc a
        ld (PROFILE_TEMP),a
        ld e,a
        ld d,0
        ld hl,(PROFILE_SPAN_TOTAL)
        add hl,de
        ld (PROFILE_SPAN_TOTAL),hl
        ld a,(PROFILE_DEST_MODE)
        or a
        ld hl,(PROFILE_FG_SPAN_TOTAL)
        jr z,.span_dest_ready
        ld hl,(PROFILE_BG_SPAN_TOTAL)
.span_dest_ready:
        add hl,de
        ld a,(PROFILE_DEST_MODE)
        or a
        jr z,.store_fg_span
        ld (PROFILE_BG_SPAN_TOTAL),hl
        jr .done
.store_fg_span:
        ld (PROFILE_FG_SPAN_TOTAL),hl
.done:
        pop hl
        pop de
        pop bc
        pop af
        ret

profile_primitive:
        push af
        push de
        push hl
        ld hl,(PROFILE_BBOX_WIDTH)
        ld a,h
        or l
        jr nz,.polygon
        ld hl,(PROFILE_BBOX_HEIGHT)
        ld a,h
        or a
        jr nz,.polygon
        ld a,l
        cp 2
        jr nc,.polygon
        ld hl,(PROFILE_POINT_TOTAL)
        jr .primitive_kind_ready
.polygon:
        ld hl,(PROFILE_POLYGON_TOTAL)
.primitive_kind_ready:
        inc hl
        ld a,(PROFILE_BBOX_WIDTH)       ; select the same counter again
        ld de,(PROFILE_BBOX_WIDTH)
        ld a,d
        or e
        jr nz,.store_polygon
        ld de,(PROFILE_BBOX_HEIGHT)
        ld a,d
        or a
        jr nz,.store_polygon
        ld a,e
        cp 2
        jr nc,.store_polygon
        ld (PROFILE_POINT_TOTAL),hl
        jr .primitive_dest
.store_polygon:
        ld (PROFILE_POLYGON_TOTAL),hl
.primitive_dest:
        ld a,(PROFILE_DEST_MODE)
        or a
        ld hl,(PROFILE_FG_PRIM_TOTAL)
        jr z,.dest_ready
        ld hl,(PROFILE_BG_PRIM_TOTAL)
.dest_ready:
        inc hl
        ld a,(PROFILE_DEST_MODE)
        or a
        jr z,.store_fg_primitive
        ld (PROFILE_BG_PRIM_TOTAL),hl
        jr .primitive_done
.store_fg_primitive:
        ld (PROFILE_FG_PRIM_TOTAL),hl
.primitive_done:
        pop hl
        pop de
        pop af
        ret

profile_full_bitmap:
        push de
        push hl
        ld hl,(PROFILE_FULL_TOTAL)
        ld de,0x1800
        add hl,de
        ld (PROFILE_FULL_TOTAL),hl
        pop hl
        pop de
        ret

profile_text_byte:
        push af
        push hl
        ld hl,(PROFILE_TEXT_TOTAL)
        inc hl
        ld (PROFILE_TEXT_TOTAL),hl
        pop hl
        pop af
        ret
"""


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one marker, found {count}")
    return text.replace(old, new, 1)


def patch_vm(text: str) -> str:
    text = replace_once(
        text,
        "LAST_SAMPLE_BANK       EQU 0x9332\n",
        "LAST_SAMPLE_BANK       EQU 0x9332\n" + PROFILE_EQUATES,
        "VM profile equates",
    )
    text = replace_once(
        text,
        """main_loop:
        call wait_tick_slot
        call setup_tasks
        call run_tasks

        ld hl,(TICK)
""",
        """main_loop:
        call wait_tick_slot
        call setup_tasks
        ld a,1
        ld (PROFILE_PHASE),a
        call run_tasks
        xor a
        ld (PROFILE_PHASE),a

        ld hl,(TICK)
""",
        "VM run-tasks phase marker",
    )
    marker = "code_end:\n        ASSERT code_end < VARS\n\n        END\n"
    replacement = PROFILE_HELPERS + "\ncode_end:\n        ASSERT code_end < VARS\n\n        END\n"
    return replace_once(text, marker, replacement, "VM helper trailer")


def patch_renderer(text: str) -> str:
    marker = "ATTR_CHANGE_MASK        EQU 0x5C75\n"
    calls = (
        f"PROFILE_SPAN_HOOK       EQU 0x{PROFILE_SPAN:04X}\n"
        f"PROFILE_PRIMITIVE_HOOK  EQU 0x{PROFILE_PRIMITIVE:04X}\n"
        f"PROFILE_FULL_HOOK       EQU 0x{PROFILE_FULL:04X}\n"
        f"PROFILE_TEXT_HOOK       EQU 0x{PROFILE_TEXT:04X}\n"
    )
    text = replace_once(text, marker, marker + calls, "renderer profile hooks")

    span_marker = """        ld a,(SPAN_RIGHT)
        srl a
        srl a
        srl a
        ld (SPAN_LAST_BYTE),a

        ; Bitmap pointer for the first byte of this scanline.
"""
    text = replace_once(
        text,
        span_marker,
        span_marker.replace(
            "\n        ; Bitmap pointer",
            "\n        call PROFILE_SPAN_HOOK\n\n        ; Bitmap pointer",
        ),
        "span counter",
    )

    primitive_store = "        ld (PRIMITIVE_COUNT),hl\n"
    if text.count(primitive_store) != 3:
        raise RuntimeError(
            f"primitive counters: expected three markers, found {text.count(primitive_store)}"
        )
    text = text.replace(
        primitive_store,
        primitive_store + "        call PROFILE_PRIMITIVE_HOOK\n",
    )

    text = replace_once(
        text,
        "renderer_load_checkpoint:\n        add a,a\n",
        "renderer_load_checkpoint:\n        call PROFILE_FULL_HOOK\n        add a,a\n",
        "checkpoint full bytes",
    )
    text = replace_once(
        text,
        "fill_destination_full:\n        call prepare_color_decisions\n",
        "fill_destination_full:\n        call PROFILE_FULL_HOOK\n        call prepare_color_decisions\n",
        "full fill bytes",
    )
    text = replace_once(
        text,
        ".copy:\n        ld de,BACKGROUND\n        ld bc,0x1800\n        ldir\n",
        ".copy:\n        call PROFILE_FULL_HOOK\n        ld de,BACKGROUND\n        ld bc,0x1800\n        ldir\n",
        "screen-to-background bytes",
    )
    text = replace_once(
        text,
        "load_bitmap:\n        ld de,BACKGROUND\n",
        "load_bitmap:\n        call PROFILE_FULL_HOOK\n        ld de,BACKGROUND\n",
        "bitmap resource bytes",
    )

    snapshot_marker = ".load_snapshot:\n        ld a,0xFF"
    if text.count(snapshot_marker) != 2:
        raise RuntimeError(
            f"page3 snapshots: expected two markers, found {text.count(snapshot_marker)}"
        )
    text = text.replace(
        snapshot_marker,
        ".load_snapshot:\n        call PROFILE_FULL_HOOK\n        ld a,0xFF",
    )

    text_start = text.index("draw_text_core:\n")
    text_end = text.index("text_x_to_cell:\n", text_start)
    text_block = text[text_start:text_end]
    store = "        ld (ix+0),a\n"
    if text_block.count(store) != 2:
        raise RuntimeError(
            f"text stores: expected two markers, found {text_block.count(store)}"
        )
    text_block = text_block.replace(
        store,
        store + "        call PROFILE_TEXT_HOOK\n",
    )
    return text[:text_start] + text_block + text[text_end:]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--vm", type=Path, required=True)
    parser.add_argument("--renderer", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "vm-profile.asm").write_text(
        patch_vm(args.vm.read_text(encoding="utf-8")), encoding="utf-8"
    )
    (args.out / "renderer-profile.asm").write_text(
        patch_renderer(args.renderer.read_text(encoding="utf-8")), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
