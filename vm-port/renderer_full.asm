; ZX Spectrum-native renderer for the size-first Another World intro port.
; Code occupies the bank-5 tail and remains visible while shape/data banks are
; paged at 0xC000.

        DEVICE ZXSPECTRUM48
        ORG 0x5D20

; Public fixed-address jump table used by vm_full.asm.
        jp renderer_present
        jp renderer_draw_shape
        jp renderer_clear_background
        jp renderer_page3_to_background
        jp renderer_noop
        jp renderer_draw_text
        jp renderer_load_resource
        jp renderer_init
        jp renderer_restore_screen
        jp renderer_fill_screen
        jp renderer_page3_to_screen
        jp renderer_screen_to_background
        jp renderer_load_checkpoint

FRAME_COUNT            EQU 0x9308
TARGET_SCREEN          EQU 0x930A
DISPLAY_BIT            EQU 0x930B
TEMP_OFFSET            EQU 0x931A
QUEUE_Y                EQU 0x931C
QUEUE_ZOOM             EQU 0x931E
CURRENT_PALETTE        EQU 0x9322
PENDING_PALETTE        EQU 0x9323
TEXT_ID                EQU 0x9328
TEXT_X                 EQU 0x932A
TEXT_Y                 EQU 0x932B
TEXT_COLOR             EQU 0x932C
DRAW_DEST              EQU 0x932F

DIRTY5                 EQU 0x9000
DIRTY7                 EQU 0x9060
LZ_SRC_PTR             EQU 0x9340
LZ_SRC_BANK            EQU 0x9342
LZ_SWITCH              EQU 0x9343
LZ_FLAGS               EQU 0x9344
LZ_BITS                EQU 0x9345
LZ_RING_POS            EQU 0x9346
LZ_MATCH_REMAIN        EQU 0x9348
LZ_MATCH_POS           EQU 0x934A
LZ_OUT_PTR             EQU 0x934C
LZ_OUT_REMAIN          EQU 0x934E
LZ_FIRST               EQU 0x9350
LZ_SECOND              EQU 0x9351
LZ_LENGTH              EQU 0x9352
LZ_RING                EQU 0x9400
ATTR_STAGE             EQU 0x9C00
PAGE3_QUEUE_COUNT      EQU 0x9F00
PAGE3_BASE             EQU 0x9F01
PAGE3_QUEUE_BASE       EQU 0x9F02
BACKGROUND             EQU 0xA000
PALETTE_SLOTS          EQU 0xBB00
PALETTE_MAPS           EQU 0xBB40
DECISION_DATA          EQU 0xBE00
TEXT_DATA              EQU 0xE680

VERTEX_X               EQU 0x7000
VERTEX_Y               EQU 0x7040
LEFT_EDGE              EQU 0x7080
RIGHT_EDGE             EQU 0x7140
COLOR_DECISIONS        EQU 0x7200

CURRENT_BANK           EQU 0x7280
DEST_MODE              EQU 0x7281
RENDER_ERROR           EQU 0x7282
PRIMITIVE_COUNT        EQU 0x7283
SHAPE_OFFSET           EQU 0x7285
CENTER_X               EQU 0x7287
CENTER_Y               EQU 0x7289
SHAPE_ZOOM             EQU 0x728B
SHAPE_OVERRIDE         EQU 0x728D
BASE_X                 EQU 0x728E
BASE_Y                 EQU 0x7290
CHILD_OFFSET           EQU 0x7292
CHILD_X                EQU 0x7294
CHILD_Y                EQU 0x7296
CHILD_COLOR            EQU 0x7298
CHILD_REMAIN           EQU 0x7299
SHAPE_CODE              EQU 0x729A
LAST_SHAPE_START        EQU 0x729B
ERROR_SHAPE_START       EQU 0x729D
ERROR_SHAPE_CODE        EQU 0x729F
CURRENT_ROOT            EQU 0x72A0
ERROR_ROOT              EQU 0x72A2
POLY_COLOR              EQU 0x72A4
BBOX_WIDTH              EQU 0x72A5
BBOX_HEIGHT             EQU 0x72A7
VERTEX_COUNT            EQU 0x72A9
POLY_X1                 EQU 0x72AA
POLY_Y1                 EQU 0x72AC
MIN_Y                   EQU 0x72AE
MAX_Y                   EQU 0x72AF
EDGE_INDEX              EQU 0x72B0
EDGE_X0                 EQU 0x72B1
EDGE_Y0                 EQU 0x72B2
EDGE_X1                 EQU 0x72B3
EDGE_Y1                 EQU 0x72B4
EDGE_DX                 EQU 0x72B5
EDGE_DY                 EQU 0x72B6
EDGE_SX                 EQU 0x72B7
EDGE_ERR                EQU 0x72B8
EDGE_X                  EQU 0x72BA
EDGE_Y                  EQU 0x72BB
SPAN_Y                  EQU 0x72BC
SPAN_LEFT               EQU 0x72BD
SPAN_RIGHT              EQU 0x72BE
SPAN_FIRST_BYTE         EQU 0x72BF
SPAN_LAST_BYTE          EQU 0x72C0
SPAN_CURRENT_BYTE       EQU 0x72C1
SPAN_MASK               EQU 0x72C2
SPAN_CELL               EQU 0x72C3
BG_BYTE_PTR             EQU 0x72C5
LIST_PTR                EQU 0x72C7
LIST_REMAIN             EQU 0x72C9
TEXT_PTR                EQU 0x72CA
TEXT_START_X            EQU 0x72CC
TEXT_CURRENT_X          EQU 0x72CD
TEXT_CURRENT_Y          EQU 0x72CE
TEXT_CELL_X             EQU 0x72CF
GLYPH_STAGE             EQU 0x5CE0
MULT_ACC                EQU 0x72D0
MULT_MCAND              EQU 0x72D3
MULT_COUNT              EQU 0x72D6
RESTORE_MASK_PTR        EQU 0x72D7
RESTORE_GROUP           EQU 0x72D9
RESTORE_BIT             EQU 0x72DA
RESTORE_CELL            EQU 0x72DB
RESTORE_MASK            EQU 0x72DD
DIRTY_BYTE_INDEX        EQU 0x72DE
DIRTY_BIT_MASK          EQU 0x72E0
CELL_FILL_VALUE         EQU 0x72E1
CELL_OFFSET             EQU 0x72E2
TEXT_CHAR               EQU 0x72E4
TEXT_GLYPH_ROW          EQU 0x72E5
TEXT_SCREEN_Y           EQU 0x72E6
TEXT_BITMAP_PTR         EQU 0x72E7
MIN_X                   EQU 0x72E9
MAX_X                   EQU 0x72EA
DIRTY_RECT_X0           EQU 0x72EB
DIRTY_RECT_X1           EQU 0x72EC
DIRTY_RECT_Y            EQU 0x72ED
DIRTY_RECT_Y1           EQU 0x72EE
ATTR_RESTART_INDEX      EQU 0x72EF

        INCLUDE "generated_full_layout.inc"
