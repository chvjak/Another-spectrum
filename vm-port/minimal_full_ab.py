#!/usr/bin/env python3
"""Build baseline and ST-renderer full VM snapshots from the DOS demo resources.

This benchmark deliberately replaces the lost visual preprocessing products with
neutral but valid Spectrum attributes, bitmap resources, and checkpoints. The
original intro bytecode and 65 KiB shape resource are retained unchanged, and
all draw events are kept. Baseline and ST snapshots therefore execute the same
real VM control flow and polygon workload; only renderer_full.asm differs.
"""
from __future__ import annotations

import argparse
import base64
import importlib.util
import json
import re
import struct
import subprocess
import sys
from pathlib import Path

RESOURCE_PALETTE = 0x17
RESOURCE_BYTECODE = 0x18
RESOURCE_SHAPES = 0x19
TEXT_DATA_OFFSET_BANK1 = 0x2680
ATTR_CHUNK0_OFFSET_BANK1 = 0x2E00
ATTR_CHUNK0_SIZE = 0x1200
PAGED_DATA_OFFSET_BANK7 = 0x1B00
RENDERER_OFFSET_BANK5 = 0x1D20
EVENT_RUNS_OFFSET_BANK5 = 0x2C00
ASSET19_OFFSET_BANK5 = 0x3400


def find_ci(root: Path, name: str) -> Path:
    target = name.lower()
    for path in root.rglob("*"):
        if path.is_file() and path.name.lower() == target:
            return path
    raise FileNotFoundError(f"{name} below {root}")


def read_be32(data: bytes, pos: int) -> int:
    return int.from_bytes(data[pos : pos + 4], "big")


def bytekiller_unpack(src: bytes, dst_size: int) -> bytes:
    """Python port of rawgl bytekiller_unpack()."""
    if len(src) < 12:
        raise ValueError("short ByteKiller stream")
    sp = len(src) - 4
    out_size = read_be32(src, sp)
    sp -= 4
    if out_size > dst_size:
        raise ValueError((out_size, dst_size))
    dst = bytearray(dst_size)
    dp = out_size - 1
    crc = read_be32(src, sp)
    sp -= 4
    bits = read_be32(src, sp)
    sp -= 4
    crc ^= bits
    remaining = out_size

    def next_bit() -> int:
        nonlocal bits, crc, sp
        carry = bits & 1
        bits >>= 1
        if bits == 0:
            if sp < 0:
                raise ValueError("ByteKiller source underflow")
            bits = read_be32(src, sp)
            sp -= 4
            crc ^= bits
            carry = bits & 1
            bits = (1 << 31) | (bits >> 1)
        return carry

    def get_bits(count: int) -> int:
        value = 0
        for _ in range(count):
            value = (value << 1) | next_bit()
        return value

    def copy_literal(bits_count: int, length: int) -> None:
        nonlocal remaining, dp
        count = get_bits(bits_count) + length + 1
        remaining -= count
        if remaining < 0:
            count += remaining
            remaining = 0
        for i in range(count):
            dst[dp - i] = get_bits(8)
        dp -= count

    def copy_reference(bits_count: int, count: int) -> None:
        nonlocal remaining, dp
        remaining -= count
        if remaining < 0:
            count += remaining
            remaining = 0
        offset = get_bits(bits_count)
        for i in range(count):
            dst[dp - i] = dst[dp - i + offset]
        dp -= count

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
        raise ValueError(f"ByteKiller CRC {crc:#x}")
    return bytes(dst[:out_size])


def read_entries(data_dir: Path) -> list[dict[str, int]]:
    raw = find_ci(data_dir, "memlist.bin").read_bytes()
    entries: list[dict[str, int]] = []
    pos = 0
    while pos + 20 <= len(raw):
        status = raw[pos]
        entry = {
            "status": status,
            "type": raw[pos + 1],
            "rank": raw[pos + 6],
            "bank": raw[pos + 7],
            "position": read_be32(raw, pos + 8),
            "packed": read_be32(raw, pos + 12),
            "unpacked": read_be32(raw, pos + 16),
        }
        if status == 0xFF:
            break
        entries.append(entry)
        pos += 20
    if len(entries) <= RESOURCE_SHAPES:
        raise RuntimeError(f"only {len(entries)} MEMLIST entries")
    return entries


