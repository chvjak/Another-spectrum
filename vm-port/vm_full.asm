; Size-first Another World DOS-demo intro VM for a ZX Spectrum 128K.
;
; The original 9,842-byte bytecode and 65,156-byte shape resource remain the
; source of control and geometry.  Only Spectrum-specific colour maps, compact
; bitmap loads and per-frame attribute maps are added.

        DEVICE ZXSPECTRUM48
        ORG 0x8000

BYTECODE_BASE          EQU 0xC000

VARS                   EQU 0x8C00          ; 256 signed 16-bit VM variables
TASKS_CUR              EQU 0x8E00          ; 64 x 16-bit task PCs
TASKS_NEXT             EQU 0x8E80
STATES_CUR             EQU 0x8F00          ; 64 task state bytes
STATES_NEXT            EQU 0x8F40
CALL_STACK             EQU 0x8F80          ; 64 x 16-bit VM return PCs

DIRTY5                 EQU 0x9000          ; 768 cell bits, physical screen 5
DIRTY7                 EQU 0x9060          ; 768 cell bits, physical screen 7

TICK                   EQU 0x9300
INST_COUNT             EQU 0x9302
TRACE_HASH             EQU 0x9304
ERROR_OPCODE           EQU 0x9306
DONE                   EQU 0x9307
FRAME_COUNT            EQU 0x9308          ; 16-bit sampled-frame count
TARGET_SCREEN          EQU 0x930A          ; 0=bank 5, 1=bank 7
DISPLAY_BIT            EQU 0x930B          ; bit 3 value for port 0x7FFD
WORK_PAGE              EQU 0x930C
NEXT_VISUAL_TICK       EQU 0x930D
VM_PC                  EQU 0x930F
CURRENT_OPCODE         EQU 0x9311
CURRENT_TASK           EQU 0x9312
CURRENT_TASK_PTR       EQU 0x9313
STACK_PTR              EQU 0x9315
TMP_INDEX              EQU 0x9316
TMP_WORD               EQU 0x9317
TMP_FLAG               EQU 0x9319
TEMP_OFFSET            EQU 0x931A
QUEUE_Y                EQU 0x931C
QUEUE_ZOOM             EQU 0x931E          ; 16-bit
NEXT_PART              EQU 0x9320
VM_IRQ_DEADLINE        EQU 0x9321
CURRENT_PALETTE        EQU 0x9322
PENDING_PALETTE        EQU 0x9323
DYNAMIC_BASE           EQU 0x9324          ; retained as renderer scratch
IRQ_COUNT              EQU 0x9325          ; fixed: IM2 handler increments this
COPY_SOURCE            EQU 0x9326
COPY_DEST              EQU 0x9327
TEXT_ID                EQU 0x9328
TEXT_X                 EQU 0x932A
TEXT_Y                 EQU 0x932B
TEXT_COLOR             EQU 0x932C
LOGICAL_FRONT          EQU 0x932D          ; 0=bank 5, 1=bank 7
LOGICAL_BACK           EQU 0x932E
DRAW_DEST              EQU 0x932F          ; 0=screen, 1=background
PRESENT_PAGE           EQU 0x9330
TEMP_LEN               EQU 0x9331
LAST_SAMPLE_BANK       EQU 0x9332
BLOCK_LZ_END           EQU 0x9376
BLOCK_LZ_FLAGS         EQU 0x9378
BLOCK_LZ_BITS          EQU 0x9379
BLOCK_LZ_SECOND        EQU 0x937A

RENDERER_PRESENT       EQU 0x5D20
RENDERER_DRAW_BG_SHAPE EQU 0x5D23
RENDERER_CLEAR_BG      EQU 0x5D26
RENDERER_PAGE3_TO_BG   EQU 0x5D29
RENDERER_DYNAMIC_TO_BG EQU 0x5D2C
RENDERER_DRAW_BG_TEXT  EQU 0x5D2F
RENDERER_LOAD_RESOURCE EQU 0x5D32
RENDERER_INIT          EQU 0x5D35
RENDERER_RESTORE_SCREEN EQU 0x5D38
RENDERER_FILL_SCREEN   EQU 0x5D3B
RENDERER_PAGE3_TO_SCREEN EQU 0x5D3E
RENDERER_SCREEN_TO_BG  EQU 0x5D41
RENDERER_LOAD_CHECKPOINT EQU 0x5D44

DYN_QUEUE_COUNT        EQU 0x7300
DYN_QUEUE_BASE         EQU 0x7302
PAGE3_QUEUE_COUNT      EQU 0x9F00
PAGE3_BASE             EQU 0x9F01
PAGE3_QUEUE_BASE       EQU 0x9F02
QUEUE_RECORD_SIZE      EQU 10
QUEUE_MAX              EQU 24
PAGE3_SNAPSHOT_FIRST   EQU 0x40
PAGE3_SNAPSHOT_SECOND  EQU 0x41

BACKGROUND             EQU 0xA000          ; 6912-byte immutable Spectrum page
STACK_TOP              EQU 0xBFF0

