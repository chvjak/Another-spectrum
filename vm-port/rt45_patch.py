#!/usr/bin/env python3
"""Patch the live VM to omit selected 5 fps presentation slots."""

DROP_LIST_ADDR = 0x5C9B
RT_DROP_PTR = 0x93E6
RT_SAMPLE_SLOT = 0x93E8
RT_KEPT_COUNT = 0x93EA
RT_SUPPRESS_DISPLAY = 0x93EC
RT_LAST_KEPT_SLOT = 0x93EE

VARS = (
    f"RT_DROP_PTR             EQU 0x{RT_DROP_PTR:04X}\n"
    f"RT_SAMPLE_SLOT          EQU 0x{RT_SAMPLE_SLOT:04X}\n"
    f"RT_KEPT_COUNT           EQU 0x{RT_KEPT_COUNT:04X}\n"
    f"RT_SUPPRESS_DISPLAY     EQU 0x{RT_SUPPRESS_DISPLAY:04X}\n"
    f"RT_LAST_KEPT_SLOT       EQU 0x{RT_LAST_KEPT_SLOT:04X}\n"
)

INIT_OLD = """        ld a,(0x6C00)
        ld (EVENT_RUN_KEEP),a
        ld a,(hl)
        inc hl
        ld (EVENT_RUN_PTR),hl
        ld (EVENT_RUN_REMAIN),a
"""

INIT_NEW = INIT_OLD + f"""        ld hl,0x{DROP_LIST_ADDR:04X}
        ld (RT_DROP_PTR),hl
"""

MAYBE_OLD = """maybe_render:
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
"""

MAYBE_NEW = """maybe_render:
        ld hl,(TICK)
        ld de,(NEXT_VISUAL_TICK)
        or a
        sbc hl,de
        ret nz

        ld hl,(NEXT_VISUAL_TICK)
        ld de,10
        add hl,de
        ld (NEXT_VISUAL_TICK),hl
        ld hl,(RT_SAMPLE_SLOT)
        inc hl
        ld (RT_SAMPLE_SLOT),hl

        ld hl,(RT_DROP_PTR)
        ld e,(hl)
        inc hl
        ld d,(hl)
        ld hl,(TICK)
        or a
        sbc hl,de
        jr nz,.render
        ld hl,(RT_DROP_PTR)
        inc hl
        inc hl
        ld (RT_DROP_PTR),hl
        ld a,1
        ld (RT_SUPPRESS_DISPLAY),a
        call RENDERER_PRESENT
        ret
.render:
        ld hl,(RT_SAMPLE_SLOT)
        ld (RT_LAST_KEPT_SLOT),hl
        ld a,(LOGICAL_BACK)          ; page 0xFF becomes front on this present
        ld (LAST_SAMPLE_BANK),a
        call RENDERER_PRESENT
        ld hl,(RT_KEPT_COUNT)
        inc hl
        ld (RT_KEPT_COUNT),hl
        xor a
        ld (RT_SUPPRESS_DISPLAY),a
        ret
"""

SHOW_OLD = """.show_screen:
        or a
        jr z,.display5
"""

SHOW_NEW = """.show_screen:
        ld b,a
        ld a,(RT_SUPPRESS_DISPLAY)
        or a
        jr z,.rt_show_screen
        xor a
        ld (RT_SUPPRESS_DISPLAY),a
        jp dispatch
.rt_show_screen:
        ld a,b
        or a
        jr z,.display5
"""


def patch_vm(source: str) -> str:
    marker = "EVENT_RUN_KEEP         EQU 0x9336\n"
    if source.count(marker) != 1:
        raise ValueError(f"variable marker count={source.count(marker)}")
    source = source.replace(marker, marker + VARS, 1)
    if source.count(INIT_OLD) != 1:
        raise ValueError(f"init marker count={source.count(INIT_OLD)}")
    source = source.replace(INIT_OLD, INIT_NEW, 1)
    if source.count(MAYBE_OLD) != 1:
        raise ValueError(f"maybe_render marker count={source.count(MAYBE_OLD)}")
    source = source.replace(MAYBE_OLD, MAYBE_NEW, 1)
    if source.count(SHOW_OLD) != 1:
        raise ValueError(f"show_screen marker count={source.count(SHOW_OLD)}")
    return source.replace(SHOW_OLD, SHOW_NEW, 1)
