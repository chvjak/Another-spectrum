#!/usr/bin/env python3
"""Patch the full VM and winning ST renderer for deep primitive optimizations.

The generated VM consumes an event-specific descriptor stream in bank 7. A
child mask can skip an entire primitive before vertex decoding; a span template
can bypass compound/primitive decoding and edge construction altogether.
"""
from __future__ import annotations

VM_HELPER_ORG = 0x8900
DEEP_BEGIN = 0x8900
DEEP_NEXT = 0x8903
RENDERER_DEEP_PREP = 0x5D47
RENDERER_FILL_SPAN = 0x5D4A

VM_TAG = "; Deep child-mask/template runtime."
RENDERER_TAG = "; Deep primitive-mask/template hooks."

VM_HELPERS = r'''; Deep child-mask/template runtime.
        ASSERT $ <= 0x8900
        defs 0x8900-$,0
        ORG 0x8900
        jp deep_opt_begin
        jp deep_opt_next

; Page bank A while keeping the renderer's bank tracker coherent.
deep_page_a:
        ld (0x7280),a                 ; renderer CURRENT_BANK
        ld b,a
        ld a,(DISPLAY_BIT)
        or b
        ld bc,0x7FFD
        out (c),a
        ret

; Consume the next descriptor for a live immediate shape. The sparse stream is
; run-length encoded as {descriptor, count}; bank 7 is touched only at a run
; boundary rather than once per shape. Page-3 and checkpoint shapes never call
; this routine and therefore have no descriptor entries.
deep_read_descriptor:
        ld a,(DEEP_DESC_REMAIN)
        or a
        jr nz,.consume
        ld a,7
        call deep_page_a
        ld hl,(DEEP_DESC_STREAM_PTR)
        ld a,(hl)
        ld (DEEP_DESC_VALUE),a
        inc hl
        ld a,(hl)
        ld (DEEP_DESC_REMAIN),a
        inc hl
        ld (DEEP_DESC_STREAM_PTR),hl
        ld a,1
        call deep_page_a
.consume:
        ld a,(DEEP_DESC_REMAIN)
        dec a
        ld (DEEP_DESC_REMAIN),a
        ld a,(DEEP_DESC_VALUE)
        ld (SHAPE_DESCRIPTOR),a
        ret

; Called by renderer_draw_shape before normal recursive decoding.
; Carry set means an exact template was rendered and decode_shape must be skipped.
deep_opt_begin:
        xor a
        ld (DEEP_MASK_PTR),a
        ld (DEEP_MASK_PTR+1),a
        ld (DEEP_MASK_BITS),a
        ld (DEEP_TEMPLATE_PTR),a
        ld (DEEP_TEMPLATE_PTR+1),a
        ld a,(SHAPE_DESCRIPTOR)
        or a
        ret z

        ld l,a
        ld h,0
        add hl,hl
        add hl,hl
        ld de,DEEP_DESCRIPTOR_TABLE
        add hl,de
        ld a,7
        call deep_page_a
        ld e,(hl)
        inc hl
        ld d,(hl)
        inc hl
        ld (DEEP_MASK_PTR),de
        ld e,(hl)
        inc hl
        ld d,(hl)
        ld (DEEP_TEMPLATE_PTR),de
        ld a,d
        or e
        jr nz,deep_render_template

        ; Child-mask payloads are length-prefixed. Copy the complete mask into
        ; fixed RAM while bank 7 is already mapped; per-primitive tests then need
        ; no paging at all.
        ld hl,(DEEP_MASK_PTR)
        ld a,h
        or l
        jr z,.mask_ready
        ld b,(hl)
        inc hl
        ld de,DEEP_MASK_BUFFER
        ld a,b
        or a
        jr z,.mask_copied
        ld c,b
        ld b,0
        ldir
.mask_copied:
        ld hl,DEEP_MASK_BUFFER
        ld (DEEP_MASK_PTR),hl
.mask_ready:
        ld a,1
        call deep_page_a
        or a                            ; carry clear: continue decode_shape
        ret

; Called once after the primitive header and vertex count are fetched.
; Carry set keeps the primitive. Carry clear skips its packed vertex payload,
; while still accounting it in PRIMITIVE_COUNT for regression equality.
deep_opt_next:
        ld hl,(DEEP_MASK_PTR)
        ld a,h
        or l
        scf
        ret z
        ld a,(DEEP_MASK_BITS)
        or a
        jr nz,.have_byte
        ld hl,(DEEP_MASK_PTR)
        ld a,(hl)
        ld (DEEP_MASK_BYTE),a
        inc hl
        ld (DEEP_MASK_PTR),hl
        ld a,8
        ld (DEEP_MASK_BITS),a
.have_byte:
        ld a,(DEEP_MASK_BYTE)
        rrca
        ld (DEEP_MASK_BYTE),a
        ld a,(DEEP_MASK_BITS)
        dec a
        ld (DEEP_MASK_BITS),a
        ret c

        ; Dead primitive: advance over its 2*vertex_count packed coordinates.
        ld a,(0x72A9)                   ; renderer VERTEX_COUNT
        add a,a
        ld e,a
        ld d,0
        ld hl,(0x7285)                  ; renderer SHAPE_OFFSET
        add hl,de
        ld (0x7285),hl
        ld hl,(0x7283)                  ; renderer PRIMITIVE_COUNT
        inc hl
        ld (0x7283),hl
        or a                            ; carry clear
        ret

; Bank 7 is mapped and DEEP_TEMPLATE_PTR points at:
;   dw original_primitive_count, db record_count,
;   records {color,minx,maxx,miny,maxy,span_count,{y,left,right}*}.
deep_render_template:
        call deep_template_byte
        ld e,a
        call deep_template_byte
        ld d,a
        ld hl,(0x7283)
        add hl,de
        ld (0x7283),hl
        call deep_template_byte
        ld (DEEP_RECORD_REMAIN),a
.record_loop:
        ld a,(DEEP_RECORD_REMAIN)
        or a
        jr z,.done
        call deep_template_byte
        ld (0x72A4),a                   ; POLY_COLOR
        call deep_template_byte
        ld (0x72E9),a                   ; MIN_X
        call deep_template_byte
        ld (0x72EA),a                   ; MAX_X
        call deep_template_byte
        ld (0x72AE),a                   ; MIN_Y
        call deep_template_byte
        ld (0x72AF),a                   ; MAX_Y
        call deep_template_byte
        ld (DEEP_SPAN_REMAIN),a
        call 0x5D47
.span_loop:
        ld a,(DEEP_SPAN_REMAIN)
        or a
        jr z,.record_done
        call deep_template_byte
        ld (0x72BC),a                   ; SPAN_Y
        call deep_template_byte
        ld (0x72BD),a                   ; SPAN_LEFT
        call deep_template_byte
        ld (0x72BE),a                   ; SPAN_RIGHT
        call 0x5D4A
        ld a,(DEEP_SPAN_REMAIN)
        dec a
        ld (DEEP_SPAN_REMAIN),a
        jr .span_loop
.record_done:
        ld a,(DEEP_RECORD_REMAIN)
        dec a
        ld (DEEP_RECORD_REMAIN),a
        jr .record_loop
.done:
        ld a,1
        call deep_page_a
        scf
        ret

deep_template_byte:
        ld hl,(DEEP_TEMPLATE_PTR)
        ld a,(hl)
        inc hl
        ld (DEEP_TEMPLATE_PTR),hl
        ret
'''