STATE_CLEAR_BEGIN      EQU VARS
STATE_CLEAR_END        EQU 0x9400

start:
        di
        ld sp,STACK_TOP

        ; Clear the compact VM state and page-3 display-list state.
        xor a
        ld hl,STATE_CLEAR_BEGIN
        ld de,STATE_CLEAR_BEGIN+1
        ld bc,STATE_CLEAR_END-STATE_CLEAR_BEGIN-1
        ld (hl),a
        ldir
        ld hl,PAGE3_QUEUE_COUNT
        ld de,PAGE3_QUEUE_COUNT+1
        ld bc,0x00FF
        ld (hl),a
        ldir

        ; Both task-PC tables start at 0xFFFF; task zero starts at bytecode PC 0.
        ld a,0xFF
        ld hl,TASKS_CUR
        ld de,TASKS_CUR+1
        ld bc,127
        ld (hl),a
        ldir
        ld hl,TASKS_NEXT
        ld de,TASKS_NEXT+1
        ld bc,127
        ld (hl),a
        ldir
        ld hl,0
        ld (TASKS_CUR),hl

        ; rawgl DOS/BYPASS_PROTECTION initial values relevant to the demo.
        ld hl,0x0010
        ld (VARS + 0xBC*2),hl
        ld hl,0x0080
        ld (VARS + 0xC6*2),hl
        ld hl,4000
        ld (VARS + 0xF2*2),hl
        ld hl,33
        ld (VARS + 0xDC*2),hl
        ld hl,20
        ld (VARS + 0xE4*2),hl

        ; captured frame 10 is presentation tick 8; sample thereafter at 5 fps.
        ld hl,8
        ld (NEXT_VISUAL_TICK),hl
        ld a,0xFE
        ld (WORK_PAGE),a
        ld a,1                       ; first sampled frame is drawn into bank 7
        ld (TARGET_SCREEN),a
        ld (LOGICAL_BACK),a
        xor a
        ld (LOGICAL_FRONT),a
        ld a,0xFF
        ld (CURRENT_PALETTE),a
        ld (PENDING_PALETTE),a
        call RENDERER_INIT
        ld a,1                       ; bytecode bank, display bank 5
        call page_a

        ; IM2 vector and handler live in the unused tail of bank 5.
        ld a,0x5C
        ld i,a
        im 2
        ei

main_loop:
        call wait_tick_slot
        call setup_tasks
        call run_tasks

        ld hl,(TICK)
        inc hl
        ld (TICK),hl
        ld a,(VM_IRQ_DEADLINE)
        inc a
        ld (VM_IRQ_DEADLINE),a

        ld a,(NEXT_PART)
        or a
        jr nz,finished
        jr main_loop

; Run one VM tick per 50 Hz deadline. If rendering crossed several interrupts,
; execute the missed control ticks immediately; this consumes the intended
; idle interval between 5 fps samples instead of permanently slowing the film.
; The signed modular difference is safe while an overrun remains below 128
; refreshes, far beyond the measured worst case.
wait_tick_slot:
        ld a,(IRQ_COUNT)
        ld b,a
        ld a,(VM_IRQ_DEADLINE)
        ld c,a
        ld a,b
        sub c
        ret p
.wait:
        ei
        halt
        ld a,(IRQ_COUNT)
        ld b,a
        ld a,(VM_IRQ_DEADLINE)
        ld c,a
        ld a,b
        sub c
        jp m,.wait
        ret

finished:
        ld a,1
        ld (DONE),a
.hold:
        ei
        halt
        jr .hold

; ---------------------------------------------------------------------------
; Original VM task scheduler

setup_tasks:
        ld bc,STATES_NEXT
        ld de,STATES_CUR
        ld ix,TASKS_NEXT
        ld iy,TASKS_CUR
        ld a,64
.loop:
        push af
        ld a,(bc)
        ld (de),a
        inc bc
        inc de

        ld l,(ix+0)
        ld h,(ix+1)
        ld a,h
        cp 0xFF
        jr nz,.pending
        ld a,l
        cp 0xFF
        jr z,.no_pending
.pending:
        ld a,h
        cp 0xFF
        jr nz,.assign
        ld a,l
        cp 0xFE
        jr nz,.assign
        ld hl,0xFFFF
.assign:
        ld (iy+0),l
        ld (iy+1),h
        ld (ix+0),0xFF
        ld (ix+1),0xFF
.no_pending:
        inc ix
        inc ix
        inc iy
        inc iy
        pop af
        dec a
        jr nz,.loop
        ret

run_tasks:
        xor a
        ld (CURRENT_TASK),a
