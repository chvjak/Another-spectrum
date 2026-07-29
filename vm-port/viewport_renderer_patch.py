#!/usr/bin/env python3
"""ST renderer variant with fixed-bank coordinate lookup tables.

AW_VIEWPORT selects one of 256x192, 224x176 or 224x160. Smaller modes keep
all original 320x200 coordinates, scale them into a centred rectangle, and
leave a border around the dynamic polygon viewport.
"""

from __future__ import annotations

import os

from st_renderer_patch_base import patch_renderer as patch_st_renderer

X_SCALE_TABLE = 0xB800
Y_SCALE_TABLE = 0xB940
TABLE_BANK2_OFFSET = X_SCALE_TABLE - 0x8000

VIEWPORTS = {
    "256x192": (256, 192),
    "224x176": (224, 176),
    "224x160": (224, 160),
}

POLYGON_MARKER = "; ---------------------------------------------------------------------------\n; Polygon edge construction and scanline fill"


def selected_viewport() -> tuple[int, int]:
    name = os.environ.get("AW_VIEWPORT", "256x192")
    try:
        return VIEWPORTS[name]
    except KeyError as exc:
        raise ValueError(f"unsupported AW_VIEWPORT={name!r}") from exc


def _ceil_scale(value: int, output: int, input_size: int) -> int:
    """Centred viewport mapping with the original renderer's ceil-like bias."""
    return min(output - 1, (value * output + input_size - 1) // input_size)


def viewport_tables() -> bytes:
    width, height = selected_viewport()
    left = (256 - width) // 2
    top = (192 - height) // 2

    if (width, height) == (256, 192):
        # Preserve the existing renderer semantics exactly for the control case,
        # including the unused x=319/y=199 endpoint values that wrap/overflow
        # the nominal destination bounds in the original arithmetic routines.
        xs = [(x - x // 5) & 0xFF for x in range(320)]
        ys = [(y - y // 25) & 0xFF for y in range(200)]
    else:
        xs = [left + _ceil_scale(x, width, 320) for x in range(320)]
        ys = [top + _ceil_scale(y, height, 200) for y in range(200)]

    assert len(xs) == 320 and len(ys) == 200
    assert all(0 <= value <= 255 for value in xs)
    assert all(0 <= value <= 255 for value in ys)
    if (width, height) != (256, 192):
        assert all(left <= value < left + width for value in xs)
        assert all(top <= value < top + height for value in ys)
    return bytes(xs + ys)


def _lookup_routines(width: int, height: int) -> str:
    left = (256 - width) // 2
    top = (192 - height) // 2
    right = left + width - 1
    bottom = top + height - 1
    return f'''scale_x_clamped:
        bit 7,h
        jr z,.non_negative
        ld a,{left}
        ret
.non_negative:
        push hl
        ld de,320
        or a
        sbc hl,de
        pop hl
        jr c,.lookup
        ld a,{right}
        ret
.lookup:
        ld de,{X_SCALE_TABLE:#06x}
        add hl,de
        ld a,(hl)
        ret

scale_y_clamped:
        bit 7,h
        jr z,.non_negative
        ld a,{top}
        ret
.non_negative:
        push hl
        ld de,200
        or a
        sbc hl,de
        pop hl
        jr c,.lookup
        ld a,{bottom}
        ret
.lookup:
        ld de,{Y_SCALE_TABLE:#06x}
        add hl,de
        ld a,(hl)
        ret
'''


def patch_renderer(source: str) -> str:
    patched = patch_st_renderer(source)
    width, height = selected_viewport()
    start = patched.index("scale_x_clamped:\n")
    end = patched.index(POLYGON_MARKER, start)
    return patched[:start] + _lookup_routines(width, height) + "\n" + patched[end:]
