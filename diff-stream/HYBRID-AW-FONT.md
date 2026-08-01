# 25 fps hybrid diff stream with 6x6 Another World text

This build keeps every picture frame in the corrected 25 fps AWD2 stream and
rebuilds recognized text from RawGL's original Another World font.  The original
8x8 glyphs are area-resized to 6x6 before the affected Spectrum bitmap cells are
delta-encoded again.  Picture cells outside the scheduled text regions stay
byte-for-byte unchanged.

This is a build-time hybrid: the emulator still runs the compact alternating
bank-5/bank-7 AWD2 decoder, while the authored stream contains the rebuilt text.
It does not add a live vector renderer to the Z80 player.

## Inputs

- a corrected 25 fps AWD2 capture;
- RawGL's `staticres.cpp`, used as the font and English/demo string source;
- Pillow for deterministic `BOX` area resizing.

The repository does not contain the game data, generated stream, snapshots,
tape image, emulator, or Spectrum ROMs.

## Build

```sh
python3 diff-stream/build_hybrid_aw_font.py \
  --input /path/to/intro25.awd \
  --rawgl-staticres /path/to/rawgl/staticres.cpp \
  --rawgl-revision 049e4ade49543a12414f68a7838a94ec0a6c149d \
  --output /tmp/intro25-hybrid-aw6.awd \
  --stats /tmp/intro25-hybrid-aw6.json
```

`hybrid_aw_font_schedule.json` records the inclusive source-frame ranges,
RawGL string IDs, original text coordinates, and Spectrum colours.  The build
manifest records hashes for the input stream, RawGL source, extracted font,
schedule, and output stream.  The default four-byte delta merge gap packages the
result in 27 external-media blocks.  It reduces decoder control-loop overhead
enough for the published player to decode into the hidden bank before every
deadline, then flip with an exact two-refresh cadence: all 4,113 presentations
take 40 ms and completion remains exactly 8,226 refreshes (164.52 seconds).