def extract_resource(data_dir: Path, entries: list[dict[str, int]], number: int) -> bytes:
    entry = entries[number]
    prefix = "demo" if any(p.name.lower() == "demo01" for p in data_dir.rglob("*")) else "bank"
    bank_path = find_ci(data_dir, f"{prefix}{entry['bank']:02x}")
    bank = bank_path.read_bytes()
    start = entry["position"]
    packed = bank[start : start + entry["packed"]]
    if len(packed) != entry["packed"]:
        raise RuntimeError(f"short resource {number:#x}")
    if entry["packed"] == entry["unpacked"]:
        return packed
    return bytekiller_unpack(packed, entry["unpacked"])



def extract_js_resources(path: Path) -> tuple[bytes, bytes, bytes]:
    """Extract palette/bytecode/shapes embedded by another_js ootwdemo.js."""
    text = path.read_text(encoding="utf-8")
    resources: dict[int, bytes] = {}
    for number in (RESOURCE_PALETTE, RESOURCE_BYTECODE, RESOURCE_SHAPES):
        hex_id = f"{number:02x}"
        data_match = re.search(rf'const data{hex_id} = "([A-Za-z0-9+/=]+)";', text)
        size_match = re.search(rf'const size{hex_id} = (\d+);', text)
        if data_match is None or size_match is None:
            raise RuntimeError(f"resource {number:#x} missing from {path}")
        expected = int(size_match.group(1))
        payload = base64.b64decode(data_match.group(1), validate=True)
        if len(payload) != expected:
            # another_js stores compressed DOS resources as ByteKiller
            # streams.  The historical CI helper assumed every embedded
            # payload was already unpacked, so it never reproduced the real
            # shareware resource pack locally.
            payload = bytekiller_unpack(payload, expected)
        if len(payload) != expected:
            raise RuntimeError(
                f"resource {number:#x}: decoded {len(payload)} bytes, expected {expected}"
            )
        resources[number] = payload
    return (
        resources[RESOURCE_BYTECODE],
        resources[RESOURCE_SHAPES],
        resources[RESOURCE_PALETTE],
    )

def spectrum_decisions() -> bytes:
    # Standard Spectrum RGB, normal then bright.
    palette = [
        (0, 0, 0), (0, 0, 205), (205, 0, 0), (205, 0, 205),
        (0, 205, 0), (0, 205, 205), (205, 205, 0), (205, 205, 205),
        (0, 0, 0), (0, 0, 255), (255, 0, 0), (255, 0, 255),
        (0, 255, 0), (0, 255, 255), (255, 255, 0), (255, 255, 255),
    ]
    out = bytearray()
    for desired in range(16):
        for group in range(16):
            bits = 0
            for low in range(8):
                attr = group * 8 + low
                bright = (attr >> 6) & 1
                ink = (attr & 7) + bright * 8
                paper = ((attr >> 3) & 7) + bright * 8
                ie = sum((palette[desired][i] - palette[ink][i]) ** 2 for i in range(3))
                pe = sum((palette[desired][i] - palette[paper][i]) ** 2 for i in range(3))
                if ie < pe:
                    bits |= 1 << low
            out.append(bits)
    for group in range(16):
        bits = 0
        for low in range(8):
            attr = group * 8 + low
            bright = (attr >> 6) & 1
            ink = (attr & 7) + bright * 8
            paper = ((attr >> 3) & 7) + bright * 8
            if sum(palette[ink]) > sum(palette[paper]):
                bits |= 1 << low
        out.append(bits)
    assert len(out) == 272
    return bytes(out)


def all_keep_runs(count: int = 9648) -> bytes:
    out = bytearray([1])
    while count > 255:
        out.extend((255, 0))
        count -= 255
    out.append(count)
    return bytes(out)


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def assemble(sjasmplus: Path, source: Path, output: Path) -> bytes:
    subprocess.run(
        [str(sjasmplus), f"--raw={output}", source.name],
        cwd=source.parent,
        check=True,
    )
    return output.read_bytes()


def put(page: bytearray, offset: int, payload: bytes, label: str) -> None:
    if offset < 0 or offset + len(payload) > len(page):
        raise RuntimeError(f"{label} overflow: {offset:#x}+{len(payload):#x}")
    page[offset : offset + len(payload)] = payload