BITMAP19                EQU 0x7400
ATTR_CHANGE_MASK        EQU 0x5C75

renderer_noop:
        ret

renderer_load_checkpoint:
        add a,a
        ld l,a
        ld h,0
        ld de,checkpoint_ptrs
        add hl,de
        ld e,(hl)
        inc hl
        ld d,(hl)
        ex de,hl
        ld a,7
        ld c,0
        call lz_reset
        ld de,BACKGROUND
        ld bc,0x1800
        call lz_decode
        call restart_middle_attributes
        call mark_both_full
        jp restore_bytecode

checkpoint_ptrs:
        dw CHECKPOINT0,CHECKPOINT1,CHECKPOINT2,CHECKPOINT3,CHECKPOINT4

renderer_init:
        ld a,1
        ld (CURRENT_BANK),a
        call mark_both_full
        xor a
        ld hl,ATTR_STAGE
        ld de,ATTR_STAGE+1
        ld bc,0x02FF
        ld (hl),a
        ldir
        ret

; A sampled presentation: publish the staged attributes to both physical
; screens, advance the compact stream, and leave bytecode bank 1 mapped.
renderer_present:
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
        inc hl
        ld (FRAME_COUNT),hl
        ld de,298
        or a
        sbc hl,de
        jp z,restore_bytecode
        ld hl,(FRAME_COUNT)
        call attribute_changes_next
        or a
        jp z,restore_bytecode
        ld de,ATTR_STAGE
        ld bc,0x0300
        call lz_decode
        jp restore_bytecode

attribute_changes_next:
        ld a,l
        and 7
        ld b,a
        srl h
        rr l
        srl h
        rr l
        srl h
        rr l
        ld de,ATTR_CHANGE_MASK
        add hl,de
        ld c,(hl)
        ld a,b
        or a
        jr z,.ready
.shift:
        srl c
        djnz .shift
.ready:
        ld a,c
        and 1
        ret

; Checkpoint decompression uses the same 2 KiB LZSS history as the resumable
; attribute stream. Rebuild the latter's state by decoding only the distinct
; maps reached since resource 71 began at sampled frame 6. Five restarts are
; substantially smaller than a second history buffer or independent streams.
restart_middle_attributes:
        ld hl,0xEE00
        ld a,1
        ld c,1
        call lz_reset
        ld de,ATTR_STAGE
        ld bc,0x0300
        call lz_decode                 ; first map, sampled frame 6
        ld hl,6
        ld (ATTR_RESTART_INDEX),hl
.loop:
        ld hl,(ATTR_RESTART_INDEX)
        call attribute_changes_next
        or a
        jr z,.map_ready
        ld de,ATTR_STAGE
        ld bc,0x0300
        call lz_decode
.map_ready:
        ld hl,(ATTR_RESTART_INDEX)
        ld de,(FRAME_COUNT)
        or a
        sbc hl,de
        ret z
        ld hl,(ATTR_RESTART_INDEX)
        inc hl
        ld (ATTR_RESTART_INDEX),hl
        jr .loop

renderer_draw_shape:
        ld a,(DRAW_DEST)
        ld (DEST_MODE),a
        ld hl,(TEMP_OFFSET)
        ld (CURRENT_ROOT),hl
        ld de,(TEMP_OFFSET)
        ld (SHAPE_OFFSET),de
        ld de,(0x9317)                ; VM TMP_WORD: centre X
        ld (CENTER_X),de
        ld de,(QUEUE_Y)
        ld (CENTER_Y),de
        ld de,(QUEUE_ZOOM)
        ld (SHAPE_ZOOM),de
        ld a,0xFF
        ld (SHAPE_OVERRIDE),a
        call decode_shape
        jp restore_bytecode

renderer_draw_text:
        ld a,(DRAW_DEST)
        ld (DEST_MODE),a
        call draw_text_core
        jp restore_bytecode

renderer_clear_background:
        ld (POLY_COLOR),a
        ld a,1
        ld (DEST_MODE),a
        call fill_destination_full
        call mark_both_full
        jp restore_bytecode

renderer_fill_screen:
        ld (POLY_COLOR),a
        xor a
        ld (DEST_MODE),a
        call fill_destination_full
        call mark_target_full
        jr restore_bytecode

renderer_restore_screen:
        xor a
        ld (DEST_MODE),a
        call restore_dirty_cells
        jr restore_bytecode

renderer_screen_to_background:
        ld a,(TARGET_SCREEN)
        or a
        jr z,.bank5
        ld a,(DISPLAY_BIT)
        or 7
        call page_a
        ld hl,0xC000
        jr .copy
.bank5:
        ld hl,0x4000
.copy:
        ld de,BACKGROUND
        ld bc,0x1800
        ldir
        call mark_both_full
        jr restore_bytecode

renderer_page3_to_background:
        ld a,1
        ld (DEST_MODE),a
        ld a,(PAGE3_BASE)
        bit 7,a
        jr z,.replay
        and 0x0F
        ld (POLY_COLOR),a
        call fill_destination_full
        call mark_both_full
.replay:
        call replay_page3
        jr restore_bytecode

renderer_page3_to_screen:
        xor a
        ld (DEST_MODE),a
        ld a,(PAGE3_BASE)
        bit 7,a
        jr z,.background
        and 0x0F
        ld (POLY_COLOR),a
        call fill_destination_full
        call mark_target_full
        jr .replay
.background:
        call restore_dirty_cells
.replay:
        call replay_page3
        jr restore_bytecode

restore_bytecode:
        ld a,(DISPLAY_BIT)
        or 1
        jp page_a

replay_page3:
        ld a,(PAGE3_QUEUE_COUNT)
        or a
        ret z
        ld (LIST_REMAIN),a
        ld hl,PAGE3_QUEUE_BASE
        ld (LIST_PTR),hl
.loop:
        ld hl,(LIST_PTR)
        ld a,(hl)
        inc hl
        or a
        jr nz,.text
        ld e,(hl)
        inc hl
        ld d,(hl)
        inc hl
        ld (SHAPE_OFFSET),de
        ld (CURRENT_ROOT),de
        ld e,(hl)
        inc hl
        ld d,(hl)
        inc hl
        ld (CENTER_X),de
        ld e,(hl)
        inc hl
        ld d,(hl)
        inc hl
        ld (CENTER_Y),de
        ld e,(hl)
        inc hl
        ld d,(hl)
        inc hl
        ld (SHAPE_ZOOM),de
        ld a,(hl)
        ld (SHAPE_OVERRIDE),a
        call decode_shape
        jr .next