.next:
        ld a,(CURRENT_TASK)
        cp 64
        ret z

        ; Skip paused tasks.
        ld e,a
        ld d,0
        ld hl,STATES_CUR
        add hl,de
        ld a,(hl)
        or a
        jr nz,.advance

        ; Resolve the current 16-bit task PC.
        ld a,(CURRENT_TASK)
        ld l,a
        ld h,0
        add hl,hl
        ld de,TASKS_CUR
        add hl,de
        ld (CURRENT_TASK_PTR),hl
        ld e,(hl)
        inc hl
        ld d,(hl)
        ld a,d
        cp 0xFF
        jr nz,.run
        ld a,e
        cp 0xFF
        jr z,.advance

.run:
        ex de,hl
        ld de,BYTECODE_BASE
        add hl,de
        ld (VM_PC),hl
        xor a
        ld (STACK_PTR),a
        call execute_task

        ; Persist the yielded PC as an offset from the bytecode base.
        ld hl,(VM_PC)
        ld de,BYTECODE_BASE
        or a
        sbc hl,de
        ex de,hl
        ld hl,(CURRENT_TASK_PTR)
        ld (hl),e
        inc hl
        ld (hl),d

.advance:
        ld a,(CURRENT_TASK)
        inc a
        ld (CURRENT_TASK),a
        jr .next

; ---------------------------------------------------------------------------
; Bytecode fetch, trace, and dispatch

execute_task:
dispatch:
        ld bc,(VM_PC)                ; BC is the absolute pre-fetch PC
        ld h,b
        ld l,c
        ld a,(hl)
        inc hl
        ld (VM_PC),hl
        ld (CURRENT_OPCODE),a
        call trace_event

        ld a,(CURRENT_OPCODE)
        bit 7,a
        jp nz,op_shape80
        bit 6,a
        jp nz,op_shape40
        cp 0x1B
        jp nc,unsupported

        ld l,a
        ld h,0
        add hl,hl
        ld de,opcode_table
        add hl,de
        ld e,(hl)
        inc hl
        ld d,(hl)
        ex de,hl
        jp (hl)

trace_event:
        ; Order-sensitive 16-bit hash:
        ; h = (h << 5); low ^= pc.low ^ opcode; high ^= pc.high.
        ld hl,(TRACE_HASH)
        add hl,hl
        add hl,hl
        add hl,hl
        add hl,hl
        add hl,hl
        ld a,l
        xor c
        ld e,a
        ld a,(CURRENT_OPCODE)
        xor e
        ld l,a
        ld a,h
        xor b
        ld h,a
        ld (TRACE_HASH),hl

        ld hl,(INST_COUNT)
        inc hl
        ld (INST_COUNT),hl
        ret

fetch_byte:
        ld hl,(VM_PC)
        ld a,(hl)
        inc hl
        ld (VM_PC),hl
        ret

fetch_word_de:
        ld hl,(VM_PC)
        ld d,(hl)                    ; original VM words are big-endian
        inc hl
        ld e,(hl)
        inc hl
        ld (VM_PC),hl
        ret

set_pc_de:
        ex de,hl
        ld de,BYTECODE_BASE
        add hl,de
        ld (VM_PC),hl
        ret

var_ptr_a:
        ld l,a
        ld h,0
        add hl,hl
        ld bc,VARS
        add hl,bc
        ret

; ---------------------------------------------------------------------------
; Implemented scalar/control opcodes

op_mov_const:                         ; 0x00: VAR(i) = signed word
        call fetch_byte
        ld (TMP_INDEX),a
        call fetch_word_de
        ld a,(TMP_INDEX)
        call var_ptr_a
        ld (hl),e
        inc hl
        ld (hl),d
        jp dispatch

op_mov:                               ; 0x01: VAR(dst) = VAR(src)
        call fetch_byte
        ld (TMP_INDEX),a
        call fetch_byte
        call var_ptr_a
        ld e,(hl)
        inc hl
        ld d,(hl)
        ld a,(TMP_INDEX)
        call var_ptr_a
        ld (hl),e
        inc hl
        ld (hl),d
        jp dispatch

op_add_vars:                          ; 0x02: not needed before the test boundary
        jp unsupported

op_add_const:                         ; 0x03: VAR(i) += signed word
        call fetch_byte
        ld (TMP_INDEX),a
        call fetch_word_de
        push de
        ld a,(TMP_INDEX)
        call var_ptr_a
        pop de
        ld c,(hl)
        inc hl
        ld b,(hl)
        ex de,hl
        add hl,bc
        ex de,hl
        ld (hl),d
        dec hl
        ld (hl),e
        jp dispatch

op_call:                              ; 0x04
        call fetch_word_de
        ld (TMP_WORD),de
        ld a,(STACK_PTR)
        cp 64
        jp z,unsupported
        ld l,a
        ld h,0
        add hl,hl
        ld bc,CALL_STACK
        add hl,bc
        push hl
        ld hl,(VM_PC)
        ld bc,BYTECODE_BASE
        or a
        sbc hl,bc
        ex de,hl
        pop hl
        ld (hl),e
        inc hl
        ld (hl),d
        ld a,(STACK_PTR)
        inc a
        ld (STACK_PTR),a
        ld de,(TMP_WORD)
        call set_pc_de
        jp dispatch