def write_layout(source_dir: Path, packed_attrs: list[bytes], packed_bitmaps: list[bytes], checkpoints: list[bytes], direct_rows: bytes, page3_snapshots: list[bytes]) -> dict[str, int]:
    cursor = PAGED_DATA_OFFSET_BANK7
    addresses: dict[str, int] = {}
    def alloc(name: str, size: int) -> None:
        nonlocal cursor
        addresses[name] = 0xC000 + cursor
        cursor += size
    alloc("ATTR_MIDDLE_CHUNK1", max(0, len(packed_attrs[1]) - ATTR_CHUNK0_SIZE))
    alloc("ATTR_FIRST", len(packed_attrs[0]))
    alloc("ATTR_LAST", len(packed_attrs[2]))
    alloc("BITMAP18", len(packed_bitmaps[0]))
    alloc("BITMAP71", len(packed_bitmaps[1]))
    for i, payload in enumerate(checkpoints):
        alloc(f"CHECKPOINT{i}", len(payload))
    alloc("DIRECT_DECISION_ROWS", len(direct_rows))
    page3_cursor = 0x6C80
    for i, payload in enumerate(page3_snapshots):
        addresses[f"PAGE3_SNAPSHOT{i}"] = page3_cursor
        page3_cursor += len(payload)
    (source_dir / "generated_full_layout.inc").write_text(
        "; generated by minimal_full_ab.py\n" +
        "".join(f"{name:<24} EQU 0x{addr:04X}\n" for name, addr in addresses.items()),
        encoding="utf-8",
    )
    addresses["BANK7_END"] = cursor
    return addresses


