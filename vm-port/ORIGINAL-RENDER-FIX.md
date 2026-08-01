# Original renderer repair

This build is the first renderer check in this branch that uses an independent
reference: 298 indexed 320x200 presentations captured directly from the
bundled JavaScript Another World VM.  No Spectrum SNA or diff stream is used
as its visual baseline.

## Repairs

- Replaced the incomplete geometry-trace parser with exact indexed and RGB
  captures from the original VM.
- Generated all 298 Spectrum attribute maps from the original visible frames.
- Replaced the stale two-stage palette lookup with 176 deduplicated direct
  logical-colour-to-PAPER/INK decision rows.
- Preserved the two real page-0 snapshots copied into logical page 3 instead of
  treating page 3 as a mutable alias of the current background.
- Removed the unsafe historical draw-event filter.  The full 2,980-tick VM
  trace and all 298 sampled presentations execute.
- Treats `COL_ALPHA` as preserve on the two-colour Spectrum target.  A true
  indexed-colour OR operation cannot be represented by a single Spectrum
  bitmap bit without additional per-cell state.

## Measured result

The final SNA SHA-256 is
`334e2740c20a90c4c3f370d90a55a8aafaab4a4f7c048a1b3d4aa7ce1d080c8a`.

- JSSpeccy run: 31,184 refreshes, 623.68 seconds, 298 presentations,
  `vmTick=2980`, normal completion.
- Attribute mismatch against the generated Spectrum reference: zero on every
  presentation.
- Average screen mismatch: 522.26 of 6,912 bytes, down from 1,338.90 in the
  original base SNA under the same independent reference.
- Original-RGB MSE: 2,550.56, down from 2,817.53 in the base SNA.  The ideal
  Spectrum conversion itself measures 2,156.56 because of unavoidable colour
  and resolution loss.

This is a real live VM/vector renderer, not a replay.  It is materially closer
to the original and removes the stale page-3 and palette-table corruption, but
it is not pixel-perfect or real-time.  Dense hand/keypad frames and several
late polygon scenes still expose rasterisation and two-colour approximation
differences.

## Reproduction

Generate the three independent capture inputs with
`capture_original_colour_preview.mjs` in `--indexed`, `--palette-ids`, and
`--page3-snapshots` modes.  Build with `build_original_visuals.py`, capture the
SNA presentations with `capture_snapshot_screens.mjs`, then run
`compare_original_reference.py` against the generated `reference-screens`.
