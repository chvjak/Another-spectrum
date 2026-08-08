; Another World sprite/background feasibility test for stock Spectrum 128K.
;
; Runtime design:
;   - screens 5/7 are true double buffers;
;   - the hidden screen's previous dirty rectangle is restored from saved-under
;     RAM, so no full-screen copy occurs during animation;
;   - Lester/Buddy masks are pre-shifted offline for X mod 8 = 0/2/4/6;
;   - one current frame per actor is copied to fixed RAM, then XOR composited;
;   - scene changes are prepared on the hidden screen and flipped at vblank;
;   - the red border marks renderer CPU time for emulator/hardware profiling.

        DEVICE ZXSPECTRUM128
        ORG 0x8000

        jp entry

        INCLUDE "generated_layout.inc"

PORT_7FFD               EQU 0x7FFD
PORT_FE                 EQU 0x00FE
SCREEN_BYTES            EQU 6912
DIRTY_MAX_WIDTH         EQU 10
DIRTY_BYTES             EQU DIRTY_HEIGHT * DIRTY_MAX_WIDTH

entry:
        di
        ld sp,0xBFF0
        xor a
        ld (screen_bit),a
        ld (scene_index),a
        ld (status_scene),a
        ld (anim_frame),a
        ld (valid5),a
        ld (valid7),a
        ld (status_missed),a
        ld (status_render_irq_max),a
        ld (status_transitions),a
        ld (status_transitions+1),a
        ld hl,0
        ld (position_x),hl
        ld (status_frames),hl
        ld a,7
        call page_bank

        ld a,0xA0
        ld i,a
        im 2
        ei
        call wait_irq_once

main_loop:
        ld a,2
        out (PORT_FE),a
        ld a,(status_irq)
        ld (render_start_irq),a

        call prepare_sprites
        call restore_hidden
        call calculate_new_rectangle
        call save_hidden
        call draw_actors

        xor a
        out (PORT_FE),a
        call record_render_interrupts
        call wait_render_deadline
        call flip_screen

        ld hl,(status_frames)
        inc hl
        ld (status_frames),hl
        ld a,(anim_frame)
        inc a
        and 7
        ld (anim_frame),a
        ld (status_anim),a

        ld hl,(position_x)
        inc hl
        inc hl
        ld (position_x),hl
        ld (status_position),hl
        ld de,256
        or a
        sbc hl,de
        jr c,main_loop
        call next_scene
        jp main_loop


; ---------------------------------------------------------------------------
; Timing and paging

page_bank:
        ld (current_latch),a
        ld bc,PORT_7FFD
        out (c),a
        ret

wait_irq_once:
        ld a,(status_irq)
.wait:
        halt
        ld hl,status_irq
        cp (hl)
        jr z,.wait
        ret

record_render_interrupts:
        ld a,(status_irq)
        ld hl,render_start_irq
        sub (hl)
        ld b,a
        ld a,(status_render_irq_max)
        cp b
        jr nc,.max_done
        ld a,b
        ld (status_render_irq_max),a
.max_done:
        ld a,b
        cp 2
        ret c
        ld hl,status_missed
        inc (hl)
        ret

wait_render_deadline:
.wait:
        ld a,(status_irq)
        ld hl,render_start_irq
        sub (hl)
        cp 2
        ret nc
        halt
        jr .wait

flip_screen:
        ld a,(screen_bit)
        xor 8
        ld (screen_bit),a
        ld (status_screen_bit),a
        or 7
        jp page_bank


; ---------------------------------------------------------------------------
; Sprite preparation.  The pageable source banks are uncontended (0 and 1).
; Only the current pre-shifted frame is copied into fixed bank 2.

prepare_sprites:
        xor a
        ld (lester_visible),a
        ld (buddy_visible),a

        ld hl,(position_x)
        ld de,217
        or a
        sbc hl,de
        jr nc,.lester_done
        ld hl,(position_x)
        ld a,l
        ld (lester_x),a
        call lester_pointer_index
        call pointer_lester
        ld a,(screen_bit)          ; bank 0
        call page_bank
        ld de,LESTER_WORK
        ld bc,LESTER_FRAME_BYTES
        ldir
        ld a,1
        ld (lester_visible),a
.lester_done:

        ld hl,(position_x)
        ld de,40
        or a
        sbc hl,de
        jr c,.buddy_done
        ld de,217
        push hl
        or a
        sbc hl,de
        pop hl
        jr nc,.buddy_done
        ld a,l
        ld (buddy_x),a
        call buddy_pointer_index
        call pointer_buddy
        ld a,(screen_bit)
        or 1                       ; bank 1
        call page_bank
        ld de,BUDDY_WORK
        ld bc,BUDDY_FRAME_BYTES
        ldir
        ld a,1
        ld (buddy_visible),a
.buddy_done:
        ld a,(screen_bit)
        or 7                       ; keep screen 7 CPU-visible for drawing
        jp page_bank

