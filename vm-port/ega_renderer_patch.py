#!/usr/bin/env python3
"""EGA-inspired renderer experiments and exact pixel-write profiling.

The benchmark variants build on the current child-culling renderer:

* ``restore`` replaces 8x8-cell restoration with full-page/full-row/horizontal
  run copies, mirroring the EGA port's emphasis on wide framebuffer copies.
* ``stack`` writes long uniform span interiors two bytes at a time with PUSH.
* ``both`` combines the two experiments.
* ``profile`` leaves rendering unchanged and latches exact bitmap write counts
  at every presentation.

All helper code lives in fixed bank 2.  The renderer calls a small fixed jump
vector beginning at 0x90C0.
"""
from __future__ import annotations

from dataclasses import dataclass

HELPER_VECTOR = 0x90C0
EGA_RESTORE = HELPER_VECTOR
EGA_STACK = HELPER_VECTOR + 3
PROFILE_SPAN = HELPER_VECTOR + 6
PROFILE_RESTORE = HELPER_VECTOR + 9
PROFILE_FULL = HELPER_VECTOR + 12
PROFILE_LATCH = HELPER_VECTOR + 15

VM_TAG = "; EGA-inspired copy/span helpers."
PROFILE_TAG = "; Exact bitmap-write profile hooks."
RESTORE_TAG = "; EGA-style horizontal dirty-run restoration."
STACK_TAG = "; EGA-style two-byte stack span writer."

# Fixed scratch/counter region.  Deep child masks use 0x9360..0x9378 and the
# LZ ring begins at 0x9400.
VARS = r'''
EGA_MASK_PTR           EQU 0x9380
EGA_ROW                EQU 0x9382
EGA_X                  EQU 0x9383
EGA_RUN_START          EQU 0x9384
EGA_RUN_LEN            EQU 0x9385
EGA_MASK_BYTE          EQU 0x9386
EGA_SRC_PTR            EQU 0x9387
EGA_DST_PTR            EQU 0x9389
EGA_SCAN_REMAIN        EQU 0x938B
EGA_SAVED_SP           EQU 0x938C
EGA_DEST_END           EQU 0x938E
EGA_ATTR_END           EQU 0x9390

PROFILE_SPAN_TOTAL     EQU 0x9392
PROFILE_EDGE_TOTAL     EQU 0x9394
PROFILE_INTERIOR_TOTAL EQU 0x9396
PROFILE_RESTORE_TOTAL  EQU 0x9398
PROFILE_FULL_TOTAL     EQU 0x939A
PROFILE_LATCH_BASE     EQU 0x939C
'''

JUMP_VECTOR = r'''; EGA-inspired copy/span helpers.
        ASSERT $ <= 0x90C0
        defs 0x90C0-$,0
        ORG 0x90C0
        jp ega_restore_dirty_runs
        jp ega_stack_span
        jp profile_span_bytes
        jp profile_restore_bytes
        jp profile_full_page
        jp profile_latch
'''

RET_STUBS = r'''
ega_restore_dirty_runs:
        ret
ega_stack_span:
        ret
profile_span_bytes:
        ret
profile_restore_bytes:
        ret
profile_full_page:
        ret
profile_latch:
        ret
'''

