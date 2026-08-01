# Polygon SOTA benchmark

This benchmark compares the current renderer structure against an exact-output direct edge-combination path for random triangles whose three vertices lie on the 256x192 screen border.

## Modes

- `baseline`: current-style per-polygon left/right edge tables, range clear, Bresenham edge updates, table readback, byte span fill.
- `direct`: preserves the exact current Bresenham edge inclusion but combines active edge samples directly, avoiding edge-table clear/write/read traffic.
- `direct_post`: draws the same direct triangle twice and suppresses unchanged destination-byte stores on the second draw. This approximates an offline post-quantization/post-draw no-op pass.

## Result

5,000 deterministic random triangles:

- Exact framebuffer equality: 5,000 / 5,000.
- Mean modeled baseline cost: 85,382 T-states.
- Mean modeled direct cost: 49,334 T-states.
- Modeled direct-edge speedup: 1.73x.
- Two repeated direct draws with post-draw store suppression versus two ordinary direct draws: 1.27x.

## Limitations

These values are from an explicit relative Z80 T-state model, not an emulator or hardware run. They intentionally isolate polygon edge setup, span work, and changed-byte suppression. They do not include VM dispatch, resource paging, attribute lookup preparation, dirty restoration, contention, or interrupts.

The direct mode is suitable as an implementation target because it is output-identical under the existing edge inclusion convention. A half-pixel fixed-point DDA prototype was rejected because it did not match the current rasterization convention.

## Run

```bash
python vm-port/tools/polygon_sota_benchmark.py
```