lester_pointer_index:
        ld a,(anim_frame)
        add a,a
        add a,a
        ld b,a
        ld a,(lester_x)
        and 6
        srl a
        or b
        ret

buddy_pointer_index:
        ld a,(anim_frame)
        add a,2
        and 7
        add a,a
        add a,a
        ld b,a
        ld a,(buddy_x)
        and 6
        srl a
        or b
        ret

pointer_lester:
        add a,a
        ld e,a
        ld d,0
        ld hl,lester_pointers
        add hl,de
        ld e,(hl)
        inc hl
        ld d,(hl)
        ex de,hl
        ret

pointer_buddy:
        add a,a
        ld e,a
        ld d,0
        ld hl,buddy_pointers
        add hl,de
        ld e,(hl)
        inc hl
        ld d,(hl)
        ex de,hl
        ret


; ---------------------------------------------------------------------------
; Saved-under dirty rectangle

restore_hidden:
        ld a,(screen_bit)
        or a
        jr nz,.screen5
.screen7:
        ld a,(valid7)
        or a
        ret z
        ld ix,ROW_TABLE7 + DIRTY_TOP * 2
        ld iy,SAVE7
        ld a,(old_x7)
        ld hl,old_width7
        ld c,(hl)
        jp restore_block
.screen5:
        ld a,(valid5)
        or a
        ret z
        ld ix,ROW_TABLE5 + DIRTY_TOP * 2
        ld iy,SAVE5
        ld a,(old_x5)
        ld hl,old_width5
        ld c,(hl)
        jp restore_block

restore_screen7_for_transition:
        ld a,(valid7)
        or a
        ret z
        ld ix,ROW_TABLE7 + DIRTY_TOP * 2
        ld iy,SAVE7
        ld a,(old_x7)
        ld hl,old_width7
        ld c,(hl)
        jp restore_block

restore_block:
        ld (rect_x_work),a
        ld a,c
        ld (rect_width_work),a
        ld b,DIRTY_HEIGHT
.row:
        ld l,(ix+0)
        ld h,(ix+1)
        ld a,(rect_x_work)
        ld e,a
        ld d,0
        add hl,de
        ex de,hl                   ; DE = screen destination
        push bc
        push ix
        push iy
        pop hl                     ; HL = saved-under source
        ld a,(rect_width_work)
        ld c,a
        ld b,0
        ldir
        push hl
        pop iy
        pop ix
        pop bc
        inc ix
        inc ix
        djnz .row
        ret

calculate_new_rectangle:
        ld a,(buddy_visible)
        or a
        jr z,.lester_only
        ld a,(buddy_x)
        srl a
        srl a
        srl a
        ld (new_x),a
        ld a,(lester_visible)
        or a
        ld a,5
        jr z,.clip_width
        ld a,10
        jr .clip_width
.lester_only:
        ld a,(lester_x)
        srl a
        srl a
        srl a
        ld (new_x),a
        ld a,5
.clip_width:
        ld b,a
        ld a,(new_x)
        add a,b
        cp 33
        jr c,.store_width
        ld a,32
        ld hl,new_x
        sub (hl)
        ld b,a
.store_width:
        ld a,b
        ld (new_width),a
        ret

save_hidden:
        ld a,(screen_bit)
        or a
        jr nz,.screen5
.screen7:
        ld a,(new_x)
        ld (old_x7),a
        ld a,(new_width)
        ld (old_width7),a
        ld a,1
        ld (valid7),a
        ld ix,ROW_TABLE7 + DIRTY_TOP * 2
        ld iy,SAVE7
        jr save_block
.screen5:
        ld a,(new_x)
        ld (old_x5),a
        ld a,(new_width)
        ld (old_width5),a
        ld a,1
        ld (valid5),a
        ld ix,ROW_TABLE5 + DIRTY_TOP * 2
        ld iy,SAVE5

save_block:
        ld b,DIRTY_HEIGHT
.row:
        ld l,(ix+0)
        ld h,(ix+1)
        ld a,(new_x)
        ld e,a
        ld d,0
        add hl,de                  ; HL = screen source
        push bc
        push ix
        push iy
        pop de                     ; DE = saved-under destination
        ld a,(new_width)
        ld c,a
        ld b,0
        ldir
        push de
        pop iy
        pop ix
        pop bc
        inc ix
        inc ix
        djnz .row
        ret


; ---------------------------------------------------------------------------
; XOR compositor.  ULA attributes remain untouched; the actor always flips
; PAPER/INK locally, avoiding attribute writes and color-clash blocks.

draw_actors:
        ld a,(screen_bit)
        or a
        jr nz,.screen5
        ld ix,ROW_TABLE7
        jr .table_ready
.screen5:
        ld ix,ROW_TABLE5
.table_ready:
        ld a,(lester_visible)
        or a
        jr z,.buddy
        push ix
        ld de,LESTER_Y * 2
        add ix,de
        ld iy,LESTER_WORK
        ld a,(lester_x)
        srl a
        srl a
        srl a
        ld c,a
        ld b,LESTER_HEIGHT
        call xor_mask
        pop ix
