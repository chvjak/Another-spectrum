#!/usr/bin/env python3
"""Deterministic framebuffer optimizations for the AW Spectrum intro.

This patcher is applied to generated EGA-copy winner assembly.  It provides:
* trace mode: log every exact dirty mask to unused bank-7 RAM;
* precompiled restore scripts in bank 7;
* optional fall-through LDI run copying;
* precomputed character-row bitmap addresses;
* visible-page-only attribute publication;
* row-oriented full-page colour fills.
"""
from __future__ import annotations

TRACE_BASE = 0xE600
TRACE_OFFSET_BANK7 = TRACE_BASE - 0xC000
TRACE_RECORD_SIZE = 103  # seq, target, presentation, tick, 96-byte mask
TRACE_CAPACITY = 64
ROW_TABLE_BASE = 0xE600
ROW_TABLE_BYTES = 24 * 2
SCRIPT_BASE = ROW_TABLE_BASE + ROW_TABLE_BYTES  # E630
SCRIPT_OFFSET_BANK7 = SCRIPT_BASE - 0xC000

FINAL_VARS = r'''
FINAL_RESTORE_PTR      EQU 0x93D0
FINAL_RESTORE_NEXT     EQU 0x93D2
FINAL_RESTORE_COUNT    EQU 0x93D4
FINAL_RESTORE_REMAIN   EQU 0x93D6
FINAL_TRACE_SEQ        EQU 0x93D8
FINAL_TRACE_PTR        EQU 0x93DA
FINAL_TRACE_SLOT       EQU 0x93DC
FINAL_TRACE_SAVED_BANK EQU 0x93DD
FINAL_FILL_ATTR_PTR    EQU 0x93DE
FINAL_FILL_TOP_PTR     EQU 0x93E0
FINAL_FILL_ROW         EQU 0x93E2
FINAL_FILL_LINE        EQU 0x93E3
FINAL_EMPTY_REMAIN     EQU 0x93E4
'''


def row_address_table() -> bytes:
    """24 absolute BACKGROUND addresses for the top scanline of each 8px row."""
    out = bytearray()
    for row in range(24):
        y = row * 8
        offset = ((y & 0xC0) << 5) | ((y & 7) << 8) | ((y & 0x38) << 2)
        address = 0xA000 + offset
        out += address.to_bytes(2, "little")
    return bytes(out)


TRACE_ROUTINE = rf'''
final_trace_restore:
        ld a,(0x7280)                  ; renderer CURRENT_BANK
        ld (FINAL_TRACE_SAVED_BANK),a
        ld a,7
        call deep_page_a

        ld hl,(FINAL_TRACE_SEQ)
        inc hl
        ld (FINAL_TRACE_SEQ),hl
        ex de,hl
        ld hl,(FINAL_TRACE_PTR)
        ld (hl),e
        inc hl
        ld (hl),d
        inc hl
        ld a,(TARGET_SCREEN)
        ld (hl),a
        inc hl
        ld de,(FRAME_COUNT)
        ld (hl),e
        inc hl
        ld (hl),d
        inc hl
        ld de,(TICK)
        ld (hl),e
        inc hl
        ld (hl),d
        inc hl
        ex de,hl                     ; DE = ring destination
        ld a,(TARGET_SCREEN)
        or a
        ld hl,DIRTY5
        jr z,.mask_ready
        ld hl,DIRTY7
.mask_ready:
        ld bc,96
        ldir

        ld a,(FINAL_TRACE_SLOT)
        inc a
        and {TRACE_CAPACITY - 1}
        ld (FINAL_TRACE_SLOT),a
        jr nz,.keep_ptr
        ld de,{TRACE_BASE:#06x}
.keep_ptr:
        ld (FINAL_TRACE_PTR),de
        ld a,(FINAL_TRACE_SAVED_BANK)
        call deep_page_a
        ret
'''

