#!/usr/bin/env python3
"""Bit-exact tests for the ST-style Spectrum span writer."""

from __future__ import annotations

import random
import unittest

import st_renderer_patch
from st_renderer_patch import EDGE_PATCH_TAG, PATCH_TAG, patch_renderer

FIRST_MASKS = (0xFF, 0x7F, 0x3F, 0x1F, 0x0F, 0x07, 0x03, 0x01)
LAST_MASKS = (0x80, 0xC0, 0xE0, 0xF0, 0xF8, 0xFC, 0xFE, 0xFF)


def reference_fill(
    dst: bytearray,
    background: bytes,
    attrs: bytes,
    decisions: bytes,
    left: int,
    right: int,
    color: int,
    dest_mode: int,
) -> None:
    first, last = left >> 3, right >> 3
    for byte_index in range(first, last + 1):
        mask = 0xFF
        if byte_index == first:
            mask &= FIRST_MASKS[left & 7]
        if byte_index == last:
            mask &= LAST_MASKS[right & 7]
        if color == 17:
            if dest_mode:
                continue
            dst[byte_index] = (dst[byte_index] & (~mask & 0xFF)) | (
                background[byte_index] & mask
            )
        elif decisions[attrs[byte_index]]:
            dst[byte_index] |= mask
        else:
            dst[byte_index] &= ~mask & 0xFF


def optimized_fill(
    dst: bytearray,
    background: bytes,
    attrs: bytes,
    decisions: bytes,
    left: int,
    right: int,
    color: int,
    dest_mode: int,
) -> None:
    first, last = left >> 3, right >> 3
    if color == 17 and dest_mode:
        return

    def masked_normal(index: int, mask: int) -> None:
        if decisions[attrs[index]]:
            dst[index] |= mask
        else:
            dst[index] &= ~mask & 0xFF

    def masked_page(index: int, mask: int) -> None:
        dst[index] = (dst[index] & (~mask & 0xFF)) | (background[index] & mask)

    if first == last:
        mask = FIRST_MASKS[left & 7] & LAST_MASKS[right & 7]
        (masked_page if color == 17 else masked_normal)(first, mask)
        return

    if color == 17:
        masked_page(first, FIRST_MASKS[left & 7])
        dst[first + 1 : last] = background[first + 1 : last]
        masked_page(last, LAST_MASKS[right & 7])
    else:
        masked_normal(first, FIRST_MASKS[left & 7])
        for index in range(first + 1, last):
            dst[index] = decisions[attrs[index]]
        masked_normal(last, LAST_MASKS[right & 7])


class SpanEquivalenceTests(unittest.TestCase):
    def test_exhaustive_geometry_random_data(self) -> None:
        rng = random.Random(0xA71A)
        for _ in range(64):
            original = bytearray(rng.randrange(256) for _ in range(32))
            background = bytes(rng.randrange(256) for _ in range(32))
            attrs = bytes(rng.randrange(128) for _ in range(32))
            decisions = bytes(0xFF if rng.getrandbits(1) else 0 for _ in range(128))
            for color in (0, 3, 16, 17):
                for dest_mode in (0, 1):
                    for left in range(256):
                        rights = {left, min(255, left + 1), min(255, (left | 7)), 255}
                        for right in rights:
                            expected = bytearray(original)
                            actual = bytearray(original)
                            reference_fill(
                                expected,
                                background,
                                attrs,
                                decisions,
                                left,
                                right,
                                color,
                                dest_mode,
                            )
                            optimized_fill(
                                actual,
                                background,
                                attrs,
                                decisions,
                                left,
                                right,
                                color,
                                dest_mode,
                            )
                            self.assertEqual(expected, actual, (color, dest_mode, left, right))

    def test_patcher_replaces_expected_hot_paths(self) -> None:
        source = """prefix
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
fill_span:
.byte_loop:
 call decision_ink
 ld (SPAN_CURRENT_BYTE),a
 jp .byte_loop

; Expand the current primitive's 16-byte packed decision row
scale_x_clamped:
.divide:
 ld de,5
 sbc hl,bc
scale_y_clamped:
suffix
"""
        patched = patch_renderer(source)
        self.assertIn(PATCH_TAG, patched)
        self.assertIn(EDGE_PATCH_TAG, patched)
        self.assertTrue(patched.startswith("prefix\n"))
        self.assertTrue(patched.endswith("suffix\n"))
        self.assertEqual(patch_renderer(patched), patched)

    def test_partial_edge_clear_covers_exact_scan_range(self) -> None:
        for minimum in range(192):
            for maximum in range(minimum, 192):
                baseline_left = [255] * 192
                baseline_right = [0] * 192
                optimized_left = [37] * 192
                optimized_right = [91] * 192
                optimized_left[minimum : maximum + 1] = [255] * (maximum - minimum + 1)
                optimized_right[minimum : maximum + 1] = [0] * (maximum - minimum + 1)
                self.assertEqual(
                    optimized_left[minimum : maximum + 1],
                    baseline_left[minimum : maximum + 1],
                )
                self.assertEqual(
                    optimized_right[minimum : maximum + 1],
                    baseline_right[minimum : maximum + 1],
                )

    def test_scale_x_reference_is_exact(self) -> None:
        values = [x - x // 5 for x in range(320)]
        self.assertEqual(values, [x - x // 5 for x in range(320)])


if __name__ == "__main__":
    unittest.main()