RESTORE_HELPER = r'''
; Screen is already mapped by renderer map_destination.
ega_restore_dirty_runs:
        ld a,(TARGET_SCREEN)
        or a
        ld hl,DIRTY5
        jr z,ega_restore_mask_ready
        ld hl,DIRTY7
ega_restore_mask_ready:
        ld (EGA_MASK_PTR),hl

        ; Full dirty page: clear the mask and copy all 6144 bitmap bytes once.
        push hl
        ld b,96
ega_restore_full_check:
        ld a,(hl)
        cp 0xFF
        jr nz,ega_restore_not_full
        inc hl
        djnz ega_restore_full_check
        pop hl
        xor a
        ld (hl),a
        push hl
        pop de
        inc de
        ld bc,95
        ldir
        ld hl,BACKGROUND
        ld a,(TARGET_SCREEN)
        or a
        ld de,0x4000
        jr z,ega_restore_full_dest
        ld de,0xC000
ega_restore_full_dest:
        ld bc,0x1800
        ldir
        ret
ega_restore_not_full:
        pop hl
        xor a
        ld (EGA_ROW),a

ega_restore_row_loop:
        ; Four mask bytes describe one 32-byte character row.
        ld hl,(EGA_MASK_PTR)
        ld a,(hl)
        inc hl
        or (hl)
        inc hl
        or (hl)
        inc hl
        or (hl)
        jr nz,ega_restore_row_nonzero
        inc hl
        ld (EGA_MASK_PTR),hl
        jr ega_restore_next_row

ega_restore_row_nonzero:
        ; Dense row: one 32-byte copy on each of its eight scanlines.
        ld hl,(EGA_MASK_PTR)
        ld a,(hl)
        cp 0xFF
        jr nz,ega_restore_scan_row
        inc hl
        ld a,(hl)
        cp 0xFF
        jr nz,ega_restore_scan_row
        inc hl
        ld a,(hl)
        cp 0xFF
        jr nz,ega_restore_scan_row
        inc hl
        ld a,(hl)
        cp 0xFF
        jr nz,ega_restore_scan_row
        ld hl,(EGA_MASK_PTR)
        xor a
        ld (hl),a
        inc hl
        ld (hl),a
        inc hl
        ld (hl),a
        inc hl
        ld (hl),a
        inc hl
        ld (EGA_MASK_PTR),hl
        xor a
        ld (EGA_RUN_START),a
        ld a,32
        ld (EGA_RUN_LEN),a
        call ega_restore_copy_run
        jr ega_restore_next_row

ega_restore_scan_row:
        xor a
        ld (EGA_X),a
        ld (EGA_RUN_LEN),a
        ld b,4
ega_restore_mask_byte_loop:
        ld hl,(EGA_MASK_PTR)
        ld a,(hl)
        ld (EGA_MASK_BYTE),a
        xor a
        ld (hl),a
        inc hl
        ld (EGA_MASK_PTR),hl
        ld c,8
ega_restore_bit_loop:
        ld a,(EGA_MASK_BYTE)
        srl a
        ld (EGA_MASK_BYTE),a
        jr nc,ega_restore_clear_bit
        ld a,(EGA_RUN_LEN)
        or a
        jr nz,ega_restore_extend_run
        ld a,(EGA_X)
        ld (EGA_RUN_START),a
        ld a,1
        ld (EGA_RUN_LEN),a
        jr ega_restore_advance_bit
ega_restore_extend_run:
        inc a
        ld (EGA_RUN_LEN),a
        jr ega_restore_advance_bit
ega_restore_clear_bit:
        ld a,(EGA_RUN_LEN)
        or a
        jr z,ega_restore_advance_bit
        push bc
        call ega_restore_copy_run
        pop bc
        xor a
        ld (EGA_RUN_LEN),a
ega_restore_advance_bit:
        ld a,(EGA_X)
        inc a
        ld (EGA_X),a
        dec c
        jr nz,ega_restore_bit_loop
        djnz ega_restore_mask_byte_loop
        ld a,(EGA_RUN_LEN)
        or a
        jr z,ega_restore_next_row
        call ega_restore_copy_run
        xor a
        ld (EGA_RUN_LEN),a

ega_restore_next_row:
        ld a,(EGA_ROW)
        inc a
        ld (EGA_ROW),a
        cp 24
        jp nz,ega_restore_row_loop
        ret

; Copy EGA_RUN_LEN adjacent cells beginning at EGA_RUN_START for EGA_ROW.
; The Spectrum bitmap is contiguous horizontally and +0x100 vertically inside
; an 8-line character row.
ega_restore_copy_run:
        ld a,(EGA_ROW)
        ld b,a
        and 7
        rlca
        rlca
        rlca
        rlca
        rlca
        ld c,a
        ld a,(EGA_RUN_START)
        add a,c
        ld l,a
        ld a,b
        srl a
        srl a
        srl a
        rlca
        rlca
        rlca
        add a,0xA0
        ld h,a
        ld (EGA_SRC_PTR),hl
        ld a,h
        and 0x1F
        ld b,a
        ld a,(TARGET_SCREEN)
        or a
        ld a,0x40
        jr z,ega_restore_dest_base
        ld a,0xC0
ega_restore_dest_base:
        add a,b
        ld h,a
        ld (EGA_DST_PTR),hl

        ld a,(EGA_RUN_LEN)
        cp 1
        jr nz,ega_restore_copy_wide
        ld hl,(EGA_SRC_PTR)
        ld de,(EGA_DST_PTR)
        ld b,8
ega_restore_copy_one:
        ld a,(hl)
        ld (de),a
        inc h
        inc d
        djnz ega_restore_copy_one
        ret

ega_restore_copy_wide:
        ld a,8
        ld (EGA_SCAN_REMAIN),a
ega_restore_scanline_loop:
        ld hl,(EGA_SRC_PTR)
        ld de,(EGA_DST_PTR)
        ld a,(EGA_RUN_LEN)
        ld c,a
        ld b,0
        ldir
        ld hl,(EGA_SRC_PTR)
        inc h
        ld (EGA_SRC_PTR),hl
        ld hl,(EGA_DST_PTR)
        inc h
        ld (EGA_DST_PTR),hl
        ld a,(EGA_SCAN_REMAIN)
        dec a
        ld (EGA_SCAN_REMAIN),a
        jr nz,ega_restore_scanline_loop
        ret
'''