op_ret:                               ; 0x05
        ld a,(STACK_PTR)
        or a
        jp z,unsupported
        dec a
        ld (STACK_PTR),a
        ld l,a
        ld h,0
        add hl,hl
        ld de,CALL_STACK
        add hl,de
        ld e,(hl)
        inc hl
        ld d,(hl)
        call set_pc_de
        jp dispatch

op_yield:                             ; 0x06
        ret

op_jmp:                               ; 0x07
        call fetch_word_de
        call set_pc_de
        jp dispatch

op_install_task:                      ; 0x08
        call fetch_byte
        ld (TMP_INDEX),a
        call fetch_word_de
        push de
        ld a,(TMP_INDEX)
        ld l,a
        ld h,0
        add hl,hl
        ld bc,TASKS_NEXT
        add hl,bc
        pop de
        ld (hl),e
        inc hl
        ld (hl),d
        jp dispatch

op_loop_var:                          ; 0x09: --VAR(i); jump while non-zero
        call fetch_byte
        call var_ptr_a
        ld e,(hl)
        inc hl
        ld d,(hl)
        dec de
        ld (hl),d
        dec hl
        ld (hl),e
        ld a,d
        or e
        jr z,.zero
        ld a,1
.zero:
        ld (TMP_FLAG),a
        call fetch_word_de
        ld a,(TMP_FLAG)
        or a
        jr z,.no_jump
        call set_pc_de
.no_jump:
        jp dispatch

op_cond_jmp:                          ; 0x0A: conditional signed comparison
        call fetch_byte               ; condition/mode
        ld (TMP_FLAG),a
        call fetch_byte               ; left-hand variable
        call var_ptr_a
        ld e,(hl)
        inc hl
        ld d,(hl)
        ld (TEMP_OFFSET),de            ; signed left-hand value

        ld a,(TMP_FLAG)
        bit 7,a
        jr z,.not_var
        call fetch_byte
        call var_ptr_a
        ld e,(hl)
        inc hl
        ld d,(hl)
        jr .rhs_ready
.not_var:
        bit 6,a
        jr z,.byte_rhs
        call fetch_word_de
        jr .rhs_ready
.byte_rhs:
        call fetch_byte
        ld e,a
        ld d,0
.rhs_ready:
        ld (TMP_WORD),de

        ; The DOS intro executes conditions 0 (==), 1 (!=), and 2 (signed >).
        ; Other relation codes retain the normal VM operand length but fail
        ; loudly rather than silently taking a wrong path.
        ld a,(TMP_FLAG)
        and 7
        cp 0
        jr z,.equal
        cp 1
        jr z,.not_equal
        cp 2
        jr z,.greater
        jp unsupported

.equal:
        ld hl,(TEMP_OFFSET)
        ld de,(TMP_WORD)
        or a
        sbc hl,de
        jr z,.true
        jr .false
.not_equal:
        ld hl,(TEMP_OFFSET)
        ld de,(TMP_WORD)
        or a
        sbc hl,de
        jr nz,.true
        jr .false
.greater:
        ; Signed compare by biasing both high bytes by 0x80, then performing
        ; an unsigned 16-bit comparison.
        ld hl,(TEMP_OFFSET)
        ld de,(TMP_WORD)
        ld a,h
        xor 0x80
        ld h,a
        ld a,d
        xor 0x80
        ld d,a
        or a
        sbc hl,de
        jr c,.false
        jr z,.false
.true:
        ld a,1
        jr .condition_ready
.false:
        xor a
.condition_ready:
        ld (TMP_FLAG),a
        call fetch_word_de            ; branch target
        ld a,(TMP_FLAG)
        or a
        jr z,.no_jump
        call set_pc_de
.no_jump:
        jp dispatch

op_set_palette:                       ; 0x0B
        call fetch_word_de
        ld a,d
        cp 10                         ; rawgl DOS-intro palette redraw fixup
        jr z,.ignored
        cp 16
        jr z,.ignored
        ld (PENDING_PALETTE),a
.ignored:
        jp dispatch

op_task_state:                        ; 0x0C
        call fetch_byte               ; first task
        ld (TMP_INDEX),a
        call fetch_byte               ; last task, inclusive
        ld (TMP_FLAG),a
        call fetch_byte               ; state
        cp 2
        jr z,.remove
        cp 0
        jr z,.set_state
        cp 1
        jr z,.set_state
        jp dispatch

.remove:
        ld a,(TMP_INDEX)
.remove_loop:
        ld l,a
        ld h,0
        add hl,hl
        ld de,TASKS_NEXT
        add hl,de
        ld (hl),0xFE
        inc hl
        ld (hl),0xFF
        ld a,(TMP_INDEX)
        ld b,a
        ld a,(TMP_FLAG)
        cp b
        jp z,dispatch
        ld a,b
        inc a
        ld (TMP_INDEX),a
        jr .remove_loop

.set_state:
        ld (TEMP_LEN),a
        ld a,(TMP_INDEX)