.text:
        ld e,(hl)
        inc hl
        ld d,(hl)
        inc hl
        ld (TEXT_ID),de
        ld a,(hl)
        ld (TEXT_X),a
        inc hl
        inc hl
        ld a,(hl)
        ld (TEXT_Y),a
        inc hl
        inc hl
        ld a,(hl)
        ld (TEXT_COLOR),a
        call draw_text_core
.next:
        ld hl,(LIST_PTR)
        ld de,10
        add hl,de
        ld (LIST_PTR),hl
        ld a,(LIST_REMAIN)
        dec a
        ld (LIST_REMAIN),a
        jr nz,.loop
        ret

renderer_load_resource:
        ld a,d
        or a
        ret nz
        ld a,e
        cp 18
        jr z,.resource18
        cp 71
        jr z,.resource71
        cp 19
        jr z,.resource19
        ret
.resource18:
        ld hl,BITMAP18
        ld a,7
        ld c,0
        call lz_reset
        call load_bitmap
        ld hl,ATTR_FIRST
        ld a,7
        ld c,0
        jr .attribute_stream
.resource71:
        ld hl,BITMAP71
        ld a,7
        ld c,0
        call lz_reset
        call load_bitmap
        ld hl,0xEE00
        ld a,1
        ld c,1
        jr .attribute_stream
.resource19:
        ld hl,BITMAP19
        ld a,0xFF                    ; fixed bank-5 source
        ld c,0
        call lz_reset
        call load_bitmap
        ld hl,ATTR_LAST
        ld a,7
        ld c,0
.attribute_stream:
        call lz_reset
        ld de,ATTR_STAGE
        ld bc,0x0300
        call lz_decode
        call mark_both_full
        jp restore_bytecode

load_bitmap:
        ld de,BACKGROUND
        ld bc,0x1B00
        jp lz_decode

; Initialise the resumable 2 KiB-window LZSS reader.
; HL=source, A=source bank (0xFF fixed), C=transition bank1:EE00 -> bank7:DB00.
lz_reset:
        ld (LZ_SRC_PTR),hl
        ld (LZ_SRC_BANK),a
        ld a,c
        ld (LZ_SWITCH),a
        xor a
        ld (LZ_FLAGS),a
        ld (LZ_BITS),a
        ld hl,0
        ld (LZ_RING_POS),hl
        ld (LZ_MATCH_REMAIN),hl
        ld (LZ_MATCH_POS),hl
        ret

; DE=output, BC=number of bytes. Decoder state may stop in the middle of a
; match and resume on the next 768-byte attribute frame.
lz_decode:
        ld (LZ_OUT_PTR),de
        ld (LZ_OUT_REMAIN),bc
.loop:
        ld hl,(LZ_OUT_REMAIN)
        ld a,h
        or l
        ret z
        call lz_next_byte
        ld hl,(LZ_OUT_PTR)
        ld (hl),a
        inc hl
        ld (LZ_OUT_PTR),hl
        ld hl,(LZ_OUT_REMAIN)
        dec hl
        ld (LZ_OUT_REMAIN),hl
        jr .loop

lz_next_byte:
        ld hl,(LZ_MATCH_REMAIN)
        ld a,h
        or l
        jr nz,.match_byte

        ld a,(LZ_BITS)
        or a
        jr nz,.have_flags
        call lz_fetch
        ld (LZ_FLAGS),a
        ld a,8
        ld (LZ_BITS),a
.have_flags:
        ld a,(LZ_FLAGS)
        srl a
        ld (LZ_FLAGS),a
        ld a,(LZ_BITS)
        dec a
        ld (LZ_BITS),a
        jr c,.literal

        call lz_fetch
        ld (LZ_FIRST),a
        call lz_fetch
        ld (LZ_SECOND),a

        ; distance = ((first << 3) | (second >> 5)) + 1
        ld a,(LZ_FIRST)
        ld h,0
        ld l,a
        add hl,hl
        add hl,hl
        add hl,hl
        ld a,(LZ_SECOND)
        rrca
        rrca
        rrca
        rrca
        rrca
        and 7
        ld e,a
        ld d,0
        add hl,de
        inc hl
        ex de,hl                     ; DE=distance
        ld hl,(LZ_RING_POS)
        or a
        sbc hl,de
        ld a,h
        and 7
        ld h,a
        ld (LZ_MATCH_POS),hl

        ld a,(LZ_SECOND)
        and 31
        ld l,a
        ld h,0
        cp 31
        jr nz,.length_ready
.extension:
        push hl
        call lz_fetch
        pop hl
        ld e,a
        ld d,0
        add hl,de
        cp 255
        jr z,.extension
.length_ready:
        ld de,3
        add hl,de
        ld (LZ_MATCH_REMAIN),hl

.match_byte:
        ld hl,(LZ_MATCH_POS)
        ld de,LZ_RING
        add hl,de
        ld a,(hl)
        push af
        ld hl,(LZ_MATCH_POS)
        inc hl
        ld a,h
        and 7
        ld h,a
        ld (LZ_MATCH_POS),hl
        ld hl,(LZ_MATCH_REMAIN)
        dec hl
        ld (LZ_MATCH_REMAIN),hl
        pop af
        jr .emit
.literal:
        call lz_fetch
.emit:
        push af
        ld hl,(LZ_RING_POS)
        ld de,LZ_RING
        add hl,de
        pop af
        ld (hl),a
        push af
        ld hl,(LZ_RING_POS)
        inc hl
        ld a,h
        and 7
        ld h,a
        ld (LZ_RING_POS),hl
        pop af
        ret

lz_fetch:
        ld a,(LZ_SRC_BANK)
        cp 0xFF
        jr z,.mapped
        ld b,a
        ld a,(CURRENT_BANK)
        cp b
        jr z,.mapped
        ld a,(DISPLAY_BIT)
        or b
        call page_a
.mapped:
        ld hl,(LZ_SRC_PTR)
        ld a,(hl)
        push af
        inc hl
        ld (LZ_SRC_PTR),hl
        ld a,h
        or l
        jr nz,.done
        ld a,(LZ_SWITCH)
        or a
        jr z,.done
        xor a
        ld (LZ_SWITCH),a
        ld a,7
        ld (LZ_SRC_BANK),a
        ld hl,ATTR_MIDDLE_CHUNK1
        ld (LZ_SRC_PTR),hl
.done:
        pop af
        ret

; ---------------------------------------------------------------------------
; Cell-granular background restoration and full-page colour operations

mark_both_full:
        ld a,0xFF
        ld hl,DIRTY5
        ld de,DIRTY5+1
        ld bc,95
        ld (hl),a
        ldir
        ld hl,DIRTY7
        ld de,DIRTY7+1
        ld bc,95
        ld (hl),a
        ldir
        ret

mark_target_full:
        ld a,(TARGET_SCREEN)
        or a
        ld hl,DIRTY5
        jr z,.selected
        ld hl,DIRTY7
