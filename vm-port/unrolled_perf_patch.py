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


def patch_vm(source: str, *, w1: str | None = None, short: tuple[int, ...] = (),
             hot: tuple[int, ...] = ()) -> str:
    start_marker = "        ld (EGA_DST_PTR),hl\n\n        ld a,(EGA_RUN_LEN)\n"
    end_marker = "ega_restore_copy_wide:\n"
    start = source.index(start_marker) + len("        ld (EGA_DST_PTR),hl\n")
    end = source.index(end_marker, start)
    tests: list[str] = []
    routines: list[str] = []
    if w1:
        tests += ["        ld a,(EGA_RUN_LEN)", "        cp 1", "        jp z,unrolled_copy_w1"]
        routines.append(_copy_one_body(w1 == "unrolled"))
    for width in short:
        tests += ["        ld a,(EGA_RUN_LEN)", f"        cp {width}", f"        jp z,unrolled_copy_w{width}"]
        routines.append(_copy_width_body(width))
    for width in hot:
        tests += ["        ld a,(EGA_RUN_LEN)", f"        cp {width}", f"        jp z,unrolled_copy_w{width}"]
        routines.append(_copy_hot_body(width))
    if not w1:
        tests += ["        ld a,(EGA_RUN_LEN)", "        cp 1", "        jr nz,ega_restore_copy_wide",
                  "        ld hl,(EGA_SRC_PTR)", "        ld de,(EGA_DST_PTR)", "        ld b,8",
                  "ega_restore_copy_one:", "        ld a,(hl)", "        ld (de),a", "        inc h",
                  "        inc d", "        djnz ega_restore_copy_one", "        ret"]
    else:
        tests += ["        jp ega_restore_copy_wide"]
    replacement = "\n" + "\n".join(tests) + "\n\n" + "\n".join(routines) + "\n"
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


def patch_renderer(source: str, *, fill_cell8: bool = False) -> str:
    if fill_cell8:
        source = _unroll_cell_fill(source)
    return source
