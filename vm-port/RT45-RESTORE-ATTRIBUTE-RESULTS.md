# RT45 restore and attribute publication optimization

This change keeps the existing VM/vector entry points and adds two runtime
fast paths to `renderer_full.asm`:

- dirty cells are counted per physical screen, so a dense restore can copy the
  6,144-byte bitmap with one `LDIR` instead of scanning 768 mask cells;
- staged attributes carry a generation number, so a presentation copies the
  768-byte attribute plane only to physical screens that are stale.

The dense split is currently a conservative 512 stale cells. It is based on
the exact cell count, so overlapping draw operations do not inflate the work
estimate. The bitmap and attribute paths remain independent, preserving the
double-buffered screen semantics.

## Local validation

- SjASMPlus 1.23.1 assembled the canonical VM and renderer with zero errors or
  warnings. The real DOS shareware resources were read successfully: 9,842
  bytes of bytecode, 65,156 bytes of shapes, and 2,048 bytes of palette data.
- The assembled neutral-resource snapshot reports 2,473 VM bytes and 3,957
  renderer bytes. Its visual assets are intentionally neutral and are not a
  production visual regression.
- The downloaded site RT45 snapshot completed in the local JSSpeccy core:
  2,980 VM ticks, 298 sampled presentations, 8,228 host refreshes, and zero
  renderer errors. Its SHA-256 is
  `e6a11a13452e45fcf29fc90f435cc43851f4d8f30a611358138e1391a2639de`.

The exact production visual build is not regenerated here because this
checkout does not contain the historical `analyze_visual_assets.py`,
`build_vm_port.py`, or the original JavaScript indexed captures referenced by
`build_full_vm_port.py`. The existing site SNA was therefore left untouched;
no unverified replacement was published.
