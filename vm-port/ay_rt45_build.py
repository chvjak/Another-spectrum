#!/usr/bin/env python3
"""Add compact AY v5 playback to the measured cost-selected 4.5 fps SNA.

The source music is the 50 Hz AY50 register stream from diff-stream-music/v5.
For the standalone 128K build it is sampled on even 50 Hz ticks (25 AY updates
per second), while the interrupt handler itself still runs every 50 Hz. Tone
period low bytes and all non-period registers are stored inline; the uncommon
period-high changes are carried in a separate fixed-bank bit stream.
"""
from __future__ import annotations

import argparse
import json
import struct
import subprocess
from pathlib import Path

TICKS_50HZ = 8226
AY_UPDATES = (TICKS_50HZ + 1) // 2
HANDLER_ADDR = 0x7800
WAIT_ADDR = 0x7B80
HANDLER_LIMIT = 0x7C00
ATTR0_OFFSET_BANK1 = 0x2E00
ATTR0_RESERVED = 0x1200

AY_INIT = 0x93EA
AY_PHASE = 0x93EB
AY_REMAIN = 0x93EC
AY_PTR = 0x93EE
AY_SEG_END = 0x93F0
AY_SEG_BANK = 0x93F2
AY_SEG_TABLE_PTR = 0x93F3
AY_FLAG_PTR = 0x93F5
AY_FLAG_BYTE = 0x93F7
AY_FLAG_BITS = 0x93F8
AY_SAVED_PAGE = 0x93F9
AY_UPDATE_COUNT = 0x93FA
AY_VM_FINISHED = 0x93FC


def bank_offset(bank: int) -> int:
    if bank == 5:
        return 27
    if bank == 2:
        return 27 + 0x4000
    if bank == 0:
        return 27 + 0x8000
    return 49183 + [1, 3, 4, 6, 7].index(bank) * 0x4000


def parse_ay50(path: Path) -> list[tuple[int, ...]]:
    raw = path.read_bytes()
    if raw[:4] != b"AY50":
        raise RuntimeError(f"{path}: missing AY50 header")
    ticks = struct.unpack_from("<H", raw, 4)[0]
    if ticks < TICKS_50HZ:
        raise RuntimeError(f"AY source has {ticks} ticks, need {TICKS_50HZ}")
    pos = 6
    regs = [0] * 14
    regs[7] = 0x3F
    out: list[tuple[int, ...]] = []
    for _ in range(ticks):
        mask = struct.unpack_from("<H", raw, pos)[0]
        pos += 2
        for reg in range(14):
            if mask & (1 << reg):
                regs[reg] = raw[pos]
                pos += 1
        out.append(tuple(regs))
    if pos != len(raw):
        raise RuntimeError(f"AY source parse ended at {pos}, file has {len(raw)} bytes")
    return out


