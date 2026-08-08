# Sprite and background feasibility build

This experiment turns ten authentic `Another World` shareware frames into
legal ZX Spectrum ULA screens and animates Lester plus a shared-vector Buddy
sequence over three of them.  The runnable target is a stock 128K Spectrum at
3.5469 MHz; it does not rely on Next-only hardware.

## Outputs

- `artifacts/another-world-speccy-backgrounds-contact-sheet.png`: ten 256x192
  screens after per-attribute-cell ULA quantisation.
- `artifacts/lester-sprite-contact-sheet.png`: eight original Lester vector
  frames and their Spectrum masks.
- `artifacts/buddy-sprite-contact-sheet.png`: eight frames from the shared
  common polygon bank and their Spectrum masks.
- `generated_assets.py`: reproducible, compressed screen data and pre-shifted
  masks used by the assembler build.
- `artifacts/verification.json` and `artifacts/capture.json`: emulator-observed
  presentation timing, scene coverage, deadline counters, and capture totals.
- `build/sprite-eval-runtime/another-world-sprite-background-eval-25fps.sna`:
  128K snapshot generated locally.
- `build/sprite-eval-runtime/another-world-sprite-background-eval-25fps.mp4`:
  18-second capture sourced directly from JSSpeccy's frame buffer.

The data and emulator binaries stay uncommitted.  The source scripts,
generated source, manifests, and contact sheets are committed.

## Performance design

- Bank 5 and bank 7 are true display/render buffers; flips happen on the
  Spectrum interrupt.
- Three ULA background screens live in banks 3, 4, and 6.
- Lester and Buddy masks live in banks 0 and 1, with four pre-shifts for the
  two-pixel horizontal motion grid.
- Each frame restores one combined saved-under rectangle, copies the selected
  actor frames into fixed RAM, then XOR-composites them.  Sprite rendering does
  not rewrite attributes, so the source screen's PAPER/INK choice is preserved.
- Logical presentation is 25 fps on the 50 Hz display.  Scene changes are
  copied into the hidden buffer and flipped only after vblank.
- A fixed status block at `0x9f00` exposes frame count, scene, deadline misses,
  render interrupt span, and transition count to the local verifier.

## Rebuild locally

Prerequisites are Node.js, Python 3 with Pillow and NumPy, FFmpeg, a local
`sjasmplus` binary, the public DOS-shareware `another_js` data/engine files, and
the JSSpeccy core WebAssembly module.  The examples below assume the same local
paths used by the other repository experiments.

```sh
python3 sprite-eval/build_assets.py
python3 sprite-eval/build_sna.py

node sprite-eval/verify_sprite_eval.mjs \
  /path/to/jsspeccy-core.wasm \
  build/sprite-eval-runtime/another-world-sprite-background-eval-25fps.sna \
  build/sprite-eval-runtime/verification.json \
  1800

node sprite-eval/capture_sprite_eval.mjs \
  /path/to/jsspeccy-core.wasm \
  build/sprite-eval-runtime/another-world-sprite-background-eval-25fps.sna \
  900 2>build/sprite-eval-runtime/capture.json | \
ffmpeg -y -f rawvideo -pixel_format rgb24 -video_size 320x240 \
  -framerate 25 -i - -vf scale=960:720:flags=neighbor \
  -c:v libx264 -crf 18 -pix_fmt yuv420p \
  build/sprite-eval-runtime/another-world-sprite-background-eval-25fps.mp4
```

The 36-second verification run must see all three scenes, report no 40 ms
deadline miss, and observe no more than one 20 ms interrupt boundary during the
heaviest render.  The normal presentation interval is two refreshes; the only
long intervals are deliberate, tear-free background transitions.
