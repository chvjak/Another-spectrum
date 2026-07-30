#!/usr/bin/env python3
"""Run the viewport matrix with colour attributes copied to both screens.

The earlier single-screen experiment was faster but can expose stale colours for
one hardware frame when rendering crosses an interrupt before the page flip.
This launcher keeps the active-viewport optimisations while preserving the
original double-buffer colour publication semantics.
"""
from __future__ import annotations
from pathlib import Path

base_path = Path(__file__).with_name("viewport_color_build.py")
source = base_path.read_text()
start = source.index("def patch_attr_vm(")
end = source.index("\ndef main()", start)

safe_function = r'''def patch_attr_vm(source: str, width: int, height: int) -> str:
    x0 = (256 - width) // 16
    y0 = (192 - height) // 16
    wc = width // 8
    hc = height // 8

    marker = "        jp profile_latch\n"
    if source.count(marker) != 1:
        raise ValueError("EGA vector marker changed")
    source = source.replace(marker, marker + "        jp active_attr_copy\n", 1)

    helper = f"""
active_attr_copy:
        ; Preserve the original semantics: publish the staged colours to both
        ; physical screens before the sampled page flip. Only active cells are
        ; copied for reduced viewports.
        ld hl,{0x9C00 + y0 * 32 + x0:#06x}
        ld de,{0x5800 + y0 * 32 + x0:#06x}
        ld a,{hc}
.bank5_row:
        push af
        ld bc,{wc}
        ldir
        ld bc,{32 - wc}
        add hl,bc
        ex de,hl
        add hl,bc
        ex de,hl
        pop af
        dec a
        jr nz,.bank5_row

        ld a,(DISPLAY_BIT)
        or 7
        call page_a
        ld hl,{0x9C00 + y0 * 32 + x0:#06x}
        ld de,{0xD800 + y0 * 32 + x0:#06x}
        ld a,{hc}
.bank7_row:
        push af
        ld bc,{wc}
        ldir
        ld bc,{32 - wc}
        add hl,bc
        ex de,hl
        add hl,bc
        ex de,hl
        pop af
        dec a
        jr nz,.bank7_row
        ret
"""
    marker = "        ASSERT $ <= 0x9300\n\n        END\n"
    if source.count(marker) != 1:
        raise ValueError("VM helper end marker changed")
    return source.replace(marker, helper + "        ASSERT $ <= 0x9300\n\n        END\n", 1)

'''

source = source[:start] + safe_function + source[end + 1:]
source = source.replace('"full-colorcopy": (256, 192, True),', '"full-safe": (256, 192, True),')
source = source.replace('"mode": "EGA winner plus single-screen colour copy and active viewport",', '"mode": "EGA winner plus safe double-screen active viewport",')
namespace = {"__name__": "__main__", "__file__": str(base_path)}
exec(compile(source, str(base_path), "exec"), namespace)
