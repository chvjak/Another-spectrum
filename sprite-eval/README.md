# Sprite and background feasibility build

This experiment turns ten frames from the playable Water level of the
`Another World` shareware demo into legal ZX Spectrum ULA screens.  It animates
Lester and Buddy through bidirectional runs, stops, and turns over three of
those scenes.  The runnable target is a stock 128K Spectrum at 3.5469 MHz; it
does not rely on Next-only hardware.

## Outputs

- `artifacts/another-world-speccy-backgrounds-contact-sheet.png`: ten 256x192
  screens after per-attribute-cell ULA quantisation.
- `artifacts/lester-sprite-contact-sheet.png`: Lester's complete ten-frame
  right and left gaits plus six stop/turn poses and their Spectrum masks.
- `artifacts/buddy-sprite-contact-sheet.png`: twenty actual Jail run
  composites, each assembled from its head, body, and arm layers, plus three
  state poses and their Spectrum masks.
- `generated_assets.py`: reproducible, compressed screen data and pre-shifted
  masks used by the assembler build.
- `artifacts/verification.json` and `artifacts/capture.json`: emulator-observed
  presentation timing, scene coverage, deadline counters, and capture totals.
- `build/sprite-eval-runtime/another-world-gameplay-gaits-25fps.sna`: 128K
  snapshot generated locally.
- `artifacts/another-world-gameplay-gaits-25fps.mp4`: 18-second local capture
  sourced directly from JSSpeccy's frame buffer.

The data and emulator binaries stay uncommitted.  The source scripts,
generated source, manifests, and contact sheets are committed.

## Performance design

- Bank 5 and bank 7 are true display/render buffers; flips happen on the
  Spectrum interrupt.
- The three runtime ULA backgrounds are packed into banks 3 and 4.
- Lester's 26 poses and Buddy's 23 composite poses are spread across banks 0,
  1, 3, 4, and 6, with four pre-shifts for the two-pixel horizontal motion
  grid.
- Each frame restores one combined saved-under rectangle, copies the selected
  actor frames into fixed RAM, then XOR-composites them.  Sprite rendering does
  not rewrite attributes, so the source screen's PAPER/INK choice is preserved.
- Logical presentation is 25 fps on the 50 Hz display.  Scene changes are
  copied into the hidden buffer and flipped only after vblank.
- A fixed status block at `0x9f00` exposes frame count, scene, deadline misses,
  render interrupt span, and transition count to the local verifier.

## Rebuild locally

Prerequisites are Node.js, Python 3 with Pillow and NumPy, FFmpeg, a local
`sjasmplus` binary, the public DOS-shareware `another_js` data/engine files,
`DEMO3.JOY`, the official 15th Anniversary demo's `Data/Pak01.pak`, and the
JSSpeccy core WebAssembly module.  The Anniversary pack is used only to extract
the unencrypted Jail resources required to reconstruct Buddy's actual layered
gameplay composites; the generated pack input remains uncommitted.

```sh
python3 sprite-eval/extract_anniversary_jail.py \
  /path/to/AnotherWorld-Demo/Data/Pak01.pak \
  build/anniversary-demo-jail.js

python3 sprite-eval/build_assets.py --demo-joy /path/to/DEMO3.JOY
python3 sprite-eval/build_sna.py

node sprite-eval/verify_sprite_eval.mjs \
  /path/to/jsspeccy-core.wasm \
  build/sprite-eval-runtime/another-world-gameplay-gaits-25fps.sna \
  sprite-eval/artifacts/verification.json \
  1800

node sprite-eval/capture_sprite_eval.mjs \
  /path/to/jsspeccy-core.wasm \
  build/sprite-eval-runtime/another-world-gameplay-gaits-25fps.sna \
  900 2>sprite-eval/artifacts/capture.json | \
ffmpeg -y -f rawvideo -pixel_format rgb24 -video_size 320x240 \
  -framerate 25 -i - -vf scale=960:720:flags=neighbor \
  -c:v libx264 -crf 18 -pix_fmt yuv420p \
  sprite-eval/artifacts/another-world-gameplay-gaits-25fps.mp4
```

The 36-second verification run must see all three scenes, report no 40 ms
deadline miss, and observe no more than one 20 ms interrupt boundary during the
heaviest render.  The normal presentation interval is two refreshes; the only
long intervals are deliberate, tear-free background transitions.
