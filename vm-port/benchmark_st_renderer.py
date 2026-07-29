#!/usr/bin/env python3
"""Cycle-model benchmark for the ST-style renderer hot paths.

Counts documented Z80 T-states for the current baseline and generated variant.
The model intentionally excludes memory contention and unchanged caller/edge-
walker work. It is a comparative microbenchmark, not an end-to-end VM result.
"""

from __future__ import annotations

import json
from statistics import mean


def ldir_cycles(count: int) -> int:
    if count <= 0:
        return 0
    return 21 * (count - 1) + 16


def old_scale_x_cycles(x: int) -> int:
    if not 0 <= x < 320:
        raise ValueError(x)
    # Fixed path + one successful 5-subtraction loop per floor(x/5), then the
    # final failing subtraction. Derived directly from scale_x_clamped.
    return 187 + 44 * (x // 5)


def new_scale_x_cycles(x: int) -> int:
    if not 0 <= x < 320:
        raise ValueError(x)
    quotient = x // 5
    # Range check + setup/tail, then six quotient-bit steps. A successful bit
    # costs 78 T-states and a rejected bit 86.
    set_bits = quotient.bit_count()
    return 146 + 78 * set_bits + 86 * (6 - set_bits)


def old_edge_clear_cycles() -> int:
    # 192 bytes per table: one seed byte + LDIR BC=191.
    left = 10 + 10 + 10 + 10 + ldir_cycles(191)
    right = 10 + 10 + 10 + 4 + 7 + ldir_cycles(191)
    return left + right


def new_edge_clear_cycles(height: int) -> int:
    if not 1 <= height <= 192:
        raise ValueError(height)
    if height == 1:
        return 204
    # Exact instruction count with BC preserved across the first LDIR.
    return 191 + 42 * height


def pointer_setup_cycles(dest_mode: int = 0, target: int = 0) -> int:
    cycles = 0
    cycles += 13 + 4 + 7 + 4 + 4 + 7 + 12 + 4 + 4
    cycles += 13 + 4 + 7
    if dest_mode:
        cycles += 12
    else:
        cycles += 7 + 13 + 4 + 7
        cycles += 12 if target == 0 else 7 + 7
    cycles += 4 + 4 + 4 + 7 + 8 + 4 + 13 + 4 + 4 + 11
    cycles += 4 + 7 + 7 + 4 + 16
    cycles += 13 + 7 + 4 + 7 + 22 + 13 + 4 + 7 + 11 + 16 + 10 + 11 + 4
    cycles += 10 + 11 + 14 + 11 + 14
    return cycles


def old_span_cycles(left: int, right: int, ink: bool = True) -> int:
    """Baseline complete fill_span, normal colour, bank-5 screen destination."""
    first, last = left >> 3, right >> 3
    cycles = 113 + pointer_setup_cycles()
    for byte_index in range(first, last + 1):
        cycles += 7 + 13
        cycles += 13 + 4 + 13 + 4
        if byte_index == first:
            cycles += 7 + 13 + 7 + 4 + 7 + 10 + 11 + 7 + 13
        else:
            cycles += 12
        cycles += 13 + 4 + 13 + 4
        if byte_index == last:
            cycles += 7 + 13 + 7 + 4 + 7 + 10 + 11 + 13 + 7 + 13
        else:
            cycles += 12
        cycles += 13 + 7 + 7
        cycles += 19 + 17 + 4 + 7 + 7 + 4 + 10 + 4
        if ink:
            cycles += 7 + 13 + 19 + 19 + 12
        else:
            cycles += 12 + 13 + 4 + 19 + 19 + 12
        cycles += 10 + 10 + 16 + 6 + 16 + 16 + 6 + 16
        cycles += 13 + 4 + 13 + 4
        if byte_index == last:
            cycles += 11
        else:
            cycles += 5 + 4 + 4 + 13 + 10
    return cycles


def masked_normal_cycles(ink: bool = True) -> int:
    cycles = 19 + 7 + 7 + 4
    if ink:
        return cycles + 7 + 13 + 19 + 19 + 10
    return cycles + 12 + 13 + 4 + 19 + 19 + 10


def mask_setup_cycles() -> int:
    return 13 + 7 + 4 + 7 + 10 + 11 + 7 + 13


def combined_mask_cycles() -> int:
    return 13 + 7 + 4 + 7 + 10 + 11 + 7 + 13 + 7 + 4 + 7 + 10 + 11 + 7 + 4 + 13 + 10


def new_span_cycles(left: int, right: int, ink: bool = True) -> int:
    """Generated complete fill_span, normal colour, bank-5 screen destination."""
    first, last = left >> 3, right >> 3
    cycles = 100 + pointer_setup_cycles()
    cycles += 13 + 7 + 12
    cycles += 13 + 4 + 13 + 4
    if first == last:
        return cycles + 12 + 17 + combined_mask_cycles() + 10 + masked_normal_cycles(ink)
    cycles += 7
    cycles += mask_setup_cycles() + 17 + masked_normal_cycles(ink) + 10 + 10
    cycles += 13 + 4 + 13 + 4 + 4 + 4 + 4
    interior = last - first - 1
    if interior == 0:
        cycles += 12
    else:
        cycles += 7 + 4
        for index in range(interior):
            cycles += 19 + 7 + 7 + 19 + 10 + 10
            cycles += 8 if index == interior - 1 else 13
    cycles += mask_setup_cycles() + 10 + masked_normal_cycles(ink)
    return cycles


def average_span(width: int, fn) -> float:
    starts = range(1) if width == 256 else range(8)
    return mean(fn(start, start + width - 1) for start in starts)


def primitive_case(height: int, width: int, vertices: int) -> dict[str, float]:
    old = old_edge_clear_cycles()
    new = new_edge_clear_cycles(height)
    old += vertices * mean(old_scale_x_cycles(x) for x in range(320))
    new += vertices * mean(new_scale_x_cycles(x) for x in range(320))
    old += height * average_span(width, old_span_cycles)
    new += height * average_span(width, new_span_cycles)
    return {
        "height": height,
        "width": width,
        "vertices": vertices,
        "old_tstates": round(old, 1),
        "new_tstates": round(new, 1),
        "speedup": round(old / new, 3),
        "saved_percent": round((1 - new / old) * 100, 1),
    }


BASELINE_REFRESHES = 29392
CONTROL_FLOOR_REFRESHES = 2980


def full_run_projection(hotpath_share: float, hotpath_speedup: float) -> dict[str, float]:
    """Project total refreshes from the measured baseline via Amdahl's law.

    CONTROL_FLOOR_REFRESHES is the exact 2,980 VM-tick floor. The remainder is
    rendering/overrun time. This is deliberately a sensitivity model, not an
    emulator result.
    """
    if not 0 <= hotpath_share <= 1:
        raise ValueError(hotpath_share)
    if hotpath_speedup <= 0:
        raise ValueError(hotpath_speedup)
    render_overhead = BASELINE_REFRESHES - CONTROL_FLOOR_REFRESHES
    projected = CONTROL_FLOOR_REFRESHES + render_overhead * (
        (1 - hotpath_share) + hotpath_share / hotpath_speedup
    )
    return {
        "hotpath_share_percent": round(hotpath_share * 100, 1),
        "hotpath_speedup": round(hotpath_speedup, 3),
        "projected_refreshes": round(projected),
        "whole_run_speedup": round(BASELINE_REFRESHES / projected, 3),
        "whole_run_saved_percent": round((1 - projected / BASELINE_REFRESHES) * 100, 1),
    }


def main() -> None:
    span_rows = []
    for width in (1, 8, 16, 32, 64, 128, 256):
        old = average_span(width, old_span_cycles)
        new = average_span(width, new_span_cycles)
        span_rows.append(
            {
                "pixel_width": width,
                "old_tstates": round(old, 1),
                "new_tstates": round(new, 1),
                "speedup": round(old / new, 3),
                "saved_percent": round((1 - new / old) * 100, 1),
            }
        )

    edge_rows = []
    old_edge = old_edge_clear_cycles()
    for height in (1, 8, 16, 24, 48, 96, 160, 192):
        new_edge = new_edge_clear_cycles(height)
        edge_rows.append(
            {
                "scanlines": height,
                "old_tstates": old_edge,
                "new_tstates": new_edge,
                "speedup": round(old_edge / new_edge, 3),
                "saved_percent": round((1 - new_edge / old_edge) * 100, 1),
            }
        )

    old_x = [old_scale_x_cycles(x) for x in range(320)]
    new_x = [new_scale_x_cycles(x) for x in range(320)]
    report = {
        "scope": "uncontended Z80 T-state model of changed renderer hot paths",
        "correctness": {
            "span_equivalence": "exhaustive geometry/random-data unit test passes",
            "edge_range_equivalence": "all MIN_Y..MAX_Y ranges pass",
            "x_transform": "six-step quotient matches x-floor(x/5) for all 320 coordinates",
        },
        "scale_x": {
            "old_average_tstates": mean(old_x),
            "new_average_tstates": mean(new_x),
            "speedup": round(mean(old_x) / mean(new_x), 3),
            "saved_percent": round((1 - mean(new_x) / mean(old_x)) * 100, 1),
            "old_min": min(old_x),
            "old_max": max(old_x),
            "new_min": min(new_x),
            "new_max": max(new_x),
        },
        "span_writer": span_rows,
        "edge_clear": edge_rows,
        "combined_changed_hotpaths": [
            primitive_case(8, 16, 4),
            primitive_case(24, 32, 6),
            primitive_case(64, 96, 8),
        ],
        "full_run_sensitivity": {
            "baseline_refreshes": BASELINE_REFRESHES,
            "exact_vm_tick_floor": CONTROL_FLOOR_REFRESHES,
            "render_overhead_refreshes": BASELINE_REFRESHES - CONTROL_FLOOR_REFRESHES,
            "note": "Projection only; share of time in changed routines must be measured in emulator.",
            "conservative_2_6x_hotpath": [
                full_run_projection(share, 2.6)
                for share in (0.25, 0.5, 0.75, 1.0)
            ],
            "large_shape_3_32x_hotpath": [
                full_run_projection(share, 3.32)
                for share in (0.25, 0.5, 0.75, 1.0)
            ],
        },
        "limitations": [
            "does not include contended-screen wait states",
            "does not include unchanged resource decoding or edge walking",
            "cannot produce the full 29,392-refresh comparison without excluded local AW assets",
        ],
    }
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
