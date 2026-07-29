# Atari ST-style renderer optimization

This variant keeps the original Another World bytecode and shape resource. It
changes only measured Spectrum renderer hot paths.

## Implemented

The baseline renderer handled every covered bitmap byte through one generic
read/modify/write loop. That repeated edge-mask tests, colour dispatch and an
attribute decision call even for bytes entirely inside a polygon.

`build_st_optimized.py` generates `renderer_full_st.asm` with:

- separate masked first/last-byte paths;
- direct `0x00` / `0xFF` stores for complete interior bytes;
- an inlined attribute-to-INK/PAPER decision lookup;
- a separate direct-copy interior loop for Another World's `COL_PAGE`;
- immediate no-op exit for `COL_PAGE` while rendering page 0;
- range-limited edge-table clears over `MIN_Y..MAX_Y`;
- exact compact division for `x - floor(x/5)`;
- no additional geometry or span templates.

This mirrors the useful part of the Atari ST implementation: edge work remains
special, while most polygon area becomes an aligned block fill.

## Correctness tests

```sh
python3 test_st_renderer_patch.py
```

The local run passes:

- randomized/exhaustive span geometry against the baseline semantics;
- all `MIN_Y..MAX_Y` edge-table ranges;
- all 320 source X coordinates for the compact divide-by-five transform;
- patch-marker and idempotence checks.

A first 320-byte X table was rejected twice: its original rounding was wrong
(`floor(4x/5)` instead of `x-floor(x/5)`), and the corrected table would overlap
the event-run stream at `$6C00`.

## Measured hot-path effect

The uncontended Z80 T-state model gives:

- X transform: **1,573 → 638 T-states average**, **2.47×**;
- 32-pixel span: **2,830 → 1,286 T-states average**, **2.20×**;
- 64-pixel span: **4,618 → 1,626 T-states average**, **2.84×**;
- 24-line edge-table setup: **8,093 → 1,199 T-states**, **6.75×**;
- representative changed-hotpath primitive models: **2.38–3.22×**.

This proves the changed routines are worth keeping. It is not yet an end-to-end
VM timing result because the repository intentionally excludes the locally
supplied AW resources, trace, reference screens, ROMs and emulator binary.

## Whole-run sensitivity

The previous measured baseline was 29,392 refreshes for 2,980 control ticks. If
the changed routines account for 25%, 50% or 75% of rendering-overrun time, the
model projects approximately 14–16%, 28–31% or 42–47% whole-run saving. These
are Amdahl projections, not emulator measurements.

## Fixed-bank size check

The baseline renderer is 3,585 bytes and ends at `$6B21`; the event-run stream
begins at `$6C00`, leaving 223 bytes. A static opcode-size audit gives a net
**+190 bytes** for the compact variant, ending near `$6BDF` and leaving **33
bytes**. The project assembler remains the final size authority.

## Build and exact A/B test

```sh
python3 build_st_optimized.py --zxasm /path/to/zxasm
python3 benchmark_st_full.py --zxasm /path/to/zxasm
```

With the excluded local inputs restored, `benchmark_st_full.py` rebuilds both
variants, runs the same emulator regression twice, and writes
`build-full/st-ab-result.json` containing exact host refreshes, trace equality,
primitive count, visual mismatch and renderer growth.