.selected:
        ld a,0xFF
        ld d,h
        ld e,l
        inc de
        ld bc,95
        ld (hl),a
        ldir
        ret

; Mark SPAN_CELL for restoration the next time its physical screen is reused.
; Background changes mark both screens because either can contain an old copy.
mark_span_dirty:
        ld hl,(SPAN_CELL)
        ld a,l
        and 7
        ld c,a
        srl h
        rr l
        srl h
        rr l
        srl h
        rr l
        ld (DIRTY_BYTE_INDEX),hl
        ld b,1
        ld a,c
        or a
        jr z,.mask_ready
.mask_shift:
        sla b
        dec a
        jr nz,.mask_shift
.mask_ready:
        ld a,b
        ld (DIRTY_BIT_MASK),a
        ld a,(DEST_MODE)
        or a
        jr z,.target_only
        ld de,DIRTY5
        call mark_one_dirty
        ld de,DIRTY7
        jr mark_one_dirty
.target_only:
        ld a,(TARGET_SCREEN)
        or a
        ld de,DIRTY5
        jr z,mark_one_dirty
        ld de,DIRTY7
mark_one_dirty:
        ld hl,(DIRTY_BYTE_INDEX)
        add hl,de
        ld a,(DIRTY_BIT_MASK)
        or (hl)
        ld (hl),a
        ret

mark_polygon_dirty:
        ld a,(MIN_X)
        srl a
        srl a
        srl a
        ld (DIRTY_RECT_X0),a
        ld a,(MAX_X)
        srl a
        srl a
        srl a
        ld (DIRTY_RECT_X1),a
        ld a,(MIN_Y)
        srl a
        srl a
        srl a
        ld (DIRTY_RECT_Y),a
        ld a,(MAX_Y)
        srl a
        srl a
        srl a
        ld (DIRTY_RECT_Y1),a
.row:
        ld a,(DIRTY_RECT_Y)
        ld l,a
        ld h,0
        add hl,hl
        add hl,hl
        add hl,hl
        add hl,hl
        add hl,hl
        ld a,(DIRTY_RECT_X0)
        ld e,a
        ld d,0
        add hl,de
        ld (SPAN_CELL),hl
        ld a,(DIRTY_RECT_X0)
        ld b,a
.column:
        push bc
        call mark_span_dirty
        pop bc
        ld hl,(SPAN_CELL)
        inc hl
        ld (SPAN_CELL),hl
        ld a,(DIRTY_RECT_X1)
        cp b
        jr z,.row_done
        inc b
        jr .column
.row_done:
        ld a,(DIRTY_RECT_Y)
        ld b,a
        ld a,(DIRTY_RECT_Y1)
        cp b
        ret z
        ld a,b
        inc a
        ld (DIRTY_RECT_Y),a
        jr .row

restore_dirty_cells:
        call map_destination
        ld a,(TARGET_SCREEN)
        or a
        ld hl,DIRTY5
        jr z,.base_ready
        ld hl,DIRTY7
.base_ready:
        ld (RESTORE_MASK_PTR),hl
        xor a
        ld (RESTORE_GROUP),a
.group_loop:
        ld hl,(RESTORE_MASK_PTR)
        ld a,(hl)
        ld (RESTORE_MASK),a
        xor a
        ld (hl),a
        ld (RESTORE_BIT),a
.bit_loop:
        ld a,(RESTORE_MASK)
        srl a
        ld (RESTORE_MASK),a
        jr nc,.next_bit
        ld a,(RESTORE_GROUP)
        ld l,a
        ld h,0
        add hl,hl
        add hl,hl
        add hl,hl
        ld a,(RESTORE_BIT)
        ld e,a
        ld d,0
        add hl,de
        ld (RESTORE_CELL),hl
        call copy_background_cell
.next_bit:
        ld a,(RESTORE_BIT)
        inc a
        ld (RESTORE_BIT),a
        cp 8
        jr nz,.bit_loop
        ld hl,(RESTORE_MASK_PTR)
        inc hl
        ld (RESTORE_MASK_PTR),hl
        ld a,(RESTORE_GROUP)
        inc a
        ld (RESTORE_GROUP),a
        cp 96
        jr nz,.group_loop
        ret

copy_background_cell:
        ld hl,(RESTORE_CELL)
        call cell_to_offset
        ld (CELL_OFFSET),hl
        ld de,BACKGROUND
        add hl,de
        push hl                       ; source
        ld hl,(CELL_OFFSET)
        ld a,(TARGET_SCREEN)
        or a
        ld de,0x4000
        jr z,.target_ready
        ld de,0xC000
.target_ready:
        add hl,de
        ex de,hl                     ; DE=destination
        pop hl                       ; HL=background source
        ld b,8
.row:
        ld a,(hl)
        ld (de),a
        inc h                         ; next Spectrum scanline in this cell
        inc d
        djnz .row
        ret

; Fill the selected destination using the current attribute map and one
; original palette colour.  A cell becomes all INK or all PAPER.
fill_destination_full:
        call prepare_color_decisions
        call map_destination
        ld hl,0
        ld (RESTORE_CELL),hl
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
        ld de,0x0300
        or a
        sbc hl,de
        jr nz,.cell_loop
        ret

fill_destination_cell:
        call cell_to_offset
        ld a,(DEST_MODE)
        or a
        ld de,BACKGROUND
        jr nz,.base_ready
        ld a,(TARGET_SCREEN)
        or a
        ld de,0x4000
        jr z,.base_ready
        ld de,0xC000
.base_ready:
        add hl,de
        ex de,hl
        ld a,(CELL_FILL_VALUE)
        ld b,8
.row:
        ld (de),a
        inc d
        djnz .row
        ret

; HL=cell 0..767, return Spectrum bitmap offset of its top scanline.
cell_to_offset:
        ld a,l
        and 31
        ld e,a                        ; x byte
        srl h
        rr l
        srl h
        rr l
        srl h
        rr l
        srl h
        rr l
        srl h
        rr l                          ; HL=character row 0..23
        ld a,l
        and 7
        rlca
        rlca
        rlca
        rlca
        rlca                           ; within-third row * 32
        add a,e
        ld e,a
        ld a,l
        srl a
        srl a
        srl a
        rlca
        rlca
        rlca                           ; third * 8 high bytes
        ld d,a
        ex de,hl
        ret

map_destination:
        ld a,(DEST_MODE)
        or a
        ret nz
        ld a,(TARGET_SCREEN)
        or a
        ret z
        ld a,(DISPLAY_BIT)
        or 7
        jp page_a

; ---------------------------------------------------------------------------
; Original compound-shape resource decoder