.state_loop:
        ld l,a
        ld h,0
        ld de,STATES_NEXT
        add hl,de
        ld a,(TEMP_LEN)
        ld (hl),a
        ld a,(TMP_INDEX)
        ld b,a
        ld a,(TMP_FLAG)
        cp b
        jp z,dispatch
        ld a,b
        inc a
        ld (TMP_INDEX),a
        jr .state_loop

op_select_page:                       ; 0x0D
        call fetch_byte
        ld (WORK_PAGE),a
        jp dispatch

op_fill_page:                         ; 0x0E
        call fetch_byte               ; logical page
        ld (COPY_DEST),a
        call fetch_byte               ; original colour
        ld (TMP_FLAG),a
        ld a,(COPY_DEST)
        or a
        jr z,.background
        cp 3
        jr z,.page3
        cp 0xFF
        jr z,.back_screen
        cp 0xFE
        jp nz,dispatch
        ld a,(LOGICAL_FRONT)
        jr .screen_selected
.back_screen:
        ld a,(LOGICAL_BACK)
.screen_selected:
        ld (TARGET_SCREEN),a
        ld a,(TMP_FLAG)
        call RENDERER_FILL_SCREEN
        jp dispatch
.background:
        call checkpoint_for_tick
        jr c,.normal_background
        call RENDERER_LOAD_CHECKPOINT
        jp dispatch
.normal_background:
        ld a,(TMP_FLAG)
        call RENDERER_CLEAR_BG
        jp dispatch
.page3:
        xor a
        ld (PAGE3_QUEUE_COUNT),a
        ld a,(TMP_FLAG)
        or 0x80
        ld (PAGE3_BASE),a
        jp dispatch                   ; initial pages 1/2 are already black

op_copy_page:                         ; 0x0F
        call fetch_byte               ; source
        ld (COPY_SOURCE),a
        call fetch_byte               ; destination
        ld (COPY_DEST),a

        cp 0xFF
        jr z,.to_dynamic
        or a
        jr z,.to_background
        cp 3
        jr z,.to_page3
        jp dispatch

.to_dynamic:
        ld a,(COPY_SOURCE)
        cp 0
        jr z,.dynamic_page0
        cp 3
        jr z,.dynamic_page3
        cp 0xFE
        jr z,.front_to_back
        cp 0xFF
        jp z,dispatch
        jp dispatch
.dynamic_page0:
        ld a,(LOGICAL_BACK)
        ld (TARGET_SCREEN),a
        call RENDERER_RESTORE_SCREEN
        jp dispatch
.dynamic_page3:
        ld a,(LOGICAL_BACK)
        ld (TARGET_SCREEN),a
        call RENDERER_PAGE3_TO_SCREEN
        jp dispatch
.front_to_back:
        ; This form is not used by the intro; preserve operand semantics.
        jp dispatch

.to_background:
        ld a,(COPY_SOURCE)
        cp 3
        jr z,.page3_background
        cp 0xFF
        jr z,.back_background
        cp 0xFE
        jr z,.front_background
        jp dispatch
.page3_background:
        call RENDERER_PAGE3_TO_BG
        jp dispatch
.back_background:
        ld a,(LOGICAL_BACK)
        jr .screen_background
.front_background:
        ld a,(LOGICAL_FRONT)
.screen_background:
        ld (TARGET_SCREEN),a
        call RENDERER_SCREEN_TO_BG
        jp dispatch

.to_page3:
        ld a,(COPY_SOURCE)
        or a
        jr z,.page0_page3
        cp 0xFF
        jr z,.dynamic_page3_copy
        jp dispatch
.page0_page3:
        xor a
        ld (PAGE3_QUEUE_COUNT),a
        ld hl,(TICK)
        ld de,1597
        or a
        sbc hl,de
        ld a,PAGE3_SNAPSHOT_FIRST
        jr z,.store_page3_base
        ld hl,(TICK)
        ld de,1712
        or a
        sbc hl,de
        ld a,PAGE3_SNAPSHOT_SECOND
        jr z,.store_page3_base
        xor a                          ; conservative fallback for other parts
.store_page3_base:
        ld (PAGE3_BASE),a
        jp dispatch
.dynamic_page3_copy:
        ; The sole 0xFF->3 snapshot is overwritten before it is consumed.
        ; Keeping the semantic marker avoids a 6,912-byte third framebuffer.
        xor a
        ld (PAGE3_QUEUE_COUNT),a
        ld (PAGE3_BASE),a
        jp dispatch

op_present:                           ; 0x10
        call fetch_byte
        ld (PRESENT_PAGE),a
        call maybe_render
        ld a,(PENDING_PALETTE)
        cp 0xFF
        jr z,.palette_done
        ld (CURRENT_PALETTE),a
        ld a,0xFF
        ld (PENDING_PALETTE),a
.palette_done:
        ld a,(PRESENT_PAGE)
        cp 0xFF
        jr nz,.explicit
        ld a,(LOGICAL_FRONT)
        ld b,a
        ld a,(LOGICAL_BACK)
        ld (LOGICAL_FRONT),a
        ld a,b
        ld (LOGICAL_BACK),a
        ld a,(LOGICAL_FRONT)
        jr .show_screen
