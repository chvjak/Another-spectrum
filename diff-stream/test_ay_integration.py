#!/usr/bin/env python3
"""Regression tests for diff-stream/AY reel construction.

These tests validate stream round-tripping, exact 50 Hz timing, SNA layout and
presence of AY port writes. They do not replace execution in a Z80 emulator.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile

ROOT = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("build_full_speccy", ROOT / "build_full_speccy.py")
assert SPEC and SPEC.loader
build = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(build)


def main() -> None:
    ay_path = ROOT.parent / "music" / "v6" / "aw_intro_ay_v6_2m50s.bin.zlib.b64"
    ay_frames = build.load_ay50(ay_path)
    assert len(ay_frames) == 8500

    # Every reel is independently restartable: its first AY tick is a full state.
    for start, end in ((0, 10), (1234, 1500), (8200, 8500)):
        encoded = build.encode_ay_segment(ay_frames[start:end])
        assert encoded[:2] == b"\xff\x3f"
        assert build.decode_ay_segment(encoded, end - start) == ay_frames[start:end]

    # Channel A is tone-only in v6; noisy onsets and snares remain on B/C.
    assert all(frame[7] & 0x08 for frame in ay_frames)
    assert any((frame[7] & 0x10) == 0 for frame in ay_frames)
    assert any((frame[7] & 0x20) == 0 for frame in ay_frames)

    code = build.player_code(frame_count=10, tail_ticks=272)
    assert build.PLAYER_ORIGIN + len(code) <= build.IM2_VECTOR_LOW_ADDRESS
    assert bytes.fromhex("01fdff") in code  # ld bc,$fffd
    assert bytes.fromhex("ed79") in code    # out (c),a

    # The corrected 4,114-frame timeline at 25 fps uses 8,228 AY ticks and
    # leaves a 272-tick tail, exactly filling the 8,500-tick / 170 s track.
    frames = [(index, bytes(6912)) for index in range(4114)]
    with tempfile.TemporaryDirectory() as directory:
        output = Path(directory)
        reels = build.build_reels(frames, ay_frames, output)
        assert sum(int(reel["frames"]) for reel in reels) == 4114
        assert sum(int(reel["ay_ticks"]) for reel in reels) == 8500
        assert int(reels[-1]["tail_ticks"]) == 272
        assert all(int(reel["video_bytes"]) <= build.VIDEO_STREAM_LIMIT for reel in reels)
        assert all(int(reel["ay_bytes"]) <= build.AY_DATA_LIMIT for reel in reels)

        snapshot = (output / str(reels[0]["reel"])).read_bytes()
        assert len(snapshot) == 131103
        page5 = snapshot[27 : 27 + 0x4000]
        vector = build.IM2_VECTOR_LOW_ADDRESS - 0x4000
        handler = build.IM2_HANDLER_ADDRESS - 0x4000
        assert page5[vector : vector + 2] == bytes((0x10, 0x5D))
        assert page5[handler : handler + 3] == bytes((0xFB, 0xED, 0x4D))

    print(
        "passed: 8500 AY ticks, AY delta round-trip, no channel-A noise gate, "
        f"player={len(code)} bytes, corrected timeline tail=272 ticks"
    )


if __name__ == "__main__":
    main()