def make_snapshot(
    vm: bytes, renderer: bytes, bytecode: bytes, shapes: bytes,
    packed_attrs: list[bytes], packed_bitmaps: list[bytes], checkpoints: list[bytes],
    palette_tables: bytes, decisions: bytes, event_runs: bytes, text_data: bytes,
    direct_rows: bytes, page3_snapshots: list[bytes],
) -> bytes:
    pages = [bytearray(0x4000) for _ in range(8)]
    put(pages[2], 0, vm, "VM")
    put(pages[1], 0, bytecode, "bytecode")
    put(pages[1], TEXT_DATA_OFFSET_BANK1, text_data, "compact text")
    for index, bank in enumerate((0, 3, 4, 6)):
        chunk = shapes[index * 0x4000 : (index + 1) * 0x4000]
        put(pages[bank], 0, chunk, f"shapes bank {bank}")

    middle = packed_attrs[1]
    put(pages[1], ATTR_CHUNK0_OFFSET_BANK1, middle[:ATTR_CHUNK0_SIZE], "middle attrs")
    cursor = PAGED_DATA_OFFSET_BANK7
    def put7(payload: bytes, label: str) -> None:
        nonlocal cursor
        put(pages[7], cursor, payload, label)
        cursor += len(payload)
    put7(middle[ATTR_CHUNK0_SIZE:], "middle attrs tail")
    put7(packed_attrs[0], "first attrs")
    put7(packed_attrs[2], "last attrs")
    put7(packed_bitmaps[0], "bitmap18")
    put7(packed_bitmaps[1], "bitmap71")
    for i, payload in enumerate(checkpoints):
        put7(payload, f"checkpoint{i}")
    put7(direct_rows, "direct decision rows")

    put(pages[5], RENDERER_OFFSET_BANK5, renderer, "renderer")
    put(pages[5], EVENT_RUNS_OFFSET_BANK5, event_runs, "event runs")
    page3_cursor = 0x2C80
    for i, payload in enumerate(page3_snapshots):
        put(pages[5], page3_cursor, payload, f"page3 snapshot {i}")
        page3_cursor += len(payload)
    put(pages[5], ASSET19_OFFSET_BANK5, packed_bitmaps[2], "bitmap19")
    put(pages[5], 0x1B00, bytes([0xFF]) * ((2980 + 7) // 8), "live ticks")
    put(pages[5], 0x1C75, bytes((298 + 7) // 8), "attr change mask")
    put(pages[2], 0x3B00, palette_tables + decisions, "palette/decisions")

    pages[5][0x1CFF] = 0x10
    pages[5][0x1D00] = 0x5D
    pages[5][0x1D10 : 0x1D1C] = bytes((0xF5,0xE5,0x21,0x25,0x93,0x34,0xE1,0xF1,0xFB,0xED,0x4D,0x00))

    header = bytearray(27)
    header[19] = 4
    header[23:25] = struct.pack("<H", 0xBFF0)
    header[25] = 2
    blob = bytearray(header) + pages[5] + pages[2] + pages[0]
    blob += struct.pack("<HBB", 0x8000, 0, 0)
    for bank in (1, 3, 4, 6, 7):
        blob += pages[bank]
    assert len(blob) == 131103
    return bytes(blob)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--source-dir", type=Path, required=True)
    p.add_argument("--patch-dir", type=Path)
    inputs = p.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--data-dir", type=Path)
    inputs.add_argument("--resource-js", type=Path)
    p.add_argument("--sjasmplus", type=Path, required=True)
    p.add_argument("--text-data", type=Path)
    p.add_argument("--baseline-only", action="store_true")
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()
    source = args.source_dir.resolve()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)

    if args.resource_js is not None:
        bytecode, shapes, palette = extract_js_resources(args.resource_js)
    else:
        assert args.data_dir is not None
        entries = read_entries(args.data_dir)
        bytecode = extract_resource(args.data_dir, entries, RESOURCE_BYTECODE)
        shapes = extract_resource(args.data_dir, entries, RESOURCE_SHAPES)
        palette = extract_resource(args.data_dir, entries, RESOURCE_PALETTE)
    print(json.dumps({"bytecode":len(bytecode),"shapes":len(shapes),"palette":len(palette)}))
    if len(bytecode) != 9842 or len(shapes) != 65156 or len(palette) != 2048:
        raise RuntimeError("unexpected DOS demo resource sizes")

    lzss = load_module(source / "lzss.py", "aw_lzss")
    attr = bytes([0x47]) * 768
    bitmap = bytes(6912)
    packed_attrs = [lzss.compress(attr), lzss.compress(attr), lzss.compress(attr)]
    packed_bitmaps = [lzss.compress(bitmap), lzss.compress(bitmap), lzss.compress(bitmap)]
    checkpoints = [lzss.compress(bytes(6144)) for _ in range(5)]
    direct_rows = bytes(16 * 16)
    page3_snapshots = [lzss.compress(bytes(6144)) for _ in range(2)]
    addresses = write_layout(source, packed_attrs, packed_bitmaps, checkpoints, direct_rows, page3_snapshots)

    vm = assemble(args.sjasmplus, source / "vm_full.asm", out / "vm.bin")
    baseline_renderer = assemble(args.sjasmplus, source / "renderer_full.asm", out / "renderer-baseline.bin")

    st_renderer = b""
    if not args.baseline_only:
        if args.patch_dir is None:
            raise RuntimeError("--patch-dir is required unless --baseline-only is used")
        patch = load_module(args.patch_dir / "st_renderer_patch.py", "st_renderer_patch")
        st_source = source / "renderer_full_st.asm"
        st_source.write_text(patch.patch_renderer((source / "renderer_full.asm").read_text(encoding="utf-8")), encoding="utf-8")
        st_renderer = assemble(args.sjasmplus, st_source, out / "renderer-st.bin")
        st_source.unlink(missing_ok=True)

    palette_tables = bytes(64) + bytes(range(16))
    decisions = spectrum_decisions()
    event_runs = all_keep_runs()
    text_data = args.text_data.read_bytes() if args.text_data else bytes(7)
    if len(text_data) > ATTR_CHUNK0_OFFSET_BANK1 - TEXT_DATA_OFFSET_BANK1:
        raise RuntimeError(f"compact text is too large: {len(text_data)} bytes")
    (out / "baseline.sna").write_bytes(make_snapshot(vm, baseline_renderer, bytecode, shapes, packed_attrs, packed_bitmaps, checkpoints, palette_tables, decisions, event_runs, text_data, direct_rows, page3_snapshots))
    if st_renderer:
        (out / "st.sna").write_bytes(make_snapshot(vm, st_renderer, bytecode, shapes, packed_attrs, packed_bitmaps, checkpoints, palette_tables, decisions, event_runs, text_data, direct_rows, page3_snapshots))
    manifest = {
        "mode": "real DOS bytecode/shapes, all draw events, neutral visual assets",
        "resource_sizes": {"bytecode":len(bytecode),"shapes":len(shapes),"palette":len(palette)},
        "vm_bytes": len(vm),
        "baseline_renderer_bytes": len(baseline_renderer),
        "st_renderer_bytes": len(st_renderer) if st_renderer else None,
        "renderer_growth_bytes": len(st_renderer)-len(baseline_renderer) if st_renderer else None,
        "renderer_gap_remaining": EVENT_RUNS_OFFSET_BANK5 - (RENDERER_OFFSET_BANK5 + len(st_renderer)) if st_renderer else None,
        "event_runs_bytes": len(event_runs),
        "bank7_end": addresses["BANK7_END"],
    }
    (out / "minimal-manifest.json").write_text(json.dumps(manifest, indent=2)+"\n")
    print(json.dumps(manifest, indent=2))

if __name__ == "__main__":
    main()
