# Another World ZX Spectrum 25 fps diff-stream prototype

This build uses the original pre-rendered diff-stream approach:

1. rawgl executes the DOS shareware intro VM and renders every second 50 Hz tick.
2. Each 320x200 RGB frame is resized and quantized to a legal 256x192 Spectrum
   bitmap plus one attribute byte per 8x8 cell.
3. Frames are encoded as changed byte spans relative to the previous contents
   of the same physical screen. Bank 5 therefore references frame N-2 when
   preparing frame N, and bank 7 does the same independently.
4. A small Z80 player applies the spans, flips the displayed screen through
   port $7FFD, and holds each presentation for two 50 Hz interrupts.
5. Every RAM-sized reel is executed through the JSSpeccy Z80/Spectrum core.
   Emulator output is concatenated and encoded as a 25 fps MP4.

## Measured result

- Source VM presentations: 1,491
- Presentation rate: 25 fps
- Duration: 59.64 seconds
- Delta payload: 996,821 bytes
- Snapshot reels: 70
- Screen format: 6,144 bitmap bytes + 768 attribute bytes
- MP4: H.264 960x720, nearest-neighbour scale, AAC AY-style soundtrack

This is pre-rendered video playback, not the runtime VM/polygon-renderer port.
Equivalent physical hardware playback needs a storage stream or reel loader;
the complete delta payload does not fit in 128K RAM at once.

## Relevant files

- `capture_frames.cpp`: rawgl tick-rate capture; output directory and stride are
  command-line parameters.
- `build_full_speccy.py`: Spectrum quantizer, per-screen delta encoder, Z80
  player assembler and 128K SNA reel builder.
- `run_full_speccy_capture.mjs`: deterministic Spectrum-core runner.
- `full-speccy-25fps/reels.csv`: exact frame and byte counts per reel.
- `full-speccy-25fps/reel-*.sna`: loadable 128K reels.