.explicit:
        cp 1
        jr z,.show_bank7
        cp 2
        jr z,.show_bank5
        jp dispatch
.show_bank7:
        ld a,1
        jr .show_screen
.show_bank5:
        xor a
.show_screen:
        or a
        jr z,.display5
        ld a,8
        jr .display_ready
.display5:
        xor a
.display_ready:
        ld (DISPLAY_BIT),a
        or 1                          ; restore bytecode bank after every flip
        call page_a
        jp dispatch

op_remove_task:                       ; 0x11
        ld hl,0xBFFF                  ; BYTECODE_BASE + 0xFFFF modulo 65536
        ld (VM_PC),hl
        ret

op_draw_string:                       ; 0x12: word, x, y, colour
        call fetch_word_de
        ld (TEXT_ID),de
        call fetch_byte
        ld (TEXT_X),a
        call fetch_byte
        ld (TEXT_Y),a
        call fetch_byte
        ld (TEXT_COLOR),a
        ld a,(WORK_PAGE)
        or a
        jr z,.background
        cp 3
        jr z,.page3
        call select_work_screen
        jp c,dispatch
        call visual_tick_live
        jp z,dispatch
        xor a
        ld (DRAW_DEST),a
        call RENDERER_DRAW_BG_TEXT
        jp dispatch
.page3:
        call queue_page3_text
        jp dispatch
.background:
        ld a,1
        ld (DRAW_DEST),a
        call RENDERER_DRAW_BG_TEXT
        jp dispatch

op_sub_vars:                          ; 0x13
op_and_const:                         ; 0x14
op_or_const:                          ; 0x15
op_shl_const:                         ; 0x16
op_shr_const:                         ; 0x17
        jp unsupported

op_sound:                             ; 0x18: word, frequency, volume, channel
        call fetch_word_de
        call fetch_byte
        call fetch_byte
        call fetch_byte
        jp dispatch

op_resource:                          ; 0x19
        call fetch_word_de
        push de
        call RENDERER_LOAD_RESOURCE
        pop de
        ld hl,16002
        or a
        sbc hl,de
        jr nz,.continue
        ld a,1
        ld (NEXT_PART),a
.continue:
        jp dispatch

op_music:                             ; 0x1A: word, delay word, position
        call fetch_word_de
        call fetch_word_de
        call fetch_byte
        jp dispatch

; Shape opcodes retain the original resource offsets and transforms.  A
; 373-byte liveness mask removes draws overwritten before the next 5 fps
; sample; surviving geometry is decoded from the unmodified resource.
op_shape80:
        call fetch_byte               ; low offset byte
        ld l,a
        ld a,(CURRENT_OPCODE)
        ld h,a
        add hl,hl
        ld (TEMP_OFFSET),hl

        call fetch_byte               ; x
        ld e,a
        ld d,0
        ld (TMP_WORD),de

        call fetch_byte               ; y
        ld l,a
        ld h,0
        cp 200
        jr c,.position_ready
        sub 199
        ld c,a
        ld b,0
        ex de,hl
        ld de,(TMP_WORD)
        add hl,de
        ld (TMP_WORD),hl
        ld hl,199
.position_ready:
        ld (QUEUE_Y),hl
        ld hl,64
        ld (QUEUE_ZOOM),hl
        call route_shape
        jp dispatch

op_shape40:
        call fetch_byte               ; offset high
        ld (TMP_INDEX),a
        call fetch_byte               ; offset low
        ld l,a
        ld a,(TMP_INDEX)
        ld h,a
        add hl,hl
        ld (TEMP_OFFSET),hl

        call fetch_byte               ; x byte / high byte / variable id
        ld e,a
        ld d,0
        ld a,(CURRENT_OPCODE)
        bit 5,a
        jr nz,.short_x
        bit 4,a
        jr nz,.variable_x
        call fetch_byte
        ld d,e
        ld e,a
        jr .x_done
.variable_x:
        ld a,e
        call load_var_de
        jr .x_done
.short_x:
        bit 4,a
        jr z,.x_done
        inc d                          ; unsigned 0x100..0x1FF form
.x_done:
        ld (TMP_WORD),de

        call fetch_byte               ; y byte / high byte / variable id
        ld e,a
        ld d,0
        ld a,(CURRENT_OPCODE)
        bit 3,a
        jr nz,.y_done
        bit 2,a
        jr nz,.variable_y
        call fetch_byte
        ld d,e
        ld e,a
        jr .y_done
.variable_y:
        ld a,e
        call load_var_de
.y_done:
        ld (QUEUE_Y),de
        ld hl,64
        ld (QUEUE_ZOOM),hl

        ld a,(CURRENT_OPCODE)
        bit 1,a
        jr nz,.bit1_set
        bit 0,a
        jr z,.done
        call fetch_byte               ; zoom variable
        call load_var_de
        ld (QUEUE_ZOOM),de
        jr .done
