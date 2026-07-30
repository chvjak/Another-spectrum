#!/usr/bin/env python3
"""Generate specialized unrolled copy/fill variants from the measured final sources."""
from __future__ import annotations


def _copy_one_body(unrolled: bool) -> str:
    lines = [
        "unrolled_copy_w1:",
        "        ld hl,(EGA_SRC_PTR)",
        "        ld de,(EGA_DST_PTR)",
    ]
    if unrolled:
        for i in range(8):
            lines += ["        ld a,(hl)", "        ld (de),a"]
            if i != 7:
                lines += ["        inc h", "        inc d"]
        lines += ["        ret"]
    else:
        lines += [
            "        ld b,8",
            ".row:",
            "        ld a,(hl)",
            "        ld (de),a",
            "        inc h",
            "        inc d",
            "        djnz .row",
            "        ret",
        ]
    return "\n".join(lines) + "\n"


def _copy_width_body(width: int) -> str:
    assert 2 <= width <= 4
    lines = [
        f"unrolled_copy_w{width}:",
        "        ld hl,(EGA_SRC_PTR)",
        "        ld de,(EGA_DST_PTR)",
        "        ld b,8",
        ".row:",
    ]
    for i in range(width):
        lines += ["        ld a,(hl)", "        ld (de),a"]
        if i != width - 1:
            lines += ["        inc l", "        inc e"]
    for _ in range(width - 1):
        lines += ["        dec l", "        dec e"]
    lines += ["        inc h", "        inc d", "        djnz .row", "        ret"]
    return "\n".join(lines) + "\n"


def _copy_hot_body(width: int) -> str:
    assert width in (8, 16, 32)
    lines = [
        f"unrolled_copy_w{width}:",
        "        ld hl,(EGA_SRC_PTR)",
        "        ld de,(EGA_DST_PTR)",
        "        ld a,8",
        "        ld (EGA_SCAN_REMAIN),a",
        ".row:",
        f"        ld bc,{width}",
    ]
    lines += ["        ldi"] * width
    lines += [
        "        ld a,l",
        f"        sub {width}",
        "        ld l,a",
        "        inc h",
        "        ld a,e",
        f"        sub {width}",
        "        ld e,a",
        "        inc d",
        "        ld a,(EGA_SCAN_REMAIN)",
        "        dec a",
        "        ld (EGA_SCAN_REMAIN),a",
        "        jr nz,.row",
        "        ret",
    ]
    return "\n".join(lines) + "\n"


def patch_vm(source: str, *, w1: str | None = None, short: bool = False,
             hot: tuple[int, ...] = ()) -> str:
    """Add dispatch before the existing generic 8-scanline copy loop."""
    marker = "        ld (EGA_DST_PTR),hl\n        ld a,8\n        ld (EGA_SCAN_REMAIN),a\n"
    if source.count(marker) != 1:
        raise ValueError(f"copy dispatch marker count={source.count(marker)}")

    dispatch: list[str] = []
    routines: list[str] = []
    if w1:
        dispatch += ["        ld a,(EGA_RUN_LEN)", "        cp 1", "        jp z,unrolled_copy_w1"]
        routines.append(_copy_one_body(w1 == "unrolled"))
    if short:
        if not w1:
            dispatch += ["        ld a,(EGA_RUN_LEN)", "        cp 1", "        jp z,unrolled_copy_w1"]
            routines.append(_copy_one_body(True))
        for width in (2, 3, 4):
            dispatch += ["        ld a,(EGA_RUN_LEN)", f"        cp {width}", f"        jp z,unrolled_copy_w{width}"]
            routines.append(_copy_width_body(width))
    for width in hot:
        dispatch += ["        ld a,(EGA_RUN_LEN)", f"        cp {width}", f"        jp z,unrolled_copy_w{width}"]
        routines.append(_copy_hot_body(width))

    if not dispatch:
        return source
    replacement = "        ld (EGA_DST_PTR),hl\n" + "\n".join(dispatch) + "\n        ld a,8\n        ld (EGA_SCAN_REMAIN),a\n"
    source = source.replace(marker, replacement, 1)
    insert = source.index("profile_span_bytes:\n")
    source = source[:insert] + "\n".join(routines) + "\n" + source[insert:]
    return source


def _unroll_first_line(source: str, factor: int) -> str:
    if factor not in (4, 8):
        raise ValueError(factor)
    old = '''        ld b,32
.first_line:
        ld l,(iy+0)
        ld h,0x72
        ld a,(hl)
        ld (ix+0),a
        inc ix
        inc iy
        djnz .first_line
'''
    seq = '''        ld l,(iy+0)
        ld h,0x72
        ld a,(hl)
        ld (ix+0),a
        inc ix
        inc iy
'''
    new = f"        ld b,{32 // factor}\n.first_line:\n" + seq * factor + "        djnz .first_line\n"
    if source.count(old) != 1:
        raise ValueError(f"first-line marker count={source.count(old)}")
    return source.replace(old, new, 1)


def _unroll_copy32(source: str) -> str:
    old = '''        ld bc,32
        ldir
        ld a,(FINAL_FILL_LINE)
'''
    new = "        ld bc,32\n" + "        ldi\n" * 32 + "        ld a,(FINAL_FILL_LINE)\n"
    if source.count(old) != 1:
        raise ValueError(f"fill copy marker count={source.count(old)}")
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

        ; One-byte span: combine both edge masks once and avoid the generic loop.
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


def patch_renderer(source: str, *, fill_copy32: bool = False,
                   fill_first: int | None = None, span1: bool = False) -> str:
    if fill_copy32:
        source = _unroll_copy32(source)
    if fill_first:
        source = _unroll_first_line(source, fill_first)
    if span1:
        source = _single_span_fast(source)
    return source