.buddy:
        ld a,(buddy_visible)
        or a
        ret z
        ld de,BUDDY_Y * 2
        add ix,de
        ld iy,BUDDY_WORK
        ld a,(buddy_x)
        srl a
        srl a
        srl a
        ld c,a
        ld b,BUDDY_HEIGHT
        jp xor_mask

xor_mask:
        ld a,c
        ld (sprite_x_byte),a
.row:
        ld l,(ix+0)
        ld h,(ix+1)
        ld a,(sprite_x_byte)
        ld e,a
        ld d,0
        add hl,de

        ld a,(iy+0)
        xor (hl)
        ld (hl),a
        inc hl
        ld a,(iy+1)
        xor (hl)
        ld (hl),a
        inc hl
        ld a,(iy+2)
        xor (hl)
        ld (hl),a
        inc hl
        ld a,(iy+3)
        xor (hl)
        ld (hl),a
        inc hl
        ld a,(iy+4)
        xor (hl)
        ld (hl),a

        ld de,5
        add iy,de
        inc ix
        inc ix
        djnz .row
        ret


; ---------------------------------------------------------------------------
; Tear-free scene switch. Screen 7 shows the old scene while the new source is
; copied to hidden screen 5; the flip then exposes screen 5 while it seeds 7.

next_scene:
        ld a,(scene_index)
        inc a
        cp 3
        jr c,.scene_ok
        xor a
.scene_ok:
        ld (scene_index),a
        ld (status_scene),a
        ld hl,(status_transitions)
        inc hl
        ld (status_transitions),hl
        call load_scene
        xor a
        ld h,a
        ld l,a
        ld (position_x),hl
        ld (status_position),hl
        ld (anim_frame),a
        ld (status_anim),a
        ret

load_scene:
        ld a,1
        out (PORT_FE),a

        ld a,(screen_bit)
        or 7
        call page_bank
        call restore_screen7_for_transition
        call wait_irq_once

        ld a,8
        ld (screen_bit),a
        ld (status_screen_bit),a
        or 7
        call page_bank              ; show screen 7

        ld a,(scene_index)
        ld e,a
        ld d,0
        ld hl,scene_banks
        add hl,de
        ld a,(hl)
        ld (scene_bank_work),a
        or 8
        call page_bank
        ld hl,0xC000
        ld de,0x4000
        ld bc,SCREEN_BYTES
        ldir

        call wait_irq_once
        xor a
        ld (screen_bit),a
        ld (status_screen_bit),a
        ld a,(scene_bank_work)
        call page_bank              ; flip to the new screen 5
        ld a,7
        call page_bank
        ld hl,0x4000
        ld de,0xC000
        ld bc,SCREEN_BYTES
        ldir

        xor a
        ld (valid5),a
        ld (valid7),a
        out (PORT_FE),a
        ret

scene_banks:
        db 3,4,6

        ASSERT $ < 0x9000


; ---------------------------------------------------------------------------
; Fixed-bank tables and work buffers

        defs 0x9000-$,0
        INCLUDE "generated_rows.inc"

        defs 0x9300-$,0
LESTER_WORK:
        defs LESTER_FRAME_BYTES,0

        defs 0x9400-$,0
BUDDY_WORK:
        defs BUDDY_FRAME_BYTES,0

        defs 0x9600-$,0
SAVE5:
        defs DIRTY_BYTES,0

        defs 0x9900-$,0
SAVE7:
        defs DIRTY_BYTES,0

        ASSERT $ < 0x9F00

        defs 0x9F00-$,0
status_magic:
        db "SPRT"
status_frames:
        dw 0
status_scene:
        db 0
status_missed:
        db 0
status_render_irq_max:
        db 0
status_screen_bit:
        db 0
status_irq:
        db 0
status_position:
        dw 0
status_anim:
        db 0
status_transitions:
        dw 0

screen_bit:
        db 0
scene_index:
        db 0
current_latch:
        db 0
scene_bank_work:
        db 0
render_start_irq:
        db 0
anim_frame:
        db 0
position_x:
        dw 0
lester_visible:
        db 0
buddy_visible:
        db 0
lester_x:
        db 0
buddy_x:
        db 0
valid5:
        db 0
valid7:
        db 0
old_x5:
        db 0
old_width5:
        db 0
old_x7:
        db 0
old_width7:
        db 0
new_x:
        db 0
new_width:
        db 0
rect_x_work:
        db 0
rect_width_work:
        db 0
sprite_x_byte:
        db 0

        ASSERT $ < 0xA000


; 257 identical bytes make every IM2 vector resolve to 0xA1A1.
        defs 0xA000-$,0
im2_vectors:
        defs 257,0xA1

        defs 0xA1A1-$,0
im2_handler:
        push af
        ld a,(status_irq)
        inc a
        ld (status_irq),a
        pop af
        ei
        reti

        ASSERT $ < 0xBFF0