STACK_HELPER = r'''
; B=interior byte count, IX=destination, IY=attribute stage.
; Long runs are emitted backwards with PUSH DE (two screen bytes per PUSH).
ega_stack_span:
        ld a,b
        cp 8
        jr nc,ega_stack_fast
ega_stack_scalar:
        ld l,(iy+0)
        ld h,0x72
        ld a,(hl)
        ld (ix+0),a
        inc ix
        inc iy
        djnz ega_stack_scalar
        ret

ega_stack_fast:
        bit 0,b
        jr z,ega_stack_even
        ld l,(iy+0)
        ld h,0x72
        ld a,(hl)
        ld (ix+0),a
        inc ix
        inc iy
        dec b
ega_stack_even:
        push ix
        pop hl
        ld e,b
        ld d,0
        add hl,de
        ld (EGA_DEST_END),hl
        push iy
        pop hl
        add hl,de
        ld (EGA_ATTR_END),hl
        push hl
        pop iy
        srl b
        di
        ld (EGA_SAVED_SP),sp
        ld sp,(EGA_DEST_END)
ega_stack_pair_loop:
        dec iy
        ld l,(iy+0)
        ld h,0x72
        ld d,(hl)
        dec iy
        ld l,(iy+0)
        ld e,(hl)
        push de
        djnz ega_stack_pair_loop
        ld sp,(EGA_SAVED_SP)
        ei
        ld ix,(EGA_DEST_END)
        ld iy,(EGA_ATTR_END)
        ret
'''