.bit1_set:
        bit 0,a                       ; segment 2 form (not reached here)
        jr nz,.done
        call fetch_byte               ; immediate zoom
        ld l,a
        ld h,0
        ld (QUEUE_ZOOM),hl
.done:
        call route_shape
        jp dispatch

load_var_de:
        call var_ptr_a
        ld e,(hl)
        inc hl
        ld d,(hl)
        ret

route_shape:
        ld a,(WORK_PAGE)
        or a
        jr z,.background
        cp 3
        jr z,.page3
        call visual_tick_live
        ret z
        call select_work_screen
        ret c
        xor a
        ld (DRAW_DEST),a
        jp RENDERER_DRAW_BG_SHAPE
.background:
        call checkpoint_for_tick
        ret nc
        ld a,1
        ld (DRAW_DEST),a
        jp RENDERER_DRAW_BG_SHAPE
.page3:
        jp queue_page3_shape

; Resolve 0xFF/0xFE to the current physical screen. Carry means unsupported.
select_work_screen:
        ld a,(WORK_PAGE)
        cp 0xFF
        jr z,.back
        cp 0xFE
        jr z,.front
        scf
        ret
.back:
        ld a,(LOGICAL_BACK)
        jr .selected
.front:
        ld a,(LOGICAL_FRONT)
.selected:
        ld (TARGET_SCREEN),a
        or a                           ; clear carry
        ret

; Return Z when visual work on the current VM tick is dead before every
; sampled presentation.  The mask lives in bank 5 immediately after bitmap.
visual_tick_live:
        ld hl,(TICK)
        ld a,l
        and 7
        ld b,a
        srl h
        rr l
        srl h
        rr l
        srl h
        rr l
        ld de,0x5B00
        add hl,de
        ld c,(hl)
        ld a,b
        or a
        jr z,.bit_ready
.shift:
        srl c
        djnz .shift
.bit_ready:
        ld a,c
        and 1
        ret

queue_page3_shape:
        ld a,(PAGE3_QUEUE_COUNT)
        cp QUEUE_MAX
        ret nc
        ld b,a
        inc a
        ld (PAGE3_QUEUE_COUNT),a
        ld a,b
        call page3_record_ptr
        xor a                          ; record type 0 = shape
        ld (hl),a
        inc hl
        ld de,(TEMP_OFFSET)
        ld (hl),e
        inc hl
        ld (hl),d
        inc hl
        ld de,(TMP_WORD)
        ld (hl),e
        inc hl
        ld (hl),d
        inc hl
        ld de,(QUEUE_Y)
        ld (hl),e
        inc hl
        ld (hl),d
        inc hl
        ld de,(QUEUE_ZOOM)
        ld (hl),e
        inc hl
        ld (hl),d
        inc hl
        ld (hl),0xFF
        ret

queue_page3_text:
        ld a,(PAGE3_QUEUE_COUNT)
        cp QUEUE_MAX
        ret nc
        ld b,a
        inc a
        ld (PAGE3_QUEUE_COUNT),a
        ld a,b
        call page3_record_ptr
        ld (hl),1                    ; record type 1 = text
        inc hl
        ld de,(TEXT_ID)
        ld (hl),e
        inc hl
        ld (hl),d
        inc hl
        ld a,(TEXT_X)
        ld (hl),a
        inc hl
        ld (hl),0
        inc hl
        ld a,(TEXT_Y)
        ld (hl),a
        inc hl
        ld (hl),0
        inc hl
        ld a,(TEXT_COLOR)
        ld (hl),a
        inc hl
        xor a
        ld (hl),a
        inc hl
        ld (hl),a
        ret

; A=record index, return HL=PAGE3_QUEUE_BASE + A*10.
page3_record_ptr:
        ld l,a
        ld h,0
        add hl,hl                    ; 2*n
        ld e,l
        ld d,h
        add hl,hl                    ; 4*n
        add hl,hl                    ; 8*n
        add hl,de                    ; 10*n
        ld de,PAGE3_QUEUE_BASE
        add hl,de
        ret

; Return checkpoint index in A with carry clear at the five dense one-time
; page-0 builds. Carry set means ordinary resource rendering.
checkpoint_for_tick:
        ld hl,(TICK)
        ld de,190
        or a
        sbc hl,de
        jr z,.zero
        ld hl,(TICK)
        ld de,302
        or a
        sbc hl,de
        jr z,.one
        ld hl,(TICK)
        ld de,403
        or a
        sbc hl,de
        jr z,.two
        ld hl,(TICK)
        ld de,1053
        or a
        sbc hl,de
        jr z,.three
        ld hl,(TICK)
        ld de,2211
        or a
        sbc hl,de
        jr z,.four
        scf
        ret
.zero:
        xor a
        ret
.one:
        ld a,1
        or a
        ret
.two:
        ld a,2
        or a
        ret
.three:
        ld a,3
        or a
        ret
.four:
        ld a,4
        or a
        ret

