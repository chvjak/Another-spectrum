# Another World on ZX Spectrum 128K

Experimental ports of the Another World DOS-shareware intro to the ZX Spectrum
128K.

## Implementations

- `diff-stream/`: pre-rendered Spectrum screens encoded as alternating bank-5 /
  bank-7 byte deltas.
- `vm-port/`: intro-specific Z80 VM and polygon renderer using the original VM
  bytecode and shape resources supplied locally by the user.

The repository contains source code and measured results only. It intentionally
does not include Another World data, Spectrum ROMs, generated snapshots, videos,
or emulator binaries.

## Status

The recovered source reflects two tested milestones:

- a 25 fps diff-stream prototype;
- a complete VM trace with draw elimination and a size-first 128K layout.

The diff-stream documentation records the original 59.64-second timing bug.
Later testing established that the intro script lasts about 164.52 seconds; the
timestamp-aware correction must be reapplied to the recovered source.

See the README in each implementation directory for details and prerequisites.
