#!/usr/bin/env python3
"""Row-oriented full-screen fill variants for the measured EGA-copy renderer."""
from __future__ import annotations

ROW_VARS = r'''
ROW_FILL_ATTR_PTR       EQU 0x93E0
ROW_FILL_ROW            EQU 0x93E2
ROW_FILL_TOP_PTR        EQU 0x93E3
ROW_FILL_LINE           EQU 0x93E5
'''


def _row_offsets() -> list[int]:
    out=[]
    for row in range(24):
        y=row*8
        out.append(((y & 0xC0) << 5) | ((y & 7) << 8) | ((y & 0x38) << 2))
    return out


def _insert_vars(source: str) -> str:
    if "ROW_FILL_ATTR_PTR" in source:
        return source
    marker="DRAW_DEST              EQU 0x932F\n"
    if source.count(marker) != 1:
        raise ValueError(f"row var marker count={source.count(marker)}")
    return source.replace(marker, marker + ROW_VARS, 1)


GET_TOP_ARITH = r'''
row_fill_get_top:
        ld a,(ROW_FILL_ROW)
        ld b,a
        and 7
        rlca
        rlca
        rlca
        rlca
        rlca
        ld l,a
        ld a,b
        srl a
        srl a
        srl a
        rlca
        rlca
        rlca
        ld h,a
        ld a,(DEST_MODE)
        or a
        ld a,0xA0
        jr nz,.base_ready
        ld a,(TARGET_SCREEN)
        or a
        ld a,0x40
        jr z,.base_ready
        ld a,0xC0
.base_ready:
        add a,h
        ld h,a
        ret
'''


def _get_top_table() -> str:
    words=','.join(f'0x{x:04X}' for x in _row_offsets())
    return rf'''
row_fill_get_top:
        ld a,(ROW_FILL_ROW)
        add a,a
        ld l,a
        ld h,0
        ld de,row_fill_row_offsets
        add hl,de
        ld e,(hl)
        inc hl
        ld d,(hl)
        ex de,hl
        ld a,(DEST_MODE)
        or a
        ld a,0xA0
        jr nz,.base_ready
        ld a,(TARGET_SCREEN)
        or a
        ld a,0x40
        jr z,.base_ready
        ld a,0xC0
.base_ready:
        add a,h
        ld h,a
        ret
row_fill_row_offsets:
        dw {words}
'''


PROLOGUE = r'''fill_destination_full:
        call prepare_color_decisions
        call map_destination
        ld hl,ATTR_STAGE
        ld (ROW_FILL_ATTR_PTR),hl
        xor a
        ld (ROW_FILL_ROW),a
.row:
        call row_fill_get_top
'''

EPILOGUE = r'''        ld a,(ROW_FILL_ROW)
        inc a
        ld (ROW_FILL_ROW),a
        cp 24
        jr nz,.row
        ret
'''

FIRST_LINE_INDEXED = r'''        ld (ROW_FILL_TOP_PTR),hl
        push hl
        pop ix
        ld iy,(ROW_FILL_ATTR_PTR)
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
        ld (ROW_FILL_ATTR_PTR),hl
'''


def _row_ldir() -> str:
    return PROLOGUE + FIRST_LINE_INDEXED + r'''
        ld a,1
        ld (ROW_FILL_LINE),a
.copy_line:
        ld hl,(ROW_FILL_TOP_PTR)
        ld de,(ROW_FILL_TOP_PTR)
        ld a,(ROW_FILL_LINE)
        add a,d
        ld d,a
        ld bc,32
        ldir
        ld a,(ROW_FILL_LINE)
        inc a
        ld (ROW_FILL_LINE),a
        cp 8
        jr nz,.copy_line
''' + EPILOGUE + GET_TOP_ARITH


def _row_ldi32() -> str:
    copy32='\n'.join(['        ldi']*32)
    return PROLOGUE + FIRST_LINE_INDEXED + r'''
        ld a,1
        ld (ROW_FILL_LINE),a
.copy_line:
        ld hl,(ROW_FILL_TOP_PTR)
        ld de,(ROW_FILL_TOP_PTR)
        ld a,(ROW_FILL_LINE)
        add a,d
        ld d,a
        ld bc,32
        call row_fill_copy32
        ld a,(ROW_FILL_LINE)
        inc a
        ld (ROW_FILL_LINE),a
        cp 8
        jr nz,.copy_line
''' + EPILOGUE + GET_TOP_ARITH + '\nrow_fill_copy32:\n' + copy32 + '\n        ret\n'


VERTICAL_WRITES = r'''        ld (de),a
        inc d
        ld (de),a
        inc d
        ld (de),a
        inc d
        ld (de),a
        inc d
        ld (de),a
        inc d
        ld (de),a
        inc d
        ld (de),a
        inc d
        ld (de),a
        ld a,d
        sub 7
        ld d,a
        inc e
'''


def _row_vertical_indexed() -> str:
    return PROLOGUE + r'''        ex de,hl
        ld iy,(ROW_FILL_ATTR_PTR)
        ld b,32
.cell:
        ld l,(iy+0)
        ld h,0x72
        ld a,(hl)
''' + VERTICAL_WRITES + r'''        inc iy
        djnz .cell
        push iy
        pop hl
        ld (ROW_FILL_ATTR_PTR),hl
''' + EPILOGUE + GET_TOP_ARITH


def _row_vertical_exx(table: bool) -> str:
    return PROLOGUE + r'''        ex de,hl
        ld hl,(ROW_FILL_ATTR_PTR)
        ld c,32
        exx
        push hl
        ld h,0x72
        exx
.cell:
        ld a,(hl)
        inc hl
        exx
        ld l,a
        ld a,(hl)
        exx
''' + VERTICAL_WRITES + r'''        dec c
        jr nz,.cell
        exx
        pop hl
        exx
        ld (ROW_FILL_ATTR_PTR),hl
''' + EPILOGUE + (_get_top_table() if table else GET_TOP_ARITH)


def patch_renderer(source: str, mode: str) -> str:
    source=_insert_vars(source)
    start=source.index('fill_destination_full:\n')
    end=source.index('map_destination:\n', start)
    if mode == 'row-ldir': new=_row_ldir()
    elif mode == 'row-ldi32': new=_row_ldi32()
    elif mode == 'row-vertical-indexed': new=_row_vertical_indexed()
    elif mode == 'row-vertical-exx': new=_row_vertical_exx(False)
    elif mode == 'row-vertical-exx-table': new=_row_vertical_exx(True)
    else: raise ValueError(mode)
    return source[:start] + new + '\n' + source[end:]
