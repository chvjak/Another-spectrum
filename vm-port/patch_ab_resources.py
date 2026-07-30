#!/usr/bin/env python3
"""Patch the recovered A/B harness to read another_js ByteKiller resources."""

from __future__ import annotations

import argparse
from pathlib import Path

DECODER = r'''
def extract_js_resources(path):
    text = path.read_text(encoding="utf-8")

    def be32(buf, offset):
        return int.from_bytes(buf[offset:offset + 4], "big")

    def unpack_bytekiller(src, expected):
        src_offset = len(src) - 4
        remaining = be32(src, src_offset)
        src_offset -= 4
        if remaining != expected:
            raise RuntimeError(f"ByteKiller size {remaining}, expected {expected}")

        dst = bytearray(remaining)
        dst_offset = remaining - 1
        crc = be32(src, src_offset)
        src_offset -= 4
        bits = be32(src, src_offset)
        src_offset -= 4
        crc ^= bits

        def next_bit():
            nonlocal bits, crc, src_offset
            carry = bits & 1
            bits >>= 1
            if bits == 0:
                if src_offset < 0:
                    raise RuntimeError("ByteKiller source underrun")
                bits = be32(src, src_offset)
                src_offset -= 4
                crc ^= bits
                carry = bits & 1
                bits = 0x80000000 | (bits >> 1)
            return carry

        def get_bits(count):
            value = 0
            for _ in range(count):
                value = (value << 1) | next_bit()
            return value

        def copy_literal(bits_count, extra):
            nonlocal remaining, dst_offset
            count = get_bits(bits_count) + extra + 1
            remaining -= count
            if remaining < 0:
                count += remaining
                remaining = 0
            for i in range(count):
                dst[dst_offset - i] = get_bits(8)
            dst_offset -= count

        def copy_reference(bits_count, count):
            nonlocal remaining, dst_offset
            remaining -= count
            if remaining < 0:
                count += remaining
                remaining = 0
            offset = get_bits(bits_count)
            for i in range(count):
                dst[dst_offset - i] = dst[dst_offset - i + offset]
            dst_offset -= count

        while remaining > 0:
            if not next_bit():
                if not next_bit():
                    copy_literal(3, 0)
                else:
                    copy_reference(8, 2)
            else:
                code = get_bits(2)
                if code == 3:
                    copy_literal(8, 8)
                elif code == 2:
                    copy_reference(12, get_bits(8) + 1)
                elif code == 1:
                    copy_reference(10, 4)
                else:
                    copy_reference(9, 3)

        if crc != 0:
            raise RuntimeError(f"ByteKiller CRC {crc:#x}")
        return bytes(dst)

    resources = {}
    for number in (RESOURCE_PALETTE, RESOURCE_BYTECODE, RESOURCE_SHAPES):
        hex_id = f"{number:02x}"
        data_match = re.search(rf'const data{hex_id} = "([A-Za-z0-9+/=]+)";', text)
        size_match = re.search(rf'const size{hex_id} = (\d+);', text)
        if data_match is None or size_match is None:
            raise RuntimeError(f"resource {number:#x} missing from {path}")
        payload = base64.b64decode(data_match.group(1), validate=True)
        expected = int(size_match.group(1))
        if len(payload) != expected:
            payload = unpack_bytekiller(payload, expected)
        if len(payload) != expected:
            raise RuntimeError(f"resource {number:#x}: {len(payload)} != {expected}")
        resources[number] = payload

    return (
        resources[RESOURCE_BYTECODE],
        resources[RESOURCE_SHAPES],
        resources[RESOURCE_PALETTE],
    )
'''


def patch(path: Path) -> None:
    source = path.read_text(encoding="utf-8")
    marker = '\nif __name__ == "__main__":'
    if marker not in source:
        raise RuntimeError("helper main marker missing")
    path.write_text(source.replace(marker, DECODER + marker, 1), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("helper", type=Path)
    args = parser.parse_args()
    patch(args.helper)


if __name__ == "__main__":
    main()