; HL=byte offset in the original shape resource, DE=center X, BC=center Y,
; A=colour override (0xFF means use each primitive's encoded colour).
draw_shape_root:
        ld (SHAPE_OFFSET),hl
        ld (CENTER_X),de
        ld (CENTER_Y),bc
        ld (SHAPE_OVERRIDE),a
        jp decode_shape

decode_shape:
        ld hl,(SHAPE_OFFSET)
        ld (LAST_SHAPE_START),hl
        call shape_fetch
        ld (SHAPE_CODE),a
        cp 0xC0
        jp nc,decode_primitive
        and 0x3F
        cp 2
        jr z,decode_compound
        ld a,(RENDER_ERROR)
        or a
        ret nz
        ld hl,(LAST_SHAPE_START)
        ld (ERROR_SHAPE_START),hl
        ld hl,(CURRENT_ROOT)
        ld (ERROR_ROOT),hl
        ld a,(SHAPE_CODE)
        ld (ERROR_SHAPE_CODE),a
        ld a,2
        ld (RENDER_ERROR),a
        ret

decode_compound:
        call shape_fetch               ; anchor X
        call scale_byte_zoom
        ld hl,(CENTER_X)
        or a
        sbc hl,de
        ld (BASE_X),hl

        call shape_fetch               ; anchor Y
        call scale_byte_zoom
        ld hl,(CENTER_Y)
        or a
        sbc hl,de
        ld (BASE_Y),hl

        call shape_fetch               ; encoded count is N-1
        inc a
        ld (CHILD_REMAIN),a

.child_loop:
        call shape_fetch_word          ; DE = big-endian child word
        ld a,d
        and 0x80
        ld (CHILD_COLOR),a             ; temporary extension flag
        ex de,hl
        add hl,hl
        ld (CHILD_OFFSET),hl

        call shape_fetch               ; relative X
        call scale_byte_zoom
        ld hl,(BASE_X)
        add hl,de
        ld (CHILD_X),hl

        call shape_fetch               ; relative Y
        call scale_byte_zoom
        ld hl,(BASE_Y)
        add hl,de
        ld (CHILD_Y),hl

        ld a,(CHILD_COLOR)
        or a
        jr z,.default_color
        call shape_fetch               ; explicit colour
        ld (CHILD_COLOR),a
        call shape_fetch               ; sprite/head number, unused in DOS demo
        jr .child_ready
.default_color:
        ld a,0xFF
        ld (CHILD_COLOR),a
.child_ready:
        ; Preserve the parent's continuation and compound-local state across
        ; the recursive child decode. The observed intro nesting depth is 3.
        ld hl,(SHAPE_OFFSET)
        push hl
        ld hl,(BASE_X)
        push hl
        ld hl,(BASE_Y)
        push hl
        ld a,(CHILD_REMAIN)
        push af

        ld hl,(CHILD_OFFSET)
        ld (SHAPE_OFFSET),hl
        ld hl,(CHILD_X)
        ld (CENTER_X),hl
        ld hl,(CHILD_Y)
        ld (CENTER_Y),hl
        ld a,(CHILD_COLOR)
        ld (SHAPE_OVERRIDE),a
        call decode_shape

        pop af
        ld (CHILD_REMAIN),a
        pop hl
        ld (BASE_Y),hl
        pop hl
        ld (BASE_X),hl
        pop hl
        ld (SHAPE_OFFSET),hl

        ld a,(CHILD_REMAIN)
        dec a
        ld (CHILD_REMAIN),a
        jp nz,.child_loop
        ret

decode_primitive:
        ld a,(SHAPE_OVERRIDE)
        bit 7,a
        jr z,.override_color
        ld a,(SHAPE_CODE)
        and 0x3F
.override_color:
        cp 17
        jr c,.color_ok
        cp 17
        jr z,.color_ok
        xor a
.color_ok:
        ld (POLY_COLOR),a

        call shape_fetch               ; bounding width
        call scale_byte_zoom
        ld (BBOX_WIDTH),de
        srl d
        rr e
        ld hl,(CENTER_X)
        or a
        sbc hl,de
        ld (POLY_X1),hl

        call shape_fetch               ; bounding height
        call scale_byte_zoom
        ld (BBOX_HEIGHT),de
        srl d
        rr e
        ld hl,(CENTER_Y)
        or a
        sbc hl,de
        ld (POLY_Y1),hl

        call shape_fetch               ; vertex count
        ld (VERTEX_COUNT),a
        ld c,a
        ld hl,(BBOX_WIDTH)
        ld a,h
        or l
        jr nz,.decode_vertices
        ld hl,(BBOX_HEIGHT)
        ld a,h
        or a
        jr nz,.decode_vertices
        ld a,l
        cp 2
        jr nc,.decode_vertices

        ; Point resources carry a nominal four-vertex payload which is never
        ; consulted by the original renderer. Skip it without paging bytes.
        ld a,c
        add a,a
        ld e,a
        ld d,0
        ld hl,(SHAPE_OFFSET)
        add hl,de
        ld (SHAPE_OFFSET),hl
        ld hl,(PRIMITIVE_COUNT)
        inc hl
        ld (PRIMITIVE_COUNT),hl
        call prepare_color_decisions
        ld hl,(CENTER_X)
        call scale_x_clamped
        ld (SPAN_LEFT),a
        ld (SPAN_RIGHT),a
        srl a
        srl a
        srl a
        ld (DIRTY_RECT_X0),a
        ld a,(CENTER_Y)
        ld l,a
        ld a,(CENTER_Y+1)
        ld h,a
        call scale_y_clamped
        ld (SPAN_Y),a
        push af
        srl a
        srl a
        srl a
        ld l,a
        ld h,0
        add hl,hl
        add hl,hl
        add hl,hl
        add hl,hl
        add hl,hl
        ld a,(DIRTY_RECT_X0)
        ld e,a
        ld d,0
        add hl,de
        ld (SPAN_CELL),hl
        call mark_span_dirty
        pop af
        ld (SPAN_Y),a
        call map_destination
        jp fill_span

.decode_vertices:
        ld a,c
        ld b,a
        ld ix,VERTEX_X
        ld iy,VERTEX_Y
        ld a,191
        ld (MIN_Y),a
        ld a,255
        ld (MIN_X),a
        xor a
        ld (MAX_Y),a
        ld (MAX_X),a
.vertex_loop:
        call shape_fetch               ; relative X
        call scale_byte_zoom
        ld hl,(POLY_X1)
        add hl,de
        push bc
        call scale_x_clamped
        pop bc
        ld (ix+0),a
        inc ix
        ld e,a
        ld a,(MIN_X)
        cp e
        jr c,.min_x_done
        jr z,.min_x_done
        ld a,e
        ld (MIN_X),a
.min_x_done:
        ld a,(MAX_X)
        cp e
        jr nc,.max_x_done
        ld a,e
        ld (MAX_X),a
.max_x_done:

        call shape_fetch               ; relative Y
        call scale_byte_zoom
        ld hl,(POLY_Y1)
        add hl,de
        push bc
        call scale_y_clamped
        pop bc
        ld (iy+0),a
        inc iy

        ld e,a
        ld a,(MIN_Y)
        cp e
        jr c,.min_done
        jr z,.min_done
        ld a,e
        ld (MIN_Y),a
.min_done:
        ld a,(MAX_Y)
        cp e
        jr nc,.max_done
        ld a,e
        ld (MAX_Y),a
.max_done:
        djnz .vertex_loop

        ld hl,(PRIMITIVE_COUNT)
        inc hl
        ld (PRIMITIVE_COUNT),hl
        call prepare_color_decisions
        call mark_polygon_dirty

        ld hl,(BBOX_WIDTH)
        ld a,h
        or l
        jr nz,.polygon
        ld hl,(BBOX_HEIGHT)
        ld a,h
        or a
        jr nz,.polygon
        ld a,l
        cp 2
        jr nc,.polygon
        ld hl,(CENTER_X)
        call scale_x_clamped
        ld (SPAN_LEFT),a
        ld (SPAN_RIGHT),a
        ld hl,(CENTER_Y)
        call scale_y_clamped
        ld (SPAN_Y),a
        call map_destination
        call fill_span
        ret
.polygon:
        call fill_polygon
        ret

; A=resource coordinate, return DE=floor(A * SHAPE_ZOOM / 64).
; Zoom 64 is overwhelmingly common and has a two-instruction fast path.
scale_byte_zoom:
        push bc
        ld e,a
        ld d,0
        ld hl,(SHAPE_ZOOM)
        ld a,h
        or a
        jr nz,.multiply
        ld a,l
        cp 64
        jr z,.return
.multiply:
        xor a
        ld (MULT_ACC),a
        ld (MULT_ACC+1),a
        ld (MULT_ACC+2),a
        ld hl,(SHAPE_ZOOM)
        ld (MULT_MCAND),hl
        xor a
        ld (MULT_MCAND+2),a
        ld a,e
        ld (MULT_COUNT),a
        ld b,8
.bit:
        ld a,(MULT_COUNT)
        rrca
        ld (MULT_COUNT),a
        jr nc,.shift
        ld hl,(MULT_ACC)
        ld de,(MULT_MCAND)
        add hl,de
        ld (MULT_ACC),hl
        ld a,(MULT_ACC+2)
        ld c,a
        ld a,(MULT_MCAND+2)
        adc a,c
        ld (MULT_ACC+2),a
.shift:
        ld hl,(MULT_MCAND)
        add hl,hl
        ld (MULT_MCAND),hl
        ld a,(MULT_MCAND+2)
        rla
        ld (MULT_MCAND+2),a
        djnz .bit
        ; 24-bit product >> 6.  Only the low 16 result bits are relevant.
        ld a,(MULT_ACC)
        ld e,a
        ld a,(MULT_ACC+1)
        ld d,a
        ld a,(MULT_ACC+2)
        ld c,a
        ld b,6
.divide:
        srl c
        rr d
        rr e
        djnz .divide
.return:
        pop bc
        ret

; Scale original 320x200 coordinates to 256x192. Inputs outside the original
; viewport are conservatively clamped before rasterization.
scale_x_clamped:
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
        jr c,.divide
        ld a,255
        ret
.divide:
        push hl                       ; original value
        ld de,5
        ld bc,0                       ; quotient
.loop:
        or a
        sbc hl,de
        jr c,.done
        inc bc
        jr .loop
.done:
        pop hl
        or a
        sbc hl,bc                     ; x - floor(x/5)
        ld a,l
        ret

scale_y_clamped:
        bit 7,h
        jr z,.non_negative
        xor a
        ret
.non_negative:
        push hl
        ld de,200
        or a
        sbc hl,de
        pop hl
        jr c,.divide
        ld a,191
        ret
.divide:
        push hl
        ld de,25
        ld bc,0
.loop:
        or a
        sbc hl,de
        jr c,.done
        inc bc
        jr .loop
.done:
        pop hl
        or a
        sbc hl,bc                     ; y - floor(y/25)
        ld a,l
        ret

; ---------------------------------------------------------------------------
; Polygon edge construction and scanline fill

fill_polygon:
        ; Empty edge tables are encoded as left=255, right=0.
        ld hl,LEFT_EDGE
        ld de,LEFT_EDGE+1
        ld bc,191
        ld (hl),255
        ldir
        ld hl,RIGHT_EDGE
        ld de,RIGHT_EDGE+1
        ld bc,191
        xor a
        ld (hl),a
        ldir

        xor a
        ld (EDGE_INDEX),a
.edge_loop:
        ld a,(EDGE_INDEX)
        ld c,a
        inc a
        ld b,a
        ld a,(VERTEX_COUNT)
        cp b
        jr nz,.next_ready
        ld b,0
.next_ready:
        call load_edge_pair
        call raster_edge

        ld a,(EDGE_INDEX)
        inc a
        ld (EDGE_INDEX),a
        ld b,a
        ld a,(VERTEX_COUNT)
        cp b
        jp nz,.edge_loop

        call map_destination
        ld a,(MIN_Y)
        ld (SPAN_Y),a
.scanline_loop:
        ld a,(SPAN_Y)
        ld e,a
        ld d,0
        ld hl,LEFT_EDGE
        add hl,de
        ld a,(hl)
        ld (SPAN_LEFT),a
        ld hl,RIGHT_EDGE
        add hl,de
        ld a,(hl)
        ld (SPAN_RIGHT),a
        ld e,a
        ld a,(SPAN_LEFT)
        cp e
        jr c,.draw_span
        jr z,.draw_span
        jr .next_scanline
.draw_span:
        call fill_span
.next_scanline:
        ld a,(SPAN_Y)
        ld b,a
        ld a,(MAX_Y)
        cp b
        ret z
        ld a,b
        inc a
        ld (SPAN_Y),a
        jr .scanline_loop

; C=index of the first endpoint, B=index of the second endpoint.
load_edge_pair:
        ld e,c
        ld d,0
        ld hl,VERTEX_X
        add hl,de
        ld a,(hl)
        ld (EDGE_X0),a
        ld hl,VERTEX_Y
        add hl,de
        ld a,(hl)
        ld (EDGE_Y0),a

        ld e,b
        ld d,0
        ld hl,VERTEX_X
        add hl,de
        ld a,(hl)
        ld (EDGE_X1),a
        ld hl,VERTEX_Y
        add hl,de
        ld a,(hl)
        ld (EDGE_Y1),a
        ret

raster_edge:
        ; Sort endpoints by Y so the scan conversion always advances down.
        ld a,(EDGE_Y0)
        ld b,a
        ld a,(EDGE_Y1)
        cp b
        jr nc,.sorted
        ld a,(EDGE_Y0)
        ld b,a
        ld a,(EDGE_Y1)
        ld (EDGE_Y0),a
        ld a,b
        ld (EDGE_Y1),a
        ld a,(EDGE_X0)
        ld b,a
        ld a,(EDGE_X1)
        ld (EDGE_X0),a
        ld a,b
        ld (EDGE_X1),a
.sorted:
        ld a,(EDGE_Y1)
        ld b,a
        ld a,(EDGE_Y0)
        ld c,a
        ld a,b
        sub c
        ld (EDGE_DY),a
        jr nz,.non_horizontal

        ld a,(EDGE_X0)
        ld (EDGE_X),a
        ld a,(EDGE_Y0)
        ld (EDGE_Y),a
        call update_boundary
        ld a,(EDGE_X1)
        ld (EDGE_X),a
        jp update_boundary

.non_horizontal:
        ld a,(EDGE_X1)
        ld b,a
        ld a,(EDGE_X0)
        ld c,a
        ld a,b
        sub c
        jr c,.negative_dx
        ld (EDGE_DX),a
        ld a,1
        ld (EDGE_SX),a
        jr .edge_ready
.negative_dx:
        neg
        ld (EDGE_DX),a
        ld a,0xFF
        ld (EDGE_SX),a
.edge_ready:
        xor a
        ld (EDGE_ERR),a
        ld (EDGE_ERR+1),a
        ld a,(EDGE_X0)
        ld (EDGE_X),a
        ld a,(EDGE_Y0)
        ld (EDGE_Y),a

.y_loop:
        call update_boundary
        ld a,(EDGE_Y)
        ld b,a
        ld a,(EDGE_Y1)
        cp b
        ret z

        ld a,(EDGE_DX)
        ld e,a
        ld d,0
        ld hl,(EDGE_ERR)
        add hl,de
        ld (EDGE_ERR),hl
.x_loop:
        ld a,(EDGE_DY)
        ld e,a
        ld d,0
        ld hl,(EDGE_ERR)
        or a
        sbc hl,de
        jr c,.advance_y
        ld (EDGE_ERR),hl
        ld a,(EDGE_X)
        ld b,a
        ld a,(EDGE_SX)
        add a,b
        ld (EDGE_X),a
        jr .x_loop
.advance_y:
        ld a,(EDGE_Y)
        inc a
        ld (EDGE_Y),a
        jr .y_loop

update_boundary:
        ld a,(EDGE_Y)
        ld e,a
        ld d,0
        ld hl,LEFT_EDGE
        add hl,de
        ld a,(EDGE_X)
        ld b,a
        ld a,(hl)
        cp b
        jr c,.left_done
        jr z,.left_done
        ld (hl),b
.left_done:
        ld hl,RIGHT_EDGE
        add hl,de
        ld a,(hl)
        cp b
        ret nc
        ld (hl),b
        ret

fill_span:
        ld a,(SPAN_LEFT)
        srl a
        srl a
        srl a
        ld (SPAN_FIRST_BYTE),a
        ld (SPAN_CURRENT_BYTE),a
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

        ; Attribute-stage pointer and linear cell number.
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

.byte_loop:
        ld a,0xFF
        ld (SPAN_MASK),a
        ld a,(SPAN_CURRENT_BYTE)
        ld b,a
        ld a,(SPAN_FIRST_BYTE)
        cp b
        jr nz,.not_first
        ld a,(SPAN_LEFT)
        and 7
        ld c,a
        ld b,0
        ld hl,first_masks
        add hl,bc
        ld a,(hl)
        ld (SPAN_MASK),a
.not_first:
        ld a,(SPAN_CURRENT_BYTE)
        ld b,a
        ld a,(SPAN_LAST_BYTE)
        cp b
        jr nz,.mask_ready
        ld a,(SPAN_RIGHT)
        and 7
        ld c,a
        ld b,0
        ld hl,last_masks
        add hl,bc
        ld a,(SPAN_MASK)
        and (hl)
        ld (SPAN_MASK),a
.mask_ready:
        ld a,(POLY_COLOR)
        cp 17
        jr z,.page_color
        ld a,(iy+0)
        call decision_ink
        or a
        jr z,.paper
        ld a,(SPAN_MASK)
        or (ix+0)
        ld (ix+0),a
        jr .byte_done
.paper:
        ld a,(SPAN_MASK)
        cpl
        and (ix+0)
        ld (ix+0),a
        jr .byte_done
.page_color:
        ld a,(DEST_MODE)
        or a
        jr nz,.byte_done              ; page colour on page 0 is a no-op
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
.byte_done:
        inc ix
        inc iy
        ld hl,(BG_BYTE_PTR)
        inc hl
        ld (BG_BYTE_PTR),hl
        ld hl,(SPAN_CELL)
        inc hl
        ld (SPAN_CELL),hl
        ld a,(SPAN_CURRENT_BYTE)
        ld b,a
        ld a,(SPAN_LAST_BYTE)
        cp b
        ret z
        ld a,b
        inc a
        ld (SPAN_CURRENT_BYTE),a
        jp .byte_loop

; Expand the current primitive's 16-byte packed decision row into a direct
; 128-byte attribute lookup. This is paid once per primitive and makes every
; covered Spectrum byte substantially cheaper.
prepare_color_decisions:
        ld a,(POLY_COLOR)
        cp 17
        ret z
        cp 16
        jr z,.desired_ready
        ld c,a                        ; original colour 0..15
        ld a,(PENDING_PALETTE)
        cp 0xFF
        jr nz,.palette_ready
        ld a,(CURRENT_PALETTE)
        cp 0xFF
        jr nz,.palette_ready
        xor a
.palette_ready:
        ld l,a
        ld h,0
        ld de,PALETTE_SLOTS
        add hl,de
        ld a,(hl)
        cp 0xFF
        jr nz,.slot_ready
        xor a
.slot_ready:
        ld l,a
        ld h,0
        add hl,hl
        add hl,hl
        add hl,hl
        add hl,hl
        ld de,PALETTE_MAPS
        add hl,de
        ld e,c
        ld d,0
        add hl,de
        ld a,(hl)
.desired_ready:
        ld l,a
        ld h,0
        add hl,hl
        add hl,hl
        add hl,hl
        add hl,hl
        ld de,DECISION_DATA
        add hl,de
        push hl
        pop ix
        ld iy,COLOR_DECISIONS
        ld b,16
.group:
        ld c,(ix+0)
        inc ix
        ld d,8
.bit:
        srl c
        ld a,0
        jr nc,.store
        dec a
.store:
        ld (iy+0),a
        inc iy
        dec d
        jr nz,.bit
        djnz .group
        ret

; A=attribute. Return A=0xFF when the current primitive maps to INK,
; otherwise return zero for PAPER.
decision_ink:
        ld l,a
        ld h,0x72
        ld a,(hl)
        ret

first_masks:
        db 0xFF,0x7F,0x3F,0x1F,0x0F,0x07,0x03,0x01
last_masks:
        db 0x80,0xC0,0xE0,0xF0,0xF8,0xFC,0xFE,0xFF

; ---------------------------------------------------------------------------
; Compact native 8x8 text renderer

draw_text_core:
        ld a,(TEXT_COLOR)
        ld (POLY_COLOR),a
        call prepare_color_decisions
        ld a,(TEXT_X)
        ld (TEXT_START_X),a
        ld (TEXT_CURRENT_X),a
        ld a,(TEXT_Y)
        ld (TEXT_CURRENT_Y),a

        ld a,(DISPLAY_BIT)
        or 1
        call page_a
        ld a,(TEXT_DATA)
        ld b,a
        ld hl,TEXT_DATA+7
.find:
        ld a,b
        or a
        ret z
        ld e,(hl)
        inc hl
        ld d,(hl)
        inc hl
        push hl
        ld hl,(TEXT_ID)
        or a
        sbc hl,de
        pop hl
        jr z,.found
        inc hl
        inc hl
        djnz .find
        ret
.found:
        ld e,(hl)
        inc hl
        ld d,(hl)
        ld hl,TEXT_DATA
        add hl,de
        ld (TEXT_PTR),hl

.character:
        ld a,(DISPLAY_BIT)
        or 1
        call page_a
        ld hl,(TEXT_PTR)
        ld a,(hl)
        inc hl
        ld (TEXT_PTR),hl
        or a
        ret z
        cp 10
        jp z,.newline
        cp 13
        jp z,.newline
        ld (TEXT_CHAR),a
        sub 0x20
        cp 96
        jp nc,.advance

        ld c,a
        ld hl,(TEXT_DATA+3)           ; glyph-map offset
        ld de,TEXT_DATA
        add hl,de
        ld e,c
        ld d,0
        add hl,de
        ld a,(hl)
        cp 0xFF
        jp z,.advance
        ld l,a
        ld h,0
        add hl,hl
        add hl,hl
        add hl,hl
        ld de,(TEXT_DATA+5)           ; glyph-data offset
        add hl,de
        ld de,TEXT_DATA
        add hl,de
        ld de,GLYPH_STAGE
        ld bc,8
        ldir

        call text_x_to_cell
        cp 32
        jp nc,.advance
        ld (TEXT_CELL_X),a
        ld a,(TEXT_CURRENT_Y)
        ld l,a
        ld h,0
        call scale_y_clamped
        ld (TEXT_SCREEN_Y),a
        call map_destination
        xor a
        ld (TEXT_GLYPH_ROW),a
.glyph_row:
        ld a,(TEXT_SCREEN_Y)
        ld b,a
        ld a,(TEXT_GLYPH_ROW)
        add a,b
        cp 192
        jr nc,.advance
        ld (SPAN_Y),a
        ld c,a                        ; save screen y
        ld a,(TEXT_CELL_X)
        ld (SPAN_CURRENT_BYTE),a
        call text_row_pointer
        push hl
        pop ix

        ld a,c
        srl a
        srl a
        srl a
        ld l,a
        ld h,0
        add hl,hl
        add hl,hl
        add hl,hl
        add hl,hl
        add hl,hl                     ; cell row * 32
        ld a,(TEXT_CELL_X)
        ld e,a
        ld d,0
        add hl,de
        ld (SPAN_CELL),hl
        push hl
        ld de,ATTR_STAGE
        add hl,de
        ld a,(hl)
        call decision_ink
        ld (CELL_FILL_VALUE),a
        pop hl
        call mark_span_dirty

        ld a,(TEXT_GLYPH_ROW)
        ld e,a
        ld d,0
        ld hl,GLYPH_STAGE
        add hl,de
        ld a,(hl)
        ld c,a
        ld a,(CELL_FILL_VALUE)
        or a
        jr z,.glyph_paper
        ld a,c
        or (ix+0)
        ld (ix+0),a
        jr .next_row
.glyph_paper:
        ld a,c
        cpl
        and (ix+0)
        ld (ix+0),a
.next_row:
        ld a,(TEXT_GLYPH_ROW)
        inc a
        ld (TEXT_GLYPH_ROW),a
        cp 8
        jr nz,.glyph_row
.advance:
        ld a,(TEXT_CURRENT_X)
        inc a
        ld (TEXT_CURRENT_X),a
        jp .character
.newline:
        ld a,(TEXT_CURRENT_Y)
        add a,8
        ld (TEXT_CURRENT_Y),a
        ld a,(TEXT_START_X)
        ld (TEXT_CURRENT_X),a
        jp .character

text_x_to_cell:
        ld a,(TEXT_CURRENT_X)
        ld c,a
        ld b,0
.divide:
        cp 5
        jr c,.done
        sub 5
        inc b
        jr .divide
.done:
        ld a,c
        sub b                         ; floor(x * 4 / 5)
        ret

; C=screen Y, TEXT_CELL_X set. Return HL=destination bitmap byte.
text_row_pointer:
        ld a,c
        ld b,a
        and 7
        ld d,a
        ld a,b
        and 0xC0
        rrca
        rrca
        rrca
        add a,d
        ld d,a
        ld a,(DEST_MODE)
        or a
        ld a,0xA0
        jr nz,.base
        ld a,(TARGET_SCREEN)
        or a
        ld a,0x40
        jr z,.base
        ld a,0xC0
.base:
        add a,d
        ld h,a
        ld a,b
        and 0x38
        rlca
        rlca
        ld d,a
        ld a,(TEXT_CELL_X)
        add a,d
        ld l,a
        ret

; Fetch one byte from the original 65,156-byte resource packed across banks
; 0,3,4,6. SHAPE_OFFSET is a linear byte offset and may cross a 16 KB boundary.
shape_fetch:
        push bc
        ld hl,(SHAPE_OFFSET)
        ld a,h
        and 0xC0
        jr z,.bank0
        cp 0x40
        jr z,.bank3
        cp 0x80
        jr z,.bank4
        ld a,6
        jr .page
.bank0:
        xor a
        jr .page
.bank3:
        ld a,3
        jr .page
.bank4:
        ld a,4
.page:
        ld b,a
        ld a,(CURRENT_BANK)
        cp b
        jr z,.mapped
        ld a,(DISPLAY_BIT)
        or b
        call page_a
.mapped:
        ld hl,(SHAPE_OFFSET)
        ld a,h
        and 0x3F
        or 0xC0
        ld h,a
        ld a,(hl)
        push af
        ld hl,(SHAPE_OFFSET)
        inc hl
        ld (SHAPE_OFFSET),hl
        pop af
        pop bc
        ret

shape_fetch_word:
        call shape_fetch
        ld d,a
        call shape_fetch
        ld e,a
        ret

page_a:
        push af
        and 7
        ld (CURRENT_BANK),a
        pop af
        ld bc,0x7FFD
        out (c),a
        ret

renderer_code_end:
        ASSERT renderer_code_end < 0x7000

        END
