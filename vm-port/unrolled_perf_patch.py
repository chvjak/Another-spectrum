#!/usr/bin/env python3
"""Specialized copy/fill variants layered on the measured EGA-copy winner."""
from __future__ import annotations


def _copy_one_body(unrolled: bool) -> str:
    lines = ["unrolled_copy_w1:", "        ld hl,(EGA_SRC_PTR)", "        ld de,(EGA_DST_PTR)"]
    if unrolled:
        for i in range(8):
            lines += ["        ld a,(hl)", "        ld (de),a"]
            if i != 7:
                lines += ["        inc h", "        inc d"]
        lines += ["        ret"]
    else:
        lines += ["        ld b,8", ".row:", "        ld a,(hl)", "        ld (de),a",
                  "        inc h", "        inc d", "        djnz .row", "        ret"]
    return "\n".join(lines) + "\n"


def _copy_width_body(width: int) -> str:
    lines = [f"unrolled_copy_w{width}:", "        ld hl,(EGA_SRC_PTR)",
             "        ld de,(EGA_DST_PTR)", "        ld b,8", ".row:"]
    for i in range(width):
        lines += ["        ld a,(hl)", "        ld (de),a"]
        if i != width - 1:
            lines += ["        inc l", "        inc e"]
    for _ in range(width - 1):
        lines += ["        dec l", "        dec e"]
    lines += ["        inc h", "        inc d", "        djnz .row", "        ret"]
    return "\n".join(lines) + "\n"


def _copy_hot_body(width: int) -> str:
    lines = [f"unrolled_copy_w{width}:", "        ld hl,(EGA_SRC_PTR)",
             "        ld de,(EGA_DST_PTR)", "        ld a,8", "        ld (EGA_SCAN_REMAIN),a", ".row:"]
    lines += ["        ldi"] * width
    lines += ["        ld a,l", f"        sub {width}", "        ld l,a", "        inc h",
              "        ld a,e", f"        sub {width}", "        ld e,a", "        inc d",
              "        ld a,(EGA_SCAN_REMAIN)", "        dec a", "        ld (EGA_SCAN_REMAIN),a",
              "        jr nz,.row", "        ret"]
    return "\n".join(lines) + "\n"


def patch_vm(source: str, *, w1: str | None = None, short: bool = False,
             hot: tuple[int, ...] = ()) -> str:
    start_marker = "        ld (EGA_DST_PTR),hl\n\n        ld a,(EGA_RUN_LEN)\n"
    end_marker = "ega_restore_copy_wide:\n"
    start = source.index(start_marker) + len("        ld (EGA_DST_PTR),hl\n")
    end = source.index(end_marker, start)
    dispatch: list[str] = []
    routines: list[str] = []
    if w1 or short:
        dispatch += ["        ld a,(EGA_RUN_LEN)", "        cp 1", "        jp z,unrolled_copy_w1"]
        routines.append(_copy_one_body((w1 == "unrolled") or short))
    else:
        dispatch += ["        ld a,(EGA_RUN_LEN)", "        cp 1", "        jr nz,ega_restore_copy_wide",
                     "        ld hl,(EGA_SRC_PTR)", "        ld de,(EGA_DST_PTR)", "        ld b,8",
                     "ega_restore_copy_one:", "        ld a,(hl)", "        ld (de),a", "        inc h",
                     "        inc d", "        djnz ega_restore_copy_one", "        ret"]
    if short:
        for width in (2, 3, 4):
            dispatch += ["        ld a,(EGA_RUN_LEN)", f"        cp {width}", f"        jp z,unrolled_copy_w{width}"]
            routines.append(_copy_width_body(width))
    for width in hot:
        dispatch += ["        ld a,(EGA_RUN_LEN)", f"        cp {width}", f"        jp z,unrolled_copy_w{width}"]
        routines.append(_copy_hot_body(width))
    if w1 or short or hot:
        dispatch += ["        jp ega_restore_copy_wide"]
    replacement = "\n" + "\n".join(dispatch) + "\n\n" + "\n".join(routines) + "\n"
    return source[:start] + replacement + source[end:]


def _unroll_cell_fill(source: str) -> str:
    old = '''        ld a,(CELL_FILL_VALUE)
        ld b,8
.row:
        ld (de),a
        inc d
        djnz .row
        ret
'''
    lines = ["        ld a,(CELL_FILL_VALUE)"]
    for i in range(8):
        lines.append("        ld (de),a")
        if i != 7:
            lines.append("        inc d")
    lines.append("        ret")
    new = "\n".join(lines) + "\n"
    if source.count(old) != 1:
        raise ValueError(f"cell fill marker count={source.count(old)}")
    return source.replace(old, new, 1)


def _single_span_fast(source: str) -> str:
    marker = '''        push de
        pop iy

.byte_loop:
'''
    if source.count(marker) != 1:
        raise ValueError(f"span marker count={source.count(marker)}")
    fast = r'''        push de
        pop iy
        ld a,(SPAN_FIRST_BYTE)
        ld b,a
        ld a,(SPAN_LAST_BYTE)
        cp b
        jp nz,.byte_loop
        ld a,(SPAN_LEFT)
        and 7
        ld c,a
        ld b,0
        ld hl,first_masks
        add hl,bc
        ld a,(hl)
        ld (SPAN_MASK),a
        ld a,(SPAN_RIGHT)
        and 7
        ld c,a
        ld b,0
        ld hl,last_masks
        add hl,bc
        ld a,(SPAN_MASK)
        and (hl)
        ld (SPAN_MASK),a
        ld a,(POLY_COLOR)
        cp 17
        jr z,.single_page
        ld a,(iy+0)
        call decision_ink
        or a
        jr z,.single_paper
        ld a,(SPAN_MASK)
        or (ix+0)
        ld (ix+0),a
        ret
.single_paper:
        ld a,(SPAN_MASK)
        cpl
        and (ix+0)
        ld (ix+0),a
        ret
.single_page:
        ld a,(DEST_MODE)
        or a
        ret nz
        ld a,(SPAN_MASK)
        ld c,a
        cpl
        and (ix+0)
        ld b,a
        ld hl,(BG_BYTE_PTR)
        ld a,(hl)
        and c
        or b
        ld (ix+0),a
        ret

.byte_loop:
'''
    return source.replace(marker, fast, 1)


def patch_renderer(source: str, *, fill_cell8: bool = False, span1: bool = False) -> str:
    if fill_cell8:
        source = _unroll_cell_fill(source)
    if span1:
        source = _single_span_fast(source)
    return source