PROFILE_HELPERS = r'''
profile_add_a:
        ld e,a
        ld d,0
        add hl,de
        ret

profile_span_bytes:
        ld a,(0x72C0)                 ; SPAN_LAST_BYTE
        ld b,a
        ld a,(0x72BF)                 ; SPAN_FIRST_BYTE
        ld c,a
        ld a,b
        sub c
        inc a                          ; total bytes in span
        push af
        ld hl,(PROFILE_SPAN_TOTAL)
        call profile_add_a
        ld (PROFILE_SPAN_TOTAL),hl
        pop af
        cp 1
        ld a,1
        jr z,profile_span_edge_ready
        ld a,2
profile_span_edge_ready:
        push af
        ld hl,(PROFILE_EDGE_TOTAL)
        call profile_add_a
        ld (PROFILE_EDGE_TOTAL),hl
        pop af
        ld b,a
        ld a,(0x72C0)
        ld c,a
        ld a,(0x72BF)
        ld d,a
        ld a,c
        sub d
        inc a
        sub b
        ret c
        ret z
        ld hl,(PROFILE_INTERIOR_TOTAL)
        call profile_add_a
        ld (PROFILE_INTERIOR_TOTAL),hl
        ret

profile_restore_bytes:
        ld a,(TARGET_SCREEN)
        or a
        ld hl,DIRTY5
        jr z,profile_restore_mask_ready
        ld hl,DIRTY7
profile_restore_mask_ready:
        ld de,0
        ld b,96
profile_restore_byte_loop:
        ld a,(hl)
        inc hl
        ld c,8
profile_restore_bit_loop:
        rrca
        jr nc,profile_restore_no_bit
        inc de
profile_restore_no_bit:
        dec c
        jr nz,profile_restore_bit_loop
        djnz profile_restore_byte_loop
        ex de,hl
        add hl,hl
        add hl,hl
        add hl,hl                       ; cells * 8 bitmap bytes
        ex de,hl
        ld hl,(PROFILE_RESTORE_TOTAL)
        add hl,de
        ld (PROFILE_RESTORE_TOTAL),hl
        ret

profile_full_page:
        ld hl,(PROFILE_FULL_TOTAL)
        ld de,0x1800
        add hl,de
        ld (PROFILE_FULL_TOTAL),hl
        ret

profile_latch:
        ld hl,PROFILE_SPAN_TOTAL
        ld de,PROFILE_LATCH_BASE
        ld bc,10
        ldir
        ret
'''


def _insert_vars(source: str) -> str:
    if "EGA_MASK_PTR" in source:
        return source
    marker = "DEEP_MASK_BUFFER       EQU 0x9360\n"
    if source.count(marker) != 1:
        raise ValueError("deep VM variable marker changed")
    return source.replace(marker, marker + VARS, 1)


def patch_vm(source: str, mode: str) -> str:
    """Add fixed-bank helper code for one experiment mode."""
    if VM_TAG in source:
        return source
    source = _insert_vars(source)
    restore = mode in {"restore", "both"}
    stack = mode in {"stack", "both"}
    profile = mode == "profile"

    helpers = [JUMP_VECTOR]
    helpers.append(RESTORE_HELPER if restore else "ega_restore_dirty_runs:\n        ret\n")
    helpers.append(STACK_HELPER if stack else "ega_stack_span:\n        ret\n")
    if profile:
        helpers.append(PROFILE_HELPERS)
    else:
        helpers.append(
            "profile_span_bytes:\n        ret\n"
            "profile_restore_bytes:\n        ret\n"
            "profile_full_page:\n        ret\n"
            "profile_latch:\n        ret\n"
        )
    block = "\n".join(helpers).rstrip() + "\n"
    # Preserve helper code in the otherwise-unused 0x90C0..0x92FF gap.  The
    # original blanket state clear would overwrite it, so clear 0x9300..0x93FF
    # separately.
    source = source.replace("STATE_CLEAR_END        EQU 0x9400", "STATE_CLEAR_END        EQU 0x90C0", 1)
    clear_marker = """        ld (hl),a
        ldir
        ld hl,PAGE3_QUEUE_COUNT
"""
    clear_repl = """        ld (hl),a
        ldir
        ld hl,0x9300
        ld de,0x9301
        ld bc,0x00FF
        ld (hl),a
        ldir
        ld hl,PAGE3_QUEUE_COUNT
"""
    if source.count(clear_marker) != 1:
        raise ValueError("VM state clear marker changed")
    source = source.replace(clear_marker, clear_repl, 1)

    marker = "code_end:\n        ASSERT code_end < VARS\n\n        END\n"
    if source.count(marker) != 1:
        raise ValueError("VM code end marker changed")
    trailer = (
        "code_end:\n        ASSERT code_end < VARS\n\n"
        + block
        + "        ASSERT $ <= 0x9300\n\n        END\n"
    )
    source = source.replace(marker, trailer, 1)
    return source


