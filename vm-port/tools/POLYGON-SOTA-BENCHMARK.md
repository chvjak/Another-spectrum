# Approximate DDA and post-draw benchmark

This benchmark compares the current edge-table/Bresenham model with an approximate signed 8.8 fixed-point DDA. Raster deviations are permitted and reported rather than treated as failure.

## Workload

- 5,000 deterministic triangles.
- Three random points on the 256x192 viewport border.
- Direct 1-bit span fill.
- Relative Z80 T-state model only; not emulator timing.

## Results

| Mode | Mean modeled T-states | Relative result |
|---|---:|---:|
| Current Bresenham + edge tables | 85,382.1 | 1.00x |
| Approximate 8.8 DDA | 57,509.1 | 1.48x faster |
| Repeated DDA with runtime post-draw suppression | 77,581.0 | 1.48x vs two ordinary DDA draws |
| Offline changed-byte stream, replayed twice | 51,720.6 | 2.22x vs two ordinary DDA draws |

## Raster deviations

- Exact framebuffers: 395 / 5,000
- Mean differing pixels: 158.3
- Median differing pixels: 122
- 95th percentile differing pixels: 428
- Mean differing bytes: 138.9

The approximate DDA is faster in the model, but its edge convention differs materially from the current renderer. It should therefore be evaluated on the actual intro visually, not assumed to be a drop-in exact replacement.

The offline mode records only destination bytes that changed after DDA rasterization. This removes geometry, edge setup and no-op writes at runtime, and gives the largest modeled gain for repeated or deterministic draws.

## Limitations

The model excludes VM dispatch, paging, Spectrum contention, attributes, dirty restoration, interrupts and actual Z80 instruction scheduling.

## Run

```bash
python vm-port/tools/polygon_sota_benchmark.py
```