SCRIPT_RESTORE = rf'''
ega_restore_dirty_runs:
        ; Clear the runtime mask in one contiguous copy. Exact run geometry is
        ; consumed from the compact deterministic bank-7 stream.
        ld a,(TARGET_SCREEN)
        or a
        ld hl,DIRTY5
        jr z,.mask_ready
        ld hl,DIRTY7
.mask_ready:
        xor a
        ld (hl),a
        push hl
        pop de
        inc de
        ld bc,95
        ldir

        ld a,7
        call deep_page_a
        ld a,(FINAL_EMPTY_REMAIN)
        or a
        jr z,.read_opcode
        dec a
        ld (FINAL_EMPTY_REMAIN),a
        jr .done_call

.read_opcode:
        ld hl,(FINAL_RESTORE_PTR)
        ld a,(hl)
        inc hl
        ld (FINAL_RESTORE_PTR),hl
        bit 7,a
        jr nz,.non_empty
        ld (FINAL_EMPTY_REMAIN),a
        jr .done_call

.non_empty:
        cp 0xC0
        jr nc,.elided_call
        cp 0x80
        jr nz,.active_runs
        ld hl,BACKGROUND
        ld a,(TARGET_SCREEN)
        or a
        ld de,0x4000
        jr z,.full_dest
        ld de,0xC000
.full_dest:
        ld bc,0x1800
        ldir
        jr .done_call

.active_runs:
        and 0x3F
        ld l,a
        ld h,0
        ld (FINAL_RESTORE_REMAIN),hl
.run_loop:
        ld hl,(FINAL_RESTORE_REMAIN)
        ld a,h
        or l
        jr z,.done_call
        dec hl
        ld (FINAL_RESTORE_REMAIN),hl
        ld hl,(FINAL_RESTORE_PTR)
        ld e,(hl)
        inc hl
        ld d,(hl)
        inc hl
        ld (FINAL_RESTORE_PTR),hl
        bit 7,d
        jr nz,.run_loop              ; offline-elided overwritten run

        ld a,e
        and 31
        ld (EGA_ROW),a
        ld a,e
        and 0xE0
        rrca
        rrca
        rrca
        rrca
        rrca
        ld b,a
        ld a,d
        and 3
        rlca
        rlca
        rlca
        or b
        ld (EGA_RUN_START),a
        ld a,d
        and 0x7C
        rrca
        rrca
        inc a
        ld (EGA_RUN_LEN),a
        call final_restore_copy_run
        jr .run_loop

.elided_call:
        and 0x3F
        jr z,.done_call
        add a,a
        ld e,a
        ld d,0
        ld hl,(FINAL_RESTORE_PTR)
        add hl,de
        ld (FINAL_RESTORE_PTR),hl

.done_call:
        ld hl,(FINAL_RESTORE_COUNT)
        inc hl
        ld (FINAL_RESTORE_COUNT),hl
        ret
'''

COPY_PREFIX_TABLE = rf'''
; Precomputed address path: bank 7 is already mapped for the script stream.
final_restore_copy_run:
        ld a,(EGA_ROW)
        add a,a
        ld l,a
        ld h,0
        ld de,{ROW_TABLE_BASE:#06x}
        add hl,de
        ld e,(hl)
        inc hl
        ld d,(hl)
        ex de,hl                     ; HL = BACKGROUND top scanline
        jr final_restore_address_ready
'''

COPY_PREFIX_ARITH = r'''
; Arithmetic control path retained for an isolated address-table measurement.
final_restore_copy_run:
        ld a,(EGA_ROW)
        ld b,a
        and 7
        rlca
        rlca
        rlca
        rlca
        rlca
        ld c,a
        ld l,c
        ld a,b
        srl a
        srl a
        srl a
        rlca
        rlca
        rlca
        add a,0xA0
        ld h,a
'''

COPY_COMMON = r'''
final_restore_address_ready:
        ld a,(EGA_RUN_START)
        add a,l
        ld l,a
        ld (EGA_SRC_PTR),hl
        ld a,h
        and 0x1F
        ld b,a
        ld a,(TARGET_SCREEN)
        or a
        ld a,0x40
        jr z,.dest_base
        ld a,0xC0
.dest_base:
        add a,b
        ld h,a
        ld (EGA_DST_PTR),hl
        ld a,8
        ld (EGA_SCAN_REMAIN),a
.scanline:
        ld hl,(EGA_SRC_PTR)
        ld de,(EGA_DST_PTR)
        call final_copy_n
        ld hl,(EGA_SRC_PTR)
        inc h
        ld (EGA_SRC_PTR),hl
        ld hl,(EGA_DST_PTR)
        inc h
        ld (EGA_DST_PTR),hl
        ld a,(EGA_SCAN_REMAIN)
        dec a
        ld (EGA_SCAN_REMAIN),a
        jr nz,.scanline
        ret
'''

