#!/usr/bin/env python3
"""Generate the size-first ST-style span-writer variant of renderer_full.asm.

The original source remains unchanged.  The generated file replaces only the
`fill_span` routine and is assembled by build_st_optimized.py.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

START_MARKER = "fill_span:\n"
END_MARKER = "; Expand the current primitive's 16-byte packed decision row"
SCALE_START_MARKER = "scale_x_clamped:\n"
SCALE_END_MARKER = "scale_y_clamped:\n"
PATCH_TAG = "; ST-style fast span writer: masked edges + direct full-byte interior."
EDGE_PATCH_TAG = "; ST-style edge setup: clear only MIN_Y..MAX_Y."
EDGE_START_MARKER = "fill_polygon:\n"
EDGE_END_MARKER = "        xor a\n        ld (EDGE_INDEX),a\n"

FAST_FILL_SPAN = r'''fill_span:
        ld a,(SPAN_LEFT)
        srl a
        srl a
        srl a
        ld (SPAN_FIRST_BYTE),a
        ld a,(SPAN_RIGHT)
        srl a
        srl a
        srl a
        ld (SPAN_LAST_BYTE),a

        ; Bitmap pointer for the first byte of this scanline.
        ld a,(SPAN_Y)
        ld b,a
        and 7
        ld c,a
        ld a,b
        and 0xC0
        rrca
        rrca
        rrca
        add a,c
        ld c,a
        ld a,(DEST_MODE)
        or a
        ld a,0xA0
        jr nz,.bitmap_base
        ld a,(TARGET_SCREEN)
        or a
        ld a,0x40
        jr z,.bitmap_base
        ld a,0xC0
.bitmap_base:
        add a,c
        ld h,a
        ld a,b
        and 0x38
        rlca
        rlca
        ld c,a
        ld a,(SPAN_FIRST_BYTE)
        add a,c
        ld l,a
        push hl                       ; destination bitmap pointer

        ; Background byte at the same Spectrum offset (for COL_PAGE).
        ld a,h
        and 0x1F
        or 0xA0
        ld h,a
        ld (BG_BYTE_PTR),hl

        ; Attribute-stage pointer for the first covered byte.
        ld a,(SPAN_Y)
        and 0xF8
        ld l,a
        ld h,0
        add hl,hl
        add hl,hl
        ld a,(SPAN_FIRST_BYTE)
        ld e,a
        ld d,0
        add hl,de
        ld (SPAN_CELL),hl
        ld de,ATTR_STAGE
        add hl,de
        ex de,hl                     ; DE = staged attribute pointer
        pop hl                       ; HL = bitmap pointer
        push hl
        pop ix
        push de
        pop iy

        ; ST-style fast span writer: masked edges + direct full-byte interior.
        ; COL_PAGE on page 0 is a no-op, so avoid all edge/interior work.
        ld a,(POLY_COLOR)
        cp 17
        jr nz,.normal_color
        ld a,(DEST_MODE)
        or a
        ret nz
        jr .page_color

.normal_color:
        ld a,(SPAN_FIRST_BYTE)
        ld b,a
        ld a,(SPAN_LAST_BYTE)
        cp b
        jr z,.single_normal

        ; Masked left edge.
        ld a,(SPAN_LEFT)
        and 7
        ld c,a
        ld b,0
        ld hl,first_masks
        add hl,bc
        ld a,(hl)
        ld (SPAN_MASK),a
        call .write_masked_normal
        inc ix
        inc iy

        ; Interior byte count = last - first - 1.
        ld a,(SPAN_LAST_BYTE)
        ld b,a
        ld a,(SPAN_FIRST_BYTE)
        inc a
        ld c,a
        ld a,b
        sub c
        jr z,.last_normal
        ld b,a

        ; Full bytes need no read/modify/write. COLOR_DECISIONS already contains
        ; the final 0x00/0xFF value for every Spectrum attribute.
.full_normal_loop:
        ld l,(iy+0)
        ld h,0x72                    ; COLOR_DECISIONS is fixed at 0x7200
        ld a,(hl)
        ld (ix+0),a
        inc ix
        inc iy
        djnz .full_normal_loop

.last_normal:
        ld a,(SPAN_RIGHT)
        and 7
        ld c,a
        ld b,0
        ld hl,last_masks
        add hl,bc
        ld a,(hl)
        ld (SPAN_MASK),a
        jp .write_masked_normal

.single_normal:
        call .combined_edge_mask
        jp .write_masked_normal

.page_color:
        ld a,(SPAN_FIRST_BYTE)
        ld b,a
        ld a,(SPAN_LAST_BYTE)
        cp b
        jr z,.single_page

        ; Masked left edge copied from the immutable background.
        ld a,(SPAN_LEFT)
        and 7
        ld c,a
        ld b,0
        ld hl,first_masks
        add hl,bc
        ld a,(hl)
        ld (SPAN_MASK),a
        call .write_masked_page
        inc ix
        ld hl,(BG_BYTE_PTR)
        inc hl
        ld (BG_BYTE_PTR),hl

        ; Interior background bytes are direct copies.
        ld a,(SPAN_LAST_BYTE)
        ld b,a
        ld a,(SPAN_FIRST_BYTE)
        inc a
        ld c,a
        ld a,b
        sub c
        jr z,.last_page
        ld b,a
.full_page_loop:
        ld hl,(BG_BYTE_PTR)
        ld a,(hl)
        ld (ix+0),a
        inc hl
        ld (BG_BYTE_PTR),hl
        inc ix
        djnz .full_page_loop

.last_page:
        ld a,(SPAN_RIGHT)
        and 7
        ld c,a
        ld b,0
        ld hl,last_masks
        add hl,bc
        ld a,(hl)
        ld (SPAN_MASK),a
        jp .write_masked_page

.single_page:
        call .combined_edge_mask
        jp .write_masked_page

; Return SPAN_MASK = first_masks[left&7] & last_masks[right&7].
.combined_edge_mask:
        ld a,(SPAN_LEFT)
        and 7
        ld c,a
        ld b,0
        ld hl,first_masks
        add hl,bc
        ld e,(hl)
        ld a,(SPAN_RIGHT)
        and 7
        ld c,a
        ld b,0
        ld hl,last_masks
        add hl,bc
        ld a,(hl)
        and e
        ld (SPAN_MASK),a
        ret

; Normal-colour masked edge. The lookup is inlined to avoid CALL/RET per edge.
.write_masked_normal:
        ld l,(iy+0)
        ld h,0x72
        ld a,(hl)
        or a
        jr z,.masked_paper
        ld a,(SPAN_MASK)
        or (ix+0)
        ld (ix+0),a
        ret
.masked_paper:
        ld a,(SPAN_MASK)
        cpl
        and (ix+0)
        ld (ix+0),a
        ret

; COL_PAGE masked edge: preserve uncovered destination bits and copy only the
; polygon mask from the immutable background.
.write_masked_page:
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
'''

FAST_EDGE_CLEAR = r'''fill_polygon:
        ; ST-style edge setup: clear only MIN_Y..MAX_Y. Preserve the range
        ; count across the first LDIR instead of calculating it twice.
        ld a,(MAX_Y)
        ld b,a
        ld a,(MIN_Y)
        ld c,a
        ld a,b
        sub c                         ; BC = rows-1 for LDIR
        ld c,a
        ld b,0
        ld a,(MIN_Y)
        ld e,a
        ld d,0
        ld hl,LEFT_EDGE
        add hl,de
        ld (hl),255
        ld a,b
        or c
        jr z,.left_ready
        push bc
        ld d,h
        ld e,l
        inc de
        ldir
        pop bc
.left_ready:
        ld a,(MIN_Y)
        ld e,a
        ld d,0
        ld hl,RIGHT_EDGE
        add hl,de
        xor a
        ld (hl),a
        ld a,b
        or c
        jr z,.right_ready
        ld d,h
        ld e,l
        inc de
        ldir
.right_ready:
'''

def _scale_x_table_asm() -> str:
    """Retained for tests/documentation; the runtime now uses compact division."""
    values = [str(x - x // 5) for x in range(320)]
    rows = ["        db " + ",".join(values[i : i + 16]) for i in range(0, 320, 16)]
    return "\n".join(rows)


FAST_SCALE_X = r'''scale_x_clamped:
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
        jr c,.transform
        ld a,255
        ret
.transform:
        ; Exact q=floor(x/5) using six greedy binary quotient bits. This keeps
        ; the optimization inside the fixed-bank gap before EVENT_RUNS at $6C00.
        push hl                       ; preserve original x
        ld bc,0                       ; C = quotient
        ld de,160
        ld a,32
        call .division_step
        ld de,80
        ld a,16
        call .division_step
        ld de,40
        ld a,8
        call .division_step
        ld de,20
        ld a,4
        call .division_step
        ld de,10
        ld a,2
        call .division_step
        ld de,5
        ld a,1
        call .division_step
        pop hl
        or a
        sbc hl,bc                     ; x - floor(x/5)
        ld a,l
        ret

; A=quotient bit, DE=5*bit, HL=current remainder, C=current quotient.
.division_step:
        or a                           ; clear carry, preserve A
        sbc hl,de
        jr c,.restore
        or c
        ld c,a
        ret
.restore:
        add hl,de
        ret
'''


def patch_renderer(source: str) -> str:
    """Return the optimized renderer source, validating the expected baseline."""
    if PATCH_TAG in source:
        return source
    patched = source
    if os.environ.get("AW_ST_FAST_FILL", "1") != "0":
        if patched.count(START_MARKER) != 1:
            raise ValueError("expected exactly one fill_span label")
        if patched.count(END_MARKER) != 1:
            raise ValueError("expected exactly one prepare_color_decisions marker")
        start = patched.index(START_MARKER)
        end = patched.index(END_MARKER, start)
        old = patched[start:end]
        required = (
            ".byte_loop:",
            "call decision_ink",
            "ld (SPAN_CURRENT_BYTE),a",
            "jp .byte_loop",
        )
        missing = [token for token in required if token not in old]
        if missing:
            raise ValueError(f"renderer baseline changed; missing {missing}")
        patched = patched[:start] + FAST_FILL_SPAN.rstrip() + "\n\n" + patched[end:]

    if os.environ.get("AW_ST_FAST_EDGE", "1") != "0" and EDGE_PATCH_TAG not in patched:
        if patched.count(EDGE_START_MARKER) != 1 or patched.count(EDGE_END_MARKER) != 1:
            raise ValueError("expected exactly one fill_polygon edge-clear block")
        edge_start = patched.index(EDGE_START_MARKER)
        edge_end = patched.index(EDGE_END_MARKER, edge_start)
        old_edge = patched[edge_start:edge_end]
        for token in ("ld hl,LEFT_EDGE", "ld bc,191", "ld hl,RIGHT_EDGE"):
            if token not in old_edge:
                raise ValueError(f"edge-clear baseline changed; missing {token}")
        patched = patched[:edge_start] + FAST_EDGE_CLEAR.rstrip() + "\n" + patched[edge_end:]

    if os.environ.get("AW_ST_FAST_SCALE", "1") != "0":
        if patched.count(SCALE_START_MARKER) != 1 or patched.count(SCALE_END_MARKER) != 1:
            raise ValueError("expected exactly one scale_x_clamped/scale_y_clamped pair")
        scale_start = patched.index(SCALE_START_MARKER)
        scale_end = patched.index(SCALE_END_MARKER, scale_start)
        old_scale = patched[scale_start:scale_end]
        for token in ("ld de,5", "sbc hl,bc", ".divide:"):
            if token not in old_scale:
                raise ValueError(f"scale_x baseline changed; missing {token}")
        patched = patched[:scale_start] + FAST_SCALE_X.rstrip() + "\n\n" + patched[scale_end:]
    return patched


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    source = args.source.read_text(encoding="utf-8")
    patched = patch_renderer(source)
    if args.check:
        print(
            {
                "source_lines": source.count("\n") + 1,
                "patched_lines": patched.count("\n") + 1,
                "source_bytes": len(source.encode()),
                "patched_bytes": len(patched.encode()),
                "changed": patched != source,
            }
        )
        return
    args.output.write_text(patched, encoding="utf-8")


if __name__ == "__main__":
    main()