RENDERER_COMMON = r'''; Deep primitive-mask/template hooks.
deep_draw_current:
        call 0x8900
        ret c
        jp decode_shape

; Public helper used by the fixed-bank template player. MIN/MAX and POLY_COLOR
; are already populated; set up attribute decisions, dirty cells and destination.
renderer_deep_prepare:
        call prepare_color_decisions
        call mark_polygon_dirty
        jp map_destination
'''


def patch_vm(source: str) -> str:
    if VM_TAG in source:
        return source
    vars_marker = "EVENT_RUN_KEEP         EQU 0x9336\n"
    vars_insert = vars_marker + """
SHAPE_DESCRIPTOR       EQU 0x9337
DEEP_DESC_STREAM_PTR   EQU 0x9338
DEEP_MASK_PTR          EQU 0x933A
DEEP_MASK_BITS         EQU 0x933C
DEEP_MASK_BYTE         EQU 0x933D
DEEP_TEMPLATE_PTR      EQU 0x933E
DEEP_RECORD_REMAIN     EQU 0x9353
DEEP_SPAN_REMAIN       EQU 0x9354
DEEP_DESC_REMAIN       EQU 0x9355
DEEP_DESC_VALUE        EQU 0x9356
DEEP_MASK_BUFFER       EQU 0x9360
"""
    if source.count(vars_marker) != 1:
        raise ValueError("VM event variable marker changed")
    source = source.replace(vars_marker, vars_insert, 1)

    include_marker = "BYTECODE_BASE          EQU 0xC000\n"
    if source.count(include_marker) != 1:
        raise ValueError("VM bytecode marker changed")
    source = source.replace(include_marker, include_marker + '        INCLUDE "deep_layout.inc"\n', 1)

    init_marker = """        ld a,(hl)
        inc hl
        ld (EVENT_RUN_PTR),hl
        ld (EVENT_RUN_REMAIN),a
        ld a,1                       ; bytecode bank, display bank 5
"""
    init_repl = """        ld a,(hl)
        inc hl
        ld (EVENT_RUN_PTR),hl
        ld (EVENT_RUN_REMAIN),a
        ld hl,DEEP_DESCRIPTOR_STREAM
        ld (DEEP_DESC_STREAM_PTR),hl
        xor a
        ld (SHAPE_DESCRIPTOR),a
        ld (DEEP_DESC_REMAIN),a
        ld (DEEP_DESC_VALUE),a
        ld a,1                       ; bytecode bank, display bank 5
"""
    if source.count(init_marker) != 1:
        raise ValueError("VM event initialization marker changed")
    source = source.replace(init_marker, init_repl, 1)

    route_start = source.index("route_shape:\n")
    route_end = source.index("\n; Resolve 0xFF/0xFE", route_start)
    old_route = source[route_start:route_end]
    required = ("call visual_event_live", "jp RENDERER_DRAW_BG_SHAPE", "jp queue_page3_shape")
    if any(token not in old_route for token in required):
        raise ValueError("VM route_shape changed")
    new_route = r'''route_shape:
        call visual_event_live
        ret z
        ld a,(WORK_PAGE)
        or a
        jr z,.background
        cp 3
        jr z,.page3
        call visual_tick_live
        ret z
        call select_work_screen
        ret c
        call deep_read_descriptor
        xor a
        ld (DRAW_DEST),a
        jp RENDERER_DRAW_BG_SHAPE
.background:
        call checkpoint_for_tick
        ret nc
        call deep_read_descriptor
        ld a,1
        ld (DRAW_DEST),a
        jp RENDERER_DRAW_BG_SHAPE
.page3:
        jp queue_page3_shape
'''
    source = source[:route_start] + new_route + source[route_end:]

    code_marker = "code_end:\n        ASSERT code_end < VARS\n"
    if source.count(code_marker) != 1:
        raise ValueError("VM code end marker changed")
    source = source.replace(code_marker, VM_HELPERS.rstrip() + "\n\ncode_end:\n        ASSERT code_end < VARS\n", 1)
    return source