def pack_music(frames: list[tuple[int, ...]]) -> tuple[list[bytes], bytes, bytes, int]:
    previous = [0] * 14
    previous[7] = 0x3F
    records: list[bytes] = []
    high_flags: list[bool] = []
    for tick in range(0, TICKS_50HZ, 2):
        current = frames[tick]
        mask = 0
        values = bytearray()
        for group, (low, high) in enumerate(((0, 1), (2, 3), (4, 5))):
            if current[low] != previous[low] or current[high] != previous[high]:
                mask |= 1 << group
                values.append(current[low])
                high_changed = current[high] != previous[high]
                high_flags.append(high_changed)
                if high_changed:
                    values.append(current[high])
        for group, reg in enumerate((6, 7, 8, 9, 10), start=3):
            if current[reg] != previous[reg]:
                mask |= 1 << group
                values.append(current[reg])
        records.append(bytes((mask,)) + values)
        previous[:] = current
    if len(records) != AY_UPDATES:
        raise RuntimeError(f"packed {len(records)} updates, expected {AY_UPDATES}")
    flags = bytearray((len(high_flags) + 7) // 8)
    for index, value in enumerate(high_flags):
        if value:
            flags[index >> 3] |= 1 << (index & 7)
    return records, b"".join(records), bytes(flags), len(high_flags)


def align(value: int, boundary: int) -> int:
    return (value + boundary - 1) & -boundary


def choose_segments(manifest: dict, flag_bytes: int) -> tuple[int, list[tuple[int, int, int]]]:
    sizes = manifest["sizes"]
    layout = manifest["layout"]
    bank7_end = 0x1B00
    for item in layout.values():
        if isinstance(item, dict) and item.get("bank") == 7:
            bank7_end = max(bank7_end, int(item["offset"]) + int(item["bytes"]))
    bytecode_end = int(sizes["bytecode"])
    text_size = int(sizes["text"])
    if text_size != 0:
        raise RuntimeError(f"expected no resident intro text, got {text_size} bytes")
    middle_size = int(sizes["attribute_streams"][1])
    attr0_size = min(middle_size, ATTR0_RESERVED)
    asset = layout["bitmap19"]
    asset_end_address = 0x4000 + int(asset["offset"]) + int(asset["bytes"])
    flag_address = asset_end_address
    fixed_main_start = align(flag_address + flag_bytes, 16)
    if fixed_main_start >= HANDLER_ADDR:
        raise RuntimeError("AY flags leave no fixed-bank main-stream space")
    segments = [
        (7, 0xC000 + bank7_end, 0x10000),
        (1, 0xC000 + bytecode_end, 0xC000 + ATTR0_OFFSET_BANK1),
        (1, 0xC000 + ATTR0_OFFSET_BANK1 + attr0_size, 0x10000),
        (0xFF, fixed_main_start, HANDLER_ADDR),
        (0xFF, HANDLER_LIMIT, 0x8000),
    ]
    for bank, start, end in segments:
        if not 0 <= start < end <= 0x10000:
            raise RuntimeError(f"bad segment bank={bank} {start:#x}-{end:#x}")
    return flag_address, segments


def split_records(records: list[bytes], segments: list[tuple[int, int, int]]) -> list[dict]:
    result: list[dict] = []
    record_index = 0
    for bank, start, capacity_end in segments:
        payload = bytearray()
        first_record = record_index
        while record_index < len(records):
            record = records[record_index]
            if len(payload) + len(record) > capacity_end - start:
                break
            payload += record
            record_index += 1
        if payload:
            result.append({"bank": bank, "start": start, "end": start + len(payload),
                           "payload": bytes(payload), "records": record_index - first_record})
        if record_index == len(records):
            break
    if record_index != len(records):
        remaining = sum(len(item) for item in records[record_index:])
        raise RuntimeError(f"music main stream does not fit: {len(records)-record_index} records / {remaining} bytes remain")
    return result


def asm_source(entries: list[dict], flag_address: int) -> str:
    table = []
    for item in entries:
        table.append(f"        db {int(item['bank'])}")
        table.append(f"        dw 0x{int(item['start']) & 0xFFFF:04X},0x{int(item['end']) & 0xFFFF:04X}")
    return f"""; Generated by ay_rt45_build.py
        DEVICE ZXSPECTRUM48
        ORG 0x{HANDLER_ADDR:04X}

IRQ_COUNT          EQU 0x9325
DISPLAY_BIT        EQU 0x930B
CURRENT_BANK       EQU 0x7280
AY_INIT            EQU 0x{AY_INIT:04X}
AY_PHASE           EQU 0x{AY_PHASE:04X}
AY_REMAIN          EQU 0x{AY_REMAIN:04X}
AY_PTR             EQU 0x{AY_PTR:04X}
AY_SEG_END         EQU 0x{AY_SEG_END:04X}
AY_SEG_BANK        EQU 0x{AY_SEG_BANK:04X}
AY_SEG_TABLE_PTR   EQU 0x{AY_SEG_TABLE_PTR:04X}
AY_FLAG_PTR        EQU 0x{AY_FLAG_PTR:04X}
AY_FLAG_BYTE       EQU 0x{AY_FLAG_BYTE:04X}
AY_FLAG_BITS       EQU 0x{AY_FLAG_BITS:04X}
AY_SAVED_PAGE      EQU 0x{AY_SAVED_PAGE:04X}
AY_UPDATE_COUNT    EQU 0x{AY_UPDATE_COUNT:04X}
AY_VM_FINISHED     EQU 0x{AY_VM_FINISHED:04X}
AY_FLAG_DATA       EQU 0x{flag_address:04X}
AY_UPDATE_TOTAL    EQU {AY_UPDATES}
DONE               EQU 0x9307

ay_irq:
        push af
        push bc
        push de
        push hl
        push ix
        ld hl,IRQ_COUNT
        inc (hl)
        ld a,(AY_INIT)
        or a
        jr nz,.phase
        inc a
        ld (AY_INIT),a
        ld hl,AY_UPDATE_TOTAL
        ld (AY_REMAIN),hl
        ld hl,AY_FLAG_DATA
        ld (AY_FLAG_PTR),hl
        xor a
        ld (AY_FLAG_BITS),a
        ld hl,ay_segments
        ld (AY_SEG_TABLE_PTR),hl
        call ay_load_segment
        ld a,1
        ld (AY_PHASE),a
.phase:
        ld a,(AY_PHASE)
        xor 1
        ld (AY_PHASE),a
        jr nz,.exit
        ld hl,(AY_REMAIN)
        ld a,h
        or l
        jr z,.silence_once
        dec hl
        ld (AY_REMAIN),hl
        call ay_update
        ld hl,(AY_UPDATE_COUNT)
        inc hl
        ld (AY_UPDATE_COUNT),hl
        jr .exit
.silence_once:
        ld a,(AY_INIT)
        cp 2
        jr z,.exit
        ld a,2
        ld (AY_INIT),a
        call ay_silence
.exit:
        pop ix
        pop hl
        pop de
        pop bc
        pop af
        ei
        reti

ay_update:
        ld a,(CURRENT_BANK)
        ld e,a
        ld a,(DISPLAY_BIT)
        or e
        ld (AY_SAVED_PAGE),a
        ld a,(AY_SEG_BANK)
        cp 0xFF
        jr z,.mapped
        ld e,a
        ld a,(DISPLAY_BIT)
        or e
        ld bc,0x7FFD
        out (c),a
.mapped:
        ld ix,(AY_PTR)
        ld d,(ix+0)
        inc ix
        bit 0,d
        jr z,.tone_b
        ld e,(ix+0)
        inc ix
        xor a
        call ay_write
        call ay_high_flag
        jr nc,.tone_b
        ld e,(ix+0)
        inc ix
        ld a,1
        call ay_write
.tone_b:
        bit 1,d
        jr z,.tone_c
        ld e,(ix+0)
        inc ix
        ld a,2
        call ay_write
        call ay_high_flag
        jr nc,.tone_c
        ld e,(ix+0)
        inc ix
        ld a,3
        call ay_write
.tone_c:
        bit 2,d
        jr z,.noise
        ld e,(ix+0)
        inc ix
        ld a,4
        call ay_write
        call ay_high_flag
        jr nc,.noise
        ld e,(ix+0)
        inc ix
        ld a,5
        call ay_write
.noise:
        bit 3,d
        jr z,.mixer
        ld e,(ix+0)
        inc ix
        ld a,6
        call ay_write
.mixer:
        bit 4,d
        jr z,.vol_a
        ld e,(ix+0)
        inc ix
        ld a,7
        call ay_write
.vol_a:
        bit 5,d
        jr z,.vol_b
        ld e,(ix+0)
        inc ix
        ld a,8
        call ay_write
.vol_b:
        bit 6,d
        jr z,.vol_c
        ld e,(ix+0)
        inc ix
        ld a,9
        call ay_write
.vol_c:
        bit 7,d
        jr z,.record_done
        ld e,(ix+0)
        inc ix
        ld a,10
        call ay_write
.record_done:
        ld (AY_PTR),ix
        ld hl,(AY_REMAIN)
        ld a,h
        or l
        jr z,.restore
        push ix
        pop hl
        ld de,(AY_SEG_END)
        or a
        sbc hl,de
        call z,ay_load_segment
.restore:
        ld a,(AY_SAVED_PAGE)
        ld bc,0x7FFD
        out (c),a
        ret

ay_high_flag:
        ld a,(AY_FLAG_BITS)
        or a
        jr nz,.have
        ld hl,(AY_FLAG_PTR)
        ld a,(hl)
        inc hl
        ld (AY_FLAG_PTR),hl
        ld (AY_FLAG_BYTE),a
        ld a,8
        ld (AY_FLAG_BITS),a
.have:
        ld a,(AY_FLAG_BYTE)
        rrca
        ld (AY_FLAG_BYTE),a
        ld a,(AY_FLAG_BITS)
        dec a
        ld (AY_FLAG_BITS),a
        ret

ay_write:
        ld bc,0xFFFD
        out (c),a
        ld b,0xBF
        out (c),e
        ret

ay_silence:
        ld e,0x3F
        ld a,7
        call ay_write
        xor a
        ld e,a
        ld a,8
        call ay_write
        ld a,9
        call ay_write
        ld a,10
        jp ay_write

ay_load_segment:
        ld hl,(AY_SEG_TABLE_PTR)
        ld a,(hl)
        inc hl
        ld (AY_SEG_BANK),a
        ld e,(hl)
        inc hl
        ld d,(hl)
        inc hl
        ld (AY_PTR),de
        ld e,(hl)
        inc hl
        ld d,(hl)
        inc hl
        ld (AY_SEG_END),de
        ld (AY_SEG_TABLE_PTR),hl
        ret

ay_segments:
{chr(10).join(table)}

handler_end:
        ASSERT handler_end <= 0x{WAIT_ADDR:04X}

        ORG 0x{WAIT_ADDR:04X}
ay_wait_finish:
        ld a,1
        ld (AY_VM_FINISHED),a
        ei
.wait:
        halt
        ld hl,(AY_UPDATE_COUNT)
        ld de,AY_UPDATE_TOTAL
        or a
        sbc hl,de
        jr c,.wait
        ld a,1
        ld (DONE),a
.hold:
        ei
        halt
        jr .hold

wait_end:
        ASSERT wait_end <= 0x{HANDLER_LIMIT:04X}
        END
"""


def inject(snapshot: bytearray, bank: int, address: int, payload: bytes, label: str) -> None:
    offset = address - (0x4000 if bank == 5 else 0xC000)
    if not 0 <= offset <= 0x4000 - len(payload):
        raise RuntimeError(f"{label} outside bank {bank}")
    pos = bank_offset(bank) + offset
    old = snapshot[pos:pos + len(payload)]
    if any(old):
        raise RuntimeError(f"{label} target is not empty: bank {bank}, address {address:#x}, bytes {len(payload)}")
    snapshot[pos:pos + len(payload)] = payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-sna", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--ay50", type=Path, required=True)
    parser.add_argument("--sjasmplus", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    frames = parse_ay50(args.ay50)
    records, main_stream, flag_stream, high_flag_count = pack_music(frames)
    manifest = json.loads(args.manifest.read_text())
    flag_address, candidate_segments = choose_segments(manifest, len(flag_stream))
    entries = split_records(records, candidate_segments)

    asm_path = args.out / "ay-irq.asm"
    bin_path = args.out / "ay-irq.bin"
    asm_path.write_text(asm_source(entries, flag_address))
    subprocess.run([str(args.sjasmplus), f"--raw={bin_path}", asm_path.name], cwd=asm_path.parent, check=True)
    handler = bin_path.read_bytes()
    if len(handler) > HANDLER_LIMIT - HANDLER_ADDR:
        raise RuntimeError(f"handler image is {len(handler)} bytes; limit is {HANDLER_LIMIT-HANDLER_ADDR}")

    snapshot = bytearray(args.base_sna.read_bytes())
    if len(snapshot) != 131103:
        raise RuntimeError(f"unexpected SNA size {len(snapshot)}")
    inject(snapshot, 5, flag_address, flag_stream, "AY high-period flags")
    payload_concat = bytearray()
    for entry in entries:
        actual_bank = 5 if int(entry["bank"]) == 0xFF else int(entry["bank"])
        inject(snapshot, actual_bank, int(entry["start"]), entry["payload"], "AY main stream")
        payload_concat += entry["payload"]
    if bytes(payload_concat) != main_stream:
        raise RuntimeError("segmented AY stream differs from packed stream")
    inject(snapshot, 5, HANDLER_ADDR, handler, "AY interrupt handler")

    stub_pos = bank_offset(5) + (0x5D10 - 0x4000)
    snapshot[stub_pos:stub_pos + 3] = bytes((0xC3, HANDLER_ADDR & 0xFF, HANDLER_ADDR >> 8))

    finished_pattern = bytes((0x3E, 0x01, 0x32, 0x07, 0x93, 0xFB, 0x76, 0x18, 0xFC))
    bank2_pos = bank_offset(2)
    bank2 = bytes(snapshot[bank2_pos:bank2_pos + 0x4000])
    matches = [i for i in range(0x4000 - len(finished_pattern) + 1) if bank2.startswith(finished_pattern, i)]
    if len(matches) != 1:
        raise RuntimeError(f"expected one finished routine, found {len(matches)}")
    finish_offset = matches[0]
    snapshot[bank2_pos + finish_offset:bank2_pos + finish_offset + 3] = bytes((0xC3, WAIT_ADDR & 0xFF, WAIT_ADDR >> 8))

    state_start = bank_offset(2) + (AY_INIT - 0x8000)
    state_bytes = AY_VM_FINISHED + 1 - AY_INIT
    snapshot[state_start:state_start + state_bytes] = b"\x00" * state_bytes

    out_sna = args.out / "cost-4p5-ay.sna"
    out_sna.write_bytes(snapshot)
    (args.out / "ay-main-stream.bin").write_bytes(main_stream)
    (args.out / "ay-high-flags.bin").write_bytes(flag_stream)

    result = {
        "source_ticks_50hz": TICKS_50HZ,
        "playback_updates": AY_UPDATES,
        "playback_update_rate_hz": 25,
        "source_ay50_bytes": args.ay50.stat().st_size,
        "main_stream_bytes": len(main_stream),
        "high_flag_decisions": high_flag_count,
        "high_flag_capacity_bits": len(flag_stream) * 8,
        "high_flag_bytes": len(flag_stream),
        "resident_music_bytes": len(main_stream) + len(flag_stream) + len(handler) + 3,
        "handler_bytes": len(handler),
        "flag_address": flag_address,
        "handler_address": HANDLER_ADDR,
        "wait_address": WAIT_ADDR,
        "finished_patch_address": 0x8000 + finish_offset,
        "vm_finished_flag_address": AY_VM_FINISHED,
        "segments": [{k: v for k, v in entry.items() if k != "payload"} | {"bytes": len(entry["payload"])} for entry in entries],
        "snapshot_bytes": len(snapshot),
    }
    (args.out / "ay-build-manifest.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
