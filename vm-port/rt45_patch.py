#!/usr/bin/env python3
"""Patch the generated VM to skip selected 5 fps sample ticks.

The drop tick list is stored in fixed bank-5 RAM at 0x5C9B. FRAME_COUNT still
counts rendered presentations; RT_SAMPLE_SLOT counts all original 5 fps sample
slots so validation can map every retained frame back to the 298-frame baseline.
"""
from __future__ import annotations

DROP_LIST_ADDR = 0x5C9B
RT_DROP_PTR = 0x93E6
RT_SAMPLE_SLOT = 0x93E8

VARS = f'''RT_DROP_PTR             EQU 0x{RT_DROP_PTR:04X}\nRT_SAMPLE_SLOT          EQU 0x{RT_SAMPLE_SLOT:04X}\n'''

INIT_OLD = '''        ld a,(0x6C00)\n        ld (EVENT_RUN_KEEP),a\n        ld a,(hl)\n        inc hl\n        ld (EVENT_RUN_PTR),hl\n        ld (EVENT_RUN_REMAIN),a\n'''

INIT_NEW = INIT_OLD + f'''        ld hl,0x{DROP_LIST_ADDR:04X}\n        ld (RT_DROP_PTR),hl\n'''

MAYBE_OLD = '''maybe_render:\n        ld hl,(FRAME_COUNT)\n        ld de,298\n        or a\n        sbc hl,de\n        ret z\n        ld hl,(TICK)\n        ld de,(NEXT_VISUAL_TICK)\n        or a\n        sbc hl,de\n        ret nz\n        ld a,(LOGICAL_BACK)          ; page 0xFF becomes front on this present\n        ld (LAST_SAMPLE_BANK),a\n        call RENDERER_PRESENT\n        ld hl,(NEXT_VISUAL_TICK)\n        ld de,10\n        add hl,de\n        ld (NEXT_VISUAL_TICK),hl\n        ret\n'''

MAYBE_NEW = '''maybe_render:\n        ld hl,(TICK)\n        ld de,(NEXT_VISUAL_TICK)\n        or a\n        sbc hl,de\n        ret nz\n
        ; Advance the original 5 fps sample timeline whether this slot is
        ; rendered or deliberately dropped.
        ld hl,(NEXT_VISUAL_TICK)
        ld de,10
        add hl,de
        ld (NEXT_VISUAL_TICK),hl
        ld hl,(RT_SAMPLE_SLOT)
        inc hl
        ld (RT_SAMPLE_SLOT),hl

        ; Compare the current VM tick with the next 16-bit drop tick.
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
        ret
.render:
        ld a,(LOGICAL_BACK)          ; page 0xFF becomes front on this present
        ld (LAST_SAMPLE_BANK),a
        call RENDERER_PRESENT
        ret
'''


def patch_vm(source: str) -> str:
    if 'RT_DROP_PTR' not in source:
        marker = 'EVENT_RUN_KEEP         EQU 0x9336\n'
        if source.count(marker) != 1:
            raise ValueError(f'variable marker count={source.count(marker)}')
        source = source.replace(marker, marker + VARS, 1)
    if source.count(INIT_OLD) != 1:
        raise ValueError(f'init marker count={source.count(INIT_OLD)}')
    source = source.replace(INIT_OLD, INIT_NEW, 1)
    if source.count(MAYBE_OLD) != 1:
        raise ValueError(f'maybe_render marker count={source.count(MAYBE_OLD)}')
    return source.replace(MAYBE_OLD, MAYBE_NEW, 1)
