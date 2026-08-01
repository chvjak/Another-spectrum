from __future__ import annotations

import base64, json, math, struct, zlib
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parent
V6 = ROOT.parent / 'v6' / 'aw_intro_ay_v6_2m50s.bin.zlib.b64'
OUT = ROOT / 'aw_intro_ay_v7_sfx_2m50s.bin.zlib.b64'
FPS = 50
AY_CLOCK = 1_773_400.0


def sec(value: float) -> int:
    return round(value * FPS)


def period_hz(hz: float) -> int:
    return max(1, min(4095, round(AY_CLOCK / (16.0 * max(1.0, hz)))))


def period_midi(note: float) -> int:
    return period_hz(440.0 * 2.0 ** ((note - 69.0) / 12.0))


def decode(path: Path) -> np.ndarray:
    blob = zlib.decompress(base64.b64decode(path.read_text().strip()))
    assert blob[:4] == b'AY50'
    count = struct.unpack_from('<H', blob, 4)[0]
    frames = np.zeros((count, 14), dtype=np.uint8)
    state = np.zeros(14, dtype=np.uint8); state[7] = 0x3F
    pos = 6
    for tick in range(count):
        mask = struct.unpack_from('<H', blob, pos)[0]; pos += 2
        for reg in range(14):
            if mask & (1 << reg): state[reg] = blob[pos]; pos += 1
        frames[tick] = state
    assert pos == len(blob)
    return frames


def encode(frames: np.ndarray) -> bytes:
    out = bytearray(b'AY50') + struct.pack('<H', len(frames))
    previous = np.zeros(14, dtype=np.uint8); previous[7] = 0x3F
    for frame in frames:
        mask = 0; values = []
        for reg, value in enumerate(frame):
            if int(value) != int(previous[reg]):
                mask |= 1 << reg; values.append(int(value))
        out += struct.pack('<H', mask) + bytes(values)
        previous = frame.copy()
    return bytes(out)


def voice(row: np.ndarray, channel: int, tone_period: int, volume: int, tone: bool, noise: bool) -> None:
    row[channel * 2] = tone_period & 255
    row[channel * 2 + 1] = tone_period >> 8
    row[8 + channel] = max(0, min(15, volume))
    mixer = int(row[7])
    mixer = mixer & ~(1 << channel) if tone else mixer | (1 << channel)
    mixer = mixer & ~(1 << (channel + 3)) if noise else mixer | (1 << (channel + 3))
    row[7] = mixer & 255


def keypad(row: np.ndarray, age: int, note: int) -> None:
    env = [5, 10, 13, 12, 9, 6, 3, 0]
    bend = 1.6 if age == 0 else 0.7 if age == 1 else 0.0
    if age == 0: row[6] = 3
    voice(row, 1, period_midi(note + bend), env[age], True, age == 0)


def step(row: np.ndarray, age: int, index: int) -> None:
    env = [5, 9, 11, 9, 7, 5, 3, 2, 1, 0]
    note = 42.0 + (1.5 if index & 1 else 0.0) - 8.0 * age / 9.0
    row[6] = min(31, 15 + age * 2)
    voice(row, 2, period_midi(note), env[age], age < 6, age < 8)


def squeal(row: np.ndarray, age: int, duration: int) -> None:
    x = age / (duration - 1)
    edge = min(1.0, age / 7.0, (duration - 1 - age) / 12.0)
    hz = (1800.0 * (1.0 - x) + 480.0 * x) * (1.0 + .025 * math.sin(age * .71) + .012 * math.sin(age * 1.93))
    voice(row, 1, period_hz(hz), round(12 * math.sqrt(max(0.0, edge))), True, True)
    row[6] = max(2, min(18, round(3 + 13 * x + 2 * math.sin(age * .37))))
    harmonic = hz * (.48 + .04 * math.sin(age * .29))
    voice(row, 2, period_hz(harmonic), round(8 * edge * (.88 + .12 * math.sin(age * .53))), True, True)


def lightning(row: np.ndarray, age: int, duration: int) -> None:
    if age < 9:
        level = [15, 15, 14, 13, 12, 11, 9, 7, 5][age]
        row[6] = 1 + age // 2
        voice(row, 0, period_hz(620 - 42 * age), level, True, True)
        voice(row, 1, period_hz(2200 - 150 * age), max(0, level - 1), True, True)
        voice(row, 2, period_hz(1150 - 70 * age), level, True, True)
        return
    tail_age = age - 9
    y = tail_age / (duration - 10)
    tail = (1.0 - y) ** 1.35
    row[6] = max(4, min(31, round(5 + 25 * y)))
    voice(row, 0, period_hz(92 * (1 - y) + 43 * y), round(12 * tail), True, True)
    if tail_age in {7, 19, 36}:
        voice(row, 1, period_hz(980 - 8 * tail_age), round(8 * tail), True, True)
    else:
        voice(row, 1, period_hz(330), 0, False, False)
    voice(row, 2, period_hz(170 - 70 * y), round(9 * tail), False, True)


def main() -> None:
    frames = decode(V6)
    keypad_events = [(sec(t), note) for t, note in [(35.20,84),(35.44,88),(35.68,91),(35.96,86),(36.20,89),(36.48,93)]]
    step_start, step_spacing = sec(42.30), sec(.56)
    squeal_start, squeal_duration = sec(25.20), sec(1.65)
    lightning_start, lightning_duration = sec(118.0), sec(2.45)

    for tick, row in enumerate(frames):
        for start, note in keypad_events:
            age = tick - start
            if 0 <= age < 8: keypad(row, age, note)
        for index in range(10):
            age = tick - (step_start + index * step_spacing)
            if 0 <= age < 10: step(row, age, index)
        age = tick - squeal_start
        if 0 <= age < squeal_duration: squeal(row, age, squeal_duration)
        age = tick - lightning_start
        if 0 <= age < lightning_duration: lightning(row, age, lightning_duration)

    stream = encode(frames)
    OUT.write_text(base64.b64encode(zlib.compress(stream, 9)).decode() + '\n')
    print(json.dumps({'ticks': len(frames), 'ay50_bytes': len(stream), 'compressed_bytes': len(zlib.compress(stream, 9))}, indent=2))


if __name__ == '__main__': main()
