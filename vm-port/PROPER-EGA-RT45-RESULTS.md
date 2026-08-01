# Pixel-verified live renderer with 4.5 fps display schedule

This build fixes the visual corruption in the previous real-asset snapshot.
It remains a live VM/vector renderer; it is not a prerecorded diff stream.

## Correctness fixes

- Moved the X-coordinate lookup out of the bitmap-decompression destination.
- Replaced the overlapping Y lookup with exact arithmetic scaling.
- Clips the transform's `y=192` overflow before dirty-mask addressing.
- Advances renderer and attribute state on every source presentation while
  suppressing only the 30 display flips selected by the 4.5 fps plan.
- Samples `LAST_SAMPLE_BANK` during verification, rather than whichever bank
  happens to be displayed at the end of an emulator refresh.

The real-asset event filter, deep-child culling, collapsed-polygon shortcut,
fast span fill, EGA run restorer and row-fill variants are excluded from this
production build because at least one reference byte changed when each unsafe
combination was exercised.

## Local full-run verification

| Metric | Fixed build |
|---|---:|
| VM ticks | 2,980 |
| VM instructions | 56,075 |
| Trace hash | 40,691 |
| Planned retained presentations | 268/298 |
| Retained presentations observed | 268/298 |
| Exact retained presentations | **268/268** |
| Average screen-byte mismatch | **0/6,912** |
| Worst screen-byte mismatch | **0/6,912** |
| Emulated runtime | 577.82 s |
| SNA size | 131,103 bytes |
| SNA SHA-256 | `f1549ef6d323c931fd0542d629935f593eae94c0db06d2613451d47c112851b1` |

The corrected build is artifact-free against the complete visual reference,
but it is not real-time. The previous 203.28-second result depended on unsafe
draw elimination and overlapping lookup data and is retained only as a
diagnostic result.

## Rebuild

```sh
python3 vm-port/build_proper_ega.py \
  --optimized-work build/out/work \
  --vm-source build/out/work/vm-current.asm \
  --renderer-source build/out/work/renderer-current.asm \
  --full-build build/full \
  --deep-blob build/deep-data/deep-child.bin \
  --disable-event-filter \
  --disable-deep-culling \
  --disable-fast-degenerate \
  --disable-fast-fill \
  --rt45-plan vm-port/cost-4p5-render.json \
  --sjasmplus vendor/sjasmplus/sjasmplus \
  --out build/proper-ega-rt45-fixed

node vm-port/verify_proper_ega_rt45.mjs \
  jsspeccy-core.wasm \
  build/proper-ega-rt45-fixed/another-world-proper-ega-rowfill.sna \
  build/full/another-world-vm-full.sna \
  vm-port/cost-4p5-render.json \
  build/proper-ega-rt45-fixed/verification.json
```