COPY_LDIR = r'''
final_copy_n:
        ld a,(EGA_RUN_LEN)
        ld c,a
        ld b,0
        ldir
        ret
'''

COPY_LDI = r'''
; Long runs jump into N consecutive LDI instructions.  The original IX is
; restored at the shared tail before returning to the run copier.
final_copy_n:
        ld a,(EGA_RUN_LEN)
        cp 8
        jr c,.short
        push ix
        push hl
        push de
        add a,a
        ld e,a
        ld d,0
        ld hl,.ldi_done
        or a
        sbc hl,de
        push hl
        pop ix
        pop de
        pop hl
        ld a,(EGA_RUN_LEN)
        ld c,a
        ld b,0
        jp (ix)
.short:
        ld c,a
        ld b,0
        ldir
        ret
.ldi_32: ldi
.ldi_31: ldi
.ldi_30: ldi
.ldi_29: ldi
.ldi_28: ldi
.ldi_27: ldi
.ldi_26: ldi
.ldi_25: ldi
.ldi_24: ldi
.ldi_23: ldi
.ldi_22: ldi
.ldi_21: ldi
.ldi_20: ldi
.ldi_19: ldi
.ldi_18: ldi
.ldi_17: ldi
.ldi_16: ldi
.ldi_15: ldi
.ldi_14: ldi
.ldi_13: ldi
.ldi_12: ldi
.ldi_11: ldi
.ldi_10: ldi
.ldi_9:  ldi
.ldi_8:  ldi
.ldi_7:  ldi
.ldi_6:  ldi
.ldi_5:  ldi
.ldi_4:  ldi
.ldi_3:  ldi
.ldi_2:  ldi
.ldi_1:  ldi
.ldi_done:
        pop ix
        ret
'''


def _insert_vars(source: str) -> str:
    if "FINAL_RESTORE_PTR" in source:
        return source
    marker = "PROFILE_LATCH_BASE     EQU 0x939C\n"
    if source.count(marker) != 1:
        raise ValueError("final VM variable marker changed")
    return source.replace(marker, marker + FINAL_VARS, 1)


def _insert_init(source: str, *, trace: bool, script: bool) -> str:
    marker = "        call RENDERER_INIT\n"
    if source.count(marker) != 1:
        raise ValueError("renderer init marker changed")
    extra = ""
    if trace:
        extra += f"        ld hl,{TRACE_BASE:#06x}\n        ld (FINAL_TRACE_PTR),hl\n"
    if script:
        extra += f"        ld hl,{SCRIPT_BASE:#06x}\n        ld (FINAL_RESTORE_PTR),hl\n"
        extra += "        xor a\n        ld (FINAL_EMPTY_REMAIN),a\n"
    return source.replace(marker, marker + extra, 1)


def patch_vm(
    source: str,
    *,
    trace: bool = False,
    script: bool = False,
    ldi: bool = False,
    address_table: bool = False,
) -> str:
    if trace and script:
        raise ValueError("trace and script are mutually exclusive")
    source = _insert_vars(source)
    source = _insert_init(source, trace=trace, script=script)

    if trace:
        marker = "ega_restore_dirty_runs:\n"
        if source.count(marker) != 1:
            raise ValueError("restore helper label changed")
        source = source.replace(marker, marker + "        call final_trace_restore\n", 1)
        # Trace builds use the restore-only EGA source, whose stack function is
        # already a stub. Put the logger immediately before the final assertion.
        marker = "        ASSERT $ <= 0x9300\n\n        END\n"
        if source.count(marker) != 1:
            raise ValueError("VM helper end marker changed")
        return source.replace(marker, TRACE_ROUTINE + "\n        ASSERT $ <= 0x9300\n\n        END\n", 1)

    if not script:
        return source

    start = source.index("ega_restore_dirty_runs:\n")
    end = source.index("ega_stack_span:\n", start)
    # Replace both old EGA helpers; the prior stack-span path was neutral once
    # framebuffer restoration dominated and would consume the fixed-bank budget.
    profile = source.index("profile_span_bytes:\n", end)
    copier = (COPY_PREFIX_TABLE if address_table else COPY_PREFIX_ARITH) + COPY_COMMON
    copier += COPY_LDI if ldi else COPY_LDIR
    replacement = SCRIPT_RESTORE + "\nega_stack_span:\n        ret\n\n" + copier + "\n"
    source = source[:start] + replacement + source[profile:]
    return source