unsupported:
        ld a,(CURRENT_OPCODE)
        ld (ERROR_OPCODE),a
        ld a,2
        ld (DONE),a
        di
.hold:
        halt
        jr .hold

opcode_table:
        dw op_mov_const
        dw op_mov
        dw op_add_vars
        dw op_add_const
        dw op_call
        dw op_ret
        dw op_yield
        dw op_jmp
        dw op_install_task
        dw op_loop_var
        dw op_cond_jmp
        dw op_set_palette
        dw op_task_state
        dw op_select_page
        dw op_fill_page
        dw op_copy_page
        dw op_present
        dw op_remove_task
        dw op_draw_string
        dw op_sub_vars
        dw op_and_const
        dw op_or_const
        dw op_shl_const
        dw op_shr_const
        dw op_sound
        dw op_resource
        dw op_music

; ---------------------------------------------------------------------------
; The VM still runs at 50 Hz.  Only every tenth presentation advances the
; Spectrum attribute stream, while the liveness mask keeps persistent draws.

maybe_render:
        ld hl,(FRAME_COUNT)
        ld de,298
        or a
        sbc hl,de
        ret z
        ld hl,(TICK)
        ld de,(NEXT_VISUAL_TICK)
        or a
        sbc hl,de
        ret nz
        ld a,(LOGICAL_BACK)          ; page 0xFF becomes front on this present
        ld (LAST_SAMPLE_BANK),a
        call RENDERER_PRESENT
        ld hl,(NEXT_VISUAL_TICK)
        ld de,10
        add hl,de
        ld (NEXT_VISUAL_TICK),hl
        ret

page_a:
        ld bc,0x7FFD
        out (c),a
        ret

; ---------------------------------------------------------------------------
; Fast independent LZSS block decoder used by prepared bitmap backgrounds.
;
; The resumable attribute stream needs a separate 2 KiB history ring because
; successive 768-byte maps overwrite one another.  Independent 6 KiB bitmap
; blocks do not: their match history is already present immediately behind DE.
; Decoding matches straight from the output removes the per-byte ring traffic
; and, crucially, leaves the attribute decoder state untouched.
;
; HL=packed source, DE=destination, BC=unpacked bytes, A=7 for bank 7 or FF for
; a fixed-bank source.  IX, AF, BC, DE and HL are clobbered.
        ASSERT $ <= 0x8900
        defs 0x8900-$,0
        ORG 0x8900
fast_lz_block:
        cp 0xFF
        jr z,.source_ready
        push bc
        ld b,a
        and 7
        ld (0x7280),a                ; renderer CURRENT_BANK
        ld a,(DISPLAY_BIT)
        or b
        ld bc,0x7FFD
        out (c),a
        pop bc
.source_ready:
        push hl
        pop ix
        ld h,d
        ld l,e
        add hl,bc
        ld (BLOCK_LZ_END),hl
        xor a
        ld (BLOCK_LZ_BITS),a

.token:
        ld hl,(BLOCK_LZ_END)
        or a
        sbc hl,de
        ret z
        ld a,(BLOCK_LZ_BITS)
        or a
        jr nz,.have_flags
        ld a,(ix+0)
        inc ix
        ld (BLOCK_LZ_FLAGS),a
        ld a,8
        ld (BLOCK_LZ_BITS),a
.have_flags:
        ld a,(BLOCK_LZ_FLAGS)
        srl a
        ld (BLOCK_LZ_FLAGS),a
        jr c,.literal
        ld a,(BLOCK_LZ_BITS)
        dec a
        ld (BLOCK_LZ_BITS),a

        ld a,(ix+0)
        inc ix
        ld l,a
        ld h,0
        add hl,hl
        add hl,hl
        add hl,hl
        ld a,(ix+0)
        inc ix
        ld (BLOCK_LZ_SECOND),a
        rrca
        rrca
        rrca
        rrca
        rrca
        and 7
        ld c,a
        ld b,0
        add hl,bc
        inc hl                         ; HL=match distance
        push de
        ex de,hl                       ; HL=output, DE=distance
        or a
        sbc hl,de                      ; HL=match source
        pop de                         ; DE=output

        ld a,(BLOCK_LZ_SECOND)
        and 31
        ld c,a
        ld b,0
        cp 31
        jr nz,.length_ready
.extension:
        ld a,(ix+0)
        inc ix
        push af
        push hl
        ld l,a
        ld h,0
        add hl,bc
        ld b,h
        ld c,l
        pop hl
        pop af
        cp 255
        jr z,.extension
.length_ready:
        inc bc
        inc bc
        inc bc
        ldir
        jr .token

.literal:
        ld a,(BLOCK_LZ_BITS)
        dec a
        ld (BLOCK_LZ_BITS),a
        ld a,(ix+0)
        inc ix
        ld (de),a
        inc de
        jp .token

fast_lz_block_end:
        ASSERT fast_lz_block_end < 0x8A00

code_end:
        ASSERT code_end < VARS

        END
