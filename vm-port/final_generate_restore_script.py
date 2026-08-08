#!/usr/bin/env python3
"""Convert exact restore-call dirty masks into a compact bank-7 script.

Encoding is call-oriented but run-length-compresses the overwhelmingly common
empty calls:
  00..7f  : 1..128 consecutive empty restore calls
  80      : full 6144-byte page restore
  81..bf  : active call with 1..63 packed horizontal runs
  c0      : offline-elided full-page call
  c1..ff  : offline-elided call whose 1..63 packed runs are skipped
Each packed run remains a little-endian 16-bit row/x/length word; bit 15 is the
output-driven per-run skip flag.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def mask_runs(mask: bytes) -> list[tuple[int, int, int]]:
    if len(mask) != 96:
        raise ValueError(len(mask))
    runs: list[tuple[int, int, int]] = []
    for row in range(24):
        bits = int.from_bytes(mask[row * 4 : row * 4 + 4], "little")
        x = 0
        while x < 32:
            if not (bits >> x) & 1:
                x += 1
                continue
            start = x
            while x < 32 and (bits >> x) & 1:
                x += 1
            runs.append((row, start, x - start))
    return runs


def pack_run(row: int, x: int, length: int) -> int:
    if not (0 <= row < 24 and 0 <= x < 32 and 1 <= length <= 32):
        raise ValueError((row, x, length))
    return row | (x << 5) | ((length - 1) << 10)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("trace", type=Path)
    ap.add_argument("script", type=Path)
    ap.add_argument("meta", type=Path)
    args = ap.parse_args()

    trace = json.loads(args.trace.read_text())
    decoded = []
    for record in trace["records"]:
        mask = bytes.fromhex(record["mask_hex"])
        decoded.append((record, mask, [] if mask == bytes([0xFF]) * 96 else mask_runs(mask)))

    blob = bytearray()
    records_meta: list[dict] = [None] * len(decoded)  # type: ignore[list-item]
    total_runs = 0
    full_calls = 0
    empty_calls = 0
    empty_tokens = 0
    max_runs = 0
    index = 0
    while index < len(decoded):
        record, mask, runs = decoded[index]
        is_full = mask == bytes([0xFF]) * 96
        if not is_full and not runs:
            token_start = len(blob)
            count = 1
            while index + count < len(decoded) and count < 128:
                _, next_mask, next_runs = decoded[index + count]
                if next_mask == bytes([0xFF]) * 96 or next_runs:
                    break
                count += 1
            blob.append(count - 1)
            empty_tokens += 1
            for j in range(count):
                rec = decoded[index + j][0]
                records_meta[index + j] = {
                    "index": index + j,
                    "script_offset": token_start,
                    "opcode_offset": token_start,
                    "record_bytes": 1 if j == 0 else 0,
                    "run_count": 0,
                    "target_screen": rec["target_screen"],
                    "presentation": rec["presentation"],
                    "vm_tick": rec["vm_tick"],
                    "row_groups": [],
                }
            empty_calls += count
            index += count
            continue

        start = len(blob)
        row_groups: dict[int, list[int]] = {}
        if is_full:
            blob.append(0x80)
            run_count = 0xFFFF
            full_calls += 1
        else:
            run_count = len(runs)
            if not 1 <= run_count <= 63:
                raise ValueError(f"call {index} has {run_count} runs; compact opcode supports 1..63")
            blob.append(0x80 | run_count)
            for row, x, run_len in runs:
                off = len(blob)
                blob += pack_run(row, x, run_len).to_bytes(2, "little")
                row_groups.setdefault(row, []).append(off + 1)
            total_runs += run_count
            max_runs = max(max_runs, run_count)
        records_meta[index] = {
            "index": index,
            "script_offset": start,
            "opcode_offset": start,
            "record_bytes": len(blob) - start,
            "run_count": run_count,
            "target_screen": record["target_screen"],
            "presentation": record["presentation"],
            "vm_tick": record["vm_tick"],
            "row_groups": [
                {"row": row, "high_byte_offsets": offsets}
                for row, offsets in sorted(row_groups.items())
            ],
        }
        index += 1

    args.script.write_bytes(blob)
    meta = {
        "encoding": "empty-rle-opcode-v1",
        "trace_calls": len(decoded),
        "script_bytes": len(blob),
        "total_runs": total_runs,
        "max_runs_per_call": max_runs,
        "full_page_calls": full_calls,
        "empty_calls": empty_calls,
        "empty_tokens": empty_tokens,
        "records": records_meta,
    }
    args.meta.write_text(json.dumps(meta, indent=2) + "\n")
    print(json.dumps({k: v for k, v in meta.items() if k != "records"}, indent=2))


if __name__ == "__main__":
    main()
