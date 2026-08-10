# Another World ZX Spectrum diff stream + 50 Hz AY playback

This branch combines the alternating bank-5/bank-7 diff-stream player with the
170-second AY v6 score.

## Timing

The intended corrected input contains **4,114 visual frames at 25 fps**. Set:

```sh
SPECCY_WAIT_FRAMES=2
```

Each visual frame is then presented for two Spectrum 50 Hz refreshes. The player
calls the AY decoder after every `HALT`, so music advances at exactly 50 Hz:

- visual ticks: `4,114 × 2 = 8,228`;
- music ticks: `8,500`;
- final music tail: `272 ticks = 5.44 s`;
- total score: `170.00 s`.

The original recovered capture source still documents the old 59.64-second
timing bug. This integration does not recreate the missing corrected rawgl
capture; it consumes corrected frames when they are supplied in `SPECCY_CAPTURE`.

## Reel layout

- bank 2 at `$8000`: visual span stream;
- fixed bank 5 at `$5B00`: player and AY delta decoder;
- `$5CFF/$5D00`: IM2 vector;
- `$5D10`: `EI / RETI` interrupt handler;
- `$5D20..$7FFF`: per-reel AY register deltas;
- banks 5 and 7: alternating display screens.

Every reel's first music tick carries a full `0x3FFF` register mask. Therefore a
reel starts with the correct AY state even when the emulator resets between
snapshots.

## Build

Place timestamp-corrected source PPM frames in the capture directory, then run:

```sh
SPECCY_CAPTURE=corrected-captured \
SPECCY_OUTPUT=full-speccy-music \
SPECCY_WAIT_FRAMES=2 \
SPECCY_AY_STREAM=../music/v6/aw_intro_ay_v6_2m50s.bin.zlib.b64 \
python3 build_full_speccy.py
```

The generated `reels.csv` records both video and AY ranges and sizes for every
snapshot.

## Regression test

```sh
python3 test_ay_integration.py
```

The test verifies AY50 parsing, per-reel delta round-tripping, no channel-A noise
gate in v6, player/vector placement, 128K SNA size, and exact 8,500-tick timing
for a 4,114-frame corrected timeline. It is a construction-level test, not a
substitute for running the snapshots in JSSpeccy.
