# Combined DDA and post-draw preprocessing

This mode moves both edge rasterization and destination comparison offline.

## Build-time pipeline

1. Rasterize the transformed polygon with signed 8.8 fixed-point DDA.
2. Apply the polygon to the exact Spectrum framebuffer state expected at that draw event.
3. Compare bytes before and after the draw.
4. Emit only changed destination-byte records.

Each runtime record is conceptually:

```text
screen byte offset, changed-bit mask
```

The runtime applies the mask directly and performs no vertex decode, edge walk, edge table setup, span construction, or unchanged-byte test.

## Modeled result

5,000 deterministic triangles with vertices selected from the 256x192 border:

| Mode | Mean modeled T-states | Relative to current |
|---|---:|---:|
| Current Bresenham plus edge tables | 85,382 | 1.00x |
| Runtime approximate DDA | 57,509 | 1.48x |
| Offline DDA plus changed-byte replay | 32,325 | 2.64x |

The combined mode is 1.78x faster than performing DDA at runtime.

## Raster deviation

The approximate DDA intentionally does not preserve the existing Bresenham fill convention:

- exact framebuffer matches: 395 / 5,000
- median difference: 122 pixels
- mean difference: 158 pixels
- 95th percentile: 428 pixels

These full-screen border triangles are more severe than typical Another World primitives. The actual intro must be replayed and compared before selecting which events may use DDA.

## Recommended integration

Use the combined representation selectively:

- fixed transformed draw events;
- events retained by the final frame schedule;
- events whose DDA output is visually acceptable;
- events where changed-byte records are smaller and faster than generic polygon rendering.

Keep the current polygon renderer as fallback for dynamic transforms, alpha-dependent draws, or visually sensitive shared edges.

## Limitation

The numbers are from a relative Z80 T-state model, not an assembled SNA emulator or hardware benchmark. They exclude VM dispatch, paging, dirty restoration, attribute updates, contention, and interrupt overhead.