def _patch_restore(source: str) -> str:
    start = source.index("restore_dirty_cells:\n")
    end = source.index("; Fill the selected destination", start)
    replacement = f'''restore_dirty_cells:
        call map_destination
        jp {EGA_RESTORE:#06x}

'''
    return source[:start] + replacement + source[end:]


def _patch_stack(source: str) -> str:
    old = '''.full_normal_loop:
        ld l,(iy+0)
        ld h,0x72                    ; COLOR_DECISIONS is fixed at 0x7200
        ld a,(hl)
        ld (ix+0),a
        inc ix
        inc iy
        djnz .full_normal_loop
'''
    new = f'''{STACK_TAG}
.full_normal_loop:
        call {EGA_STACK:#06x}
'''
    if source.count(old) != 1:
        raise ValueError("ST interior loop changed")
    return source.replace(old, new, 1)


def _patch_profile(source: str) -> str:
    # Span byte accounting after first/last byte indices are known.
    marker = '''        ld a,(SPAN_RIGHT)
        srl a
        srl a
        srl a
        ld (SPAN_LAST_BYTE),a

        ; Bitmap pointer for the first byte of this scanline.
'''
    repl = marker.replace(
        "\n        ; Bitmap pointer",
        f"\n        call {PROFILE_SPAN:#06x}\n\n        ; Bitmap pointer",
    )
    if source.count(marker) != 1:
        raise ValueError("fill_span profile marker changed")
    source = source.replace(marker, repl, 1)

    # Count dirty cells before the original routine clears them.
    marker = "restore_dirty_cells:\n        call map_destination\n"
    repl = f"restore_dirty_cells:\n        call {PROFILE_RESTORE:#06x}\n        call map_destination\n"
    if source.count(marker) != 1:
        raise ValueError("restore profile marker changed")
    source = source.replace(marker, repl, 1)

    marker = "fill_destination_full:\n        call prepare_color_decisions\n"
    repl = f"fill_destination_full:\n        call {PROFILE_FULL:#06x}\n        call prepare_color_decisions\n"
    if source.count(marker) != 1:
        raise ValueError("full fill profile marker changed")
    source = source.replace(marker, repl, 1)

    marker = ".copy:\n        ld de,BACKGROUND\n        ld bc,0x1800\n        ldir\n"
    repl = f".copy:\n        call {PROFILE_FULL:#06x}\n        ld de,BACKGROUND\n        ld bc,0x1800\n        ldir\n"
    if source.count(marker) != 1:
        raise ValueError("screen copy profile marker changed")
    source = source.replace(marker, repl, 1)

    marker = "load_bitmap:\n        ld de,BACKGROUND\n"
    repl = f"load_bitmap:\n        call {PROFILE_FULL:#06x}\n        ld de,BACKGROUND\n"
    if source.count(marker) != 1:
        raise ValueError("bitmap load profile marker changed")
    source = source.replace(marker, repl, 1)

    marker = "renderer_load_checkpoint:\n        add a,a\n"
    repl = f"renderer_load_checkpoint:\n        call {PROFILE_FULL:#06x}\n        add a,a\n"
    if source.count(marker) != 1:
        raise ValueError("checkpoint profile marker changed")
    source = source.replace(marker, repl, 1)

    marker = "renderer_present:\n        ld hl,ATTR_STAGE\n"
    repl = f"renderer_present:\n        call {PROFILE_LATCH:#06x}\n        ld hl,ATTR_STAGE\n"
    if source.count(marker) != 1:
        raise ValueError("present profile marker changed")
    source = source.replace(marker, repl, 1)
    return source


def patch_renderer(source: str, mode: str) -> str:
    if mode in {"restore", "both"}:
        source = _patch_restore(source)
    if mode in {"stack", "both"}:
        source = _patch_stack(source)
    if mode == "profile":
        source = _patch_profile(source)
    return source
