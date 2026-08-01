# Another World → ZX Spectrum 128K: full intro VM milestone

This prototype executes the complete DOS-shareware intro control path on an
emulated 128K Spectrum. It retains the original bytecode and compound-shape
resource, renders the full visual sequence, and stops when the VM requests part
16002.

## Implemented

- Complete intro-specific Z80 VM: 2,980 ticks and 56,075 original bytecode
  instructions.
- Original 64-task scheduler, 256 signed variables, calls, branches, task
  state, page commands, text, resource commands, and both variable-length shape
  forms.
- Unmodified 9,842-byte bytecode and 65,156-byte shape resource.
- Recursive compound decoder with shape data paged across banks 0, 3, 4 and 6.
- Runtime point/polygon/text drawing to real Spectrum bank-5/bank-7 screens.
- Cell-granular dirty restoration: 96 bytes of dirty bits per physical screen.
- Five LZSS bitmap checkpoints only for dense one-time page-0 construction.
- Stable logical PAPER/INK roles derived from the original 4-bit page:
  palettes can change attributes without reinterpreting existing bitmap bits.
- Dead dynamic draws removed by a 373-byte tick mask. Geometry remains in the
  original resource; there is no per-frame polygon stream.

## Size policy

The resident design prioritizes size over precomputed speed:

- Z80 VM: 2,074 bytes
- renderer: 3,585 bytes
- original bytecode + shapes: 74,998 bytes
- compact text: 1,846 bytes
- palette/decision tables: 1,040 bytes
- attribute streams: 5,422 bytes
- three bitmap resources: 3,982 bytes
- five static checkpoints: 6,276 bytes

Including the two screens, page-0 background, VM state, decompression buffers
and renderer scratch, estimated resident use is about 126.3 KB. Approximately
4.8 KB remains in aggregate, but it is fragmented across banks.

## Current performance boundary

Control flow is exact, but the general polygon path is not real-time yet. The
full emulator run consumes about 30,900 Spectrum refresh intervals. Capture
records the 298 VM-selected presentations and repeats each for ten output
frames, producing the intended 59.8-second, 5 fps visual timeline.

The next optimization should precompile only the few repeatedly expensive
compound roots into compact spans. Broad dirty-zone lists or rendered-frame
streams are deliberately excluded unless profiling proves they save more than
they cost.

## Build and test

```sh
python3 build_full_vm_port.py
node run_full_vm_test.mjs
```

Capture:

```sh
node capture_full_vm.mjs |
  ffmpeg -f rawvideo -pixel_format rgb24 -video_size 320x240 -framerate 50 \
    -i - -vf scale=960:720:flags=neighbor -c:v libx264 -pix_fmt yuv420p \
    build-full/another-world-vm-full-intro.mp4
```

`build-full/manifest.json` contains the exact resource/layout sizes.
`build-full/test-results.json` contains the complete VM and renderer regression.

## Fixed real-asset 4.5 fps build

`build_proper_ega.py` now supports the pixel-verified production combination:
safe fixed-bank X scaling, arithmetic Y scaling, off-screen dirty clipping and
a display-only 4.5 fps schedule. The unsafe real-asset event filter, deep-child
culling, collapsed-polygon shortcut and fast span fill are disabled explicitly.

The full local verification compares the bank recorded in `LAST_SAMPLE_BANK`
for every retained presentation. The current result is 268/268 byte-exact
screens, with zero mismatched bytes. See `PROPER-EGA-RT45-RESULTS.md` for the
rebuild command, checksums and measured runtime.