LAZY_PRESENT_OLD = '''renderer_present:
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
'''

LAZY_PRESENT_NEW = '''renderer_present:
        ; Publish only the attributes of the page that becomes visible now.
        ld a,(0x9332)                 ; LAST_SAMPLE_BANK
        or a
        jr nz,.publish_bank7
        ld hl,ATTR_STAGE
        ld de,0x5800
        ld bc,0x0300
        ldir
        jr .attributes_ready
.publish_bank7:
        ld a,(DISPLAY_BIT)
        or 7
        call page_a
        ld hl,ATTR_STAGE
        ld de,0xD800
        ld bc,0x0300
        ldir
.attributes_ready:
'''

FULL_FILL_NEW = rf'''fill_destination_full:
        call prepare_color_decisions
        ; The row-address table and script share bank 7. Page it once; screen 5
        ; and the immutable background remain directly addressable.
        ld a,(DISPLAY_BIT)
        or 7
        call page_a
        ld hl,ATTR_STAGE
        ld (FINAL_FILL_ATTR_PTR),hl
        xor a
        ld (FINAL_FILL_ROW),a
.row:
        ld a,(FINAL_FILL_ROW)
        add a,a
        ld l,a
        ld h,0
        ld de,{ROW_TABLE_BASE:#06x}
        add hl,de
        ld e,(hl)
        inc hl
        ld d,(hl)
        ex de,hl                     ; background top scanline
        ld a,(DEST_MODE)
        or a
        jr nz,.top_ready
        ld a,h
        and 0x1F
        ld b,a
        ld a,(TARGET_SCREEN)
        or a
        ld a,0x40
        jr z,.screen_base
        ld a,0xC0
.screen_base:
        add a,b
        ld h,a
.top_ready:
        ld (FINAL_FILL_TOP_PTR),hl
        push hl
        pop ix
        ld iy,(FINAL_FILL_ATTR_PTR)
        ld b,32
.first_line:
        ld l,(iy+0)
        ld h,0x72
        ld a,(hl)
        ld (ix+0),a
        inc ix
        inc iy
        djnz .first_line
        push iy
        pop hl
        ld (FINAL_FILL_ATTR_PTR),hl

        ld a,1
        ld (FINAL_FILL_LINE),a
.copy_line:
        ld hl,(FINAL_FILL_TOP_PTR)
        ld de,(FINAL_FILL_TOP_PTR)
        ld a,(FINAL_FILL_LINE)
        add a,d
        ld d,a
        ld bc,32
        ldir
        ld a,(FINAL_FILL_LINE)
        inc a
        ld (FINAL_FILL_LINE),a
        cp 8
        jr nz,.copy_line
        ld a,(FINAL_FILL_ROW)
        inc a
        ld (FINAL_FILL_ROW),a
        cp 24
        jr nz,.row
        ret

'''


def patch_renderer(source: str, *, lazy: bool = False, full_fill: bool = False) -> str:
    if lazy:
        if source.count(LAZY_PRESENT_OLD) != 1:
            raise ValueError("renderer-present block changed")
        source = source.replace(LAZY_PRESENT_OLD, LAZY_PRESENT_NEW, 1)
    if full_fill:
        start = source.index("fill_destination_full:\n")
        end = source.index("map_destination:\n", start)
        source = source[:start] + FULL_FILL_NEW + source[end:]
    return source