def patch_renderer(source: str) -> str:
    if RENDERER_TAG in source:
        return source
    jump_marker = "        jp renderer_load_checkpoint\n"
    if source.count(jump_marker) != 1:
        raise ValueError("renderer public jump table changed")
    source = source.replace(
        jump_marker,
        jump_marker + "        jp renderer_deep_prepare\n        jp fill_span\n",
        1,
    )

    draw_marker = """        ld a,0xFF
        ld (SHAPE_OVERRIDE),a
        call decode_shape
        jp restore_bytecode
"""
    draw_repl = """        ld a,0xFF
        ld (SHAPE_OVERRIDE),a
        call deep_draw_current
        jp restore_bytecode
"""
    if source.count(draw_marker) != 1:
        raise ValueError("renderer draw entry changed")
    source = source.replace(draw_marker, draw_repl, 1)

    primitive_marker = """        call shape_fetch               ; vertex count
        ld (VERTEX_COUNT),a
        ld c,a
"""
    primitive_repl = primitive_marker + """        call 0x8903
        ret nc
"""
    if source.count(primitive_marker) != 1:
        raise ValueError("renderer primitive header changed")
    source = source.replace(primitive_marker, primitive_repl, 1)

    end_marker = "\n        END\n"
    if source.count(end_marker) != 1:
        raise ValueError("renderer END marker changed")
    source = source.replace(end_marker, "\n" + RENDERER_COMMON.rstrip() + "\n\n        END\n", 1)
    return source
